"""Tests for batch evaluation."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from trajeval.batch import (
    BatchResult,
    MetricAggregate,
    batch_evaluate,
    discover_trace_files,
)
from trajeval.metrics import MetricConfig


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _make_trace(trace_id: str, steps: list[dict] | None = None) -> dict:
    if steps is None:
        steps = [
            {
                "type": "llm_call",
                "name": "claude-3",
                "input": {"prompt": "hello"},
                "output": {"response": "hi"},
                "duration_ms": 100.0,
                "tokens": {"prompt": 10, "completion": 5, "total": 15},
            }
        ]
    return {
        "trace_id": trace_id,
        "agent_name": "test-agent",
        "task": "test task",
        "steps": steps,
        "final_output": "done",
    }


class TestDiscoverTraceFiles:
    def test_discovers_json_files(self, tmp_path):
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "b.json").write_text("{}")
        (tmp_path / "c.txt").write_text("")
        files = discover_trace_files(tmp_path, "auto")
        assert len(files) == 2
        assert all(f.suffix == ".json" for f in files)

    def test_discovers_jsonl_files(self, tmp_path):
        (tmp_path / "a.jsonl").write_text("{}")
        (tmp_path / "b.json").write_text("{}")
        files = discover_trace_files(tmp_path, "clawdbot")
        assert len(files) == 1
        assert files[0].suffix == ".jsonl"

    def test_discovers_json_only(self, tmp_path):
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "b.jsonl").write_text("{}")
        files = discover_trace_files(tmp_path, "json")
        assert len(files) == 1
        assert files[0].suffix == ".json"

    def test_auto_discovers_both(self, tmp_path):
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "b.jsonl").write_text("{}")
        files = discover_trace_files(tmp_path, "auto")
        assert len(files) == 2

    def test_empty_directory(self, tmp_path):
        files = discover_trace_files(tmp_path, "auto")
        assert files == []

    def test_files_sorted(self, tmp_path):
        (tmp_path / "c.json").write_text("{}")
        (tmp_path / "a.json").write_text("{}")
        (tmp_path / "b.json").write_text("{}")
        files = discover_trace_files(tmp_path, "auto")
        assert [f.name for f in files] == ["a.json", "b.json", "c.json"]


class TestBatchEvaluate:
    def test_basic_batch(self, tmp_path):
        for i in range(3):
            trace = _make_trace(f"trace-{i}")
            (tmp_path / f"trace_{i}.json").write_text(json.dumps(trace))

        result = batch_evaluate(tmp_path)
        assert result.total_traces == 3
        assert result.passed_traces == 3
        assert result.failed_traces == 0
        assert result.overall_pass_rate == 1.0
        assert len(result.errors) == 0

    def test_mixed_pass_fail(self, tmp_path):
        good_trace = _make_trace("good-trace")
        (tmp_path / "good.json").write_text(json.dumps(good_trace))

        bad_trace = _make_trace("bad-trace", steps=[
            {"type": "error", "name": "crash", "input": {}, "output": {}},
            {"type": "error", "name": "crash2", "input": {}, "output": {}},
            {"type": "error", "name": "crash3", "input": {}, "output": {}},
            {"type": "error", "name": "crash4", "input": {}, "output": {}},
        ])
        (tmp_path / "bad.json").write_text(json.dumps(bad_trace))

        result = batch_evaluate(tmp_path)
        assert result.total_traces == 2
        assert result.passed_traces == 1
        assert result.failed_traces == 1
        assert result.overall_pass_rate == 0.5

    def test_empty_directory(self, tmp_path):
        result = batch_evaluate(tmp_path)
        assert result.total_traces == 0
        assert result.trace_results == []
        assert result.metric_aggregates == []

    def test_invalid_files_recorded_as_errors(self, tmp_path):
        (tmp_path / "bad.json").write_text("not json at all")
        good_trace = _make_trace("good-trace")
        (tmp_path / "good.json").write_text(json.dumps(good_trace))

        result = batch_evaluate(tmp_path)
        assert result.total_traces == 1
        assert len(result.errors) == 1
        assert "bad.json" in result.errors[0]["file"]

    def test_all_invalid_files(self, tmp_path):
        (tmp_path / "bad1.json").write_text("not json")
        (tmp_path / "bad2.json").write_text("{invalid}")

        result = batch_evaluate(tmp_path)
        assert result.total_traces == 0
        assert len(result.errors) == 2

    def test_config_passed_through(self, tmp_path):
        trace = _make_trace("config-trace", steps=[
            {"type": "llm_call", "name": "m1", "input": {}, "output": {}, "tokens": {"prompt": 10, "completion": 5, "total": 15}},
            {"type": "llm_call", "name": "m2", "input": {}, "output": {}, "tokens": {"prompt": 10, "completion": 5, "total": 15}},
            {"type": "error", "name": "e", "input": {}, "output": {}},
            {"type": "llm_call", "name": "m3", "input": {}, "output": {}, "tokens": {"prompt": 10, "completion": 5, "total": 15}},
        ])
        (tmp_path / "trace.json").write_text(json.dumps(trace))

        lenient_config = MetricConfig(pass_threshold=0.5)
        result_lenient = batch_evaluate(tmp_path, config=lenient_config)
        assert result_lenient.total_traces == 1
        assert result_lenient.passed_traces == 1

        strict_config = MetricConfig(pass_threshold=0.99)
        result_strict = batch_evaluate(tmp_path, config=strict_config)
        assert result_strict.total_traces == 1
        assert result_strict.failed_traces == 1

    def test_input_format_filter(self, tmp_path):
        trace = _make_trace("json-trace")
        (tmp_path / "trace.json").write_text(json.dumps(trace))
        (tmp_path / "other.jsonl").write_text('{"type":"session"}\n')

        result = batch_evaluate(tmp_path, input_format="json")
        assert result.total_traces == 1


class TestMetricAggregates:
    def test_aggregate_values(self, tmp_path):
        for i in range(5):
            trace = _make_trace(f"trace-{i}")
            (tmp_path / f"trace_{i}.json").write_text(json.dumps(trace))

        result = batch_evaluate(tmp_path)
        assert len(result.metric_aggregates) > 0

        for agg in result.metric_aggregates:
            assert agg.total == 5
            assert agg.min_score <= agg.mean_score <= agg.max_score
            assert 0 <= agg.fail_rate <= 1.0
            assert agg.std_dev >= 0

    def test_single_trace_zero_std_dev(self, tmp_path):
        trace = _make_trace("single")
        (tmp_path / "trace.json").write_text(json.dumps(trace))

        result = batch_evaluate(tmp_path)
        for agg in result.metric_aggregates:
            assert agg.std_dev == 0.0
            assert agg.min_score == agg.max_score == agg.mean_score

    def test_aggregate_names_match_metrics(self, tmp_path):
        trace = _make_trace("t")
        (tmp_path / "t.json").write_text(json.dumps(trace))

        result = batch_evaluate(tmp_path)
        agg_names = {a.name for a in result.metric_aggregates}
        metric_names = {m.name for m in result.trace_results[0].report.metrics}
        assert agg_names == metric_names


class TestBatchResultModel:
    def test_default_values(self):
        r = BatchResult()
        assert r.total_traces == 0
        assert r.passed_traces == 0
        assert r.failed_traces == 0
        assert r.overall_pass_rate == 0.0
        assert r.trace_results == []
        assert r.metric_aggregates == []
        assert r.errors == []

    def test_metric_aggregate_model(self):
        a = MetricAggregate(
            name="test_metric",
            mean_score=0.85,
            min_score=0.7,
            max_score=1.0,
            std_dev=0.1,
            fail_count=1,
            total=5,
            fail_rate=0.2,
        )
        assert a.name == "test_metric"
        assert a.mean_score == 0.85


class TestBatchWithFixtures:
    def test_batch_on_fixtures_dir(self):
        result = batch_evaluate(FIXTURES_DIR, input_format="json")
        assert result.total_traces > 0
        assert len(result.metric_aggregates) > 0
        for agg in result.metric_aggregates:
            assert agg.total == result.total_traces

    def test_batch_on_fixtures_dir_all_formats(self):
        result = batch_evaluate(FIXTURES_DIR, input_format="auto")
        json_result = batch_evaluate(FIXTURES_DIR, input_format="json")
        assert result.total_traces >= json_result.total_traces
