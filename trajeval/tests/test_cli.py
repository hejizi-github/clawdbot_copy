"""CLI integration tests — verify exit codes, output formats, and error handling."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from trajeval.calibration import HumanAnnotation
from trajeval.cli import _format_details_compact, main
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

    def test_recovery_window_flag_changes_output(self):
        runner = CliRunner()
        narrow = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "recovery_trace.json"),
            "--format", "json", "--threshold", "0.1", "--recovery-window", "1",
        ])
        wide = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "recovery_trace.json"),
            "--format", "json", "--threshold", "0.1", "--recovery-window", "5",
        ])
        narrow_data = json.loads(narrow.output)
        wide_data = json.loads(wide.output)
        narrow_recovery = next(
            m for m in narrow_data["metrics"] if m["name"] == "error_recovery"
        )
        wide_recovery = next(
            m for m in wide_data["metrics"] if m["name"] == "error_recovery"
        )
        assert narrow_recovery["details"]["recovery_window"] == 1
        assert wide_recovery["details"]["recovery_window"] == 5
        assert wide_recovery["details"]["recovered"] >= narrow_recovery["details"]["recovered"]

    def test_latency_budget_flag_changes_output(self):
        runner = CliRunner()
        tight = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json", "--threshold", "0.1", "--latency-budget", "500",
        ])
        generous = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json", "--threshold", "0.1", "--latency-budget", "50000",
        ])
        tight_data = json.loads(tight.output)
        generous_data = json.loads(generous.output)
        tight_lb = next(
            m for m in tight_data["metrics"] if m["name"] == "latency_budget"
        )
        generous_lb = next(
            m for m in generous_data["metrics"] if m["name"] == "latency_budget"
        )
        assert tight_lb["details"]["budget_ms"] == 500.0
        assert generous_lb["details"]["budget_ms"] == 50000.0
        assert generous_lb["score"] >= tight_lb["score"]

    def test_latency_budget_default_no_budget(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json", "--threshold", "0.1",
        ])
        data = json.loads(result.output)
        lb = next(m for m in data["metrics"] if m["name"] == "latency_budget")
        assert lb["details"]["mode"] == "no_budget"
        assert lb["score"] == 1.0

    def test_details_flag_shows_details_column(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--threshold", "0.3", "--details",
        ])
        assert result.exit_code == 0
        assert "Details" in result.output

    def test_no_details_flag_hides_column(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--threshold", "0.3",
        ])
        assert result.exit_code == 0
        assert "Details" not in result.output

    def test_details_flag_shows_metric_info(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--threshold", "0.3", "--details",
        ])
        assert result.exit_code == 0
        assert "total_steps=" in result.output or "total_tool_calls=" in result.output

    def test_details_flag_with_json_format_ignored(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json", "--threshold", "0.3", "--details",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "metrics" in data


class TestFormatDetailsCompact:
    def test_empty_dict(self):
        assert _format_details_compact({}) == ""

    def test_basic_ints(self):
        result = _format_details_compact({"total_steps": 10, "productive_steps": 8})
        assert "total_steps=10" in result
        assert "productive_steps=8" in result

    def test_float_formatting(self):
        result = _format_details_compact({"total_duration_ms": 1234.5678})
        assert "total_duration_ms=1234.6" in result

    def test_list_shows_count(self):
        result = _format_details_compact({"loops_found": [{"p": "a"}, {"p": "b"}]})
        assert "loops_found=2" in result

    def test_skips_mode_and_note(self):
        result = _format_details_compact({"total_steps": 5, "mode": "heuristic", "note": "no errors"})
        assert "mode" not in result
        assert "note" not in result
        assert "total_steps=5" in result

    def test_comma_separated(self):
        result = _format_details_compact({"a": 1, "b": 2})
        assert ", " in result


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

    def test_recovery_window_flag_flows_through(self):
        trace = str(FIXTURES_DIR / "recovery_trace.json")
        runner = CliRunner()
        narrow = runner.invoke(main, [
            "compare", trace, trace, "--format", "json", "--recovery-window", "1",
        ])
        wide = runner.invoke(main, [
            "compare", trace, trace, "--format", "json", "--recovery-window", "5",
        ])
        assert narrow.exit_code == 0
        assert wide.exit_code == 0
        narrow_data = json.loads(narrow.output)
        wide_data = json.loads(wide.output)
        narrow_er = next(
            d for d in narrow_data["metric_deltas"] if d["name"] == "error_recovery"
        )
        wide_er = next(
            d for d in wide_data["metric_deltas"] if d["name"] == "error_recovery"
        )
        assert narrow_er["baseline_details"]["recovery_window"] == 1
        assert narrow_er["current_details"]["recovery_window"] == 1
        assert wide_er["baseline_details"]["recovery_window"] == 5
        assert wide_er["current_details"]["recovery_window"] == 5

    def test_latency_budget_flag_flows_through(self):
        trace = str(FIXTURES_DIR / "simple_trace.json")
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", trace, trace, "--format", "json", "--latency-budget", "500",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "metric_deltas" in data
        lb_delta = next(
            d for d in data["metric_deltas"] if d["name"] == "latency_budget"
        )
        assert lb_delta is not None


class TestAnnotateCommand:
    def test_saves_annotations(self, tmp_path):
        out = tmp_path / "annotations.jsonl"
        runner = CliRunner()
        result = runner.invoke(main, [
            "annotate", str(FIXTURES_DIR / "simple_trace.json"),
            "--output", str(out),
            "--dimensions", "task_completion,reasoning_quality",
        ], input="4\n3\n")
        assert result.exit_code == 0
        assert "Saved 2 annotations" in result.output
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 2
        ann = json.loads(lines[0])
        assert ann["dimension"] == "task_completion"
        assert ann["human_score"] == 4

    def test_rejects_invalid_score_then_accepts(self, tmp_path):
        out = tmp_path / "annotations.jsonl"
        runner = CliRunner()
        result = runner.invoke(main, [
            "annotate", str(FIXTURES_DIR / "simple_trace.json"),
            "--output", str(out),
            "--dimensions", "task_completion",
        ], input="9\n3\n")
        assert result.exit_code == 0
        assert "Score must be 0-5" in result.output
        lines = [l for l in out.read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        ann = json.loads(lines[0])
        assert ann["human_score"] == 3

    def test_custom_annotator(self, tmp_path):
        out = tmp_path / "annotations.jsonl"
        runner = CliRunner()
        result = runner.invoke(main, [
            "annotate", str(FIXTURES_DIR / "simple_trace.json"),
            "--output", str(out),
            "--dimensions", "task_completion",
            "--annotator", "alice",
        ], input="5\n")
        assert result.exit_code == 0
        ann = json.loads(out.read_text().strip())
        assert ann["annotator"] == "alice"

    def test_invalid_trace_exit_1(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{invalid")
        runner = CliRunner()
        result = runner.invoke(main, ["annotate", str(bad)])
        assert result.exit_code == 1


class TestCalibrateCommand:
    def _make_fixtures(self, tmp_path):
        annotations_file = tmp_path / "annotations.jsonl"
        judgments_file = tmp_path / "judgments.jsonl"

        annotations = [
            HumanAnnotation(trace_id="t1", dimension="task_completion", human_score=4),
            HumanAnnotation(trace_id="t2", dimension="task_completion", human_score=2),
            HumanAnnotation(trace_id="t3", dimension="task_completion", human_score=5),
        ]
        with open(annotations_file, "w") as f:
            for a in annotations:
                f.write(a.model_dump_json() + "\n")

        judgments = [
            JudgeResult(
                trace_id="t1", overall_score=0.8, model="test",
                dimensions=[JudgeDimension(name="task_completion", score=4, explanation="good")],
            ),
            JudgeResult(
                trace_id="t2", overall_score=0.4, model="test",
                dimensions=[JudgeDimension(name="task_completion", score=2, explanation="weak")],
            ),
            JudgeResult(
                trace_id="t3", overall_score=1.0, model="test",
                dimensions=[JudgeDimension(name="task_completion", score=5, explanation="great")],
            ),
        ]
        with open(judgments_file, "w") as f:
            for j in judgments:
                f.write(j.model_dump_json() + "\n")

        return annotations_file, judgments_file

    def test_table_output(self, tmp_path):
        ann, jdg = self._make_fixtures(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["calibrate", str(ann), str(jdg)])
        assert result.exit_code == 0
        assert "Calibration" in result.output

    def test_json_output(self, tmp_path):
        ann, jdg = self._make_fixtures(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, ["calibrate", str(ann), str(jdg), "--format", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "overall_spearman_rho" in data
        assert "total_pairs" in data
        assert data["total_pairs"] == 3

    def test_empty_annotations_exit_1(self, tmp_path):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        jdg = tmp_path / "j.jsonl"
        jdg.write_text('{"trace_id":"t1","overall_score":0.5,"model":"m","dimensions":[]}\n')
        runner = CliRunner()
        result = runner.invoke(main, ["calibrate", str(empty), str(jdg)])
        assert result.exit_code == 1
        assert "No annotations" in result.output

    def test_empty_judgments_exit_1(self, tmp_path):
        ann = tmp_path / "a.jsonl"
        ann.write_text('{"trace_id":"t1","dimension":"d","human_score":3,"annotator":"x","timestamp":"2026-01-01T00:00:00+00:00"}\n')
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        runner = CliRunner()
        result = runner.invoke(main, ["calibrate", str(ann), str(empty)])
        assert result.exit_code == 1
        assert "No judge results" in result.output

    def test_threshold_pass_exit_0(self, tmp_path):
        ann, jdg = self._make_fixtures(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, [
            "calibrate", str(ann), str(jdg), "--threshold", "0.8",
        ])
        assert result.exit_code == 0

    def test_threshold_fail_exit_1(self, tmp_path):
        ann, jdg = self._make_weak_correlation_fixtures(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, [
            "calibrate", str(ann), str(jdg), "--threshold", "0.8",
        ])
        assert result.exit_code == 1

    def test_threshold_json_includes_passed_and_threshold(self, tmp_path):
        ann, jdg = self._make_fixtures(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, [
            "calibrate", str(ann), str(jdg),
            "--format", "json", "--threshold", "0.8",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["passed"] is True
        assert data["threshold"] == 0.8

    def test_threshold_json_fail_shows_false(self, tmp_path):
        ann, jdg = self._make_weak_correlation_fixtures(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, [
            "calibrate", str(ann), str(jdg),
            "--format", "json", "--threshold", "0.8",
        ])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["passed"] is False

    def test_no_threshold_omits_passed_from_json(self, tmp_path):
        ann, jdg = self._make_fixtures(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, [
            "calibrate", str(ann), str(jdg), "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "passed" not in data
        assert "threshold" not in data

    def test_no_threshold_always_exit_0(self, tmp_path):
        ann, jdg = self._make_weak_correlation_fixtures(tmp_path)
        runner = CliRunner()
        result = runner.invoke(main, [
            "calibrate", str(ann), str(jdg),
        ])
        assert result.exit_code == 0

    def _make_weak_correlation_fixtures(self, tmp_path):
        """Human and judge scores that weakly correlate (rho < 0.8)."""
        annotations_file = tmp_path / "weak_ann.jsonl"
        judgments_file = tmp_path / "weak_jdg.jsonl"

        annotations = [
            HumanAnnotation(trace_id="t1", dimension="task_completion", human_score=5),
            HumanAnnotation(trace_id="t2", dimension="task_completion", human_score=4),
            HumanAnnotation(trace_id="t3", dimension="task_completion", human_score=3),
            HumanAnnotation(trace_id="t4", dimension="task_completion", human_score=2),
            HumanAnnotation(trace_id="t5", dimension="task_completion", human_score=1),
        ]
        with open(annotations_file, "w") as f:
            for a in annotations:
                f.write(a.model_dump_json() + "\n")

        judgments = [
            JudgeResult(trace_id="t1", overall_score=0.6, model="test",
                        dimensions=[JudgeDimension(name="task_completion", score=3, explanation="ok")]),
            JudgeResult(trace_id="t2", overall_score=0.8, model="test",
                        dimensions=[JudgeDimension(name="task_completion", score=5, explanation="great")]),
            JudgeResult(trace_id="t3", overall_score=0.4, model="test",
                        dimensions=[JudgeDimension(name="task_completion", score=2, explanation="weak")]),
            JudgeResult(trace_id="t4", overall_score=0.6, model="test",
                        dimensions=[JudgeDimension(name="task_completion", score=4, explanation="good")]),
            JudgeResult(trace_id="t5", overall_score=0.2, model="test",
                        dimensions=[JudgeDimension(name="task_completion", score=1, explanation="bad")]),
        ]
        with open(judgments_file, "w") as f:
            for j in judgments:
                f.write(j.model_dump_json() + "\n")

        return annotations_file, judgments_file
