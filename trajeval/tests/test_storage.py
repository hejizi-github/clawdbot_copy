"""Tests for SQLite-backed result storage."""

from __future__ import annotations

import time

import pytest

from trajeval.metrics import EvalReport, MetricResult
from trajeval.scorer import JudgeDimension, JudgeResult
from trajeval.storage import ResultStore


@pytest.fixture
def store(tmp_path):
    db_path = tmp_path / "test.db"
    with ResultStore(db_path) as s:
        yield s


@pytest.fixture
def sample_eval_report():
    return EvalReport(
        trace_id="eval-trace-001",
        metrics=[
            MetricResult(name="step_efficiency", score=0.8, passed=True, details={"actual": 5}),
            MetricResult(name="tool_accuracy", score=0.6, passed=False, details={}),
        ],
        overall_score=0.7,
        passed=True,
        timestamp=1700000000.0,
    )


@pytest.fixture
def sample_judge_result():
    return JudgeResult(
        trace_id="judge-trace-001",
        dimensions=[
            JudgeDimension(name="task_completion", score=4, explanation="Good"),
            JudgeDimension(name="reasoning_quality", score=3, explanation="OK"),
        ],
        overall_score=0.7,
        model="claude-sonnet-4-6",
    )


class TestSaveAndRetrieveEval:
    def test_save_returns_id(self, store, sample_eval_report):
        row_id = store.save_eval(sample_eval_report, agent_name="test-agent")
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_round_trip(self, store, sample_eval_report):
        row_id = store.save_eval(sample_eval_report, agent_name="test-agent")
        stored = store.get_eval(row_id)
        assert stored is not None
        assert stored.trace_id == "eval-trace-001"
        assert stored.agent_name == "test-agent"
        assert stored.overall_score == 0.7
        assert stored.passed is True
        assert stored.report.trace_id == "eval-trace-001"
        assert len(stored.report.metrics) == 2
        assert stored.report.metrics[0].name == "step_efficiency"

    def test_get_nonexistent_returns_none(self, store):
        assert store.get_eval(999) is None

    def test_multiple_saves_get_unique_ids(self, store, sample_eval_report):
        id1 = store.save_eval(sample_eval_report, agent_name="a")
        id2 = store.save_eval(sample_eval_report, agent_name="b")
        assert id1 != id2


class TestSaveAndRetrieveJudge:
    def test_save_returns_id(self, store, sample_judge_result):
        row_id = store.save_judge(sample_judge_result, agent_name="test-agent", passed=True)
        assert isinstance(row_id, int)
        assert row_id >= 1

    def test_round_trip(self, store, sample_judge_result):
        row_id = store.save_judge(sample_judge_result, agent_name="judge-agent", passed=True)
        stored = store.get_judge(row_id)
        assert stored is not None
        assert stored.trace_id == "judge-trace-001"
        assert stored.agent_name == "judge-agent"
        assert stored.overall_score == 0.7
        assert stored.passed is True
        assert stored.model == "claude-sonnet-4-6"
        assert len(stored.result.dimensions) == 2
        assert stored.result.dimensions[0].name == "task_completion"
        assert stored.result.dimensions[0].score == 4

    def test_get_nonexistent_returns_none(self, store):
        assert store.get_judge(999) is None

    def test_passed_false_stored_correctly(self, store, sample_judge_result):
        row_id = store.save_judge(sample_judge_result, passed=False)
        stored = store.get_judge(row_id)
        assert stored is not None
        assert stored.passed is False


