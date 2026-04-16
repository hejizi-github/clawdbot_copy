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


def loop_detection(
    trace: AgentTrace,
    ngram_sizes: list[int] | None = None,
    min_repeats: int = 2,
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

    loops_found: list[dict] = []
    total_repeated_steps = 0

    for n in ngram_sizes:
        if len(names) < n:
            continue
        ngrams = [tuple(names[i : i + n]) for i in range(len(names) - n + 1)]
        counts = Counter(ngrams)
        for gram, count in counts.items():
            if count >= min_repeats:
                loops_found.append({
                    "pattern": list(gram),
                    "length": n,
                    "occurrences": count,
                })
                total_repeated_steps += n * (count - 1)

    if not loops_found:
        score = 1.0
    else:
        penalty = min(total_repeated_steps / max(len(names), 1), 0.9)
        score = round(1.0 - penalty, 4)

    return MetricResult(
        name="loop_detection",
        score=score,
        passed=score >= 0.7,
        details={
            "step_count": len(names),
            "loops_found": loops_found,
            "total_repeated_steps": total_repeated_steps,
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
        ),
        token_efficiency(trace, baseline_tokens=config.baseline_tokens),
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
