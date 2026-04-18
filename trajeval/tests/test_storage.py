"""Tests for SQLite storage module."""

from __future__ import annotations

import time

import pytest

from trajeval.metrics import EvalReport, MetricResult
from trajeval.scorer import JudgeDimension, JudgeResult
from trajeval.storage import TrajevalDB


def _make_report(
    trace_id: str = "trace-001",
    score: float = 0.85,
    passed: bool = True,
    timestamp: float | None = None,
) -> EvalReport:
    return EvalReport(
        trace_id=trace_id,
        overall_score=score,
        passed=passed,
        timestamp=timestamp or time.time(),
        metrics=[
            MetricResult(name="step_efficiency", score=0.9, passed=True, details={"steps": 5}),
            MetricResult(name="tool_accuracy", score=0.8, passed=True, details={"correct": 4, "total": 5}),
        ],
    )


class TestSaveAndLoad:
    def test_roundtrip(self, tmp_path):
        db_path = tmp_path / "test.db"
        report = _make_report(timestamp=1000.0)
        with TrajevalDB(db_path) as db:
            db.save_eval(report, agent_name="my-agent")
            loaded = db.load_eval("trace-001")

        assert loaded is not None
        assert loaded.trace_id == "trace-001"
        assert loaded.overall_score == 0.85
        assert loaded.passed is True
        assert loaded.timestamp == 1000.0
        assert len(loaded.metrics) == 2
        assert loaded.metrics[0].name == "step_efficiency"
        assert loaded.metrics[0].score == 0.9
        assert loaded.metrics[0].details == {"steps": 5}

    def test_load_missing_returns_none(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            assert db.load_eval("nonexistent") is None

    def test_upsert_overwrites(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_eval(_make_report(score=0.5, passed=False), agent_name="a")
            db.save_eval(_make_report(score=0.9, passed=True), agent_name="a")
            loaded = db.load_eval("trace-001")

        assert loaded is not None
        assert loaded.overall_score == 0.9
        assert loaded.passed is True

    def test_metrics_details_preserved(self, tmp_path):
        report = _make_report()
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_eval(report, agent_name="a")
            loaded = db.load_eval("trace-001")

        assert loaded is not None
        assert loaded.metrics[1].details == {"correct": 4, "total": 5}

    def test_default_timestamp_when_none(self, tmp_path):
        report = _make_report(timestamp=None)
        report.timestamp = None
        before = time.time()
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_eval(report, agent_name="a")
            loaded = db.load_eval("trace-001")
        after = time.time()

        assert loaded is not None
        assert before <= loaded.timestamp <= after


class TestListEvals:
    def test_list_all(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            for i in range(5):
                db.save_eval(
                    _make_report(trace_id=f"t-{i}", timestamp=1000.0 + i),
                    agent_name="agent-a",
                )
            results = db.list_evals()

        assert len(results) == 5
        assert results[0].trace_id == "t-4"
        assert results[4].trace_id == "t-0"

    def test_list_filtered_by_agent(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_eval(_make_report(trace_id="a1"), agent_name="alpha")
            db.save_eval(_make_report(trace_id="a2"), agent_name="alpha")
            db.save_eval(_make_report(trace_id="b1"), agent_name="beta")
            results = db.list_evals(agent_name="alpha")

        assert len(results) == 2
        trace_ids = {r.trace_id for r in results}
        assert trace_ids == {"a1", "a2"}

    def test_list_respects_limit(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            for i in range(10):
                db.save_eval(
                    _make_report(trace_id=f"t-{i}", timestamp=1000.0 + i),
                    agent_name="a",
                )
            results = db.list_evals(limit=3)

        assert len(results) == 3

    def test_list_empty_db(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            assert db.list_evals() == []


class TestBaseline:
    def test_latest_baseline(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_eval(_make_report(trace_id="old", score=0.6, timestamp=100.0), agent_name="bot")
            db.save_eval(_make_report(trace_id="new", score=0.9, timestamp=200.0), agent_name="bot")
            baseline = db.get_latest_baseline("bot")

        assert baseline is not None
        assert baseline.trace_id == "new"
        assert baseline.overall_score == 0.9

    def test_baseline_missing_agent(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_eval(_make_report(), agent_name="exists")
            assert db.get_latest_baseline("missing") is None


class TestDeleteAndCount:
    def test_delete(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_eval(_make_report(trace_id="del-me"), agent_name="a")
            assert db.delete_eval("del-me") is True
            assert db.load_eval("del-me") is None

    def test_delete_nonexistent(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            assert db.delete_eval("nope") is False

    def test_count_all(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            assert db.count() == 0
            db.save_eval(_make_report(trace_id="t1"), agent_name="a")
            db.save_eval(_make_report(trace_id="t2"), agent_name="b")
            assert db.count() == 2

    def test_count_by_agent(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_eval(_make_report(trace_id="t1"), agent_name="alpha")
            db.save_eval(_make_report(trace_id="t2"), agent_name="alpha")
            db.save_eval(_make_report(trace_id="t3"), agent_name="beta")
            assert db.count(agent_name="alpha") == 2
            assert db.count(agent_name="beta") == 1


class TestDBLifecycle:
    def test_creates_parent_directories(self, tmp_path):
        deep_path = tmp_path / "a" / "b" / "c" / "test.db"
        with TrajevalDB(deep_path) as db:
            db.save_eval(_make_report(), agent_name="a")
        assert deep_path.exists()

    def test_persistence_across_connections(self, tmp_path):
        db_path = tmp_path / "test.db"
        with TrajevalDB(db_path) as db:
            db.save_eval(_make_report(trace_id="persist"), agent_name="a")

        with TrajevalDB(db_path) as db:
            loaded = db.load_eval("persist")
        assert loaded is not None
        assert loaded.trace_id == "persist"

    def test_context_manager(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_eval(_make_report(), agent_name="a")
            assert db.count() == 1


def _make_judge_result(
    trace_id: str = "judge-001",
    score: float = 0.7,
    model: str = "claude-sonnet-4-6",
) -> JudgeResult:
    return JudgeResult(
        trace_id=trace_id,
        dimensions=[
            JudgeDimension(name="task_completion", score=4, explanation="Good"),
            JudgeDimension(name="reasoning_quality", score=3, explanation="OK"),
        ],
        overall_score=score,
        model=model,
    )


class TestJudgeSaveAndList:
    def test_save_returns_id(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            row_id = db.save_judge(_make_judge_result(), agent_name="a", passed=True)
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_roundtrip_via_list(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_judge(_make_judge_result(), agent_name="bot", passed=True)
            results = db.list_judges()
        assert len(results) == 1
        assert results[0].trace_id == "judge-001"
        assert results[0].model == "claude-sonnet-4-6"
        assert len(results[0].dimensions) == 2
        assert results[0].dimensions[0].name == "task_completion"
        assert results[0].dimensions[0].score == 4

    def test_filter_by_model(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_judge(_make_judge_result(trace_id="t1", model="claude-sonnet-4-6"), passed=True)
            db.save_judge(_make_judge_result(trace_id="t2", model="gpt-4o"), passed=True)
            results = db.list_judges(model="gpt-4o")
        assert len(results) == 1
        assert results[0].model == "gpt-4o"

    def test_filter_by_agent(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_judge(_make_judge_result(trace_id="t1"), agent_name="alpha", passed=True)
            db.save_judge(_make_judge_result(trace_id="t2"), agent_name="beta", passed=True)
            results = db.list_judges(agent_name="alpha")
        assert len(results) == 1
        assert results[0].trace_id == "t1"

    def test_filter_failed_only(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_judge(_make_judge_result(trace_id="t1"), passed=True)
            db.save_judge(_make_judge_result(trace_id="t2"), passed=False)
            results = db.list_judges(failed_only=True)
        assert len(results) == 1
        assert results[0].trace_id == "t2"

    def test_count_judges(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            assert db.count_judges() == 0
            db.save_judge(_make_judge_result(trace_id="t1"), passed=True)
            db.save_judge(_make_judge_result(trace_id="t2"), passed=False)
            assert db.count_judges() == 2

    def test_judge_and_eval_independent(self, tmp_path):
        with TrajevalDB(tmp_path / "test.db") as db:
            db.save_eval(_make_report(), agent_name="a")
            db.save_judge(_make_judge_result(), agent_name="a", passed=True)
            assert db.count() == 1
            assert db.count_judges() == 1
