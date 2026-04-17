"""Tests for SQLite result storage."""

from __future__ import annotations

import time

import pytest

from trajeval.metrics import EvalReport, MetricResult
from trajeval.storage import ResultStore, StoredResult


def _make_report(
    trace_id: str = "trace-001",
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
        timestamp=timestamp,
    )


class TestResultStore:
    def test_store_and_retrieve(self, tmp_path):
        db = tmp_path / "test.db"
        store = ResultStore(db)
        report = _make_report()
        result_id = store.store_eval(report, agent_name="test-agent", source_file="trace.json")

        assert result_id == 1
        stored = store.get_result(result_id)
        assert stored is not None
        assert stored.trace_id == "trace-001"
        assert stored.agent_name == "test-agent"
        assert stored.overall_score == 0.85
        assert stored.passed is True
        assert stored.source_file == "trace.json"
        assert len(stored.metrics) == 2
        assert stored.metrics[0].name == "step_efficiency"
        store.close()

    def test_get_nonexistent_result_returns_none(self, tmp_path):
        store = ResultStore(tmp_path / "test.db")
        assert store.get_result(999) is None
        store.close()

    def test_store_preserves_metric_details(self, tmp_path):
        store = ResultStore(tmp_path / "test.db")
        report = _make_report()
        result_id = store.store_eval(report)
        stored = store.get_result(result_id)

        assert stored is not None
        assert stored.metrics[0].details == {"mode": "heuristic"}
        assert stored.metrics[1].details == {"total_tool_calls": 5}
        store.close()

    def test_store_preserves_config(self, tmp_path):
        store = ResultStore(tmp_path / "test.db")
        report = _make_report()
        config = {"pass_threshold": 0.8, "expected_steps": 10}
        result_id = store.store_eval(report, config=config)
        stored = store.get_result(result_id)

        assert stored is not None
        assert stored.config_json == config
        store.close()

    def test_count(self, tmp_path):
        store = ResultStore(tmp_path / "test.db")
        assert store.count() == 0
        store.store_eval(_make_report(trace_id="t1"))
        store.store_eval(_make_report(trace_id="t2"))
        assert store.count() == 2
        store.close()

    def test_history_returns_all_ordered_by_timestamp_desc(self, tmp_path):
        store = ResultStore(tmp_path / "test.db")
        store.store_eval(_make_report(trace_id="t1", timestamp=1000.0))
        store.store_eval(_make_report(trace_id="t2", timestamp=2000.0))
        store.store_eval(_make_report(trace_id="t3", timestamp=3000.0))

        history = store.get_history()
        assert len(history) == 3
        assert history[0].trace_id == "t3"
        assert history[1].trace_id == "t2"
        assert history[2].trace_id == "t1"
        store.close()

    def test_history_filter_by_trace_id(self, tmp_path):
        store = ResultStore(tmp_path / "test.db")
        store.store_eval(_make_report(trace_id="t1", timestamp=1000.0))
        store.store_eval(_make_report(trace_id="t2", timestamp=2000.0))
        store.store_eval(_make_report(trace_id="t1", timestamp=3000.0))

        history = store.get_history(trace_id="t1")
        assert len(history) == 2
        assert all(r.trace_id == "t1" for r in history)
        assert history[0].timestamp > history[1].timestamp
        store.close()

    def test_history_filter_by_agent_name(self, tmp_path):
        store = ResultStore(tmp_path / "test.db")
        store.store_eval(_make_report(trace_id="t1"), agent_name="agent-a")
        store.store_eval(_make_report(trace_id="t2"), agent_name="agent-b")
        store.store_eval(_make_report(trace_id="t3"), agent_name="agent-a")

        history = store.get_history(agent_name="agent-a")
        assert len(history) == 2
        assert all(r.agent_name == "agent-a" for r in history)
        store.close()

    def test_history_limit(self, tmp_path):
        store = ResultStore(tmp_path / "test.db")
        for i in range(10):
            store.store_eval(_make_report(trace_id=f"t{i}", timestamp=float(i)))

        history = store.get_history(limit=3)
        assert len(history) == 3
        assert history[0].trace_id == "t9"
        store.close()

    def test_store_uses_current_time_when_no_timestamp(self, tmp_path):
        store = ResultStore(tmp_path / "test.db")
        before = time.time()
        result_id = store.store_eval(_make_report(timestamp=None))
        after = time.time()

        stored = store.get_result(result_id)
        assert stored is not None
        assert before <= stored.timestamp <= after
        store.close()

    def test_store_failed_report(self, tmp_path):
        store = ResultStore(tmp_path / "test.db")
        report = _make_report(overall_score=0.3, passed=False)
        result_id = store.store_eval(report)
        stored = store.get_result(result_id)

        assert stored is not None
        assert stored.passed is False
        assert stored.overall_score == 0.3
        store.close()

    def test_multiple_stores_get_incrementing_ids(self, tmp_path):
        store = ResultStore(tmp_path / "test.db")
        id1 = store.store_eval(_make_report(trace_id="t1"))
        id2 = store.store_eval(_make_report(trace_id="t2"))
        id3 = store.store_eval(_make_report(trace_id="t3"))

        assert id1 == 1
        assert id2 == 2
        assert id3 == 3
        store.close()

    def test_reopening_db_preserves_data(self, tmp_path):
        db = tmp_path / "test.db"
        store1 = ResultStore(db)
        store1.store_eval(_make_report(trace_id="persistent"), agent_name="bot")
        store1.close()

        store2 = ResultStore(db)
        history = store2.get_history()
        assert len(history) == 1
        assert history[0].trace_id == "persistent"
        assert history[0].agent_name == "bot"
        store2.close()

    def test_stored_result_is_pydantic_model(self, tmp_path):
        store = ResultStore(tmp_path / "test.db")
        result_id = store.store_eval(_make_report())
        stored = store.get_result(result_id)

        assert isinstance(stored, StoredResult)
        dumped = stored.model_dump()
        assert "trace_id" in dumped
        assert "metrics" in dumped
        store.close()

    def test_combined_filters(self, tmp_path):
        store = ResultStore(tmp_path / "test.db")
        store.store_eval(_make_report(trace_id="t1"), agent_name="a")
        store.store_eval(_make_report(trace_id="t1"), agent_name="b")
        store.store_eval(_make_report(trace_id="t2"), agent_name="a")

        history = store.get_history(trace_id="t1", agent_name="a")
        assert len(history) == 1
        assert history[0].trace_id == "t1"
        assert history[0].agent_name == "a"
        store.close()
