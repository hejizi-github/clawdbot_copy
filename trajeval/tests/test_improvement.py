"""Tests for improvement loop analysis."""

from trajeval.improvement import (
    Finding,
    ImprovementReport,
    Priority,
    Recommendation,
    analyze_results,
)
from trajeval.metrics import EvalReport, MetricResult


def _report(
    trace_id: str,
    metrics: list[tuple[str, float, bool]],
    timestamp: float | None = None,
) -> EvalReport:
    return EvalReport(
        trace_id=trace_id,
        metrics=[
            MetricResult(name=n, score=s, passed=p) for n, s, p in metrics
        ],
        overall_score=sum(s for _, s, _ in metrics) / len(metrics) if metrics else 0.0,
        passed=all(p for _, _, p in metrics),
        timestamp=timestamp,
    )


class TestAnalyzeResultsEmpty:
    def test_empty_list(self):
        report = analyze_results([])
        assert report.num_evaluations == 0
        assert report.findings == []
        assert report.recommendations == []

    def test_single_passing_report(self):
        reports = [_report("t1", [("step_efficiency", 0.9, True), ("tool_accuracy", 0.95, True)])]
        report = analyze_results(reports)
        assert report.num_evaluations == 1
        assert len(report.findings) == 0
        assert len(report.recommendations) == 0
        assert "step_efficiency" in report.metric_summary
        assert "tool_accuracy" in report.metric_summary


class TestConsistentFailure:
    def test_high_fail_rate_generates_high_priority(self):
        reports = [
            _report(f"t{i}", [("tool_accuracy", 0.3, False)])
            for i in range(4)
        ]
        report = analyze_results(reports)
        assert any(f.metric == "tool_accuracy" and f.pattern == "consistently_failing" for f in report.findings)
        assert any(r.priority == Priority.HIGH and "tool_accuracy" in r.title for r in report.recommendations)

    def test_medium_fail_rate_generates_medium_priority(self):
        reports = [
            _report(f"t{i}", [("loop_detection", 0.4, False)])
            for i in range(4)
        ] + [
            _report(f"t{i}", [("loop_detection", 0.8, True)])
            for i in range(4, 10)
        ]
        report = analyze_results(reports)
        fail_findings = [f for f in report.findings if f.metric == "loop_detection" and f.pattern == "frequently_failing"]
        assert len(fail_findings) == 1, "40% fail rate should trigger medium threshold (>= 30%)"
        assert fail_findings[0].severity == Priority.MEDIUM
        recs = [r for r in report.recommendations if "loop_detection" in r.title]
        assert any(r.priority == Priority.MEDIUM for r in recs)

    def test_exact_medium_threshold(self):
        reports = [
            _report("t1", [("loop_detection", 0.4, False)]),
            _report("t2", [("loop_detection", 0.4, False)]),
            _report("t3", [("loop_detection", 0.4, False)]),
            _report("t4", [("loop_detection", 0.8, True)]),
            _report("t5", [("loop_detection", 0.8, True)]),
            _report("t6", [("loop_detection", 0.8, True)]),
            _report("t7", [("loop_detection", 0.8, True)]),
        ]
        report = analyze_results(reports)
        fail_rate = report.metric_summary["loop_detection"]["fail_rate"]
        assert abs(fail_rate - 3/7) < 0.01
        fail_findings = [f for f in report.findings if f.metric == "loop_detection" and f.pattern == "frequently_failing"]
        assert len(fail_findings) == 1, "3/7 ≈ 42.8% fail rate should trigger medium threshold (>= 30%)"
        assert fail_findings[0].severity == Priority.MEDIUM
        recs = [r for r in report.recommendations if "loop_detection" in r.title]
        assert any(r.priority == Priority.MEDIUM for r in recs)

    def test_all_passing_no_failure_finding(self):
        reports = [
            _report(f"t{i}", [("step_efficiency", 0.9, True)])
            for i in range(5)
        ]
        report = analyze_results(reports)
        fail_findings = [f for f in report.findings if f.pattern in ("consistently_failing", "frequently_failing")]
        assert len(fail_findings) == 0


