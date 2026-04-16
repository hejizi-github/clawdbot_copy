"""Tests for trace ingestion."""

import json

import pytest

from trajeval.ingester import IngestError, ingest_json


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
