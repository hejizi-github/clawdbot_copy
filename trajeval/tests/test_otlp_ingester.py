"""Tests for OTLP JSON trace ingestion."""

import json
from pathlib import Path

import pytest

from trajeval.ingester import IngestError, ingest_otlp_json


def _write_otlp(tmp_path: Path, data: dict, name: str = "trace.json") -> Path:
    """Write OTLP data to a temp file and return the path."""
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestOtlpBasic:
    def test_ingest_from_file(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert trace.trace_id == "abc123def456"
        assert trace.agent_name == "my-agent"
        assert trace.step_count == 3
        assert trace.metadata["source_format"] == "otlp_json"

    def test_step_types(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert trace.steps[0].type == "llm_call"
        assert trace.steps[1].type == "tool_call"
        assert trace.steps[2].type == "llm_call"

    def test_llm_step_names_use_model(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert trace.steps[0].name == "gpt-4"

    def test_tool_step_names(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert trace.steps[1].name == "read_file"

    def test_token_extraction(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert trace.steps[0].tokens.prompt == 150
        assert trace.steps[0].tokens.completion == 200
        assert trace.steps[0].tokens.total == 350
        assert trace.total_tokens.prompt == 650
        assert trace.total_tokens.completion == 500
        assert trace.total_tokens.total == 1150

    def test_duration_from_nanoseconds(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert trace.steps[0].duration_ms == 2000.0
        assert trace.steps[1].duration_ms == 500.0
        assert trace.steps[2].duration_ms == 2500.0

    def test_tool_arguments(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        tool_step = trace.steps[1]
        assert tool_step.input["arguments"] == '{"path": "report.pdf"}'
        assert tool_step.output["text"] == "File content here..."

    def test_final_output(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert "quarterly report shows" in trace.final_output

    def test_span_metadata(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert trace.steps[0].metadata["span_id"] == "span001"


class TestOtlpErrors:
    def test_error_span_classified_as_error(self, otlp_error_trace_path):
        trace = ingest_otlp_json(otlp_error_trace_path)
        assert trace.steps[0].type == "error"
        assert "connection timeout" in trace.steps[0].output["error"]

    def test_recovery_after_error(self, otlp_error_trace_path):
        trace = ingest_otlp_json(otlp_error_trace_path)
        assert trace.steps[1].type == "tool_call"
        assert len(trace.errors) == 1

    def test_nonexistent_file(self):
        with pytest.raises(IngestError, match="File not found"):
            ingest_otlp_json("/nonexistent/otlp.json")

    def test_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{bad json", encoding="utf-8")
        with pytest.raises(IngestError, match="Invalid JSON"):
            ingest_otlp_json(path)

    def test_empty_resource_spans(self, tmp_path):
        path = _write_otlp(tmp_path, {"resourceSpans": []})
        with pytest.raises(IngestError, match="No resourceSpans"):
            ingest_otlp_json(path)


class TestOtlpServiceName:
    def test_service_name_as_agent_name(self, tmp_path):
        data = {
            "resourceSpans": [{
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "custom-bot"}},
                    ]
                },
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [{
                        "traceId": "t2",
                        "spanId": "s1",
                        "name": "ChatCompletion",
                        "kind": 3,
                        "startTimeUnixNano": "0",
                        "endTimeUnixNano": "0",
                        "attributes": [
                            {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
                            {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4"}},
                        ],
                        "status": {"code": 0},
                    }],
                }],
            }]
        }
        path = _write_otlp(tmp_path, data)
        trace = ingest_otlp_json(path)
        assert trace.agent_name == "custom-bot"


class TestOtlpGenAiConventions:
    def test_chat_operation_creates_llm_call(self, tmp_path):
        data = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [{
                        "traceId": "t1",
                        "spanId": "s1",
                        "name": "ChatCompletion",
                        "kind": 3,
                        "startTimeUnixNano": "0",
                        "endTimeUnixNano": "1000000000",
                        "attributes": [
                            {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
                            {"key": "gen_ai.request.model", "value": {"stringValue": "claude-3"}},
                        ],
                        "status": {"code": 0},
                    }],
                }],
            }]
        }
        path = _write_otlp(tmp_path, data)
        trace = ingest_otlp_json(path)
        assert trace.steps[0].type == "llm_call"
        assert trace.steps[0].name == "claude-3"

    def test_execute_tool_creates_tool_call(self, tmp_path):
        data = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [{
                        "traceId": "t1",
                        "spanId": "s1",
                        "name": "execute_tool search",
                        "kind": 1,
                        "startTimeUnixNano": "0",
                        "endTimeUnixNano": "1000000000",
                        "attributes": [
                            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
                            {"key": "gen_ai.tool.name", "value": {"stringValue": "search"}},
                        ],
                        "status": {"code": 0},
                    }],
                }],
            }]
        }
        path = _write_otlp(tmp_path, data)
        trace = ingest_otlp_json(path)
        assert trace.steps[0].type == "tool_call"
        assert trace.steps[0].name == "search"

    def test_error_status_creates_error_step(self, tmp_path):
        data = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [{
                        "traceId": "t1",
                        "spanId": "s1",
                        "name": "failing_op",
                        "kind": 1,
                        "startTimeUnixNano": "0",
                        "endTimeUnixNano": "1000000000",
                        "attributes": [
                            {"key": "gen_ai.operation.name", "value": {"stringValue": "execute_tool"}},
                            {"key": "error.type", "value": {"stringValue": "TimeoutError"}},
                        ],
                        "status": {"code": 2, "message": "timed out"},
                    }],
                }],
            }]
        }
        path = _write_otlp(tmp_path, data)
        trace = ingest_otlp_json(path)
        assert trace.steps[0].type == "error"
        assert trace.steps[0].name == "TimeoutError"

    def test_invoke_agent_creates_decision(self, tmp_path):
        data = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [{
                        "traceId": "t1",
                        "spanId": "s1",
                        "name": "agent_dispatch",
                        "kind": 1,
                        "startTimeUnixNano": "0",
                        "endTimeUnixNano": "1000000000",
                        "attributes": [
                            {"key": "gen_ai.operation.name", "value": {"stringValue": "invoke_agent"}},
                            {"key": "gen_ai.agent.name", "value": {"stringValue": "planner"}},
                        ],
                        "status": {"code": 0},
                    }],
                }],
            }]
        }
        path = _write_otlp(tmp_path, data)
        trace = ingest_otlp_json(path)
        assert trace.steps[0].type == "decision"
        assert trace.steps[0].name == "planner"


