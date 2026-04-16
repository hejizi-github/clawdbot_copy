"""Comparison and regression detection between evaluation runs."""

from __future__ import annotations

from pydantic import BaseModel, Field

from .metrics import EvalReport, MetricResult


class MetricDelta(BaseModel):
    name: str
    baseline_score: float
    current_score: float
    delta: float
    direction: str = Field(description="improved, regressed, or unchanged")
    is_regression: bool = False
    baseline_details: dict | None = None
    current_details: dict | None = None


class ComparisonResult(BaseModel):
    baseline_trace_id: str
    current_trace_id: str
    metric_deltas: list[MetricDelta] = Field(default_factory=list)
    overall_delta: float = 0.0
    has_regression: bool = False
    tolerance: float = 0.05


def _classify_direction(delta: float, tolerance: float) -> tuple[str, bool]:
    if delta < -tolerance:
        return "regressed", True
    if delta > tolerance:
        return "improved", False
    return "unchanged", False


def compare_reports(
    baseline: EvalReport,
    current: EvalReport,
    tolerance: float = 0.05,
) -> ComparisonResult:
    """Compare two evaluation reports and detect regressions."""
    baseline_map: dict[str, MetricResult] = {m.name: m for m in baseline.metrics}
    current_map: dict[str, MetricResult] = {m.name: m for m in current.metrics}

    all_names = list(dict.fromkeys(
        [m.name for m in baseline.metrics] + [m.name for m in current.metrics]
    ))

    deltas = []
    for name in all_names:
        b_score = baseline_map[name].score if name in baseline_map else 0.0
        c_score = current_map[name].score if name in current_map else 0.0
        delta = round(c_score - b_score, 4)
        direction, is_regression = _classify_direction(delta, tolerance)
        b_details = baseline_map[name].details if name in baseline_map else None
        c_details = current_map[name].details if name in current_map else None
        deltas.append(MetricDelta(
            name=name,
            baseline_score=b_score,
            current_score=c_score,
            delta=delta,
            direction=direction,
            is_regression=is_regression,
            baseline_details=b_details or None,
            current_details=c_details or None,
        ))

    overall_delta = round(current.overall_score - baseline.overall_score, 4)
    has_regression = any(d.is_regression for d in deltas)

    return ComparisonResult(
        baseline_trace_id=baseline.trace_id,
        current_trace_id=current.trace_id,
        metric_deltas=deltas,
        overall_delta=overall_delta,
        has_regression=has_regression,
        tolerance=tolerance,
    )


def format_markdown(result: ComparisonResult) -> str:
    """Generate a markdown report suitable for PR comments."""
    status = "REGRESSION DETECTED" if result.has_regression else "No Regression"
    icon = "🔴" if result.has_regression else "🟢"

    lines = [
        f"## {icon} trajeval compare: {status}",
        "",
        f"**Baseline**: `{result.baseline_trace_id}`  ",
        f"**Current**: `{result.current_trace_id}`  ",
        f"**Tolerance**: {result.tolerance:.0%}",
        "",
        "| Metric | Baseline | Current | Delta | Status |",
        "|--------|----------|---------|-------|--------|",
    ]

    for d in result.metric_deltas:
        if d.direction == "regressed":
            status_cell = "⬇ Regressed"
        elif d.direction == "improved":
            status_cell = "⬆ Improved"
        else:
            status_cell = "— Unchanged"
        sign = "+" if d.delta > 0 else ""
        lines.append(
            f"| {d.name} | {d.baseline_score:.2f} | {d.current_score:.2f} "
            f"| {sign}{d.delta:.2f} | {status_cell} |"
        )

    sign = "+" if result.overall_delta > 0 else ""
    lines.extend([
        "",
        f"**Overall delta**: {sign}{result.overall_delta:.2f}",
    ])

    details_lines = _format_details_section(result.metric_deltas)
    if details_lines:
        lines.append("")
        lines.extend(details_lines)

    return "\n".join(lines)


def _format_details_section(deltas: list[MetricDelta]) -> list[str]:
    """Render per-metric details as collapsible GitHub markdown sections."""
    lines: list[str] = []
    for d in deltas:
        if d.baseline_details is None and d.current_details is None:
            continue
        lines.append(f"<details><summary>{d.name} details</summary>")
        lines.append("")
        if d.baseline_details is not None:
            lines.append("**Baseline**:")
            for k, v in d.baseline_details.items():
                lines.append(f"- {k}: {v}")
        if d.current_details is not None:
            lines.append("")
            lines.append("**Current**:")
            for k, v in d.current_details.items():
                lines.append(f"- {k}: {v}")
        lines.append("")
        lines.append("</details>")
    return lines
