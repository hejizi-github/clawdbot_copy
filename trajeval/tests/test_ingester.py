"""Tests for trace ingestion."""

import json
from pathlib import Path

import pytest

from trajeval.ingester import IngestError, ingest_clawdbot_jsonl, ingest_json, ingest_otlp_json


class TestIngestFromFile:
    def test_simple_trace(self, simple_trace_path):
        trace = ingest_json(simple_trace_path)
        assert trace.trace_id == "test-trace-001"
        assert trace.agent_name == "test-agent"
        assert trace.step_count == 3
        assert len(trace.llm_calls) == 2
        assert len(trace.tool_calls) == 1

    def test_minimal_trace(self, minimal_trace_path):
        trace = ingest_json(minimal_trace_path)
        assert trace.trace_id == "minimal-001"
        assert trace.step_count == 0

    def test_error_trace(self, error_trace_path):
        trace = ingest_json(error_trace_path)
        assert len(trace.errors) == 1
        assert len(trace.tool_calls) == 3

    def test_nonexistent_file(self):
        with pytest.raises(IngestError, match="File not found"):
            ingest_json("/nonexistent/path.json")


class TestIngestFromDict:
    def test_dict_input(self, simple_trace_dict):
        trace = ingest_json(simple_trace_dict)
        assert trace.trace_id == "dict-trace-001"
        assert trace.step_count == 1

    def test_empty_dict(self):
        trace = ingest_json({"trace_id": "x", "steps": []})
        assert trace.step_count == 0

    def test_auto_trace_id(self):
        trace = ingest_json({"steps": []})
        assert len(trace.trace_id) > 0


class TestIngestFromString:
    def test_json_string(self):
        data = json.dumps({"trace_id": "str-001", "steps": []})
        trace = ingest_json(data)
        assert trace.trace_id == "str-001"

    def test_invalid_json_string(self):
        with pytest.raises(IngestError, match="Invalid JSON"):
            ingest_json("{bad json")


class TestTokenAggregation:
    def test_auto_aggregation(self, simple_trace_path):
        trace = ingest_json(simple_trace_path)
        assert trace.total_tokens.prompt == 620
        assert trace.total_tokens.completion == 230
        assert trace.total_tokens.total == 850

    def test_explicit_total_tokens(self):
        data = {
            "trace_id": "tok-001",
            "steps": [
                {
                    "type": "llm_call",
                    "name": "m1",
                    "tokens": {"prompt": 10, "completion": 5, "total": 15},
                }
            ],
            "total_tokens": {"prompt": 100, "completion": 50, "total": 150},
        }
        trace = ingest_json(data)
        assert trace.total_tokens.total == 150


class TestEdgeCases:
    def test_steps_not_a_list(self):
        with pytest.raises(IngestError, match="must be a list"):
            ingest_json({"trace_id": "x", "steps": "not a list"})

    def test_step_not_a_dict(self):
        with pytest.raises(IngestError, match="expected dict"):
            ingest_json({"trace_id": "x", "steps": ["not a dict"]})

    def test_duration_auto_sum(self):
        data = {
            "trace_id": "dur-001",
            "steps": [
                {"type": "llm_call", "name": "m1", "duration_ms": 100.0},
                {"type": "tool_call", "name": "t1", "duration_ms": 200.0},
            ],
        }
        trace = ingest_json(data)
        assert trace.total_duration_ms == 300.0


def _write_clawdbot_jsonl(path: Path, entries: list[dict]) -> Path:
    """Helper to write Clawdbot JSONL fixture files."""
    path.write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    return path


def _make_session_header(session_id="test-session-001", cwd="/home/user/project"):
    return {
        "type": "session", "version": 3, "id": session_id,
        "timestamp": "2026-04-17T10:00:00Z", "cwd": cwd,
    }


def _make_user_message(content, msg_id="u1", parent_id=None, ts=1000):
    return {
        "type": "message", "id": msg_id, "parentId": parent_id,
        "timestamp": "2026-04-17T10:00:01Z",
        "message": {"role": "user", "content": content, "timestamp": ts},
    }


