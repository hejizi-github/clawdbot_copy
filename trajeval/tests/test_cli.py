"""CLI integration tests — verify exit codes, output formats, and error handling."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from trajeval.cli import main
from trajeval.scorer import JudgeDimension, JudgeResult

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestEvalCommand:
    def test_pass_exit_0(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"), "--threshold", "0.3",
        ])
        assert result.exit_code == 0

    def test_fail_exit_1(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "error_trace.json"), "--threshold", "0.7",
        ])
        assert result.exit_code == 1

    def test_invalid_file_exit_1(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json {{{")
        runner = CliRunner()
        result = runner.invoke(main, ["eval", str(bad_file)])
        assert result.exit_code == 1

    def test_nonexistent_file_exit_2(self):
        runner = CliRunner()
        result = runner.invoke(main, ["eval", "/nonexistent/trace.json"])
        assert result.exit_code == 2  # Click's UsageError for bad path

    def test_json_format_parseable(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json", "--threshold", "0.3",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "overall_score" in data
        assert "passed" in data
        assert "metrics" in data
        assert data["passed"] is True

    def test_json_format_shows_failed(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "error_trace.json"),
            "--format", "json", "--threshold", "0.7",
        ])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["passed"] is False

    def test_error_trace_parseable(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "error_trace.json"),
            "--format", "json", "--threshold", "0.3",
        ])
        data = json.loads(result.output)
        assert "overall_score" in data


class TestJudgeCommand:
    def _mock_judge_result(self, trace_id: str, score: float) -> JudgeResult:
        raw_score = int(score * 5)
        return JudgeResult(
            trace_id=trace_id,
            dimensions=[
                JudgeDimension(name="task_completion", score=raw_score, explanation="test"),
                JudgeDimension(name="reasoning_quality", score=raw_score, explanation="test"),
            ],
            overall_score=score,
            model="test-model",
        )

    @patch("trajeval.cli.judge")
    def test_pass_exit_0(self, mock_judge):
        mock_judge.return_value = self._mock_judge_result("test-trace-001", 0.8)
        runner = CliRunner()
        result = runner.invoke(main, [
            "judge", str(FIXTURES_DIR / "simple_trace.json"), "--threshold", "0.7",
        ])
        assert result.exit_code == 0

    @patch("trajeval.cli.judge")
    def test_fail_exit_1(self, mock_judge):
        mock_judge.return_value = self._mock_judge_result("test-trace-001", 0.4)
        runner = CliRunner()
        result = runner.invoke(main, [
            "judge", str(FIXTURES_DIR / "simple_trace.json"), "--threshold", "0.7",
        ])
        assert result.exit_code == 1

    @patch("trajeval.cli.judge")
    def test_error_exit_1(self, mock_judge):
        mock_judge.return_value = JudgeResult(
            trace_id="test-trace-001",
            model="test-model",
            error="API connection failed",
        )
        runner = CliRunner()
        result = runner.invoke(main, ["judge", str(FIXTURES_DIR / "simple_trace.json")])
        assert result.exit_code == 1
        assert "Judge error" in result.output

    @patch("trajeval.cli.judge")
    def test_json_format(self, mock_judge):
        mock_judge.return_value = self._mock_judge_result("test-trace-001", 0.8)
        runner = CliRunner()
        result = runner.invoke(main, [
            "judge", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json", "--threshold", "0.7",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["passed"] is True
        assert data["threshold"] == 0.7
        assert "dimensions" in data

    @patch("trajeval.cli.judge")
    def test_default_threshold_is_0_7(self, mock_judge):
        mock_judge.return_value = self._mock_judge_result("test-trace-001", 0.65)
        runner = CliRunner()
        result = runner.invoke(main, [
            "judge", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json",
        ])
        data = json.loads(result.output)
        assert data["passed"] is False
        assert result.exit_code == 1


class TestCompareCommand:
    def test_no_regression_exit_0(self):
        trace = str(FIXTURES_DIR / "simple_trace.json")
        runner = CliRunner()
        result = runner.invoke(main, ["compare", trace, trace])
        assert result.exit_code == 0

    def test_regression_exit_1(self):
        good = str(FIXTURES_DIR / "simple_trace.json")
        bad = str(FIXTURES_DIR / "error_trace.json")
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", good, bad, "--tolerance", "0.01",
        ])
        assert result.exit_code == 1

    def test_json_format(self):
        trace = str(FIXTURES_DIR / "simple_trace.json")
        runner = CliRunner()
        result = runner.invoke(main, ["compare", trace, trace, "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["has_regression"] is False
        assert "metric_deltas" in data
        assert "overall_delta" in data

    def test_markdown_format(self):
        trace = str(FIXTURES_DIR / "simple_trace.json")
        runner = CliRunner()
        result = runner.invoke(main, ["compare", trace, trace, "--format", "markdown"])
        assert result.exit_code == 0
        assert "| Metric |" in result.output
        assert "No Regression" in result.output

    def test_invalid_file_exit_1(self, tmp_path):
        good = str(FIXTURES_DIR / "simple_trace.json")
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{invalid")
        runner = CliRunner()
        result = runner.invoke(main, ["compare", good, str(bad_file)])
        assert result.exit_code == 1

    def test_custom_tolerance(self):
        good = str(FIXTURES_DIR / "simple_trace.json")
        bad = str(FIXTURES_DIR / "error_trace.json")
        runner = CliRunner()
        lenient = runner.invoke(main, [
            "compare", good, bad, "--format", "json", "--tolerance", "0.99",
        ])
        data = json.loads(lenient.output)
        assert data["has_regression"] is False
        assert lenient.exit_code == 0
