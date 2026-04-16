"""Tests for deterministic metrics engine."""

import pytest

from trajeval.ingester import ingest_json
from trajeval.metrics import (
    EvalReport,
    MetricConfig,
    error_recovery,
    evaluate,
    loop_detection,
    step_efficiency,
    token_efficiency,
    tool_accuracy,
)
from trajeval.models import AgentTrace, TokenUsage, TraceStep


class TestStepEfficiency:
    def test_empty_trace(self):
        trace = AgentTrace(trace_id="e1")
        result = step_efficiency(trace)
        assert result.score == 1.0
        assert result.passed is True

    def test_all_productive(self):
        trace = AgentTrace(
            trace_id="p1",
            steps=[
                TraceStep(type="llm_call", name="m1"),
                TraceStep(type="tool_call", name="t1"),
            ],
        )
        result = step_efficiency(trace)
        assert result.score == 1.0

    def test_with_errors(self):
        trace = AgentTrace(
            trace_id="err1",
            steps=[
                TraceStep(type="llm_call", name="m1"),
                TraceStep(type="error", name="fail"),
                TraceStep(type="tool_call", name="t1"),
                TraceStep(type="error", name="fail2"),
            ],
        )
        result = step_efficiency(trace)
        assert result.score == 0.5
        assert result.passed is False

    def test_with_baseline_efficient(self):
        trace = AgentTrace(
            trace_id="b1",
            steps=[TraceStep(type="llm_call", name="m1") for _ in range(3)],
        )
        result = step_efficiency(trace, expected_steps=3)
        assert result.score == 1.0

    def test_with_baseline_inefficient(self):
        trace = AgentTrace(
            trace_id="b2",
            steps=[TraceStep(type="llm_call", name="m1") for _ in range(10)],
        )
        result = step_efficiency(trace, expected_steps=3)
        assert result.score == 0.3
        assert result.passed is False

    def test_with_baseline_capped_at_one(self):
        trace = AgentTrace(
            trace_id="b3",
            steps=[TraceStep(type="llm_call", name="m1") for _ in range(2)],
        )
        result = step_efficiency(trace, expected_steps=5)
        assert result.score == 1.0


class TestToolAccuracy:
    def test_no_tool_calls(self):
        trace = AgentTrace(
            trace_id="nt1",
            steps=[TraceStep(type="llm_call", name="m1")],
        )
        result = tool_accuracy(trace)
        assert result.score == 1.0

    def test_all_successful(self, simple_trace_path):
        trace = ingest_json(simple_trace_path)
        result = tool_accuracy(trace)
        assert result.score == 1.0
        assert result.details["total_tool_calls"] == 1

    def test_tool_followed_by_error(self, error_trace_path):
        trace = ingest_json(error_trace_path)
        result = tool_accuracy(trace)
        assert result.details["failed"] == 1
        assert result.details["total_tool_calls"] == 3

    def test_tool_with_error_output(self):
        trace = AgentTrace(
            trace_id="eo1",
            steps=[
                TraceStep(
                    type="tool_call",
                    name="api_call",
                    output={"error": "timeout"},
                ),
                TraceStep(
                    type="tool_call",
                    name="api_call",
                    output={"result": "ok"},
                ),
            ],
        )
        result = tool_accuracy(trace)
        assert result.score == 0.5
        assert result.details["failed"] == 1


class TestLoopDetection:
    def test_no_loops(self, simple_trace_path):
        trace = ingest_json(simple_trace_path)
        result = loop_detection(trace)
        assert result.score == 1.0
        assert result.details["loops_found"] == []

    def test_single_step(self):
        trace = AgentTrace(
            trace_id="s1",
            steps=[TraceStep(type="llm_call", name="m1")],
        )
        result = loop_detection(trace)
        assert result.score == 1.0

    def test_detects_bigram_loop(self):
        trace = AgentTrace(
            trace_id="loop1",
            steps=[
                TraceStep(type="llm_call", name="think"),
                TraceStep(type="tool_call", name="search"),
                TraceStep(type="llm_call", name="think"),
                TraceStep(type="tool_call", name="search"),
                TraceStep(type="llm_call", name="think"),
                TraceStep(type="tool_call", name="search"),
            ],
        )
        result = loop_detection(trace)
        assert result.score < 1.0
        assert len(result.details["loops_found"]) > 0

    def test_loop_trace_fixture(self, loop_trace_path):
        trace = ingest_json(loop_trace_path)
        result = loop_detection(trace)
        assert result.score < 1.0
        patterns = [entry["pattern"] for entry in result.details["loops_found"]]
        bigrams = [p for p in patterns if len(p) == 2]
        assert any("search_files" in bg for bg in bigrams)

    def test_empty_trace(self):
        trace = AgentTrace(trace_id="e1")
        result = loop_detection(trace)
        assert result.score == 1.0


