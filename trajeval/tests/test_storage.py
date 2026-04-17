"""Tests for SQLite storage module."""

from __future__ import annotations

import json
import time

import pytest

from trajeval.metrics import EvalReport, MetricResult
from trajeval.storage import EvalStore


def _make_report(
    trace_id: str = "test-trace-001",
    overall_score: float = 0.85,
    passed: bool = True,
    timestamp: float | None = None,
) -> EvalReport:
    return EvalReport(
        trace_id=trace_id,
        metrics=[
            MetricResult(name="step_efficiency", score=0.9, passed=True, details={"mode": "heuristic"}),
            MetricResult(name="tool_accuracy", score=0.8, passed=True, details={"total_tool_calls": 5}),
        ],
        overall_score=overall_score,
        passed=passed,
        timestamp=timestamp if timestamp is not None else time.time(),
    )


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test.db"
    s = EvalStore(db_path=db_path)
    yield s
    s.close()


class TestEvalStore:
    def test_save_and_get(self, store):
        report = _make_report()
        eval_id = store.save_eval(report, agent_name="test-agent", task="do stuff")
        assert eval_id >= 1

        record = store.get_eval(eval_id)
        assert record is not None
        assert record.trace_id == "test-trace-001"
        assert record.overall_score == 0.85
        assert record.passed is True
        assert record.agent_name == "test-agent"
        assert record.task == "do stuff"

    def test_get_nonexistent_returns_none(self, store):
        assert store.get_eval(9999) is None

    def test_save_preserves_metrics(self, store):
        report = _make_report()
        eval_id = store.save_eval(report)
        record = store.get_eval(eval_id)
        metrics = json.loads(record.metrics_json)
        assert len(metrics) == 2
        assert metrics[0]["name"] == "step_efficiency"
        assert metrics[1]["score"] == 0.8

    def test_save_preserves_config(self, store):
        report = _make_report()
        config = {"expected_steps": 10, "pass_threshold": 0.7}
        eval_id = store.save_eval(report, config=config)
        record = store.get_eval(eval_id)
        stored_config = json.loads(record.config_json)
        assert stored_config["expected_steps"] == 10
        assert stored_config["pass_threshold"] == 0.7

    def test_list_evals_ordered_by_timestamp_desc(self, store):
        now = time.time()
        store.save_eval(_make_report(trace_id="old", timestamp=now - 100))
        store.save_eval(_make_report(trace_id="new", timestamp=now))
        store.save_eval(_make_report(trace_id="mid", timestamp=now - 50))

        records = store.list_evals()
        assert len(records) == 3
        assert records[0].trace_id == "new"
        assert records[1].trace_id == "mid"
        assert records[2].trace_id == "old"

    def test_list_evals_limit_and_offset(self, store):
        for i in range(5):
            store.save_eval(_make_report(trace_id=f"trace-{i}", timestamp=float(i)))

        first_page = store.list_evals(limit=2, offset=0)
        assert len(first_page) == 2
        assert first_page[0].trace_id == "trace-4"

        second_page = store.list_evals(limit=2, offset=2)
        assert len(second_page) == 2
        assert second_page[0].trace_id == "trace-2"

    def test_get_by_trace_id(self, store):
        store.save_eval(_make_report(trace_id="abc-123", overall_score=0.7, timestamp=1.0))
        store.save_eval(_make_report(trace_id="abc-123", overall_score=0.9, timestamp=2.0))
        store.save_eval(_make_report(trace_id="other", overall_score=0.5))

        results = store.get_by_trace_id("abc-123")
        assert len(results) == 2
        assert results[0].overall_score == 0.9
        assert results[1].overall_score == 0.7

    def test_get_by_trace_id_empty(self, store):
        assert store.get_by_trace_id("nonexistent") == []

    def test_get_latest(self, store):
        store.save_eval(_make_report(trace_id="old", timestamp=1.0))
        store.save_eval(_make_report(trace_id="new", timestamp=2.0))
        latest = store.get_latest()
        assert latest is not None
        assert latest.trace_id == "new"

    def test_get_latest_by_agent_name(self, store):
        store.save_eval(_make_report(trace_id="a1", timestamp=1.0), agent_name="alpha")
        store.save_eval(_make_report(trace_id="b1", timestamp=2.0), agent_name="beta")
        store.save_eval(_make_report(trace_id="a2", timestamp=3.0), agent_name="alpha")

        latest_alpha = store.get_latest(agent_name="alpha")
        assert latest_alpha is not None
        assert latest_alpha.trace_id == "a2"

        latest_beta = store.get_latest(agent_name="beta")
        assert latest_beta is not None
        assert latest_beta.trace_id == "b1"

    def test_get_latest_empty_store(self, store):
        assert store.get_latest() is None

    def test_count(self, store):
        assert store.count() == 0
        store.save_eval(_make_report())
        assert store.count() == 1
        store.save_eval(_make_report(trace_id="second"))
        assert store.count() == 2

    def test_delete_eval(self, store):
        eval_id = store.save_eval(_make_report())
        assert store.count() == 1
        deleted = store.delete_eval(eval_id)
        assert deleted is True
        assert store.count() == 0
        assert store.get_eval(eval_id) is None

    def test_delete_nonexistent(self, store):
        assert store.delete_eval(9999) is False

    def test_record_to_report_roundtrip(self, store):
        original = _make_report()
        eval_id = store.save_eval(original)
        record = store.get_eval(eval_id)
        reconstructed = store.record_to_report(record)
        assert reconstructed.trace_id == original.trace_id
        assert reconstructed.overall_score == original.overall_score
        assert reconstructed.passed == original.passed
        assert len(reconstructed.metrics) == len(original.metrics)
        assert reconstructed.metrics[0].name == "step_efficiency"
        assert reconstructed.metrics[1].score == 0.8

    def test_db_auto_creates_parent_directory(self, tmp_path):
        deep_path = tmp_path / "a" / "b" / "c" / "test.db"
        s = EvalStore(db_path=deep_path)
        s.save_eval(_make_report())
        assert deep_path.exists()
        assert s.count() == 1
        s.close()

    def test_failed_eval_stored_correctly(self, store):
        report = _make_report(passed=False, overall_score=0.3)
        eval_id = store.save_eval(report)
        record = store.get_eval(eval_id)
        assert record.passed is False
        assert record.overall_score == 0.3
