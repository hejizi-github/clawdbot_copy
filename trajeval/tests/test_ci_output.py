"""Tests for CI output formatting (GitHub Actions annotations)."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from trajeval.ci_output import format_compare_ci, format_eval_ci
from trajeval.cli import main
from trajeval.compare import ComparisonResult, MetricDelta
from trajeval.metrics import EvalReport, MetricResult

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestFormatEvalCI:
    def _make_report(self, metrics: list[MetricResult], passed: bool = True) -> EvalReport:
        overall = sum(m.score for m in metrics) / len(metrics) if metrics else 0.0
        return EvalReport(
            trace_id="test-trace-001",
            metrics=metrics,
            overall_score=round(overall, 4),
            passed=passed,
        )

    def test_all_pass_produces_notice_annotations(self):
        report = self._make_report([
            MetricResult(name="step_efficiency", score=0.95, passed=True, details={"total_steps": 5}),
            MetricResult(name="tool_accuracy", score=1.0, passed=True, details={"total_tool_calls": 3}),
        ])
        output = format_eval_ci(report)
        assert "::notice title=trajeval: step_efficiency PASS::" in output
        assert "::notice title=trajeval: tool_accuracy PASS::" in output
        assert "::error" not in output

    def test_failed_metric_produces_error_annotation(self):
        report = self._make_report([
            MetricResult(name="loop_detection", score=0.45, passed=False, details={"loops_found": [{"pattern": ["a", "a"], "length": 2, "occurrences": 3}], "step_count": 10, "total_repeated_steps": 4}),
        ], passed=False)
        output = format_eval_ci(report)
        assert "::error title=trajeval: loop_detection FAIL::" in output
        assert "1 loop(s) detected" in output

    def test_borderline_metric_produces_warning(self):
        report = self._make_report([
            MetricResult(name="error_recovery", score=0.75, passed=True, details={"total_errors": 2}),
        ])
        output = format_eval_ci(report)
        assert "::warning title=trajeval: error_recovery PASS::" in output

    def test_markdown_summary_table(self):
        report = self._make_report([
            MetricResult(name="step_efficiency", score=0.95, passed=True, details={}),
            MetricResult(name="tool_accuracy", score=0.60, passed=False, details={}),
        ], passed=False)
        output = format_eval_ci(report, threshold=0.7)
        assert "## trajeval Evaluation Summary" in output
        assert "| step_efficiency | 0.95 | ✅ PASS |" in output
        assert "| tool_accuracy | 0.60 | ❌ FAIL |" in output
        assert "threshold: 0.70" in output

    def test_overall_pass_status(self):
        report = self._make_report([
            MetricResult(name="m1", score=0.95, passed=True, details={}),
        ])
        output = format_eval_ci(report)
        assert "✅ PASS**" in output

    def test_overall_fail_status(self):
        report = self._make_report([
            MetricResult(name="m1", score=0.40, passed=False, details={}),
        ], passed=False)
        output = format_eval_ci(report)
        assert "❌ FAIL**" in output

    def test_metric_details_in_annotation(self):
        report = self._make_report([
            MetricResult(name="token_efficiency", score=0.90, passed=True, details={"total_tokens": 1500, "mode": "baseline"}),
        ])
        output = format_eval_ci(report)
        assert "tokens=1500" in output

    def test_latency_budget_details(self):
        report = self._make_report([
            MetricResult(name="latency_budget", score=0.85, passed=True, details={"budget_ms": 5000.0, "total_duration_ms": 5882}),
        ])
        output = format_eval_ci(report)
        assert "budget=5000ms" in output

    def test_empty_metrics_list(self):
        report = EvalReport(trace_id="empty", metrics=[], overall_score=0.0, passed=False)
        output = format_eval_ci(report)
        assert "## trajeval Evaluation Summary" in output


class TestFormatCompareCI:
    def _make_comparison(self, deltas: list[MetricDelta], has_regression: bool = False) -> ComparisonResult:
        overall = sum(d.delta for d in deltas) / len(deltas) if deltas else 0.0
        return ComparisonResult(
            baseline_trace_id="baseline-001",
            current_trace_id="current-001",
            metric_deltas=deltas,
            overall_delta=round(overall, 4),
            has_regression=has_regression,
            tolerance=0.05,
        )

    def test_regression_produces_error_annotation(self):
        result = self._make_comparison([
            MetricDelta(name="step_efficiency", baseline_score=0.90, current_score=0.60, delta=-0.30, direction="regressed"),
        ], has_regression=True)
        output = format_compare_ci(result)
        assert "::error title=trajeval: step_efficiency REGRESSED::" in output
        assert "0.90 → 0.60 (-0.30)" in output

    def test_improvement_produces_notice_annotation(self):
        result = self._make_comparison([
            MetricDelta(name="tool_accuracy", baseline_score=0.70, current_score=0.95, delta=0.25, direction="improved"),
        ])
        output = format_compare_ci(result)
        assert "::notice title=trajeval: tool_accuracy IMPROVED::" in output
        assert "0.70 → 0.95 (+0.25)" in output

    def test_unchanged_produces_notice_annotation(self):
        result = self._make_comparison([
            MetricDelta(name="loop_detection", baseline_score=1.0, current_score=1.0, delta=0.0, direction="unchanged"),
        ])
        output = format_compare_ci(result)
        assert "::notice title=trajeval: loop_detection unchanged::" in output

    def test_markdown_comparison_table(self):
        result = self._make_comparison([
            MetricDelta(name="m1", baseline_score=0.90, current_score=0.60, delta=-0.30, direction="regressed"),
            MetricDelta(name="m2", baseline_score=0.70, current_score=0.95, delta=0.25, direction="improved"),
        ], has_regression=True)
        output = format_compare_ci(result)
        assert "## trajeval Comparison Summary" in output
        assert "| m1 | 0.90 | 0.60 | -0.30 |" in output
        assert "REGRESSED" in output
        assert "| m2 | 0.70 | 0.95 | +0.25 |" in output
        assert "IMPROVED" in output

    def test_overall_regression_status(self):
        result = self._make_comparison([], has_regression=True)
        result.overall_delta = -0.15
        output = format_compare_ci(result)
        assert "REGRESSION DETECTED" in output

    def test_overall_ok_status(self):
        result = self._make_comparison([], has_regression=False)
        result.overall_delta = 0.10
        output = format_compare_ci(result)
        assert "OK**" in output

    def test_trace_ids_in_summary(self):
        result = self._make_comparison([])
        output = format_compare_ci(result)
        assert "baseline-001" in output
        assert "current-001" in output

    def test_tolerance_in_summary(self):
        result = self._make_comparison([])
        output = format_compare_ci(result)
        assert "Tolerance: 5%" in output


class TestCLICIFormat:
    def test_eval_ci_format(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "ci", "--threshold", "0.3",
        ])
        assert result.exit_code == 0
        assert "::notice" in result.output or "::warning" in result.output
        assert "## trajeval Evaluation Summary" in result.output

    def test_eval_ci_format_fail(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "error_trace.json"),
            "--format", "ci", "--threshold", "0.99",
        ])
        assert result.exit_code == 1
        assert "::error" in result.output

    def test_compare_ci_format(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare",
            str(FIXTURES_DIR / "simple_trace.json"),
            str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "ci",
        ])
        assert result.exit_code == 0
        assert "## trajeval Comparison Summary" in result.output

    def test_compare_ci_format_regression(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare",
            str(FIXTURES_DIR / "simple_trace.json"),
            str(FIXTURES_DIR / "error_trace.json"),
            "--format", "ci", "--tolerance", "0.01",
        ])
        assert result.exit_code == 1
        assert "REGRESSED" in result.output


class TestJudgeSingleAggregationWarning:
    def test_single_judge_non_default_aggregation_warns(self):
        runner = CliRunner()
        with __import__("unittest.mock", fromlist=["patch"]).patch("trajeval.cli.judge") as mock_judge:
            from trajeval.scorer import JudgeDimension, JudgeResult
            mock_judge.return_value = JudgeResult(
                trace_id="t1",
                dimensions=[JudgeDimension(name="task_completion", score=4, explanation="ok")],
                overall_score=0.8,
                model="test",
            )
            result = runner.invoke(main, [
                "judge", str(FIXTURES_DIR / "simple_trace.json"),
                "--judges", "1", "--aggregation", "mean",
            ])
        assert "Warning" in result.output
        assert "ignored" in result.output

    def test_single_judge_default_aggregation_no_warning(self):
        runner = CliRunner()
        with __import__("unittest.mock", fromlist=["patch"]).patch("trajeval.cli.judge") as mock_judge:
            from trajeval.scorer import JudgeDimension, JudgeResult
            mock_judge.return_value = JudgeResult(
                trace_id="t1",
                dimensions=[JudgeDimension(name="task_completion", score=4, explanation="ok")],
                overall_score=0.8,
                model="test",
            )
            result = runner.invoke(main, [
                "judge", str(FIXTURES_DIR / "simple_trace.json"),
                "--judges", "1", "--aggregation", "median",
            ])
        assert "Warning" not in result.output
        assert "ignored" not in result.output