class TestTrendDetection:
    def test_declining_trend_detected(self):
        reports = [
            _report("t1", [("tool_accuracy", 0.95, True)]),
            _report("t2", [("tool_accuracy", 0.9, True)]),
            _report("t3", [("tool_accuracy", 0.85, True)]),
            _report("t4", [("tool_accuracy", 0.6, False)]),
            _report("t5", [("tool_accuracy", 0.55, False)]),
            _report("t6", [("tool_accuracy", 0.5, False)]),
        ]
        report = analyze_results(reports)
        declining = [f for f in report.findings if f.pattern == "declining"]
        assert len(declining) == 1
        assert declining[0].metric == "tool_accuracy"

    def test_no_trend_with_two_reports(self):
        reports = [
            _report("t1", [("tool_accuracy", 0.95, True)]),
            _report("t2", [("tool_accuracy", 0.5, False)]),
        ]
        report = analyze_results(reports)
        declining = [f for f in report.findings if f.pattern == "declining"]
        assert len(declining) == 0, "Need >= 3 reports for trend detection"

    def test_improving_trend_not_flagged(self):
        reports = [
            _report("t1", [("step_efficiency", 0.5, False)]),
            _report("t2", [("step_efficiency", 0.6, False)]),
            _report("t3", [("step_efficiency", 0.7, True)]),
            _report("t4", [("step_efficiency", 0.8, True)]),
            _report("t5", [("step_efficiency", 0.9, True)]),
        ]
        report = analyze_results(reports)
        declining = [f for f in report.findings if f.pattern == "declining"]
        assert len(declining) == 0

    def test_timestamp_sorting_corrects_shuffled_input(self):
        reports = [
            _report("t5", [("tool_accuracy", 0.5, False)], timestamp=5.0),
            _report("t1", [("tool_accuracy", 0.95, True)], timestamp=1.0),
            _report("t6", [("tool_accuracy", 0.45, False)], timestamp=6.0),
            _report("t2", [("tool_accuracy", 0.9, True)], timestamp=2.0),
            _report("t4", [("tool_accuracy", 0.6, False)], timestamp=4.0),
            _report("t3", [("tool_accuracy", 0.85, True)], timestamp=3.0),
        ]
        report = analyze_results(reports)
        declining = [f for f in report.findings if f.pattern == "declining"]
        assert len(declining) == 1
        assert declining[0].metric == "tool_accuracy"

    def test_partial_timestamps_preserves_input_order(self):
        reports = [
            _report("t1", [("step_efficiency", 0.5, False)], timestamp=3.0),
            _report("t2", [("step_efficiency", 0.9, True)]),
            _report("t3", [("step_efficiency", 0.85, True)], timestamp=1.0),
        ]
        report = analyze_results(reports)
        assert report.metric_summary["step_efficiency"]["trend"] is not None


class TestHighVariance:
    def test_high_variance_flagged(self):
        reports = [
            _report("t1", [("loop_detection", 0.2, False)]),
            _report("t2", [("loop_detection", 0.9, True)]),
            _report("t3", [("loop_detection", 0.3, False)]),
            _report("t4", [("loop_detection", 0.95, True)]),
        ]
        report = analyze_results(reports)
        variance_findings = [f for f in report.findings if f.pattern == "high_variance"]
        assert len(variance_findings) == 1
        assert variance_findings[0].severity == Priority.LOW

    def test_low_variance_not_flagged(self):
        reports = [
            _report(f"t{i}", [("step_efficiency", 0.85 + i * 0.01, True)])
            for i in range(5)
        ]
        report = analyze_results(reports)
        variance_findings = [f for f in report.findings if f.pattern == "high_variance"]
        assert len(variance_findings) == 0


class TestMetricSummary:
    def test_summary_has_required_fields(self):
        reports = [
            _report("t1", [("step_efficiency", 0.9, True)]),
            _report("t2", [("step_efficiency", 0.8, True)]),
            _report("t3", [("step_efficiency", 0.85, True)]),
        ]
        report = analyze_results(reports)
        summary = report.metric_summary["step_efficiency"]
        assert "mean_score" in summary
        assert "fail_rate" in summary
        assert "std_dev" in summary
        assert "num_evaluations" in summary
        assert "trend" in summary
        assert summary["num_evaluations"] == 3
        assert summary["fail_rate"] == 0.0

    def test_single_report_no_trend(self):
        reports = [_report("t1", [("tool_accuracy", 0.8, True)])]
        report = analyze_results(reports)
        assert "trend" not in report.metric_summary["tool_accuracy"]

    def test_mean_score_correct(self):
        reports = [
            _report("t1", [("step_efficiency", 0.6, False)]),
            _report("t2", [("step_efficiency", 0.8, True)]),
        ]
        report = analyze_results(reports)
        assert report.metric_summary["step_efficiency"]["mean_score"] == 0.7


