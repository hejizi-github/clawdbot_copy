"""Tests for the compare module — regression detection between eval runs."""

from __future__ import annotations

import pytest

from trajeval.compare import (
    ComparisonResult,
    MetricDelta,
    _classify_direction,
    compare_reports,
    format_markdown,
)
from trajeval.metrics import EvalReport, MetricResult


def _make_report(
    trace_id: str, metrics: list[tuple[str, float, bool]], overall: float,
) -> EvalReport:
    return EvalReport(
        trace_id=trace_id,
        metrics=[MetricResult(name=n, score=s, passed=p) for n, s, p in metrics],
        overall_score=overall,
        passed=all(p for _, _, p in metrics),
    )


def _make_report_with_details(
    trace_id: str,
    metrics: list[tuple[str, float, bool, dict | None]],
    overall: float,
) -> EvalReport:
    return EvalReport(
        trace_id=trace_id,
        metrics=[
            MetricResult(name=n, score=s, passed=p, details=d or {})
            for n, s, p, d in metrics
        ],
        overall_score=overall,
        passed=all(p for _, _, p, _ in metrics),
    )


class TestClassifyDirection:
    def test_regression(self):
        direction, is_reg = _classify_direction(-0.1, tolerance=0.05)
        assert direction == "regressed"
        assert is_reg is True

    def test_improvement(self):
        direction, is_reg = _classify_direction(0.1, tolerance=0.05)
        assert direction == "improved"
        assert is_reg is False

    def test_unchanged_within_tolerance(self):
        direction, is_reg = _classify_direction(-0.03, tolerance=0.05)
        assert direction == "unchanged"
        assert is_reg is False

    def test_unchanged_exactly_at_tolerance(self):
        direction, is_reg = _classify_direction(-0.05, tolerance=0.05)
        assert direction == "unchanged"
        assert is_reg is False

    def test_zero_delta(self):
        direction, is_reg = _classify_direction(0.0, tolerance=0.05)
        assert direction == "unchanged"
        assert is_reg is False

    def test_zero_tolerance(self):
        direction, is_reg = _classify_direction(-0.001, tolerance=0.0)
        assert direction == "regressed"
        assert is_reg is True


