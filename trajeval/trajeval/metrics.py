"""Deterministic metrics for agent trace evaluation."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from .models import AgentTrace


class MetricResult(BaseModel):
    name: str
    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    details: dict = Field(default_factory=dict)


class EvalReport(BaseModel):
    trace_id: str
    metrics: list[MetricResult] = Field(default_factory=list)
    overall_score: float = 0.0
    passed: bool = False


class MetricConfig(BaseModel):
    expected_steps: int | None = None
    baseline_tokens: int | None = None
    loop_ngram_sizes: list[int] = Field(default=[2, 3])
    loop_min_repeats: int = 2
    loop_similarity_threshold: float = 1.0
    recovery_window: int = 3
    latency_budget_ms: float | None = None
    pass_threshold: float = 0.7


def step_efficiency(trace: AgentTrace, expected_steps: int | None = None) -> MetricResult:
    """Measure step efficiency: ratio of productive steps to total, or actual vs expected."""
    total = trace.step_count
    if total == 0:
        return MetricResult(
            name="step_efficiency",
            score=1.0,
            passed=True,
            details={"total_steps": 0, "mode": "empty_trace"},
        )

    if expected_steps is not None and expected_steps > 0:
        score = min(expected_steps / total, 1.0)
        return MetricResult(
            name="step_efficiency",
            score=round(score, 4),
            passed=score >= 0.7,
            details={
                "total_steps": total,
                "expected_steps": expected_steps,
                "mode": "baseline",
            },
        )

    productive = sum(1 for s in trace.steps if s.type != "error")
    score = productive / total
    return MetricResult(
        name="step_efficiency",
        score=round(score, 4),
        passed=score >= 0.7,
        details={
            "total_steps": total,
            "productive_steps": productive,
            "error_steps": total - productive,
            "mode": "heuristic",
        },
    )


def tool_accuracy(trace: AgentTrace) -> MetricResult:
    """Measure tool call success rate: tool calls not followed by an error step."""
    tools = trace.tool_calls
    if not tools:
        return MetricResult(
            name="tool_accuracy",
            score=1.0,
            passed=True,
            details={"total_tool_calls": 0, "note": "no tool calls"},
        )

    failed = 0
    for i, step in enumerate(trace.steps):
        if step.type != "tool_call":
            continue
        next_is_error = (
            i + 1 < len(trace.steps) and trace.steps[i + 1].type == "error"
        )
        output_has_error = _output_indicates_error(step.output)
        if next_is_error or output_has_error:
            failed += 1

    total = len(tools)
    successful = total - failed
    score = successful / total
    return MetricResult(
        name="tool_accuracy",
        score=round(score, 4),
        passed=score >= 0.7,
        details={
            "total_tool_calls": total,
            "successful": successful,
            "failed": failed,
        },
    )


def _output_indicates_error(output: dict) -> bool:
    error_keys = {"error", "Error", "ERROR"}
    if error_keys & set(output.keys()):
        return True
    for v in output.values():
        if isinstance(v, str) and v.lower().startswith("error"):
            return True
    return False


def _is_subpattern(short: tuple, long: tuple) -> bool:
    """Check if short is a contiguous subsequence of long."""
    ls, ll = len(short), len(long)
    if ls >= ll:
        return False
    for i in range(ll - ls + 1):
        if long[i : i + ls] == short:
            return True
    return False


def _hamming_similarity(a: tuple, b: tuple) -> float:
    """Fraction of positions where two same-length tuples match."""
    if len(a) != len(b) or not a:
        return 0.0
    return sum(x == y for x, y in zip(a, b)) / len(a)


def _deduplicate_loops(loops: list[dict]) -> list[dict]:
    """Remove shorter patterns that are subsequences of longer detected patterns."""
    sorted_loops = sorted(loops, key=lambda x: x["length"], reverse=True)
    kept: list[dict] = []
    for loop in sorted_loops:
        pattern = tuple(loop["pattern"])
        subsumed = False
        for longer in kept:
            if _is_subpattern(pattern, tuple(longer["pattern"])):
                subsumed = True
                break
        if not subsumed:
            kept.append(loop)
    return kept


def _step_coverage(positions: list[int], length: int) -> set[int]:
    """Compute the set of step indices covered by n-gram occurrences."""
    covered: set[int] = set()
    for p in positions:
        for offset in range(length):
            covered.add(p + offset)
    return covered


def _deduplicate_near_loop_clusters(clusters: list[dict]) -> list[dict]:
    """Merge near-loop clusters whose step coverage overlaps by >50%."""
    if len(clusters) <= 1:
        return clusters
    sorted_clusters = sorted(clusters, key=lambda c: c["occurrences"], reverse=True)
    kept: list[dict] = []
    kept_coverage: list[set[int]] = []
    for cluster in sorted_clusters:
        coverage = _step_coverage(cluster["_positions"], cluster["length"])
        absorbed = False
        for i, existing_cov in enumerate(kept_coverage):
            overlap = len(coverage & existing_cov)
            smaller = min(len(coverage), len(existing_cov))
            if smaller > 0 and overlap / smaller > 0.5:
                existing_cov.update(coverage)
                existing = kept[i]
                existing["_positions"] = sorted(
                    set(existing["_positions"]) | set(cluster["_positions"])
                )
                existing["occurrences"] = len(existing["_positions"])
                existing["variants"] = max(existing["variants"], cluster["variants"])
                absorbed = True
                break
        if not absorbed:
            kept.append(cluster)
            kept_coverage.append(coverage)
    return kept


def _find_near_loops(
    names: list[str],
    ngram_sizes: list[int],
    min_repeats: int,
    similarity_threshold: float,
    exact_patterns: set[tuple],
) -> list[dict]:
    """Find near-duplicate loops: sequences that repeat with minor variations."""
    near_loops: list[dict] = []

    for n in ngram_sizes:
        if len(names) < n:
            continue
        ngrams = [tuple(names[i : i + n]) for i in range(len(names) - n + 1)]

        clusters: list[dict] = []
        for i, gram in enumerate(ngrams):
            merged = False
            for cluster in clusters:
                if _hamming_similarity(gram, cluster["representative"]) >= similarity_threshold:
                    cluster["positions"].append(i)
                    cluster["variants"].add(gram)
                    merged = True
                    break
            if not merged:
                clusters.append({
                    "representative": gram,
                    "positions": [i],
                    "variants": {gram},
                })

        candidates = []
        for cluster in clusters:
            if len(cluster["positions"]) < min_repeats:
                continue
            if len(cluster["variants"]) == 1 and cluster["representative"] in exact_patterns:
                continue
            # Stable representative: lexicographic smallest variant
            rep = min(cluster["variants"])
            candidates.append({
                "pattern": list(rep),
                "length": n,
                "occurrences": len(cluster["positions"]),
                "variants": len(cluster["variants"]),
                "_positions": cluster["positions"],
            })

        candidates = _deduplicate_near_loop_clusters(candidates)
        near_loops.extend(candidates)

    return _deduplicate_loops(near_loops)


def loop_detection(
    trace: AgentTrace,
    ngram_sizes: list[int] | None = None,
    min_repeats: int = 2,
    similarity_threshold: float = 1.0,
) -> MetricResult:
    """Detect repeated step sequences via n-gram analysis on step names."""
    if ngram_sizes is None:
        ngram_sizes = [2, 3]

    names = [s.name for s in trace.steps]
    if len(names) < 2:
        return MetricResult(
            name="loop_detection",
            score=1.0,
            passed=True,
            details={"step_count": len(names), "loops_found": []},
        )

    raw_loops: list[dict] = []

    for n in ngram_sizes:
        if len(names) < n:
            continue
        ngrams = [tuple(names[i : i + n]) for i in range(len(names) - n + 1)]
        counts = Counter(ngrams)
        for gram, count in counts.items():
            if count >= min_repeats:
                positions = [
                    i for i in range(len(names) - n + 1)
                    if tuple(names[i : i + n]) == gram
                ]
                raw_loops.append({
                    "pattern": list(gram),
                    "length": n,
                    "occurrences": count,
                    "_positions": positions,
                })

    loops_found = _deduplicate_loops(raw_loops)
    exact_patterns = {tuple(l["pattern"]) for l in loops_found}

    repeated_positions: set[int] = set()
    for loop in loops_found:
        positions = loop.pop("_positions", [])
        # Skip first occurrence — it's the "original", only repeats are wasted
        for pos in positions[1:]:
            for offset in range(loop["length"]):
                repeated_positions.add(pos + offset)

    near_loops_found: list[dict] = []
    if similarity_threshold < 1.0:
        near_loops_found = _find_near_loops(
            names, ngram_sizes, min_repeats, similarity_threshold, exact_patterns,
        )
        for loop in near_loops_found:
            positions = loop.pop("_positions", [])
            for pos in sorted(positions)[1:]:
                for offset in range(loop["length"]):
                    repeated_positions.add(pos + offset)

    total_repeated_steps = len(repeated_positions)

    if not loops_found and not near_loops_found:
        score = 1.0
    else:
        penalty = min(total_repeated_steps / max(len(names), 1), 0.9)
        score = round(1.0 - penalty, 4)

    details: dict = {
        "step_count": len(names),
        "loops_found": loops_found,
        "total_repeated_steps": total_repeated_steps,
    }
    if near_loops_found:
        details["near_loops_found"] = near_loops_found

    return MetricResult(
        name="loop_detection",
        score=score,
        passed=score >= 0.7,
        details=details,
    )


def error_recovery(
    trace: AgentTrace, recovery_window: int = 3,
) -> MetricResult:
    """Measure how well the agent recovers from errors.

    For each error step, checks whether a successful step (non-error) appears
    within the next `recovery_window` steps. Score = recovered / total_errors.

    For consecutive errors (e.g. error→error→error→success with window=3),
    each error is evaluated independently — all three count as recovered because
    each one's window contains the success step.
    """
    errors = [i for i, s in enumerate(trace.steps) if s.type == "error"]

    if not errors:
        return MetricResult(
            name="error_recovery",
            score=1.0,
            passed=True,
            details={"total_errors": 0, "note": "no errors in trace"},
        )

    recovered = 0
    for err_idx in errors:
        window = trace.steps[err_idx + 1 : err_idx + 1 + recovery_window]
        if any(s.type != "error" for s in window):
            recovered += 1

    total = len(errors)
    score = recovered / total
    return MetricResult(
        name="error_recovery",
        score=round(score, 4),
        passed=score >= 0.7,
        details={
            "total_errors": total,
            "recovered": recovered,
            "unrecovered": total - recovered,
            "recovery_window": recovery_window,
        },
    )


def token_efficiency(
    trace: AgentTrace, baseline_tokens: int | None = None
) -> MetricResult:
    """Measure token efficiency against a baseline or via productive-token ratio."""
    actual = trace.total_tokens.total
    if actual == 0:
        return MetricResult(
            name="token_efficiency",
            score=1.0,
            passed=True,
            details={"total_tokens": 0, "mode": "no_tokens"},
        )

    if baseline_tokens is not None and baseline_tokens > 0:
        score = min(baseline_tokens / actual, 1.0)
        return MetricResult(
            name="token_efficiency",
            score=round(score, 4),
            passed=score >= 0.7,
            details={
                "total_tokens": actual,
                "baseline_tokens": baseline_tokens,
                "mode": "baseline",
            },
        )

    error_tokens = sum(
        s.tokens.total for s in trace.steps if s.type == "error" and s.tokens
    )
    productive_tokens = actual - error_tokens
    score = productive_tokens / actual
    return MetricResult(
        name="token_efficiency",
        score=round(score, 4),
        passed=score >= 0.7,
        details={
            "total_tokens": actual,
            "productive_tokens": productive_tokens,
            "error_tokens": error_tokens,
            "mode": "heuristic",
        },
    )


def latency_budget(trace: AgentTrace, budget_ms: float | None = None) -> MetricResult:
    """Measure whether the agent completed within a latency budget."""
    actual = trace.total_duration_ms
    if actual == 0:
        return MetricResult(
            name="latency_budget",
            score=1.0,
            passed=True,
            details={"total_duration_ms": 0, "mode": "no_duration"},
        )

    if budget_ms is None or budget_ms <= 0:
        return MetricResult(
            name="latency_budget",
            score=1.0,
            passed=True,
            details={"total_duration_ms": actual, "mode": "no_budget"},
        )

    score = min(budget_ms / actual, 1.0)
    return MetricResult(
        name="latency_budget",
        score=round(score, 4),
        passed=score >= 0.7,
        details={
            "total_duration_ms": actual,
            "budget_ms": budget_ms,
            "mode": "baseline",
        },
    )


def evaluate(trace: AgentTrace, config: MetricConfig | None = None) -> EvalReport:
    """Run all deterministic metrics and return a combined report."""
    if config is None:
        config = MetricConfig()

    results = [
        step_efficiency(trace, expected_steps=config.expected_steps),
        tool_accuracy(trace),
        loop_detection(
            trace,
            ngram_sizes=config.loop_ngram_sizes,
            min_repeats=config.loop_min_repeats,
            similarity_threshold=config.loop_similarity_threshold,
        ),
        token_efficiency(trace, baseline_tokens=config.baseline_tokens),
        error_recovery(trace, recovery_window=config.recovery_window),
        latency_budget(trace, budget_ms=config.latency_budget_ms),
    ]

    threshold = config.pass_threshold
    for r in results:
        r.passed = r.score >= threshold

    overall = sum(r.score for r in results) / len(results) if results else 0.0
    all_passed = all(r.passed for r in results)

    return EvalReport(
        trace_id=trace.trace_id,
        metrics=results,
        overall_score=round(overall, 4),
        passed=all_passed,
    )