class TestRecommendationOrdering:
    def test_high_priority_first(self):
        reports = [
            _report(f"t{i}", [
                ("tool_accuracy", 0.2, False),
                ("step_efficiency", 0.9, True),
            ])
            for i in range(5)
        ]
        report = analyze_results(reports)
        if len(report.recommendations) >= 2:
            priorities = [r.priority for r in report.recommendations]
            high_indices = [i for i, p in enumerate(priorities) if p == Priority.HIGH]
            medium_indices = [i for i, p in enumerate(priorities) if p == Priority.MEDIUM]
            low_indices = [i for i, p in enumerate(priorities) if p == Priority.LOW]
            if high_indices and medium_indices:
                assert max(high_indices) < min(medium_indices)
            if medium_indices and low_indices:
                assert max(medium_indices) < min(low_indices)


class TestMultipleMetrics:
    def test_independent_analysis_per_metric(self):
        reports = [
            _report("t1", [("step_efficiency", 0.9, True), ("tool_accuracy", 0.3, False)]),
            _report("t2", [("step_efficiency", 0.85, True), ("tool_accuracy", 0.25, False)]),
            _report("t3", [("step_efficiency", 0.88, True), ("tool_accuracy", 0.2, False)]),
        ]
        report = analyze_results(reports)
        assert "step_efficiency" in report.metric_summary
        assert "tool_accuracy" in report.metric_summary
        efficiency_findings = [f for f in report.findings if f.metric == "step_efficiency"]
        accuracy_findings = [f for f in report.findings if f.metric == "tool_accuracy"]
        assert len(efficiency_findings) == 0
        assert len(accuracy_findings) > 0


class TestLowScoring:
    def test_low_score_without_high_fail_rate(self):
        reports = [
            _report("t1", [("step_efficiency", 0.45, True)]),
            _report("t2", [("step_efficiency", 0.48, True)]),
            _report("t3", [("step_efficiency", 0.42, True)]),
        ]
        report = analyze_results(reports)
        low_findings = [f for f in report.findings if f.pattern == "low_scoring"]
        assert len(low_findings) == 1
        assert low_findings[0].severity == Priority.MEDIUM


class TestModelSerialization:
    def test_finding_model(self):
        f = Finding(metric="test", pattern="low", severity=Priority.HIGH, evidence="bad")
        d = f.model_dump()
        assert d["severity"] == "high"

    def test_recommendation_model(self):
        r = Recommendation(title="Fix X", priority=Priority.MEDIUM, finding="Y", suggestion="Z")
        d = r.model_dump()
        assert d["priority"] == "medium"

    def test_report_to_json(self):
        report = ImprovementReport(
            num_evaluations=3,
            findings=[Finding(metric="x", pattern="low", severity=Priority.LOW, evidence="e")],
            recommendations=[Recommendation(title="t", priority=Priority.LOW, finding="f", suggestion="s")],
        )
        d = report.model_dump()
        assert d["num_evaluations"] == 3
        assert len(d["findings"]) == 1
        assert len(d["recommendations"]) == 1


class TestSpecificAdvice:
    def test_tool_accuracy_advice_content(self):
        reports = [
            _report(f"t{i}", [("tool_accuracy", 0.2, False)])
            for i in range(4)
        ]
        report = analyze_results(reports)
        recs = [r for r in report.recommendations if "tool_accuracy" in r.title]
        assert len(recs) > 0
        assert "tool" in recs[0].suggestion.lower()

    def test_loop_detection_advice_content(self):
        reports = [
            _report(f"t{i}", [("loop_detection", 0.15, False)])
            for i in range(4)
        ]
        report = analyze_results(reports)
        recs = [r for r in report.recommendations if "loop_detection" in r.title]
        assert len(recs) > 0
        assert "loop" in recs[0].suggestion.lower() or "repetitive" in recs[0].suggestion.lower()

    def test_unknown_metric_gets_generic_advice(self):
        reports = [
            _report(f"t{i}", [("custom_metric_xyz", 0.1, False)])
            for i in range(4)
        ]
        report = analyze_results(reports)
        recs = [r for r in report.recommendations if "custom_metric_xyz" in r.title]
        assert len(recs) > 0
