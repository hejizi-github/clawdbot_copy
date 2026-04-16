"""Tests for core data models."""

from trajeval.models import AgentTrace, TokenUsage, TraceStep


class TestTokenUsage:
    def test_defaults(self):
        t = TokenUsage()
        assert t.prompt == 0
        assert t.completion == 0
        assert t.total == 0

    def test_explicit_values(self):
        t = TokenUsage(prompt=100, completion=50, total=150)
        assert t.prompt == 100
        assert t.total == 150


class TestTraceStep:
    def test_minimal_step(self):
        step = TraceStep(type="tool_call", name="read_file")
        assert step.type == "tool_call"
        assert step.input == {}
        assert step.tokens is None

    def test_full_step(self):
        step = TraceStep(
            type="llm_call",
            name="claude-3",
            input={"prompt": "hello"},
            output={"response": "hi"},
            duration_ms=500.0,
            tokens=TokenUsage(prompt=10, completion=5, total=15),
        )
        assert step.duration_ms == 500.0
        assert step.tokens.total == 15


class TestAgentTrace:
    def test_step_count(self):
        trace = AgentTrace(
            trace_id="t1",
            steps=[
                TraceStep(type="llm_call", name="m1"),
                TraceStep(type="tool_call", name="t1"),
            ],
        )
        assert trace.step_count == 2

    def test_filtered_steps(self):
        trace = AgentTrace(
            trace_id="t2",
            steps=[
                TraceStep(type="llm_call", name="m1"),
                TraceStep(type="tool_call", name="read"),
                TraceStep(type="error", name="timeout"),
                TraceStep(type="tool_call", name="write"),
            ],
        )
        assert len(trace.tool_calls) == 2
        assert len(trace.llm_calls) == 1
        assert len(trace.errors) == 1

    def test_empty_trace(self):
        trace = AgentTrace(trace_id="empty")
        assert trace.step_count == 0
        assert trace.tool_calls == []
        assert trace.agent_name == "unknown"
