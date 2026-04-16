"""End-to-end integration tests for the eval → judge → calibrate pipeline.

These tests exercise real module interactions without mocking internal functions.
The only mock is a fake Anthropic client for the judge (avoids real API calls).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

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
from trajeval.ingester import ingest_json
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

    def create(self, **kwargs):
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
        assert len(report.metrics) == 4
        assert 0.0 <= report.overall_score <= 1.0

        metric_names = {m.name for m in report.metrics}
        assert metric_names == {"step_efficiency", "tool_accuracy", "loop_detection", "token_efficiency"}

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

    def test_judge_cli_with_fake_client_exit_codes(self):
        """Verify CLI judge exit codes using a fake client via patch at the judge function level."""
        from unittest.mock import patch

        good_result = JudgeResult(
            trace_id="test-trace-001",
            dimensions=[],
            overall_score=0.9,
            model="fake",
        )
        bad_result = JudgeResult(
            trace_id="test-trace-001",
            dimensions=[],
            overall_score=0.3,
            model="fake",
        )

        runner = CliRunner()
        with patch("trajeval.cli.judge", return_value=good_result):
            r = runner.invoke(main, [
                "judge", str(FIXTURES_DIR / "simple_trace.json"),
                "--threshold", "0.7",
            ])
            assert r.exit_code == 0

        with patch("trajeval.cli.judge", return_value=bad_result):
            r = runner.invoke(main, [
                "judge", str(FIXTURES_DIR / "simple_trace.json"),
                "--threshold", "0.7",
            ])
            assert r.exit_code == 1


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

    def test_full_calibration_with_correlation(self, tmp_path):
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

    def test_calibration_with_disagreement(self, tmp_path):
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
