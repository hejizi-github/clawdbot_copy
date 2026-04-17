"""Tests for OTLP JSON trace ingestion."""

import json
from pathlib import Path

import pytest

from trajeval.ingester import IngestError, ingest_otlp_json


class TestOtlpBasic:
    def test_ingest_from_file(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert trace.trace_id == "abc123def456"
        assert trace.agent_name == "my-agent"
        assert trace.task == "Summarize the quarterly report"
        assert trace.step_count == 3
        assert trace.metadata["source_format"] == "otlp_json"

    def test_step_types(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert trace.steps[0].type == "llm_call"
        assert trace.steps[1].type == "tool_call"
        assert trace.steps[2].type == "llm_call"

    def test_step_names(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert trace.steps[0].name == "ChatCompletion"
        assert trace.steps[1].name == "read_file"
        assert trace.steps[2].name == "ChatCompletion"

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

    def test_llm_input_output(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert trace.steps[0].input["user_message"] == "Summarize Q3 results"
        assert "Q3 revenue grew" in trace.steps[0].output["text"]

    def test_tool_attributes(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        tool_step = trace.steps[1]
        assert tool_step.input["parameters"] == '{"path": "report.pdf"}'

    def test_final_output(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert "quarterly report shows" in trace.final_output

    def test_span_metadata(self, otlp_trace_path):
        trace = ingest_otlp_json(otlp_trace_path)
        assert trace.steps[0].metadata["span_id"] == "span001"
        assert trace.steps[0].metadata["parent_span_id"] == ""
        assert trace.steps[1].metadata["parent_span_id"] == "span001"


class TestOtlpErrors:
    def test_error_span_classified_as_error(self, otlp_error_trace_path):
        trace = ingest_otlp_json(otlp_error_trace_path)
        assert trace.steps[0].type == "error"
        assert trace.steps[0].output["error"] == "connection timeout"

    def test_recovery_after_error(self, otlp_error_trace_path):
        trace = ingest_otlp_json(otlp_error_trace_path)
        assert trace.steps[1].type == "tool_call"
        assert len(trace.errors) == 1

    def test_empty_resource_spans(self):
        with pytest.raises(IngestError, match="No resourceSpans"):
            ingest_otlp_json({"resourceSpans": []})

    def test_no_spans(self):
        data = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{"scope": {"name": "x"}, "spans": []}],
            }]
        }
        with pytest.raises(IngestError, match="No spans"):
            ingest_otlp_json(data)


class TestOtlpFromDict:
    def test_minimal_span(self):
        data = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [{
                        "traceId": "t1",
                        "spanId": "s1",
                        "name": "my_tool",
                        "kind": 1,
                        "startTimeUnixNano": "1000000000",
                        "endTimeUnixNano": "2000000000",
                        "attributes": [],
                        "status": {"code": 0},
                    }],
                }],
            }]
        }
        trace = ingest_otlp_json(data)
        assert trace.trace_id == "t1"
        assert trace.step_count == 1
        assert trace.steps[0].name == "my_tool"
        assert trace.steps[0].duration_ms == 1000.0

    def test_service_name_as_agent_name(self):
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
                        "name": "op",
                        "kind": 1,
                        "startTimeUnixNano": "0",
                        "endTimeUnixNano": "0",
                        "attributes": [],
                        "status": {"code": 0},
                    }],
                }],
            }]
        }
        trace = ingest_otlp_json(data)
        assert trace.agent_name == "custom-bot"

    def test_task_from_first_llm_prompt(self):
        data = {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [{
                        "traceId": "t3",
                        "spanId": "s1",
                        "name": "ChatCompletion",
                        "kind": 3,
                        "startTimeUnixNano": "0",
                        "endTimeUnixNano": "0",
                        "attributes": [
                            {"key": "gen_ai.system", "value": {"stringValue": "openai"}},
                            {"key": "gen_ai.prompt", "value": {"stringValue": "Write a poem"}},
                        ],
                        "status": {"code": 0},
                    }],
                }],
            }]
        }
        trace = ingest_otlp_json(data)
        assert trace.task == "Write a poem"

    def test_multiple_resource_spans(self):
        span_template = {
            "traceId": "multi",
            "spanId": "s",
            "name": "op",
            "kind": 1,
            "startTimeUnixNano": "0",
            "endTimeUnixNano": "1000000000",
            "attributes": [],
            "status": {"code": 0},
        }
        data = {
            "resourceSpans": [
                {
                    "resource": {"attributes": []},
                    "scopeSpans": [{"scope": {"name": "a"}, "spans": [
                        {**span_template, "spanId": "s1", "startTimeUnixNano": "1000000000"},
                    ]}],
                },
                {
                    "resource": {"attributes": []},
                    "scopeSpans": [{"scope": {"name": "b"}, "spans": [
                        {**span_template, "spanId": "s2", "startTimeUnixNano": "2000000000"},
                    ]}],
                },
            ]
        }
        trace = ingest_otlp_json(data)
        assert trace.step_count == 2