class TestCompareReports:
    def test_no_regression(self):
        baseline = _make_report("b1", [("m1", 0.8, True), ("m2", 0.9, True)], 0.85)
        current = _make_report("c1", [("m1", 0.85, True), ("m2", 0.88, True)], 0.865)
        result = compare_reports(baseline, current)
        assert result.has_regression is False
        assert result.overall_delta == pytest.approx(0.015, abs=0.001)

    def test_regression_detected(self):
        baseline = _make_report("b1", [("m1", 0.9, True), ("m2", 0.8, True)], 0.85)
        current = _make_report("c1", [("m1", 0.7, True), ("m2", 0.85, True)], 0.775)
        result = compare_reports(baseline, current)
        assert result.has_regression is True
        regressed = [d for d in result.metric_deltas if d.is_regression]
        assert len(regressed) == 1
        assert regressed[0].name == "m1"

    def test_custom_tolerance(self):
        baseline = _make_report("b1", [("m1", 0.8, True)], 0.8)
        current = _make_report("c1", [("m1", 0.7, True)], 0.7)
        strict = compare_reports(baseline, current, tolerance=0.05)
        assert strict.has_regression is True
        lenient = compare_reports(baseline, current, tolerance=0.15)
        assert lenient.has_regression is False

    def test_identical_reports(self):
        baseline = _make_report("b1", [("m1", 0.8, True)], 0.8)
        current = _make_report("c1", [("m1", 0.8, True)], 0.8)
        result = compare_reports(baseline, current)
        assert result.has_regression is False
        assert result.overall_delta == 0.0
        assert all(d.direction == "unchanged" for d in result.metric_deltas)

    def test_preserves_metric_order(self):
        baseline = _make_report("b1", [("a", 0.9, True), ("b", 0.8, True), ("c", 0.7, True)], 0.8)
        current = _make_report("c1", [("a", 0.9, True), ("b", 0.8, True), ("c", 0.7, True)], 0.8)
        result = compare_reports(baseline, current)
        assert [d.name for d in result.metric_deltas] == ["a", "b", "c"]

    def test_mixed_directions(self):
        baseline = _make_report("b1", [("m1", 0.5, False), ("m2", 0.9, True)], 0.7)
        current = _make_report("c1", [("m1", 0.8, True), ("m2", 0.6, False)], 0.7)
        result = compare_reports(baseline, current)
        deltas = {d.name: d for d in result.metric_deltas}
        assert deltas["m1"].direction == "improved"
        assert deltas["m2"].direction == "regressed"
        assert result.has_regression is True

    def test_trace_ids_in_result(self):
        baseline = _make_report("baseline-123", [("m1", 0.8, True)], 0.8)
        current = _make_report("current-456", [("m1", 0.8, True)], 0.8)
        result = compare_reports(baseline, current)
        assert result.baseline_trace_id == "baseline-123"
        assert result.current_trace_id == "current-456"

    def test_tolerance_stored_in_result(self):
        baseline = _make_report("b1", [("m1", 0.8, True)], 0.8)
        current = _make_report("c1", [("m1", 0.8, True)], 0.8)
        result = compare_reports(baseline, current, tolerance=0.1)
        assert result.tolerance == 0.1

    def test_misaligned_metrics_baseline_extra(self):
        baseline = _make_report("b1", [("m1", 0.9, True), ("m2", 0.8, True)], 0.85)
        current = _make_report("c1", [("m1", 0.85, True)], 0.85)
        result = compare_reports(baseline, current, tolerance=0.05)
        deltas = {d.name: d for d in result.metric_deltas}
        assert "m1" in deltas
        assert "m2" in deltas
        assert deltas["m2"].current_score == 0.0
        assert deltas["m2"].baseline_score == 0.8
        assert deltas["m2"].is_regression is True

    def test_misaligned_metrics_current_extra(self):
        baseline = _make_report("b1", [("m1", 0.8, True)], 0.8)
        current = _make_report("c1", [("m1", 0.85, True), ("m_new", 0.7, True)], 0.775)
        result = compare_reports(baseline, current, tolerance=0.05)
        deltas = {d.name: d for d in result.metric_deltas}
        assert "m_new" in deltas
        assert deltas["m_new"].baseline_score == 0.0
        assert deltas["m_new"].current_score == 0.7
        assert deltas["m_new"].direction == "improved"

    def test_completely_disjoint_metrics(self):
        baseline = _make_report("b1", [("only_baseline", 0.9, True)], 0.9)
        current = _make_report("c1", [("only_current", 0.8, True)], 0.8)
        result = compare_reports(baseline, current, tolerance=0.05)
        names = [d.name for d in result.metric_deltas]
        assert "only_baseline" in names
        assert "only_current" in names
        assert len(result.metric_deltas) == 2

    def test_details_propagated_to_deltas(self):
        baseline = _make_report_with_details(
            "b1", [("er", 0.5, True, {"recovery_window": 1, "recovered": 2})], 0.5,
        )
        current = _make_report_with_details(
            "c1", [("er", 0.7, True, {"recovery_window": 5, "recovered": 4})], 0.7,
        )
        result = compare_reports(baseline, current)
        delta = result.metric_deltas[0]
        assert delta.baseline_details == {"recovery_window": 1, "recovered": 2}
        assert delta.current_details == {"recovery_window": 5, "recovered": 4}

    def test_details_none_when_metric_has_empty_details(self):
        baseline = _make_report("b1", [("m1", 0.8, True)], 0.8)
        current = _make_report("c1", [("m1", 0.8, True)], 0.8)
        result = compare_reports(baseline, current)
        delta = result.metric_deltas[0]
        assert delta.baseline_details is None
        assert delta.current_details is None

    def test_details_in_json_serialization(self):
        baseline = _make_report_with_details(
            "b1", [("m1", 0.8, True, {"key": "val"})], 0.8,
        )
        current = _make_report_with_details(
            "c1", [("m1", 0.9, True, {"key": "new"})], 0.9,
        )
        result = compare_reports(baseline, current)
        data = result.model_dump()
        assert data["metric_deltas"][0]["baseline_details"] == {"key": "val"}
        assert data["metric_deltas"][0]["current_details"] == {"key": "new"}

    def test_misaligned_metric_details_none_for_missing_side(self):
        baseline = _make_report_with_details(
            "b1", [("m1", 0.8, True, {"info": 42})], 0.8,
        )
        current = _make_report("c1", [("m1", 0.7, True)], 0.7)
        result = compare_reports(baseline, current)
        delta = result.metric_deltas[0]
        assert delta.baseline_details == {"info": 42}
        assert delta.current_details is None