def _make_assistant_message(
    content_items, model="claude-sonnet-4-6", msg_id="a1",
    parent_id="u1", ts=2000, input_tokens=100, output_tokens=50,
    stop_reason="stop", provider="anthropic", api="anthropic-messages",
):
    return {
        "type": "message", "id": msg_id, "parentId": parent_id,
        "timestamp": "2026-04-17T10:00:02Z",
        "message": {
            "role": "assistant",
            "content": content_items,
            "api": api, "provider": provider, "model": model,
            "usage": {
                "input": input_tokens, "output": output_tokens,
                "cacheRead": 0, "cacheWrite": 0,
                "totalTokens": input_tokens + output_tokens,
                "cost": {"input": 0.001, "output": 0.002, "cacheRead": 0,
                         "cacheWrite": 0, "total": 0.003},
            },
            "stopReason": stop_reason, "timestamp": ts,
        },
    }


def _make_tool_result(tool_call_id, tool_name, content_text, is_error=False, ts=3000):
    return {
        "type": "message", "id": f"tr-{tool_call_id}", "parentId": None,
        "timestamp": "2026-04-17T10:00:03Z",
        "message": {
            "role": "toolResult", "toolCallId": tool_call_id,
            "toolName": tool_name,
            "content": [{"type": "text", "text": content_text}],
            "isError": is_error, "timestamp": ts,
        },
    }


def _make_bash_execution(command, output, exit_code=0, ts=4000):
    return {
        "type": "message", "id": "bash-1", "parentId": None,
        "timestamp": "2026-04-17T10:00:04Z",
        "message": {
            "role": "bashExecution", "command": command, "output": output,
            "exitCode": exit_code, "cancelled": False, "truncated": False,
            "timestamp": ts,
        },
    }


class TestClawdbotBasic:
    def test_simple_text_conversation(self, tmp_path):
        """A user message followed by assistant text response."""
        entries = [
            _make_session_header(),
            _make_user_message("Hello, help me debug this"),
            _make_assistant_message([{"type": "text", "text": "Sure, I can help!"}]),
        ]
        path = _write_clawdbot_jsonl(tmp_path / "session.jsonl", entries)
        trace = ingest_clawdbot_jsonl(path)

        assert trace.trace_id == "test-session-001"
        assert trace.agent_name == "clawdbot"
        assert trace.task == "Hello, help me debug this"
        assert trace.step_count == 1
        assert trace.llm_calls[0].name == "claude-sonnet-4-6"
        assert trace.llm_calls[0].output["text"] == "Sure, I can help!"
        assert trace.llm_calls[0].tokens.prompt == 100
        assert trace.llm_calls[0].tokens.completion == 50
        assert trace.metadata["source_format"] == "clawdbot_jsonl"
        assert trace.metadata["session_id"] == "test-session-001"
        assert trace.metadata["cwd"] == "/home/user/project"
        assert trace.final_output == "Sure, I can help!"

    def test_no_header(self, tmp_path):
        """JSONL without session header still works."""
        entries = [
            _make_user_message("Test"),
            _make_assistant_message([{"type": "text", "text": "Response"}]),
        ]
        path = _write_clawdbot_jsonl(tmp_path / "no_header.jsonl", entries)
        trace = ingest_clawdbot_jsonl(path)

        assert trace.agent_name == "clawdbot"
        assert trace.step_count == 1
        assert len(trace.trace_id) > 0

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.jsonl"
        path.write_text("", encoding="utf-8")
        with pytest.raises(IngestError, match="Empty JSONL"):
            ingest_clawdbot_jsonl(path)

    def test_nonexistent_file(self):
        with pytest.raises(IngestError, match="File not found"):
            ingest_clawdbot_jsonl("/nonexistent/path.jsonl")

    def test_invalid_json_line(self, tmp_path):
        path = tmp_path / "bad.jsonl"
        path.write_text('{"type":"session"}\n{bad json}\n', encoding="utf-8")
        with pytest.raises(IngestError, match="Invalid JSON at line 2"):
            ingest_clawdbot_jsonl(path)