class TestListEvals:
    def _make_report(self, trace_id: str, score: float, passed: bool, ts: float) -> EvalReport:
        return EvalReport(
            trace_id=trace_id,
            metrics=[MetricResult(name="m", score=min(score, 1.0), passed=passed)],
            overall_score=score,
            passed=passed,
            timestamp=ts,
        )

    def test_list_empty(self, store):
        assert store.list_evals() == []

    def test_list_returns_all(self, store):
        store.save_eval(self._make_report("t1", 0.8, True, 100.0), agent_name="a")
        store.save_eval(self._make_report("t2", 0.5, False, 200.0), agent_name="b")
        results = store.list_evals()
        assert len(results) == 2
        assert results[0].trace_id == "t2"  # most recent first
        assert results[1].trace_id == "t1"

    def test_filter_by_agent(self, store):
        store.save_eval(self._make_report("t1", 0.8, True, 100.0), agent_name="alpha")
        store.save_eval(self._make_report("t2", 0.5, False, 200.0), agent_name="beta")
        results = store.list_evals(agent_name="alpha")
        assert len(results) == 1
        assert results[0].agent_name == "alpha"

    def test_filter_failed_only(self, store):
        store.save_eval(self._make_report("t1", 0.8, True, 100.0), agent_name="a")
        store.save_eval(self._make_report("t2", 0.4, False, 200.0), agent_name="a")
        results = store.list_evals(failed_only=True)
        assert len(results) == 1
        assert results[0].passed is False

    def test_limit(self, store):
        for i in range(10):
            store.save_eval(
                self._make_report(f"t{i}", 0.5, True, float(i)),
                agent_name="a",
            )
        results = store.list_evals(limit=3)
        assert len(results) == 3

    def test_combined_filters(self, store):
        store.save_eval(self._make_report("t1", 0.8, True, 100.0), agent_name="alpha")
        store.save_eval(self._make_report("t2", 0.3, False, 200.0), agent_name="alpha")
        store.save_eval(self._make_report("t3", 0.2, False, 300.0), agent_name="beta")
        results = store.list_evals(agent_name="alpha", failed_only=True)
        assert len(results) == 1
        assert results[0].trace_id == "t2"


class TestListJudges:
    def _make_result(self, trace_id: str, score: float, model: str) -> JudgeResult:
        return JudgeResult(
            trace_id=trace_id,
            dimensions=[JudgeDimension(name="d", score=3, explanation="ok")],
            overall_score=score,
            model=model,
        )

    def test_list_empty(self, store):
        assert store.list_judges() == []

    def test_filter_by_model(self, store):
        store.save_judge(self._make_result("t1", 0.8, "claude-sonnet-4-6"), passed=True)
        store.save_judge(self._make_result("t2", 0.6, "gpt-4o"), passed=True)
        results = store.list_judges(model="gpt-4o")
        assert len(results) == 1
        assert results[0].model == "gpt-4o"

    def test_filter_by_agent_and_failed(self, store):
        store.save_judge(self._make_result("t1", 0.8, "m"), agent_name="a", passed=True)
        store.save_judge(self._make_result("t2", 0.3, "m"), agent_name="a", passed=False)
        store.save_judge(self._make_result("t3", 0.2, "m"), agent_name="b", passed=False)
        results = store.list_judges(agent_name="a", failed_only=True)
        assert len(results) == 1
        assert results[0].trace_id == "t2"


class TestCount:
    def test_count_empty(self, store):
        assert store.count("eval") == 0
        assert store.count("judge") == 0

    def test_count_after_inserts(self, store, sample_eval_report, sample_judge_result):
        store.save_eval(sample_eval_report)
        store.save_eval(sample_eval_report)
        store.save_judge(sample_judge_result, passed=True)
        assert store.count("eval") == 2
        assert store.count("judge") == 1


class TestContextManager:
    def test_creates_db_file(self, tmp_path):
        db_path = tmp_path / "ctx.db"
        assert not db_path.exists()
        with ResultStore(db_path) as store:
            assert db_path.exists()

    def test_usable_after_reopen(self, tmp_path, sample_eval_report):
        db_path = tmp_path / "reopen.db"
        with ResultStore(db_path) as store:
            store.save_eval(sample_eval_report, agent_name="persist")
        with ResultStore(db_path) as store:
            results = store.list_evals()
            assert len(results) == 1
            assert results[0].agent_name == "persist"