class TestOtlpAttributeParsing:
    def test_all_value_types(self):
        data = {
            "resourceSpans": [{
                "resource": {
                    "attributes": [
                        {"key": "str_attr", "value": {"stringValue": "hello"}},
                        {"key": "int_attr", "value": {"intValue": "42"}},
                        {"key": "double_attr", "value": {"doubleValue": 3.14}},
                        {"key": "bool_attr", "value": {"boolValue": True}},
                    ]
                },
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [{
                        "traceId": "attr-test",
                        "spanId": "s1",
                        "name": "op",
                        "kind": 1,
                        "startTimeUnixNano": "0",
                        "endTimeUnixNano": "0",
                        "attributes": [],
                        "status": {"code": 0},
                    }],
                }],
            }]
        }
        trace = ingest_otlp_json(data)
        assert trace.metadata["str_attr"] == "hello"
        assert trace.metadata["int_attr"] == "42"
        assert trace.metadata["double_attr"] == "3.14"
        assert trace.metadata["bool_attr"] == "True"


class TestOtlpSpanClassification:
    def _make_span(self, name="op", kind=1, attrs=None, status_code=0):
        return {
            "resourceSpans": [{
                "resource": {"attributes": []},
                "scopeSpans": [{
                    "scope": {"name": "test"},
                    "spans": [{
                        "traceId": "cls",
                        "spanId": "s1",
                        "name": name,
                        "kind": kind,
                        "startTimeUnixNano": "0",
                        "endTimeUnixNano": "1000000000",
                        "attributes": attrs or [],
                        "status": {"code": status_code},
                    }],
                }],
            }]
        }

    def test_llm_by_name(self):
        trace = ingest_otlp_json(self._make_span(name="ChatCompletion"))
        assert trace.steps[0].type == "llm_call"

    def test_llm_by_gen_ai_attr(self):
        attrs = [{"key": "gen_ai.system", "value": {"stringValue": "openai"}}]
        trace = ingest_otlp_json(self._make_span(attrs=attrs))
        assert trace.steps[0].type == "llm_call"

    def test_llm_by_client_kind(self):
        trace = ingest_otlp_json(self._make_span(name="api_call", kind=3))
        assert trace.steps[0].type == "llm_call"

    def test_error_by_status(self):
        trace = ingest_otlp_json(self._make_span(status_code=2))
        assert trace.steps[0].type == "error"

    def test_tool_by_name(self):
        trace = ingest_otlp_json(self._make_span(name="tool.execute"))
        assert trace.steps[0].type == "tool_call"

    def test_tool_by_attr(self):
        attrs = [{"key": "tool.name", "value": {"stringValue": "search"}}]
        trace = ingest_otlp_json(self._make_span(name="execute", attrs=attrs))
        assert trace.steps[0].type == "tool_call"

    def test_default_to_tool_call(self):
        trace = ingest_otlp_json(self._make_span(name="unknown_operation", kind=0))
        assert trace.steps[0].type == "tool_call"


class TestOtlpCliIntegration:
    def test_eval_with_otlp_format(self, otlp_trace_path, tmp_path):
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
                        "name": "op",
                        "kind": 1,
                        "startTimeUnixNano": "0",
                        "endTimeUnixNano": "1000000000",
                        "attributes": [],
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

    def test_compare_with_otlp(self, otlp_trace_path, tmp_path):
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
