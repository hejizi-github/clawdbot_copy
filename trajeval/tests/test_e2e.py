"""End-to-end tests: verify full CLI pipelines without mocking internal modules."""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from trajeval.cli import main

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestEvalToImprovePipeline:
    """Pipeline: eval trace → save JSON → feed to improve → get recommendations."""

    def test_single_trace_pipeline(self, tmp_path):
        runner = CliRunner()

        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json", "--threshold", "0.3",
        ])
        assert result.exit_code == 0
        eval_data = json.loads(result.output)
        assert eval_data["passed"] is True

        eval_file = tmp_path / "eval_result.json"
        eval_file.write_text(json.dumps(eval_data))

        improve_result = runner.invoke(main, ["improve", str(eval_file), "--format", "json"])
        assert improve_result.exit_code == 0
        improve_data = json.loads(improve_result.output)
        assert "findings" in improve_data
        assert "recommendations" in improve_data
        assert "metric_summary" in improve_data
        assert improve_data["num_evaluations"] == 1

    def test_multi_trace_pipeline(self, tmp_path):
        runner = CliRunner()

        traces = ["simple_trace.json", "error_trace.json", "loop_trace.json"]
        eval_files = []
        for trace_name in traces:
            result = runner.invoke(main, [
                "eval", str(FIXTURES_DIR / trace_name),
                "--format", "json", "--threshold", "0.3",
            ])
            eval_data = json.loads(result.output)
            f = tmp_path / f"eval_{trace_name}"
            f.write_text(json.dumps(eval_data))
            eval_files.append(str(f))

        args = ["improve"] + eval_files + ["--format", "json"]
        improve_result = runner.invoke(main, args)
        assert improve_result.exit_code == 0
        improve_data = json.loads(improve_result.output)
        assert improve_data["num_evaluations"] == 3

        for name, summary in improve_data["metric_summary"].items():
            assert "mean_score" in summary
            assert "fail_rate" in summary
            assert "std_dev" in summary


class TestEvalComparePipeline:
    """Pipeline: eval two traces → compare → detect regressions."""

    def test_good_vs_bad_trace(self):
        runner = CliRunner()

        result = runner.invoke(main, [
            "compare",
            str(FIXTURES_DIR / "simple_trace.json"),
            str(FIXTURES_DIR / "error_trace.json"),
            "--format", "json",
            "--tolerance", "0.05",
            "--threshold", "0.3",
        ])
        data = json.loads(result.output)
        assert "metric_deltas" in data
        assert "has_regression" in data
        assert "overall_delta" in data
        assert data["baseline_trace_id"] == "test-trace-001"
        assert data["current_trace_id"] == "error-trace-001"

    def test_same_trace_no_regression(self):
        runner = CliRunner()
        trace = str(FIXTURES_DIR / "simple_trace.json")

        result = runner.invoke(main, [
            "compare", trace, trace,
            "--format", "json", "--tolerance", "0.05",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["has_regression"] is False
        assert data["overall_delta"] == 0.0
        for d in data["metric_deltas"]:
            assert d["delta"] == 0.0

    def test_compare_markdown_output(self):
        runner = CliRunner()

        result = runner.invoke(main, [
            "compare",
            str(FIXTURES_DIR / "simple_trace.json"),
            str(FIXTURES_DIR / "error_trace.json"),
            "--format", "markdown",
            "--threshold", "0.3",
        ])
        assert "##" in result.output
        assert "Metric" in result.output

    def test_compare_ci_output(self):
        runner = CliRunner()

        result = runner.invoke(main, [
            "compare",
            str(FIXTURES_DIR / "simple_trace.json"),
            str(FIXTURES_DIR / "error_trace.json"),
            "--format", "ci",
            "--threshold", "0.3",
        ])
        assert "::" in result.output


class TestCIOutputPipeline:
    """Pipeline: eval with CI output format for GitHub Actions."""

    def test_eval_ci_format(self):
        runner = CliRunner()

        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "ci", "--threshold", "0.3",
        ])
        assert result.exit_code == 0
        assert "::" in result.output

    def test_eval_ci_fail(self):
        runner = CliRunner()

        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "error_trace.json"),
            "--format", "ci", "--threshold", "0.99",
        ])
        assert result.exit_code == 1
        assert "::" in result.output