class TestClawdbotToolCalls:
    def test_tool_call_with_result(self, tmp_path):
        """Assistant calls a tool, then toolResult is returned."""
        entries = [
            _make_session_header(),
            _make_user_message("Read the file"),
            _make_assistant_message(
                [
                    {"type": "text", "text": "Let me read that file."},
                    {"type": "toolCall", "id": "tc-1", "name": "Read",
                     "arguments": {"file_path": "/tmp/test.py"}},
                ],
                stop_reason="toolUse", ts=2000,
            ),
            _make_tool_result("tc-1", "Read", "print('hello')", ts=3000),
        ]
        path = _write_clawdbot_jsonl(tmp_path / "tool.jsonl", entries)
        trace = ingest_clawdbot_jsonl(path)

        assert trace.step_count == 2
        llm = trace.llm_calls[0]
        assert llm.output["tool_calls_count"] == 1
        assert llm.output["text"] == "Let me read that file."

        tool = trace.tool_calls[0]
        assert tool.name == "Read"
        assert tool.input == {"file_path": "/tmp/test.py"}
        assert tool.output["text"] == "print('hello')"
        assert tool.output["is_error"] is False
        assert tool.metadata["tool_name"] == "Read"

    def test_tool_call_error(self, tmp_path):
        """Tool returns an error."""
        entries = [
            _make_session_header(),
            _make_user_message("Delete the file"),
            _make_assistant_message(
                [{"type": "toolCall", "id": "tc-2", "name": "Bash",
                  "arguments": {"command": "rm /nonexistent"}}],
                ts=2000,
            ),
            _make_tool_result("tc-2", "Bash", "No such file", is_error=True, ts=3000),
        ]
        path = _write_clawdbot_jsonl(tmp_path / "error_tool.jsonl", entries)
        trace = ingest_clawdbot_jsonl(path)

        tool = trace.tool_calls[0]
        assert tool.output["is_error"] is True
        assert "No such file" in tool.output["text"]

    def test_multiple_tool_calls_in_one_message(self, tmp_path):
        """Assistant message with multiple tool calls."""
        entries = [
            _make_session_header(),
            _make_user_message("Check both files"),
            _make_assistant_message(
                [
                    {"type": "toolCall", "id": "tc-a", "name": "Read",
                     "arguments": {"file_path": "a.py"}},
                    {"type": "toolCall", "id": "tc-b", "name": "Read",
                     "arguments": {"file_path": "b.py"}},
                ],
                ts=2000,
            ),
            _make_tool_result("tc-a", "Read", "content_a", ts=2500),
            _make_tool_result("tc-b", "Read", "content_b", ts=3000),
        ]
        path = _write_clawdbot_jsonl(tmp_path / "multi_tool.jsonl", entries)
        trace = ingest_clawdbot_jsonl(path)

        assert len(trace.tool_calls) == 2
        assert trace.tool_calls[0].input == {"file_path": "a.py"}
        assert trace.tool_calls[0].output["text"] == "content_a"
        assert trace.tool_calls[1].input == {"file_path": "b.py"}
        assert trace.tool_calls[1].output["text"] == "content_b"


class TestClawdbotBashExecution:
    def test_bash_execution(self, tmp_path):
        entries = [
            _make_session_header(),
            _make_user_message("Run tests"),
            _make_assistant_message([{"type": "text", "text": "Running tests..."}], ts=2000),
            _make_bash_execution("pytest tests/", "3 passed", exit_code=0, ts=3000),
        ]
        path = _write_clawdbot_jsonl(tmp_path / "bash.jsonl", entries)
        trace = ingest_clawdbot_jsonl(path)

        bash_steps = [s for s in trace.steps if s.name == "bash"]
        assert len(bash_steps) == 1
        assert bash_steps[0].input == {"command": "pytest tests/"}
        assert bash_steps[0].output["stdout"] == "3 passed"
        assert bash_steps[0].output["exit_code"] == 0
        assert bash_steps[0].output["cancelled"] is False