class TestTokenEfficiency:
    def test_no_tokens(self):
        trace = AgentTrace(trace_id="nt1")
        result = token_efficiency(trace)
        assert result.score == 1.0
        assert result.details["mode"] == "no_tokens"

    def test_with_baseline_efficient(self):
        trace = AgentTrace(
            trace_id="te1",
            total_tokens=TokenUsage(prompt=500, completion=200, total=700),
        )
        result = token_efficiency(trace, baseline_tokens=700)
        assert result.score == 1.0

    def test_with_baseline_inefficient(self):
        trace = AgentTrace(
            trace_id="te2",
            total_tokens=TokenUsage(prompt=800, completion=400, total=1200),
        )
        result = token_efficiency(trace, baseline_tokens=600)
        assert result.score == 0.5
        assert result.passed is False

    def test_heuristic_all_productive(self, simple_trace_path):
        trace = ingest_json(simple_trace_path)
        result = token_efficiency(trace)
        assert result.score == 1.0
        assert result.details["mode"] == "heuristic"

    def test_heuristic_with_error_tokens(self):
        trace = AgentTrace(
            trace_id="het1",
            steps=[
                TraceStep(
                    type="llm_call",
                    name="m1",
                    tokens=TokenUsage(prompt=100, completion=50, total=150),
                ),
                TraceStep(
                    type="error",
                    name="fail",
                    tokens=TokenUsage(prompt=100, completion=50, total=150),
                ),
            ],
            total_tokens=TokenUsage(prompt=200, completion=100, total=300),
        )
        result = token_efficiency(trace)
        assert result.score == 0.5
        assert result.details["error_tokens"] == 150


class TestEvaluate:
    def test_simple_trace(self, simple_trace_path):
        trace = ingest_json(simple_trace_path)
        report = evaluate(trace)
        assert isinstance(report, EvalReport)
        assert report.trace_id == "test-trace-001"
        assert len(report.metrics) == 5
        assert report.overall_score > 0.0

    def test_all_pass(self, simple_trace_path):
        trace = ingest_json(simple_trace_path)
        report = evaluate(trace)
        assert report.passed is True
        for m in report.metrics:
            assert m.passed is True

    def test_with_config(self):
        trace = AgentTrace(
            trace_id="cfg1",
            steps=[TraceStep(type="llm_call", name="m1") for _ in range(10)],
            total_tokens=TokenUsage(prompt=1000, completion=500, total=1500),
        )
        config = MetricConfig(expected_steps=3, baseline_tokens=500)
        report = evaluate(trace, config)
        step_metric = next(m for m in report.metrics if m.name == "step_efficiency")
        token_metric = next(m for m in report.metrics if m.name == "token_efficiency")
        assert step_metric.score == 0.3
        assert token_metric.score < 0.5

    def test_empty_trace(self):
        trace = AgentTrace(trace_id="empty")
        report = evaluate(trace)
        assert report.passed is True
        assert report.overall_score == 1.0

    def test_threshold_low_passes(self):
        """A score of 0.5 passes with threshold=0.4 but fails with default 0.7."""
        trace = AgentTrace(
            trace_id="th1",
            steps=[
                TraceStep(type="llm_call", name="m1"),
                TraceStep(type="error", name="fail"),
            ],
            total_tokens=TokenUsage(prompt=100, completion=50, total=150),
        )
        default_report = evaluate(trace)
        step_m = next(m for m in default_report.metrics if m.name == "step_efficiency")
        assert step_m.score == 0.5
        assert step_m.passed is False

        low_config = MetricConfig(pass_threshold=0.4)
        low_report = evaluate(trace, low_config)
        step_m_low = next(m for m in low_report.metrics if m.name == "step_efficiency")
        assert step_m_low.score == 0.5
        assert step_m_low.passed is True

    def test_threshold_high_fails(self):
        """A score of 0.75 passes with default 0.7 but fails with threshold=0.9."""
        trace = AgentTrace(
            trace_id="th2",
            steps=[
                TraceStep(type="llm_call", name="m1"),
                TraceStep(type="tool_call", name="t1"),
                TraceStep(type="tool_call", name="t2"),
                TraceStep(type="error", name="fail"),
            ],
            total_tokens=TokenUsage(prompt=100, completion=50, total=150),
        )
        default_report = evaluate(trace)
        step_m = next(m for m in default_report.metrics if m.name == "step_efficiency")
        assert step_m.score == 0.75
        assert step_m.passed is True

        high_config = MetricConfig(pass_threshold=0.9)
        high_report = evaluate(trace, high_config)
        step_m_high = next(m for m in high_report.metrics if m.name == "step_efficiency")
        assert step_m_high.score == 0.75
        assert step_m_high.passed is False