class TestExitCodeContract:
    """Verify exit code semantics across all commands."""

    def test_eval_pass_threshold_boundary(self):
        runner = CliRunner()

        result_low = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "error_trace.json"),
            "--format", "json", "--threshold", "0.01",
        ])
        assert result_low.exit_code == 0

        result_high = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "error_trace.json"),
            "--format", "json", "--threshold", "0.99",
        ])
        assert result_high.exit_code == 1

    def test_compare_regression_exit_code(self):
        runner = CliRunner()

        result = runner.invoke(main, [
            "compare",
            str(FIXTURES_DIR / "simple_trace.json"),
            str(FIXTURES_DIR / "error_trace.json"),
            "--format", "json", "--tolerance", "0.01",
            "--threshold", "0.3",
        ])
        data = json.loads(result.output)
        if data["has_regression"]:
            assert result.exit_code == 1
        else:
            assert result.exit_code == 0

    def test_improve_always_exit_0(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "improve",
            str(FIXTURES_DIR / "eval_result_bad.json"),
            "--format", "json",
        ])
        assert result.exit_code == 0

    def test_improve_no_files_exit_1(self):
        runner = CliRunner()
        result = runner.invoke(main, ["improve", "--format", "json"])
        assert result.exit_code == 1


class TestOutputFormatConsistency:
    """Verify JSON output schema consistency across commands."""

    def test_eval_json_schema(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json", "--threshold", "0.3",
        ])
        data = json.loads(result.output)

        assert isinstance(data["trace_id"], str)
        assert isinstance(data["overall_score"], (int, float))
        assert isinstance(data["passed"], bool)
        assert isinstance(data["metrics"], list)
        for m in data["metrics"]:
            assert "name" in m
            assert "score" in m
            assert "passed" in m

    def test_compare_json_schema(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare",
            str(FIXTURES_DIR / "simple_trace.json"),
            str(FIXTURES_DIR / "error_trace.json"),
            "--format", "json", "--threshold", "0.3",
        ])
        data = json.loads(result.output)

        assert isinstance(data["baseline_trace_id"], str)
        assert isinstance(data["current_trace_id"], str)
        assert isinstance(data["overall_delta"], (int, float))
        assert isinstance(data["has_regression"], bool)
        assert isinstance(data["tolerance"], (int, float))
        assert isinstance(data["metric_deltas"], list)
        for d in data["metric_deltas"]:
            assert "name" in d
            assert "baseline_score" in d
            assert "current_score" in d
            assert "delta" in d
            assert "direction" in d

    def test_improve_json_schema(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "improve",
            str(FIXTURES_DIR / "eval_result_good.json"),
            str(FIXTURES_DIR / "eval_result_bad.json"),
            "--format", "json",
        ])
        data = json.loads(result.output)

        assert isinstance(data["num_evaluations"], int)
        assert isinstance(data["findings"], list)
        assert isinstance(data["recommendations"], list)
        assert isinstance(data["metric_summary"], dict)
        for f in data["findings"]:
            assert "metric" in f
            assert "pattern" in f
            assert "severity" in f
            assert "evidence" in f
        for r in data["recommendations"]:
            assert "title" in r
            assert "priority" in r
            assert "finding" in r
            assert "suggestion" in r


class TestParameterFlowThrough:
    """Verify CLI parameters actually affect output (not just accepted)."""

    def test_threshold_changes_pass_fail(self):
        runner = CliRunner()

        result_pass = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "error_trace.json"),
            "--format", "json", "--threshold", "0.3",
        ])
        result_fail = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "error_trace.json"),
            "--format", "json", "--threshold", "0.99",
        ])
        data_pass = json.loads(result_pass.output)
        data_fail = json.loads(result_fail.output)
        assert data_pass["passed"] is True
        assert data_fail["passed"] is False
        assert data_pass["overall_score"] == data_fail["overall_score"]

    def test_tolerance_changes_regression_detection(self):
        runner = CliRunner()

        result_tight = runner.invoke(main, [
            "compare",
            str(FIXTURES_DIR / "simple_trace.json"),
            str(FIXTURES_DIR / "error_trace.json"),
            "--format", "json", "--tolerance", "0.001",
            "--threshold", "0.3",
        ])
        result_loose = runner.invoke(main, [
            "compare",
            str(FIXTURES_DIR / "simple_trace.json"),
            str(FIXTURES_DIR / "error_trace.json"),
            "--format", "json", "--tolerance", "0.99",
            "--threshold", "0.3",
        ])
        data_tight = json.loads(result_tight.output)
        data_loose = json.loads(result_loose.output)
        assert data_tight["has_regression"] is True
        assert data_loose["has_regression"] is False

    def test_recovery_window_affects_score(self):
        runner = CliRunner()

        result_short = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "recovery_trace.json"),
            "--format", "json", "--threshold", "0.1", "--recovery-window", "1",
        ])
        result_long = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "recovery_trace.json"),
            "--format", "json", "--threshold", "0.1", "--recovery-window", "10",
        ])
        data_short = json.loads(result_short.output)
        data_long = json.loads(result_long.output)

        short_recovery = next(
            (m for m in data_short["metrics"] if m["name"] == "error_recovery"), None
        )
        long_recovery = next(
            (m for m in data_long["metrics"] if m["name"] == "error_recovery"), None
        )
        assert short_recovery is not None, "error_recovery metric missing for recovery-window=1"
        assert long_recovery is not None, "error_recovery metric missing for recovery-window=10"
        assert short_recovery["details"]["recovery_window"] == 1
        assert long_recovery["details"]["recovery_window"] == 10