class TestClawdbotTokensAndDuration:
    def test_token_aggregation(self, tmp_path):
        """Tokens are aggregated across all LLM call steps."""
        entries = [
            _make_session_header(),
            _make_user_message("First question", ts=1000),
            _make_assistant_message(
                [{"type": "text", "text": "Answer 1"}],
                msg_id="a1", ts=2000, input_tokens=100, output_tokens=50,
            ),
            _make_user_message("Second question", msg_id="u2", ts=3000),
            _make_assistant_message(
                [{"type": "text", "text": "Answer 2"}],
                msg_id="a2", ts=4000, input_tokens=200, output_tokens=80,
            ),
        ]
        path = _write_clawdbot_jsonl(tmp_path / "tokens.jsonl", entries)
        trace = ingest_clawdbot_jsonl(path)

        assert trace.total_tokens.prompt == 300
        assert trace.total_tokens.completion == 130
        assert trace.total_tokens.total == 430

    def test_duration_from_timestamps(self, tmp_path):
        """Duration computed from consecutive step timestamps."""
        entries = [
            _make_session_header(),
            _make_user_message("Q", ts=1000),
            _make_assistant_message(
                [{"type": "text", "text": "A1"}], msg_id="a1", ts=2000,
            ),
            _make_user_message("Q2", msg_id="u2", ts=5000),
            _make_assistant_message(
                [{"type": "text", "text": "A2"}], msg_id="a2", ts=6000,
            ),
        ]
        path = _write_clawdbot_jsonl(tmp_path / "duration.jsonl", entries)
        trace = ingest_clawdbot_jsonl(path)

        assert trace.step_count == 2
        assert trace.steps[0].duration_ms == 4000.0  # 6000 - 2000
        assert trace.steps[1].duration_ms == 0.0  # last step, no next


class TestClawdbotComplexSession:
    def test_multi_turn_with_tools(self, tmp_path):
        """Realistic multi-turn conversation with text, tools, and bash."""
        entries = [
            _make_session_header(session_id="complex-001"),
            _make_user_message("Fix the bug in main.py", ts=1000),
            _make_assistant_message(
                [
                    {"type": "text", "text": "Let me read the file first."},
                    {"type": "toolCall", "id": "tc-read", "name": "Read",
                     "arguments": {"file_path": "main.py"}},
                ],
                msg_id="a1", ts=2000, stop_reason="toolUse",
            ),
            _make_tool_result("tc-read", "Read", "def main():\n    return 1/0", ts=2500),
            _make_assistant_message(
                [
                    {"type": "text", "text": "I see the division by zero. Let me fix it."},
                    {"type": "toolCall", "id": "tc-edit", "name": "Edit",
                     "arguments": {"file_path": "main.py", "old": "1/0", "new": "1"}},
                ],
                msg_id="a2", ts=3000, input_tokens=500, output_tokens=120,
                stop_reason="toolUse",
            ),
            _make_tool_result("tc-edit", "Edit", "File edited successfully", ts=3500),
            _make_bash_execution("python main.py", "Success", exit_code=0, ts=4000),
            _make_assistant_message(
                [{"type": "text", "text": "The bug is fixed. The division by zero was replaced."}],
                msg_id="a3", ts=5000, input_tokens=600, output_tokens=30,
            ),
        ]
        path = _write_clawdbot_jsonl(tmp_path / "complex.jsonl", entries)
        trace = ingest_clawdbot_jsonl(path)

        assert trace.trace_id == "complex-001"
        assert trace.task == "Fix the bug in main.py"
        assert trace.step_count == 6  # 3 llm_calls + 2 tool_calls + 1 bash
        assert len(trace.llm_calls) == 3
        assert len(trace.tool_calls) == 3  # 2 tool calls + 1 bash
        assert trace.final_output == "The bug is fixed. The division by zero was replaced."

    def test_user_content_as_list(self, tmp_path):
        """User content can be a list of content blocks."""
        entries = [
            _make_session_header(),
            _make_user_message(
                [{"type": "text", "text": "Check this "}, {"type": "text", "text": "code"}],
                ts=1000,
            ),
            _make_assistant_message([{"type": "text", "text": "OK"}], ts=2000),
        ]
        path = _write_clawdbot_jsonl(tmp_path / "list_content.jsonl", entries)
        trace = ingest_clawdbot_jsonl(path)

        assert trace.task == "Check this  code"

    def test_skips_non_message_entries(self, tmp_path):
        """Non-message entries (compaction, model_change, etc.) are ignored."""
        entries = [
            _make_session_header(),
            {"type": "model_change", "id": "mc-1", "parentId": None,
             "timestamp": "2026-04-17T10:00:00Z", "provider": "anthropic",
             "modelId": "claude-opus-4-6"},
            _make_user_message("Hello", ts=1000),
            {"type": "compaction", "id": "comp-1", "parentId": None,
             "timestamp": "2026-04-17T10:00:00Z", "summary": "compressed",
             "firstKeptEntryId": "u1", "tokensBefore": 5000},
            _make_assistant_message([{"type": "text", "text": "Hi"}], ts=2000),
        ]
        path = _write_clawdbot_jsonl(tmp_path / "mixed.jsonl", entries)
        trace = ingest_clawdbot_jsonl(path)

        assert trace.step_count == 1
        assert trace.llm_calls[0].output["text"] == "Hi"

    def test_assistant_string_content(self, tmp_path):
        """Handle assistant content as plain string (edge case)."""
        entries = [
            _make_session_header(),
            _make_user_message("Test", ts=1000),
            _make_assistant_message("Plain text response", ts=2000),
        ]
        path = _write_clawdbot_jsonl(tmp_path / "string_content.jsonl", entries)
        trace = ingest_clawdbot_jsonl(path)

        assert trace.step_count == 1
        assert trace.llm_calls[0].output["text"] == "Plain text response"

    def test_orphan_tool_result_ignored(self, tmp_path):
        """toolResult with no matching toolCall is silently skipped."""
        entries = [
            _make_session_header(),
            _make_user_message("Test", ts=1000),
            _make_tool_result("nonexistent-tc", "Read", "data", ts=2000),
            _make_assistant_message([{"type": "text", "text": "Done"}], ts=3000),
        ]
        path = _write_clawdbot_jsonl(tmp_path / "orphan.jsonl", entries)
        trace = ingest_clawdbot_jsonl(path)

        assert trace.step_count == 1
        assert len(trace.tool_calls) == 0


