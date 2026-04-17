"""Tests for trace ingestion."""

import json
from pathlib import Path

import pytest

from trajeval.ingester import IngestError, ingest_clawdbot_jsonl, ingest_json


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