class TestClawdbotE2EPipeline:
    """Pipeline: eval Clawdbot JSONL → compare with JSON → improve."""

    CLAWDBOT_FIXTURE = FIXTURES_DIR / "clawdbot_session.jsonl"

    def test_clawdbot_eval_metric_values(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(self.CLAWDBOT_FIXTURE),
            "--input-format", "clawdbot",
            "--format", "json", "--threshold", "0.1",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)

        assert data["trace_id"] == "clawdbot-test-001"
        assert data["passed"] is True
        assert data["overall_score"] >= 0.8

        metrics_by_name = {m["name"]: m for m in data["metrics"]}
        assert "step_efficiency" in metrics_by_name
        assert "tool_accuracy" in metrics_by_name
        assert metrics_by_name["tool_accuracy"]["details"]["total_tool_calls"] == 1
        assert metrics_by_name["tool_accuracy"]["details"]["failed"] == 0
        assert metrics_by_name["step_efficiency"]["details"]["total_steps"] == 3

    def test_clawdbot_vs_json_compare(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare",
            str(FIXTURES_DIR / "simple_trace.json"),
            str(self.CLAWDBOT_FIXTURE),
            "--format", "json", "--threshold", "0.1",
        ])
        assert result.exit_code in (0, 1)
        data = json.loads(result.output)
        assert data["baseline_trace_id"] == "test-trace-001"
        assert data["current_trace_id"] == "clawdbot-test-001"
        assert isinstance(data["overall_delta"], (int, float))
        assert len(data["metric_deltas"]) >= 4

    def test_clawdbot_full_pipeline(self, tmp_path):
        runner = CliRunner()

        eval_result = runner.invoke(main, [
            "eval", str(self.CLAWDBOT_FIXTURE),
            "--format", "json", "--threshold", "0.1",
        ])
        eval_data = json.loads(eval_result.output)
        eval_file = tmp_path / "clawdbot_eval.json"
        eval_file.write_text(json.dumps(eval_data))

        improve_result = runner.invoke(main, [
            "improve", str(eval_file), "--format", "json",
        ])
        assert improve_result.exit_code == 0
        improve_data = json.loads(improve_result.output)
        assert improve_data["num_evaluations"] == 1
        assert "findings" in improve_data
        assert "recommendations" in improve_data

    def test_clawdbot_multi_eval_improve(self, tmp_path):
        runner = CliRunner()
        eval_files = []
        for i in range(3):
            result = runner.invoke(main, [
                "eval", str(self.CLAWDBOT_FIXTURE),
                "--input-format", "clawdbot",
                "--format", "json", "--threshold", "0.1",
            ])
            assert result.exit_code == 0
            f = tmp_path / f"eval_{i}.json"
            f.write_text(result.output)
            eval_files.append(str(f))

        args = ["improve"] + eval_files + ["--format", "json"]
        improve_result = runner.invoke(main, args)
        assert improve_result.exit_code == 0
        improve_data = json.loads(improve_result.output)
        assert improve_data["num_evaluations"] == 3
        assert isinstance(improve_data["metric_summary"], dict)
        assert len(improve_data["metric_summary"]) >= 3


class TestVersionCommand:
    def test_version_output(self):
        runner = CliRunner()
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "trajeval" in result.output
        assert "0.1.0" in result.output