# --- OpenTelemetry OTLP JSON ingestion tests ---

OTLP_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _make_otlp_data(spans, service_name="test-agent-svc"):
    """Build a minimal OTLP JSON structure."""
    return {
        "resourceSpans": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": service_name}},
                ],
            },
            "scopeSpans": [{
                "scope": {"name": "genai-instrumentation", "version": "1.0.0"},
                "spans": spans,
            }],
        }],
    }


def _make_otel_span(
    name, span_id="S001", trace_id="TRACE001", parent_span_id=None,
    kind=3, start_ns=1000000000000, end_ns=2000000000000,
    attributes=None, status=None,
):
    span = {
        "traceId": trace_id,
        "spanId": span_id,
        "name": name,
        "kind": kind,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "attributes": attributes or [],
        "status": status or {},
    }
    if parent_span_id:
        span["parentSpanId"] = parent_span_id
    return span


class TestOtlpBasic:
    def test_fixture_file(self):
        """Ingest the full OTLP fixture file."""
        trace = ingest_otlp_json(OTLP_FIXTURES_DIR / "otlp_trace.json")

        assert trace.trace_id == "AAAA1234BBBB5678CCCC9012DDDDEEEE"
        assert trace.agent_name == "code-reviewer"
        assert trace.step_count == 3
        assert len(trace.llm_calls) == 2
        assert len(trace.tool_calls) == 1
        assert trace.metadata["source_format"] == "otlp_json"
        assert trace.metadata["service_name"] == "my-agent-service"

    def test_fixture_tokens(self):
        """Token usage extracted from gen_ai.usage.* attributes."""
        trace = ingest_otlp_json(OTLP_FIXTURES_DIR / "otlp_trace.json")

        assert trace.total_tokens.prompt == 1300  # 500 + 800
        assert trace.total_tokens.completion == 320  # 120 + 200
        assert trace.total_tokens.total == 1620

    def test_fixture_durations(self):
        """Durations computed from startTimeUnixNano/endTimeUnixNano."""
        trace = ingest_otlp_json(OTLP_FIXTURES_DIR / "otlp_trace.json")

        assert trace.steps[0].duration_ms == 2500.0  # 2.5 billion ns = 2500ms
        assert trace.steps[1].duration_ms == 500.0
        assert trace.steps[2].duration_ms == 2000.0

    def test_fixture_tool_call(self):
        """Tool call span has correct name, input, and output."""
        trace = ingest_otlp_json(OTLP_FIXTURES_DIR / "otlp_trace.json")

        tool = trace.tool_calls[0]
        assert tool.name == "Read"
        assert tool.type == "tool_call"
        assert "file_path" in tool.input.get("arguments", "")
        assert "def main" in tool.output.get("result", "")

    def test_fixture_llm_metadata(self):
        """LLM spans have provider and operation in metadata."""
        trace = ingest_otlp_json(OTLP_FIXTURES_DIR / "otlp_trace.json")

        llm = trace.llm_calls[0]
        assert llm.metadata["provider"] == "anthropic"
        assert llm.metadata["operation"] == "chat"
        assert llm.metadata["otel_span_id"] == "SPAN000000000001"

    def test_single_llm_span(self, tmp_path):
        """Minimal: one LLM call span."""
        span = _make_otel_span(
            "chat gpt-4", attributes=[
                {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
                {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4"}},
                {"key": "gen_ai.usage.input_tokens", "value": {"intValue": 100}},
                {"key": "gen_ai.usage.output_tokens", "value": {"intValue": 50}},
            ],
        )
        data = _make_otlp_data([span])
        path = tmp_path / "single.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.step_count == 1
        assert trace.steps[0].type == "llm_call"
        assert trace.steps[0].name == "gpt-4"
        assert trace.steps[0].tokens.prompt == 100
        assert trace.steps[0].tokens.completion == 50
        assert trace.agent_name == "test-agent-svc"

    def test_service_name_fallback(self, tmp_path):
        """agent_name falls back to service.name when gen_ai.agent.name is absent."""
        span = _make_otel_span("chat model", attributes=[
            {"key": "gen_ai.request.model", "value": {"stringValue": "model"}},
        ])
        data = _make_otlp_data([span], service_name="my-svc")
        path = tmp_path / "svc.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.agent_name == "my-svc"

    def test_agent_name_from_attribute(self, tmp_path):
        """gen_ai.agent.name takes priority over service.name."""
        span = _make_otel_span("chat", attributes=[
            {"key": "gen_ai.agent.name", "value": {"stringValue": "my-agent"}},
        ])
        data = _make_otlp_data([span], service_name="svc")
        path = tmp_path / "agent.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.agent_name == "my-agent"


class TestOtlpSpanClassification:
    def test_tool_by_operation_name(self, tmp_path):
        """execute_tool operation maps to tool_call type."""
        span = _make_otel_span("execute_tool Bash", kind=1, attributes=[
            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
            {"key": "gen_ai.tool.name", "value": {"stringValue": "Bash"}},
        ])
        data = _make_otlp_data([span])
        path = tmp_path / "tool_op.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.steps[0].type == "tool_call"
        assert trace.steps[0].name == "Bash"

    def test_tool_by_name_prefix(self, tmp_path):
        """Span name starting with 'execute_tool' maps to tool_call."""
        span = _make_otel_span("execute_tool WebSearch", kind=1, attributes=[
            {"key": "gen_ai.tool.name", "value": {"stringValue": "WebSearch"}},
        ])
        data = _make_otlp_data([span])
        path = tmp_path / "tool_name.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.steps[0].type == "tool_call"

    def test_llm_by_model_attribute(self, tmp_path):
        """Span with gen_ai.request.model maps to llm_call."""
        span = _make_otel_span("inference", kind=1, attributes=[
            {"key": "gen_ai.request.model", "value": {"stringValue": "claude-3"}},
        ])
        data = _make_otlp_data([span])
        path = tmp_path / "llm_model.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.steps[0].type == "llm_call"
        assert trace.steps[0].name == "claude-3"

    def test_llm_by_client_kind(self, tmp_path):
        """CLIENT span kind without gen_ai attributes maps to llm_call."""
        span = _make_otel_span("custom-call", kind=3, attributes=[])
        data = _make_otlp_data([span])
        path = tmp_path / "client.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.steps[0].type == "llm_call"

    def test_decision_for_unknown_kind(self, tmp_path):
        """Non-CLIENT span without gen_ai attributes maps to decision."""
        span = _make_otel_span("internal-step", kind=0, attributes=[])
        data = _make_otlp_data([span])
        path = tmp_path / "decision.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.steps[0].type == "decision"

    def test_error_status_overrides_type(self, tmp_path):
        """Span with error status code 2 becomes error type."""
        span = _make_otel_span(
            "chat gpt-4", kind=3,
            attributes=[
                {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4"}},
            ],
            status={"code": 2, "message": "rate limit exceeded"},
        )
        data = _make_otlp_data([span])
        path = tmp_path / "error.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.steps[0].type == "error"
        assert trace.steps[0].output["error_message"] == "rate limit exceeded"


class TestOtlpEdgeCases:
    def test_nonexistent_file(self):
        with pytest.raises(IngestError, match="File not found"):
            ingest_otlp_json("/nonexistent/otlp.json")

    def test_empty_file(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_text("", encoding="utf-8")
        with pytest.raises(IngestError, match="Empty file"):
            ingest_otlp_json(path)

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{bad json}", encoding="utf-8")
        with pytest.raises(IngestError, match="Invalid JSON"):
            ingest_otlp_json(path)

    def test_missing_resource_spans(self, tmp_path):
        path = tmp_path / "no_rs.json"
        path.write_text('{"traces": []}', encoding="utf-8")
        with pytest.raises(IngestError, match="resourceSpans"):
            ingest_otlp_json(path)

    def test_no_spans(self, tmp_path):
        data = {"resourceSpans": [{"resource": {}, "scopeSpans": [{"scope": {}, "spans": []}]}]}
        path = tmp_path / "no_spans.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(IngestError, match="No spans found"):
            ingest_otlp_json(path)

    def test_span_no_tokens(self, tmp_path):
        """Span without token usage attributes sets tokens to None."""
        span = _make_otel_span("some-span", kind=0, attributes=[])
        data = _make_otlp_data([span])
        path = tmp_path / "no_tokens.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.steps[0].tokens is None
        assert trace.total_tokens.total == 0

    def test_multiple_resource_spans(self, tmp_path):
        """Spans from multiple resourceSpans are collected."""
        data = {
            "resourceSpans": [
                _make_otlp_data([_make_otel_span("span-1", span_id="S1")])["resourceSpans"][0],
                _make_otlp_data([_make_otel_span("span-2", span_id="S2", start_ns=3000000000000)])["resourceSpans"][0],
            ],
        }
        path = tmp_path / "multi_rs.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.step_count == 2

    def test_spans_sorted_by_start_time(self, tmp_path):
        """Spans are sorted by startTimeUnixNano regardless of input order."""
        spans = [
            _make_otel_span("later", span_id="S2", start_ns=5000000000000, end_ns=6000000000000),
            _make_otel_span("earlier", span_id="S1", start_ns=1000000000000, end_ns=2000000000000),
        ]
        data = _make_otlp_data(spans)
        path = tmp_path / "sorted.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.steps[0].metadata["otel_span_id"] == "S1"
        assert trace.steps[1].metadata["otel_span_id"] == "S2"

    def test_parent_span_id_in_metadata(self, tmp_path):
        """parentSpanId is recorded in metadata."""
        span = _make_otel_span("child", span_id="CHILD", parent_span_id="PARENT")
        data = _make_otlp_data([span])
        path = tmp_path / "parent.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.steps[0].metadata["otel_parent_span_id"] == "PARENT"

    def test_response_model_preferred_over_request_model(self, tmp_path):
        """response.model is used as step name when available."""
        span = _make_otel_span("chat model", attributes=[
            {"key": "gen_ai.request.model", "value": {"stringValue": "claude-sonnet-4-6"}},
            {"key": "gen_ai.response.model", "value": {"stringValue": "claude-sonnet-4-6-20260514"}},
        ])
        data = _make_otlp_data([span])
        path = tmp_path / "resp_model.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        trace = ingest_otlp_json(path)

        assert trace.steps[0].name == "claude-sonnet-4-6-20260514"
