"""Tests for trace ingestion."""

import json
from pathlib import Path

import pytest

from trajeval.ingester import IngestError, ingest_clawdbot_jsonl, ingest_json, ingest_otlp


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


# --- OTLP ingestion tests ---


def _make_otlp_span(
    trace_id="AAAA1234BBBB5678CCCC9012DDDDEE00",
    span_id="1111111111111111",
    parent_span_id="",
    name="chat gpt-4o",
    start_ns=1700000000000000000,
    end_ns=1700000002000000000,
    kind=3,
    attributes=None,
    status=None,
):
    span = {
        "traceId": trace_id,
        "spanId": span_id,
        "parentSpanId": parent_span_id,
        "name": name,
        "startTimeUnixNano": str(start_ns),
        "endTimeUnixNano": str(end_ns),
        "kind": kind,
        "attributes": attributes or [],
        "status": status or {},
    }
    return span


def _make_otlp_trace(spans, service_name="test-agent"):
    return {
        "resourceSpans": [{
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": service_name}},
                ],
            },
            "scopeSpans": [{
                "scope": {"name": "test.scope"},
                "spans": spans,
            }],
        }],
    }


def _genai_attrs(model="gpt-4o", provider="openai", op="chat",
                 input_tokens=100, output_tokens=50):
    attrs = [
        {"key": "gen_ai.operation.name", "value": {"stringValue": op}},
        {"key": "gen_ai.request.model", "value": {"stringValue": model}},
        {"key": "gen_ai.provider.name", "value": {"stringValue": provider}},
        {"key": "gen_ai.usage.input_tokens", "value": {"intValue": str(input_tokens)}},
        {"key": "gen_ai.usage.output_tokens", "value": {"intValue": str(output_tokens)}},
    ]
    return attrs


class TestOtlpBasic:
    def test_fixture_file(self, otlp_trace_path):
        """Loads the standard OTLP fixture file."""
        trace = ingest_otlp(otlp_trace_path)
        assert trace.trace_id == "AAAA1234BBBB5678CCCC9012DDDDEE00"
        assert trace.agent_name == "my-agent"
        assert trace.metadata["source_format"] == "otlp"
        assert trace.metadata["resource_attributes"]["service.name"] == "my-agent"

    def test_fixture_step_count(self, otlp_trace_path):
        trace = ingest_otlp(otlp_trace_path)
        assert trace.step_count == 3
        assert len(trace.llm_calls) == 2
        assert len(trace.tool_calls) == 1

    def test_fixture_token_aggregation(self, otlp_trace_path):
        trace = ingest_otlp(otlp_trace_path)
        assert trace.total_tokens.prompt == 1300  # 500 + 800
        assert trace.total_tokens.completion == 320  # 120 + 200
        assert trace.total_tokens.total == 1620

    def test_fixture_duration(self, otlp_trace_path):
        trace = ingest_otlp(otlp_trace_path)
        llm_calls = trace.llm_calls
        assert llm_calls[0].duration_ms == 2000.0  # 2 seconds
        assert llm_calls[1].duration_ms == 2000.0  # 2 seconds

    def test_dict_input(self):
        spans = [_make_otlp_span(attributes=_genai_attrs())]
        data = _make_otlp_trace(spans)
        trace = ingest_otlp(data)
        assert trace.step_count == 1
        assert trace.agent_name == "test-agent"

    def test_string_input(self):
        spans = [_make_otlp_span(attributes=_genai_attrs())]
        data = _make_otlp_trace(spans)
        trace = ingest_otlp(json.dumps(data))
        assert trace.step_count == 1

    def test_file_input(self, tmp_path):
        spans = [_make_otlp_span(attributes=_genai_attrs())]
        data = _make_otlp_trace(spans)
        path = tmp_path / "trace.json"
        path.write_text(json.dumps(data))
        trace = ingest_otlp(path)
        assert trace.step_count == 1


class TestOtlpGenAI:
    def test_model_extraction(self):
        attrs = _genai_attrs(model="claude-sonnet-4-6", provider="anthropic")
        spans = [_make_otlp_span(attributes=attrs)]
        trace = ingest_otlp(_make_otlp_trace(spans))
        assert trace.llm_calls[0].name == "claude-sonnet-4-6"
        assert trace.llm_calls[0].metadata["provider"] == "anthropic"

    def test_token_usage(self):
        attrs = _genai_attrs(input_tokens=1000, output_tokens=500)
        spans = [_make_otlp_span(attributes=attrs)]
        trace = ingest_otlp(_make_otlp_trace(spans))
        assert trace.llm_calls[0].tokens.prompt == 1000
        assert trace.llm_calls[0].tokens.completion == 500
        assert trace.llm_calls[0].tokens.total == 1500

    def test_operation_name_in_input(self):
        attrs = _genai_attrs(op="text_completion")
        spans = [_make_otlp_span(attributes=attrs)]
        trace = ingest_otlp(_make_otlp_trace(spans))
        assert trace.llm_calls[0].input["operation"] == "text_completion"

    def test_multiple_llm_spans(self):
        s1 = _make_otlp_span(
            span_id="AAA", start_ns=1000000000, end_ns=2000000000,
            attributes=_genai_attrs(model="gpt-4o", input_tokens=100, output_tokens=50),
        )
        s2 = _make_otlp_span(
            span_id="BBB", start_ns=3000000000, end_ns=4000000000,
            attributes=_genai_attrs(model="gpt-4o-mini", input_tokens=200, output_tokens=80),
        )
        trace = ingest_otlp(_make_otlp_trace([s1, s2]))
        assert len(trace.llm_calls) == 2
        assert trace.llm_calls[0].name == "gpt-4o"
        assert trace.llm_calls[1].name == "gpt-4o-mini"
        assert trace.total_tokens.prompt == 300
        assert trace.total_tokens.completion == 130

    def test_response_model_fallback(self):
        attrs = [
            {"key": "gen_ai.response.model", "value": {"stringValue": "gpt-4o-2024-08-06"}},
            {"key": "gen_ai.provider.name", "value": {"stringValue": "openai"}},
        ]
        spans = [_make_otlp_span(attributes=attrs)]
        trace = ingest_otlp(_make_otlp_trace(spans))
        assert trace.llm_calls[0].name == "gpt-4o-2024-08-06"