class TestFormatMarkdown:
    def test_no_regression_header(self):
        result = ComparisonResult(
            baseline_trace_id="b1",
            current_trace_id="c1",
            metric_deltas=[],
            overall_delta=0.0,
            has_regression=False,
        )
        md = format_markdown(result)
        assert "No Regression" in md
        assert "b1" in md
        assert "c1" in md

    def test_regression_header(self):
        result = ComparisonResult(
            baseline_trace_id="b1",
            current_trace_id="c1",
            metric_deltas=[MetricDelta(
                name="m1", baseline_score=0.9, current_score=0.5,
                delta=-0.4, direction="regressed", is_regression=True,
            )],
            overall_delta=-0.4,
            has_regression=True,
        )
        md = format_markdown(result)
        assert "REGRESSION DETECTED" in md

    def test_markdown_table_format(self):
        result = ComparisonResult(
            baseline_trace_id="b1",
            current_trace_id="c1",
            metric_deltas=[
                MetricDelta(name="m1", baseline_score=0.8, current_score=0.9,
                            delta=0.1, direction="improved", is_regression=False),
                MetricDelta(name="m2", baseline_score=0.9, current_score=0.7,
                            delta=-0.2, direction="regressed", is_regression=True),
            ],
            overall_delta=-0.05,
            has_regression=True,
        )
        md = format_markdown(result)
        assert "| Metric |" in md
        assert "| m1 |" in md
        assert "| m2 |" in md
        assert "Improved" in md
        assert "Regressed" in md

    def test_positive_delta_has_plus_sign(self):
        result = ComparisonResult(
            baseline_trace_id="b1",
            current_trace_id="c1",
            metric_deltas=[MetricDelta(
                name="m1", baseline_score=0.5, current_score=0.8,
                delta=0.3, direction="improved", is_regression=False,
            )],
            overall_delta=0.3,
            has_regression=False,
        )
        md = format_markdown(result)
        assert "+0.30" in md

    def test_tolerance_shown(self):
        result = ComparisonResult(
            baseline_trace_id="b1",
            current_trace_id="c1",
            metric_deltas=[],
            overall_delta=0.0,
            has_regression=False,
            tolerance=0.1,
        )
        md = format_markdown(result)
        assert "10%" in md

    def test_details_rendered_when_present(self):
        result = ComparisonResult(
            baseline_trace_id="b1",
            current_trace_id="c1",
            metric_deltas=[MetricDelta(
                name="error_recovery", baseline_score=0.8, current_score=0.9,
                delta=0.1, direction="improved", is_regression=False,
                baseline_details={"total_errors": 3, "recovered": 2},
                current_details={"total_errors": 3, "recovered": 3},
            )],
            overall_delta=0.1,
            has_regression=False,
        )
        md = format_markdown(result)
        assert "<details><summary>error_recovery details</summary>" in md
        assert "**Baseline**:" in md
        assert "- total_errors: 3" in md
        assert "- recovered: 2" in md
        assert "**Current**:" in md
        assert "- recovered: 3" in md
        assert "</details>" in md

    def test_details_baseline_current_separated_by_blank_line(self):
        result = ComparisonResult(
            baseline_trace_id="b1",
            current_trace_id="c1",
            metric_deltas=[MetricDelta(
                name="m1", baseline_score=0.8, current_score=0.9,
                delta=0.1, direction="improved", is_regression=False,
                baseline_details={"a": 1},
                current_details={"a": 2},
            )],
            overall_delta=0.1,
            has_regression=False,
        )
        md = format_markdown(result)
        lines = md.split("\n")
        baseline_items = [i for i, l in enumerate(lines) if l.startswith("- a:")]
        current_label = [i for i, l in enumerate(lines) if l == "**Current**:"]
        assert len(baseline_items) >= 1
        assert len(current_label) == 1
        assert lines[current_label[0] - 1] == ""

    def test_no_details_section_when_none(self):
        result = ComparisonResult(
            baseline_trace_id="b1",
            current_trace_id="c1",
            metric_deltas=[MetricDelta(
                name="m1", baseline_score=0.8, current_score=0.9,
                delta=0.1, direction="improved", is_regression=False,
            )],
            overall_delta=0.1,
            has_regression=False,
        )
        md = format_markdown(result)
        assert "<details>" not in md

    def test_details_one_side_only(self):
        result = ComparisonResult(
            baseline_trace_id="b1",
            current_trace_id="c1",
            metric_deltas=[MetricDelta(
                name="token_efficiency", baseline_score=0.7, current_score=0.0,
                delta=-0.7, direction="regressed", is_regression=True,
                baseline_details={"total_tokens": 500, "mode": "heuristic"},
                current_details=None,
            )],
            overall_delta=-0.7,
            has_regression=True,
        )
        md = format_markdown(result)
        assert "<details><summary>token_efficiency details</summary>" in md
        assert "**Baseline**:" in md
        assert "- total_tokens: 500" in md
        details_block = md.split("<details>")[1]
        assert "**Current**:" not in details_block

    def test_details_multiple_metrics(self):
        result = ComparisonResult(
            baseline_trace_id="b1",
            current_trace_id="c1",
            metric_deltas=[
                MetricDelta(
                    name="m1", baseline_score=0.8, current_score=0.9,
                    delta=0.1, direction="improved", is_regression=False,
                    baseline_details={"key": "val1"},
                    current_details={"key": "val2"},
                ),
                MetricDelta(
                    name="m2", baseline_score=0.5, current_score=0.5,
                    delta=0.0, direction="unchanged", is_regression=False,
                ),
                MetricDelta(
                    name="m3", baseline_score=0.9, current_score=0.7,
                    delta=-0.2, direction="regressed", is_regression=True,
                    baseline_details={"info": 42},
                    current_details={"info": 10},
                ),
            ],
            overall_delta=-0.03,
            has_regression=True,
        )
        md = format_markdown(result)
        assert md.count("<details>") == 2
        assert "m1 details" in md
        assert "m3 details" in md
        assert "m2 details" not in md