class TestErrorRecovery:
    def test_no_errors(self):
        trace = AgentTrace(
            trace_id="r1",
            steps=[
                TraceStep(type="llm_call", name="m1"),
                TraceStep(type="tool_call", name="t1"),
            ],
        )
        result = error_recovery(trace)
        assert result.name == "error_recovery"
        assert result.score == 1.0
        assert result.passed is True
        assert result.details["total_errors"] == 0

    def test_empty_trace(self):
        trace = AgentTrace(trace_id="r2")
        result = error_recovery(trace)
        assert result.score == 1.0
        assert result.details["total_errors"] == 0

    def test_full_recovery(self):
        trace = AgentTrace(
            trace_id="r3",
            steps=[
                TraceStep(type="error", name="fail1"),
                TraceStep(type="llm_call", name="retry1"),
                TraceStep(type="error", name="fail2"),
                TraceStep(type="tool_call", name="fix2"),
            ],
        )
        result = error_recovery(trace)
        assert result.score == 1.0
        assert result.details["recovered"] == 2
        assert result.details["unrecovered"] == 0

    def test_no_recovery(self):
        trace = AgentTrace(
            trace_id="r4",
            steps=[
                TraceStep(type="tool_call", name="t1"),
                TraceStep(type="error", name="fail1"),
                TraceStep(type="error", name="fail2"),
                TraceStep(type="error", name="fail3"),
            ],
        )
        result = error_recovery(trace)
        assert result.score == 0.0
        assert result.passed is False
        assert result.details["total_errors"] == 3
        assert result.details["recovered"] == 0

    def test_partial_recovery(self):
        trace = AgentTrace(
            trace_id="r5",
            steps=[
                TraceStep(type="error", name="fail1"),
                TraceStep(type="tool_call", name="fix1"),
                TraceStep(type="error", name="fail2"),
                TraceStep(type="error", name="fail3"),
            ],
        )
        result = error_recovery(trace)
        assert result.details["total_errors"] == 3
        assert result.details["recovered"] == 1
        assert result.score == pytest.approx(1 / 3, abs=0.01)
        assert result.passed is False

    def test_recovery_within_window(self):
        trace = AgentTrace(
            trace_id="r6",
            steps=[
                TraceStep(type="error", name="fail"),
                TraceStep(type="error", name="still_failing"),
                TraceStep(type="error", name="still_failing2"),
                TraceStep(type="tool_call", name="recovered"),
            ],
        )
        result = error_recovery(trace, recovery_window=3)
        assert result.details["total_errors"] == 3
        assert result.details["recovered"] == 3

    def test_recovery_outside_window(self):
        trace = AgentTrace(
            trace_id="r7",
            steps=[
                TraceStep(type="error", name="fail"),
                TraceStep(type="error", name="e2"),
                TraceStep(type="error", name="e3"),
                TraceStep(type="error", name="e4"),
                TraceStep(type="tool_call", name="too_late"),
            ],
        )
        result = error_recovery(trace, recovery_window=2)
        first_error_recovered = result.details["recovered"]
        assert first_error_recovered < result.details["total_errors"]

    def test_custom_window_size(self):
        trace = AgentTrace(
            trace_id="r8",
            steps=[
                TraceStep(type="error", name="fail"),
                TraceStep(type="error", name="e2"),
                TraceStep(type="error", name="e3"),
                TraceStep(type="error", name="e4"),
                TraceStep(type="error", name="e5"),
                TraceStep(type="tool_call", name="fix"),
            ],
        )
        narrow = error_recovery(trace, recovery_window=1)
        wide = error_recovery(trace, recovery_window=5)
        assert wide.details["recovered"] >= narrow.details["recovered"]

    def test_error_at_end_of_trace(self):
        trace = AgentTrace(
            trace_id="r9",
            steps=[
                TraceStep(type="tool_call", name="t1"),
                TraceStep(type="error", name="final_error"),
            ],
        )
        result = error_recovery(trace)
        assert result.details["total_errors"] == 1
        assert result.details["recovered"] == 0
        assert result.score == 0.0

    def test_evaluate_includes_error_recovery(self):
        trace = AgentTrace(
            trace_id="r10",
            steps=[
                TraceStep(type="tool_call", name="t1"),
                TraceStep(type="error", name="fail"),
                TraceStep(type="tool_call", name="fix"),
            ],
            total_tokens=TokenUsage(prompt=100, completion=50, total=150),
        )
        report = evaluate(trace)
        metric_names = {m.name for m in report.metrics}
        assert "error_recovery" in metric_names
        recovery_m = next(m for m in report.metrics if m.name == "error_recovery")
        assert recovery_m.score == 1.0

    def test_evaluate_threshold_applies_to_error_recovery(self):
        trace = AgentTrace(
            trace_id="r11",
            steps=[
                TraceStep(type="error", name="fail1"),
                TraceStep(type="tool_call", name="fix1"),
                TraceStep(type="error", name="fail2"),
                TraceStep(type="error", name="fail3"),
                TraceStep(type="error", name="fail4"),
            ],
            total_tokens=TokenUsage(prompt=100, completion=50, total=150),
        )
        low = MetricConfig(pass_threshold=0.2)
        high = MetricConfig(pass_threshold=0.9)
        low_report = evaluate(trace, low)
        high_report = evaluate(trace, high)
        low_m = next(m for m in low_report.metrics if m.name == "error_recovery")
        high_m = next(m for m in high_report.metrics if m.name == "error_recovery")
        assert low_m.passed is True
        assert high_m.passed is False
