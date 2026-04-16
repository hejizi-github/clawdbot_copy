"""End-to-end integration tests for the eval → judge → calibrate pipeline.

These tests exercise real module interactions without mocking internal functions.
The only mock is a fake Anthropic client for the judge (avoids real API calls).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from trajeval.calibration import (
    AnnotationStore,
    CalibrationResult,
    HumanAnnotation,
    compute_correlation,
    load_judge_results,
)
from trajeval.cli import main
from trajeval.compare import compare_reports
from trajeval.ingester import IngestError, ingest_json
from trajeval.metrics import EvalReport, MetricConfig, evaluate
from trajeval.scorer import JudgeConfig, JudgeResult, judge

FIXTURES_DIR = Path(__file__).parent / "fixtures"

SAMPLE_TRACE_DICT = {
    "trace_id": "integration-test-001",
    "agent_name": "test-agent",
    "task": "Summarize a document",
    "steps": [
        {
            "type": "llm_call",
            "name": "claude-sonnet",
            "input": {"prompt": "Read the document"},
            "output": {"response": "I'll read it."},
            "duration_ms": 300.0,
            "tokens": {"prompt": 100, "completion": 20, "total": 120},
        },
        {
            "type": "tool_call",
            "name": "read_file",
            "input": {"path": "doc.txt"},
            "output": {"content": "Revenue grew 10%."},
            "duration_ms": 50.0,
        },
        {
            "type": "llm_call",
            "name": "claude-sonnet",
            "input": {"prompt": "Summarize this..."},
            "output": {"response": "Revenue grew 10% YoY."},
            "duration_ms": 500.0,
            "tokens": {"prompt": 200, "completion": 50, "total": 250},
        },
    ],
    "final_output": "Revenue grew 10% year-over-year.",
    "total_duration_ms": 850.0,
}


class FakeAnthropicClient:
    """Fake Anthropic client that returns valid judge JSON without calling the API."""

    def __init__(self, scores: dict[str, int] | None = None):
        self._scores = scores or {"task_completion": 4, "reasoning_quality": 3}
        self.messages = self
        self.call_count = 0

    def create(self, **kwargs):
        self.call_count += 1
        dims = []
        for name, score in self._scores.items():
            dims.append({"name": name, "score": score, "explanation": f"Test: {name}"})
        response_json = json.dumps({"dimensions": dims})
        return SimpleNamespace(content=[SimpleNamespace(text=response_json)])


class TestFullEvalPipeline:
    """Test the complete ingest → evaluate → report flow via Python API."""

    def test_ingest_and_evaluate_from_dict(self):
        trace = ingest_json(SAMPLE_TRACE_DICT)
        assert trace.trace_id == "integration-test-001"
        assert trace.step_count == 3
        assert len(trace.tool_calls) == 1
        assert len(trace.llm_calls) == 2

        report = evaluate(trace)
        assert isinstance(report, EvalReport)
        assert report.trace_id == "integration-test-001"
        assert len(report.metrics) == 6
        assert 0.0 <= report.overall_score <= 1.0

        metric_names = {m.name for m in report.metrics}
        assert metric_names == {"step_efficiency", "tool_accuracy", "loop_detection", "token_efficiency", "error_recovery", "latency_budget"}

    def test_ingest_and_evaluate_from_file(self):
        trace = ingest_json(FIXTURES_DIR / "simple_trace.json")
        report = evaluate(trace)
        assert report.trace_id == "test-trace-001"
        assert report.overall_score > 0.5

    def test_custom_threshold_affects_pass_fail(self):
        error_trace = ingest_json(FIXTURES_DIR / "error_trace.json")
        report = evaluate(error_trace)
        assert report.overall_score < 1.0

        lenient = evaluate(error_trace, MetricConfig(pass_threshold=0.1))
        strict = evaluate(error_trace, MetricConfig(pass_threshold=0.99))

        assert lenient.passed is True
        assert strict.passed is False
        for m in lenient.metrics:
            assert m.passed is True
        assert any(m.passed is False for m in strict.metrics)

    def test_expected_steps_changes_efficiency(self):
        trace = ingest_json(SAMPLE_TRACE_DICT)

        config_match = MetricConfig(expected_steps=3, pass_threshold=0.5)
        config_excess = MetricConfig(expected_steps=1, pass_threshold=0.5)

        report_match = evaluate(trace, config_match)
        report_excess = evaluate(trace, config_excess)

        eff_match = next(m for m in report_match.metrics if m.name == "step_efficiency")
        eff_excess = next(m for m in report_excess.metrics if m.name == "step_efficiency")

        assert eff_match.score == 1.0
        assert eff_excess.score < 1.0


class TestEvalComparePipeline:
    """Test eval → compare cross-module pipeline."""

    def test_same_trace_no_regression(self):
        trace = ingest_json(FIXTURES_DIR / "simple_trace.json")
        report = evaluate(trace)
        result = compare_reports(report, report)
        assert result.has_regression is False
        assert result.overall_delta == 0.0

    def test_good_vs_bad_detects_regression(self):
        good = evaluate(ingest_json(FIXTURES_DIR / "simple_trace.json"))
        bad = evaluate(ingest_json(FIXTURES_DIR / "error_trace.json"))
        result = compare_reports(good, bad, tolerance=0.01)
        assert result.has_regression is True
        assert result.overall_delta < 0

    def test_cli_eval_then_compare_json(self):
        runner = CliRunner()
        r1 = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json", "--threshold", "0.3",
        ])
        assert r1.exit_code == 0
        data1 = json.loads(r1.output)

        r2 = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "error_trace.json"),
            "--format", "json", "--threshold", "0.3",
        ])
        data2 = json.loads(r2.output)

        assert data1["overall_score"] > data2["overall_score"]

        cmp = runner.invoke(main, [
            "compare",
            str(FIXTURES_DIR / "simple_trace.json"),
            str(FIXTURES_DIR / "error_trace.json"),
            "--format", "json", "--tolerance", "0.01",
        ])
        assert cmp.exit_code == 1
        cmp_data = json.loads(cmp.output)
        assert cmp_data["has_regression"] is True


class TestJudgeWithFakeClient:
    """Test judge() with a fake client — exercises prompt building, parsing, scoring."""

    def test_judge_returns_valid_result(self):
        trace = ingest_json(SAMPLE_TRACE_DICT)
        config = JudgeConfig(dimensions=["task_completion", "reasoning_quality"])
        client = FakeAnthropicClient({"task_completion": 4, "reasoning_quality": 3})

        result = judge(trace, config=config, client=client)

        assert isinstance(result, JudgeResult)
        assert result.error is None
        assert result.trace_id == "integration-test-001"
        assert len(result.dimensions) == 2
        assert result.overall_score == (4 + 3) / 10

    def test_judge_perfect_score(self):
        trace = ingest_json(SAMPLE_TRACE_DICT)
        config = JudgeConfig(dimensions=["task_completion"])
        client = FakeAnthropicClient({"task_completion": 5})

        result = judge(trace, config=config, client=client)
        assert result.overall_score == 1.0

    def test_judge_with_custom_dimension(self):
        trace = ingest_json(SAMPLE_TRACE_DICT)
        config = JudgeConfig(dimensions=["safety", "creativity"])
        client = FakeAnthropicClient({"safety": 5, "creativity": 2})

        result = judge(trace, config=config, client=client)
        assert len(result.dimensions) == 2
        assert result.overall_score == (5 + 2) / 10

    def test_judge_cli_with_fake_client_exit_codes(self, monkeypatch):
        """Verify CLI judge exit codes by injecting FakeAnthropicClient via sys.modules.

        Instead of patching the entire judge() function, we inject a fake anthropic
        module so the full chain runs: CLI → judge() → build_user_prompt → fake API → parse → normalize.
        """
        import sys

        runner = CliRunner()

        high_client = FakeAnthropicClient({"task_completion": 5, "reasoning_quality": 4})
        fake_anthropic = type("FakeAnthropicModule", (), {
            "Anthropic": staticmethod(lambda: high_client),
        })()
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
        r = runner.invoke(main, [
            "judge", str(FIXTURES_DIR / "simple_trace.json"),
            "--threshold", "0.7",
        ])
        assert r.exit_code == 0
        assert high_client.call_count > 0, "fake client was not invoked — sys.modules mock may be ineffective"

        low_client = FakeAnthropicClient({"task_completion": 1, "reasoning_quality": 1})
        fake_anthropic_low = type("FakeAnthropicModule", (), {
            "Anthropic": staticmethod(lambda: low_client),
        })()
        monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic_low)
        r = runner.invoke(main, [
            "judge", str(FIXTURES_DIR / "simple_trace.json"),
            "--threshold", "0.7",
        ])
        assert r.exit_code == 1
        assert low_client.call_count > 0, "fake client was not invoked — sys.modules mock may be ineffective"


class TestCalibrationPipeline:
    """Test the full annotate → judge → calibrate pipeline."""

    def test_annotation_store_roundtrip(self, tmp_path):
        path = tmp_path / "annotations.jsonl"
        store = AnnotationStore(path)

        annotations = [
            HumanAnnotation(trace_id="t1", dimension="task_completion", human_score=4),
            HumanAnnotation(trace_id="t2", dimension="task_completion", human_score=2),
            HumanAnnotation(trace_id="t3", dimension="task_completion", human_score=5),
        ]
        store.save_batch(annotations)

        loaded = store.load()
        assert len(loaded) == 3
        assert loaded[0].trace_id == "t1"
        assert loaded[0].human_score == 4

        t1_only = store.load_for_trace("t1")
        assert len(t1_only) == 1

    def test_judge_results_jsonl_roundtrip(self, tmp_path):
        path = tmp_path / "judgments.jsonl"
        results = [
            JudgeResult(trace_id="t1", overall_score=0.8, model="test",
                        dimensions=[{"name": "task_completion", "score": 4, "explanation": "good"}]),
            JudgeResult(trace_id="t2", overall_score=0.4, model="test",
                        dimensions=[{"name": "task_completion", "score": 2, "explanation": "weak"}]),
        ]
        with open(path, "w") as f:
            for r in results:
                f.write(r.model_dump_json() + "\n")

        loaded = load_judge_results(path)
        assert len(loaded) == 2
        assert loaded[0].trace_id == "t1"
        assert loaded[0].dimensions[0].score == 4

    def test_full_calibration_with_correlation(self):
        annotations = [
            HumanAnnotation(trace_id=f"t{i}", dimension="task_completion", human_score=score)
            for i, score in enumerate([1, 2, 3, 4, 5], start=1)
        ]
        judge_results = [
            JudgeResult(
                trace_id=f"t{i}", overall_score=score / 5, model="test",
                dimensions=[{"name": "task_completion", "score": score, "explanation": "test"}],
            )
            for i, score in enumerate([1, 2, 3, 4, 5], start=1)
        ]

        result = compute_correlation(annotations, judge_results)
        assert isinstance(result, CalibrationResult)
        assert result.total_pairs == 5
        assert result.overall_spearman_rho == 1.0  # perfect correlation

    def test_calibration_with_disagreement(self):
        annotations = [
            HumanAnnotation(trace_id=f"t{i}", dimension="task_completion", human_score=score)
            for i, score in enumerate([5, 4, 3, 2, 1], start=1)
        ]
        judge_results = [
            JudgeResult(
                trace_id=f"t{i}", overall_score=score / 5, model="test",
                dimensions=[{"name": "task_completion", "score": score, "explanation": "test"}],
            )
            for i, score in enumerate([1, 2, 3, 4, 5], start=1)
        ]

        result = compute_correlation(annotations, judge_results)
        assert result.overall_spearman_rho == -1.0  # perfect negative correlation

    def test_cli_calibrate_json_output(self, tmp_path):
        ann_file = tmp_path / "ann.jsonl"
        jdg_file = tmp_path / "jdg.jsonl"

        annotations = [
            HumanAnnotation(trace_id=f"t{i}", dimension="task_completion", human_score=score)
            for i, score in enumerate([1, 2, 3, 4, 5], start=1)
        ]
        judge_results = [
            JudgeResult(
                trace_id=f"t{i}", overall_score=score / 5, model="test",
                dimensions=[{"name": "task_completion", "score": score, "explanation": "test"}],
            )
            for i, score in enumerate([1, 2, 3, 4, 5], start=1)
        ]

        with open(ann_file, "w") as f:
            for a in annotations:
                f.write(a.model_dump_json() + "\n")
        with open(jdg_file, "w") as f:
            for j in judge_results:
                f.write(j.model_dump_json() + "\n")

        runner = CliRunner()
        result = runner.invoke(main, [
            "calibrate", str(ann_file), str(jdg_file), "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["total_pairs"] == 5
        assert data["overall_spearman_rho"] == 1.0


class TestCIWorkflow:
    """Simulate the documented CI integration workflow."""

    def test_eval_threshold_exit_codes(self):
        runner = CliRunner()

        r = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "error_trace.json"),
            "--threshold", "0.3",
        ])
        assert r.exit_code == 0

        r = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "error_trace.json"),
            "--threshold", "0.99",
        ])
        assert r.exit_code == 1

    def test_compare_tolerance_exit_codes(self):
        runner = CliRunner()
        good = str(FIXTURES_DIR / "simple_trace.json")
        bad = str(FIXTURES_DIR / "error_trace.json")

        r = runner.invoke(main, ["compare", good, bad, "--tolerance", "0.01"])
        assert r.exit_code == 1

        r = runner.invoke(main, ["compare", good, bad, "--tolerance", "0.99"])
        assert r.exit_code == 0

    def test_eval_json_is_machine_parseable(self):
        runner = CliRunner()
        r = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json", "--threshold", "0.3",
        ])
        assert r.exit_code == 0
        data = json.loads(r.output)

        assert isinstance(data["overall_score"], float)
        assert isinstance(data["passed"], bool)
        assert isinstance(data["metrics"], list)
        for m in data["metrics"]:
            assert "name" in m
            assert "score" in m
            assert "passed" in m

    def test_compare_json_is_machine_parseable(self):
        runner = CliRunner()
        trace = str(FIXTURES_DIR / "simple_trace.json")
        r = runner.invoke(main, ["compare", trace, trace, "--format", "json"])
        assert r.exit_code == 0
        data = json.loads(r.output)

        assert isinstance(data["has_regression"], bool)
        assert isinstance(data["overall_delta"], float)
        assert isinstance(data["metric_deltas"], list)
        assert isinstance(data["tolerance"], float)


class TestReadmePythonAPI:
    """Verify that the README Python API examples actually work."""

    def test_deterministic_eval_example(self):
        trace = ingest_json({
            "trace_id": "readme-test",
            "agent_name": "readme-agent",
            "task": "Test task",
            "steps": [
                {
                    "type": "llm_call",
                    "name": "claude-sonnet",
                    "input": {"prompt": "Hello"},
                    "output": {"response": "Hi"},
                    "duration_ms": 100.0,
                    "tokens": {"prompt": 10, "completion": 5, "total": 15},
                },
            ],
            "final_output": "Done.",
        })

        config = MetricConfig(pass_threshold=0.8, expected_steps=5)
        report = evaluate(trace, config)

        assert isinstance(report.overall_score, float)
        assert isinstance(report.passed, bool)
        for m in report.metrics:
            assert hasattr(m, "name")
            assert hasattr(m, "score")
            assert hasattr(m, "passed")

    def test_judge_example_with_fake_client(self):
        trace = ingest_json(SAMPLE_TRACE_DICT)
        judge_config = JudgeConfig(
            model="claude-sonnet-4-6",
            dimensions=["task_completion", "reasoning_quality"],
        )
        client = FakeAnthropicClient({"task_completion": 4, "reasoning_quality": 4})
        result = judge(trace, config=judge_config, client=client)

        assert result.error is None
        assert isinstance(result.overall_score, float)
        for d in result.dimensions:
            assert hasattr(d, "name")
            assert hasattr(d, "score")
            assert hasattr(d, "explanation")


class TestBoundaryScenarios:
    """Edge cases: empty traces, large traces, missing fields, malformed input."""

    EMPTY_TRACE = {
        "trace_id": "empty-001",
        "agent_name": "empty-agent",
        "task": "Do nothing",
        "steps": [],
    }

    SINGLE_STEP_TRACE = {
        "trace_id": "single-001",
        "agent_name": "single-agent",
        "task": "One step only",
        "steps": [
            {
                "type": "llm_call",
                "name": "claude-sonnet",
                "input": {"prompt": "Hello"},
                "output": {"response": "Hi"},
                "duration_ms": 100.0,
                "tokens": {"prompt": 10, "completion": 5, "total": 15},
            }
        ],
    }

    ALL_ERRORS_TRACE = {
        "trace_id": "errors-001",
        "agent_name": "error-agent",
        "task": "Everything fails",
        "steps": [
            {"type": "error", "name": "crash_1", "input": {}, "output": {"error": "boom"}},
            {"type": "error", "name": "crash_2", "input": {}, "output": {"error": "bang"}},
            {"type": "error", "name": "crash_3", "input": {}, "output": {"error": "splat"}},
        ],
    }

    def test_empty_trace_eval(self):
        trace = ingest_json(self.EMPTY_TRACE)
        assert trace.step_count == 0
        assert len(trace.tool_calls) == 0
        assert len(trace.llm_calls) == 0

        report = evaluate(trace)
        assert isinstance(report, EvalReport)
        assert report.overall_score == 1.0
        assert report.passed is True

        for m in report.metrics:
            assert m.score == 1.0

    def test_empty_trace_judge(self):
        trace = ingest_json(self.EMPTY_TRACE)
        client = FakeAnthropicClient({"task_completion": 0, "reasoning_quality": 0})
        result = judge(trace, config=JudgeConfig(dimensions=["task_completion", "reasoning_quality"]), client=client)
        assert result.error is None
        assert result.overall_score == 0.0

    def test_empty_trace_compare_no_regression(self):
        trace = ingest_json(self.EMPTY_TRACE)
        report = evaluate(trace)
        result = compare_reports(report, report)
        assert result.has_regression is False

    def test_single_step_trace_eval(self):
        trace = ingest_json(self.SINGLE_STEP_TRACE)
        assert trace.step_count == 1

        report = evaluate(trace)
        assert report.overall_score > 0
        assert len(report.metrics) == 6

    def test_all_error_steps_eval(self):
        trace = ingest_json(self.ALL_ERRORS_TRACE)
        assert len(trace.errors) == 3

        report = evaluate(trace)
        eff = next(m for m in report.metrics if m.name == "step_efficiency")
        assert eff.score == 0.0
        assert eff.details["error_steps"] == 3

    def test_large_trace_performance(self):
        """50+ step trace should evaluate in under 1 second."""
        import time

        steps = []
        for i in range(60):
            steps.append({
                "type": "tool_call" if i % 3 == 0 else "llm_call",
                "name": f"step_{i}",
                "input": {"data": f"input_{i}"},
                "output": {"result": f"output_{i}"},
                "duration_ms": 100.0,
                "tokens": {"prompt": 50, "completion": 20, "total": 70},
            })

        large_trace = {
            "trace_id": "large-001",
            "agent_name": "large-agent",
            "task": "Complex multi-step task",
            "steps": steps,
        }

        start = time.monotonic()
        trace = ingest_json(large_trace)
        report = evaluate(trace)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0
        assert trace.step_count == 60
        assert len(report.metrics) == 6
        assert 0.0 <= report.overall_score <= 1.0

    def test_large_trace_judge_prompt_building(self):
        """Verify judge prompt is built correctly for a 50+ step trace."""
        from trajeval.scorer import build_user_prompt

        steps = [
            {
                "type": "llm_call",
                "name": f"model_{i}",
                "input": {"prompt": f"question_{i}"},
                "output": {"response": f"answer_{i}"},
                "duration_ms": 50.0,
                "tokens": {"prompt": 10, "completion": 5, "total": 15},
            }
            for i in range(55)
        ]
        trace = ingest_json({"trace_id": "large-judge", "steps": steps})
        prompt = build_user_prompt(trace, ["task_completion"])
        assert "Steps (55 total)" in prompt
        assert "Step 1" in prompt
        assert "Step 55" in prompt

    def test_missing_optional_fields(self):
        minimal = {"steps": [{"type": "llm_call", "name": "x"}]}
        trace = ingest_json(minimal)
        assert trace.agent_name == "unknown"
        assert trace.task == ""
        assert trace.trace_id  # auto-generated UUID
        assert trace.step_count == 1

        report = evaluate(trace)
        assert isinstance(report, EvalReport)

    def test_malformed_json_string_raises(self):
        import pytest

        with pytest.raises(IngestError, match="Invalid JSON"):
            ingest_json("{broken json!!!")

    def test_malformed_steps_not_list_raises(self):
        import pytest

        with pytest.raises(IngestError, match="must be a list"):
            ingest_json({"steps": "not a list"})

    def test_empty_trace_cli_eval(self, tmp_path):
        """CLI eval on empty trace should still produce valid output."""
        trace_file = tmp_path / "empty_trace.json"
        trace_file.write_text(json.dumps(self.EMPTY_TRACE))

        runner = CliRunner()
        r = runner.invoke(main, [
            "eval", str(trace_file), "--format", "json", "--threshold", "0.5",
        ])
        assert r.exit_code == 0
        data = json.loads(r.output)
        assert data["overall_score"] == 1.0
        assert data["passed"] is True


class TestErrorRecoveryIntegration:
    """Integration tests for the error_recovery metric using fixture files."""

    def test_recovery_trace_fixture(self):
        trace = ingest_json(FIXTURES_DIR / "recovery_trace.json")
        report = evaluate(trace)
        recovery = next(m for m in report.metrics if m.name == "error_recovery")
        assert recovery.details["total_errors"] == 3
        assert recovery.details["recovered"] == 1
        assert recovery.score == pytest.approx(1 / 3, abs=0.01)

    def test_error_trace_has_recovery(self):
        trace = ingest_json(FIXTURES_DIR / "error_trace.json")
        report = evaluate(trace)
        recovery = next(m for m in report.metrics if m.name == "error_recovery")
        assert recovery.details["total_errors"] == 1
        assert recovery.details["recovered"] == 1
        assert recovery.score == 1.0

    def test_simple_trace_no_errors(self):
        trace = ingest_json(FIXTURES_DIR / "simple_trace.json")
        report = evaluate(trace)
        recovery = next(m for m in report.metrics if m.name == "error_recovery")
        assert recovery.score == 1.0
        assert recovery.details["total_errors"] == 0

    def test_recovery_trace_cli_json(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "recovery_trace.json"),
            "--format", "json", "--threshold", "0.0",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        metric_names = [m["name"] for m in data["metrics"]]
        assert "error_recovery" in metric_names
        recovery = next(m for m in data["metrics"] if m["name"] == "error_recovery")
        assert recovery["details"]["total_errors"] == 3

    def test_recovery_trace_compare(self):
        good = str(FIXTURES_DIR / "simple_trace.json")
        bad = str(FIXTURES_DIR / "recovery_trace.json")
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", good, bad, "--format", "json", "--tolerance", "0.01",
        ])
        data = json.loads(result.output)
        delta_names = [d["name"] for d in data["metric_deltas"]]
        assert "error_recovery" in delta_names
