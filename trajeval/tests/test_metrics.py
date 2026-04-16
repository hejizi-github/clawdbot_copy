"""Tests for deterministic metrics engine."""

from trajeval.ingester import ingest_json
from trajeval.metrics import (
    EvalReport,
    MetricConfig,
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

    def test_loop_trace_fixture(self):
        trace = ingest_json("tests/fixtures/loop_trace.json")
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
        assert len(report.metrics) == 4
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