class TestOtlpToolCalls:
    def test_non_genai_client_span_is_tool_call(self):
        tool_attrs = [
            {"key": "tool.name", "value": {"stringValue": "search"}},
        ]
        spans = [_make_otlp_span(name="search", kind=3, attributes=tool_attrs)]
        trace = ingest_otlp(_make_otlp_trace(spans))
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].name == "search"

    def test_internal_span_is_decision(self):
        spans = [_make_otlp_span(name="planning", kind=1, attributes=[])]
        trace = ingest_otlp(_make_otlp_trace(spans))
        assert trace.steps[0].type == "decision"
        assert trace.steps[0].name == "planning"


class TestOtlpErrors:
    def test_error_span(self):
        spans = [_make_otlp_span(
            name="failed_tool",
            kind=3,
            attributes=[],
            status={"code": 2, "message": "Connection timeout"},
        )]
        trace = ingest_otlp(_make_otlp_trace(spans))
        assert len(trace.errors) == 1
        assert trace.errors[0].output["message"] == "Connection timeout"

    def test_genai_span_with_error_status(self):
        """GenAI span with error status is still classified as llm_call, with error in metadata."""
        attrs = _genai_attrs()
        spans = [_make_otlp_span(
            attributes=attrs,
            status={"code": 2, "message": "Rate limit exceeded"},
        )]
        trace = ingest_otlp(_make_otlp_trace(spans))
        assert len(trace.llm_calls) == 1
        assert trace.llm_calls[0].metadata["error"] == "Rate limit exceeded"

    def test_empty_resource_spans(self):
        with pytest.raises(IngestError, match="No resourceSpans"):
            ingest_otlp({"resourceSpans": []})

    def test_no_spans(self):
        data = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{"scope": {"name": "x"}, "spans": []}],
            }],
        }
        with pytest.raises(IngestError, match="No spans"):
            ingest_otlp(data)

    def test_invalid_json_file(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{bad json")
        with pytest.raises(IngestError, match="Invalid JSON"):
            ingest_otlp(path)

    def test_nonexistent_file(self):
        with pytest.raises(IngestError, match="File not found"):
            ingest_otlp("/nonexistent/otlp.json")


class TestOtlpAttributeTypes:
    def test_string_value(self):
        attrs = [{"key": "gen_ai.request.model", "value": {"stringValue": "test-model"}}]
        spans = [_make_otlp_span(attributes=attrs)]
        trace = ingest_otlp(_make_otlp_trace(spans))
        assert trace.llm_calls[0].name == "test-model"

    def test_int_value(self):
        attrs = _genai_attrs(input_tokens=999, output_tokens=1)
        spans = [_make_otlp_span(attributes=attrs)]
        trace = ingest_otlp(_make_otlp_trace(spans))
        assert trace.llm_calls[0].tokens.prompt == 999

    def test_double_value(self):
        attrs = [
            {"key": "gen_ai.request.model", "value": {"stringValue": "m"}},
            {"key": "custom.score", "value": {"doubleValue": 0.95}},
        ]
        spans = [_make_otlp_span(attributes=attrs)]
        trace = ingest_otlp(_make_otlp_trace(spans))
        step_attrs = trace.steps[0].output.get("attributes", {})
        assert step_attrs["custom.score"] == "0.95"

    def test_bool_value(self):
        attrs = [
            {"key": "gen_ai.request.model", "value": {"stringValue": "m"}},
            {"key": "gen_ai.stream", "value": {"boolValue": True}},
        ]
        spans = [_make_otlp_span(attributes=attrs)]
        trace = ingest_otlp(_make_otlp_trace(spans))
        step_attrs = trace.steps[0].output.get("attributes", {})
        assert step_attrs["gen_ai.stream"] == "True"


class TestOtlpOrdering:
    def test_spans_ordered_by_start_time(self):
        s1 = _make_otlp_span(
            span_id="LATE", start_ns=5000000000, end_ns=6000000000,
            attributes=_genai_attrs(model="second"),
        )
        s2 = _make_otlp_span(
            span_id="EARLY", start_ns=1000000000, end_ns=2000000000,
            attributes=_genai_attrs(model="first"),
        )
        trace = ingest_otlp(_make_otlp_trace([s1, s2]))
        assert trace.steps[0].name == "first"
        assert trace.steps[1].name == "second"

    def test_multiple_scope_spans(self):
        data = {
            "resourceSpans": [{
                "resource": {"attributes": [
                    {"key": "service.name", "value": {"stringValue": "multi-scope"}},
                ]},
                "scopeSpans": [
                    {
                        "scope": {"name": "scope-a"},
                        "spans": [_make_otlp_span(
                            span_id="A", start_ns=1000000000, end_ns=2000000000,
                            attributes=_genai_attrs(model="model-a"),
                        )],
                    },
                    {
                        "scope": {"name": "scope-b"},
                        "spans": [_make_otlp_span(
                            span_id="B", start_ns=3000000000, end_ns=4000000000,
                            attributes=_genai_attrs(model="model-b"),
                        )],
                    },
                ],
            }],
        }
        trace = ingest_otlp(data)
        assert trace.step_count == 2
        assert trace.steps[0].name == "model-a"
        assert trace.steps[1].name == "model-b"
