"""CI output formatting for GitHub Actions integration."""

from __future__ import annotations

from .compare import ComparisonResult
from .metrics import EvalReport, MetricResult
from .scorer import EnsembleResult, JudgeResult


def _annotation_level(metric: MetricResult) -> str:
    if not metric.passed:
        return "error"
    if metric.score < 0.85:
        return "warning"
    return "notice"


def _annotation_line(level: str, title: str, message: str) -> str:
    return f"::{level} title={title}::{message}"


def _metric_summary(metric: MetricResult) -> str:
    parts = [f"score={metric.score:.2f}"]
    if "total_steps" in metric.details:
        parts.append(f"steps={metric.details['total_steps']}")
    if "total_tool_calls" in metric.details:
        parts.append(f"tools={metric.details['total_tool_calls']}")
    if "total_errors" in metric.details:
        parts.append(f"errors={metric.details['total_errors']}")
    if "loops_found" in metric.details:
        loops = metric.details["loops_found"]
        if loops:
            parts.append(f"{len(loops)} loop(s) detected")
    if "total_tokens" in metric.details and metric.details["total_tokens"] > 0:
        parts.append(f"tokens={metric.details['total_tokens']}")
    if "budget_ms" in metric.details:
        parts.append(f"budget={metric.details['budget_ms']:.0f}ms")
    return ", ".join(parts)


def format_eval_ci(report: EvalReport, threshold: float = 0.7) -> str:
    lines: list[str] = []

    for m in report.metrics:
        level = _annotation_level(m)
        status = "PASS" if m.passed else "FAIL"
        title = f"trajeval: {m.name} {status}"
        message = _metric_summary(m)
        lines.append(_annotation_line(level, title, message))

    lines.append("")
    lines.append("## trajeval Evaluation Summary")
    lines.append("")
    lines.append("| Metric | Score | Status |")
    lines.append("|--------|-------|--------|")
    for m in report.metrics:
        icon = "✅" if m.passed else "❌"
        status = "PASS" if m.passed else "FAIL"
        lines.append(f"| {m.name} | {m.score:.2f} | {icon} {status} |")

    overall_icon = "✅" if report.passed else "❌"
    overall_status = "PASS" if report.passed else "FAIL"
    lines.append("")
    overall = f"**Overall: {report.overall_score:.2f} — {overall_icon} {overall_status}**"
    lines.append(f"{overall} (threshold: {threshold:.2f})")

    return "\n".join(lines)


def format_compare_ci(result: ComparisonResult) -> str:
    lines: list[str] = []

    for d in result.metric_deltas:
        sign = "+" if d.delta > 0 else ""
        if d.direction == "regressed":
            level = "error"
            title = f"trajeval: {d.name} REGRESSED"
        elif d.direction == "improved":
            level = "notice"
            title = f"trajeval: {d.name} IMPROVED"
        else:
            level = "notice"
            title = f"trajeval: {d.name} unchanged"
        message = f"{d.baseline_score:.2f} → {d.current_score:.2f} ({sign}{d.delta:.2f})"
        lines.append(_annotation_line(level, title, message))

    lines.append("")
    lines.append("## trajeval Comparison Summary")
    lines.append("")
    lines.append(f"Baseline: `{result.baseline_trace_id}` → Current: `{result.current_trace_id}`")
    lines.append(f"Tolerance: {result.tolerance:.0%}")
    lines.append("")
    lines.append("| Metric | Baseline | Current | Delta | Status |")
    lines.append("|--------|----------|---------|-------|--------|")
    for d in result.metric_deltas:
        sign = "+" if d.delta > 0 else ""
        if d.direction == "regressed":
            icon = "🔴"
            status = "REGRESSED"
        elif d.direction == "improved":
            icon = "🟢"
            status = "IMPROVED"
        else:
            icon = "⚪"
            status = "unchanged"
        row = f"| {d.name} | {d.baseline_score:.2f} | {d.current_score:.2f}"
        lines.append(f"{row} | {sign}{d.delta:.2f} | {icon} {status} |")

    sign = "+" if result.overall_delta > 0 else ""
    overall_icon = "🔴" if result.has_regression else "🟢"
    overall_status = "REGRESSION DETECTED" if result.has_regression else "OK"
    lines.append("")
    lines.append(f"**Overall delta: {sign}{result.overall_delta:.2f} — {overall_icon} {overall_status}**")

    return "\n".join(lines)


def _judge_annotation_level(score: int) -> str:
    if score <= 2:
        return "error"
    if score == 3:
        return "warning"
    return "notice"


def format_judge_ci(
    result: JudgeResult | EnsembleResult,
    threshold: float = 0.7,
    passed: bool | None = None,
) -> str:
    if passed is None:
        passed = result.overall_score >= threshold
    lines: list[str] = []
    is_ensemble = isinstance(result, EnsembleResult)

    for d in result.dimensions:
        level = _judge_annotation_level(d.score)
        title = f"trajeval: {d.name} {d.score}/5"
        lines.append(_annotation_line(level, title, d.explanation))

    lines.append("")
    if is_ensemble:
        lines.append(f"## trajeval Judge Summary ({result.num_judges} judges, {result.aggregation})")
    else:
        lines.append("## trajeval Judge Summary")
    lines.append("")

    if is_ensemble:
        stat_map = {s.name: s for s in result.dimension_stats}
        lines.append("| Dimension | Score | Std Dev | Explanation |")
        lines.append("|-----------|-------|---------|-------------|")
        for d in result.dimensions:
            stat = stat_map.get(d.name)
            std_str = f"{stat.std_dev:.2f}" if stat else "-"
            lines.append(f"| {d.name} | {d.score}/5 | {std_str} | {d.explanation} |")
    else:
        lines.append("| Dimension | Score | Explanation |")
        lines.append("|-----------|-------|-------------|")
        for d in result.dimensions:
            lines.append(f"| {d.name} | {d.score}/5 | {d.explanation} |")

    overall_icon = "✅" if passed else "❌"
    overall_status = "PASS" if passed else "FAIL"
    lines.append("")
    overall = f"**Overall: {result.overall_score:.0%} — {overall_icon} {overall_status}**"
    lines.append(f"{overall} (threshold: {threshold:.0%})")

    return "\n".join(lines)