class TestOtlpCliIntegration:
    def test_eval_with_otlp_format(self, otlp_trace_path):
        from click.testing import CliRunner
        from trajeval.cli import main

        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(otlp_trace_path), "--input-format", "otlp", "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["trace_id"] == "abc123def456"
        assert len(data["metrics"]) == 6

    def test_eval_auto_detect_otlp(self, tmp_path):
        from click.testing import CliRunner
        from trajeval.cli import main

        otlp_data = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [{
                        "traceId": "auto-detect",
                        "spanId": "s1",
                        "name": "ChatCompletion",
                        "kind": 3,
                        "startTimeUnixNano": "0",
                        "endTimeUnixNano": "1000000000",
                        "attributes": [
                            {"key": "gen_ai.operation.name", "value": {"stringValue": "chat"}},
                            {"key": "gen_ai.request.model", "value": {"stringValue": "gpt-4"}},
                        ],
                        "status": {"code": 0},
                    }],
                }],
            }]
        }
        otlp_file = tmp_path / "test.otlp.json"
        otlp_file.write_text(json.dumps(otlp_data))

        runner = CliRunner()
        result = runner.invoke(main, ["eval", str(otlp_file), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["trace_id"] == "auto-detect"

    def test_compare_with_otlp(self, otlp_trace_path):
        from click.testing import CliRunner
        from trajeval.cli import main

        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", str(otlp_trace_path), str(otlp_trace_path),
            "--input-format", "otlp", "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["metric_deltas"]) > 0
