"""CLI integration tests — verify exit codes, output formats, and error handling."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from trajeval.calibration import HumanAnnotation
from trajeval.cli import _format_details_compact, main
from trajeval.scorer import ALL_DIMENSIONS, DimensionStat, EnsembleResult, JudgeDimension, JudgeResult

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

    def test_similarity_threshold_default_no_near_loops(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json", "--threshold", "0.1",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        loop_m = next(m for m in data["metrics"] if m["name"] == "loop_detection")
        assert "near_loops_found" not in loop_m["details"]

    def test_similarity_threshold_flag_changes_output(self):
        runner = CliRunner()
        exact_result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "loop_trace.json"),
            "--format", "json", "--threshold", "0.1",
        ])
        fuzzy_result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "loop_trace.json"),
            "--format", "json", "--threshold", "0.1",
            "--similarity-threshold", "0.5",
        ])
        assert exact_result.exit_code == 0
        assert fuzzy_result.exit_code == 0
        exact_data = json.loads(exact_result.output)
        fuzzy_data = json.loads(fuzzy_result.output)
        exact_loop = next(m for m in exact_data["metrics"] if m["name"] == "loop_detection")
        fuzzy_loop = next(m for m in fuzzy_data["metrics"] if m["name"] == "loop_detection")
        assert "near_loops_found" not in exact_loop["details"]
        assert "near_loops_found" in fuzzy_loop["details"]
        assert fuzzy_loop["score"] < exact_loop["score"]


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

    @patch("trajeval.cli.judge")
    def test_no_randomize_flag(self, mock_judge):
        mock_judge.return_value = self._mock_judge_result("test-trace-001", 0.8)
        runner = CliRunner()
        result = runner.invoke(main, [
            "judge", str(FIXTURES_DIR / "simple_trace.json"), "--no-randomize",
        ])
        assert result.exit_code == 0
        call_kwargs = mock_judge.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[1].get("config") or call_kwargs[0][1]
        assert config.randomize_order is False

    @patch("trajeval.cli.ensemble_judge")
    def test_judges_flag_triggers_ensemble(self, mock_ensemble):
        mock_ensemble.return_value = EnsembleResult(
            trace_id="test-trace-001",
            dimensions=[
                JudgeDimension(name="task_completion", score=4, explanation="test"),
            ],
            overall_score=0.8,
            model="test-model",
            num_judges=3,
            aggregation="median",
            individual_results=[],
            dimension_stats=[
                DimensionStat(name="task_completion", median_score=4.0, mean_score=4.0, std_dev=0.5, scores=[3, 4, 5]),
            ],
        )
        runner = CliRunner()
        result = runner.invoke(main, [
            "judge", str(FIXTURES_DIR / "simple_trace.json"), "--judges", "3",
        ])
        assert result.exit_code == 0
        assert mock_ensemble.call_count == 1
        call_kwargs = mock_ensemble.call_args
        ensemble_config = call_kwargs.kwargs.get("ensemble_config") or call_kwargs[1].get("ensemble_config")
        assert ensemble_config.num_judges == 3

    @patch("trajeval.cli.ensemble_judge")
    def test_ensemble_json_format(self, mock_ensemble):
        mock_ensemble.return_value = EnsembleResult(
            trace_id="test-trace-001",
            dimensions=[
                JudgeDimension(name="task_completion", score=4, explanation="test"),
            ],
            overall_score=0.8,
            model="test-model",
            num_judges=3,
            aggregation="median",
            individual_results=[
                JudgeResult(trace_id="t", overall_score=0.7, model="m"),
                JudgeResult(trace_id="t", overall_score=0.8, model="m"),
                JudgeResult(trace_id="t", overall_score=0.9, model="m"),
            ],
            dimension_stats=[
                DimensionStat(name="task_completion", median_score=4.0, mean_score=4.0, std_dev=0.5, scores=[3, 4, 5]),
            ],
        )
        runner = CliRunner()
        result = runner.invoke(main, [
            "judge", str(FIXTURES_DIR / "simple_trace.json"),
            "--judges", "3", "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "ensemble" in data
        assert data["ensemble"]["num_judges"] == 3
        assert data["ensemble"]["aggregation"] == "median"
        assert len(data["ensemble"]["individual_scores"]) == 3
        assert "agreement" in data["ensemble"]


    def test_judges_zero_rejected(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "judge", str(FIXTURES_DIR / "simple_trace.json"), "--judges", "0",
        ])
        assert result.exit_code == 2

    def test_judges_negative_rejected(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "judge", str(FIXTURES_DIR / "simple_trace.json"), "--judges", "-1",
        ])
        assert result.exit_code == 2

    @patch("trajeval.cli.ensemble_judge")
    def test_aggregation_flag_flows_through(self, mock_ensemble):
        mock_ensemble.return_value = EnsembleResult(
            trace_id="test-trace-001",
            dimensions=[
                JudgeDimension(name="task_completion", score=4, explanation="test"),
            ],
            overall_score=0.8,
            model="test-model",
            num_judges=3,
            aggregation="mean",
            individual_results=[],
            dimension_stats=[
                DimensionStat(name="task_completion", median_score=4.0, mean_score=4.0, std_dev=0.5, scores=[3, 4, 5]),
            ],
        )
        runner = CliRunner()
        result = runner.invoke(main, [
            "judge", str(FIXTURES_DIR / "simple_trace.json"),
            "--judges", "3", "--aggregation", "mean",
        ])
        assert result.exit_code == 0
        call_kwargs = mock_ensemble.call_args
        ensemble_config = call_kwargs.kwargs.get("ensemble_config") or call_kwargs[1].get("ensemble_config")
        assert ensemble_config.aggregation == "mean"

    def test_aggregation_invalid_rejected(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "judge", str(FIXTURES_DIR / "simple_trace.json"),
            "--judges", "3", "--aggregation", "mode",
        ])
        assert result.exit_code == 2


class TestImproveCommand:
    def test_json_output_with_good_results(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "improve", str(FIXTURES_DIR / "eval_result_good.json"), "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["num_evaluations"] == 1
        assert "step_efficiency" in data["metric_summary"]
        assert data["metric_summary"]["step_efficiency"]["mean_score"] == 0.9

    def test_json_output_with_bad_results(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "improve",
            str(FIXTURES_DIR / "eval_result_bad.json"),
            str(FIXTURES_DIR / "eval_result_bad.json"),
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["num_evaluations"] == 2
        assert len(data["findings"]) > 0
        assert len(data["recommendations"]) > 0
        high_recs = [r for r in data["recommendations"] if r["priority"] == "high"]
        assert len(high_recs) > 0

    def test_table_output_runs(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "improve", str(FIXTURES_DIR / "eval_result_good.json"),
        ])
        assert result.exit_code == 0
        assert "Improvement Analysis" in result.output
        assert "Metric Summary" in result.output

    def test_multiple_files(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "improve",
            str(FIXTURES_DIR / "eval_result_good.json"),
            str(FIXTURES_DIR / "eval_result_bad.json"),
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["num_evaluations"] == 2

    def test_no_recommendations_for_healthy_results(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "improve", str(FIXTURES_DIR / "eval_result_good.json"), "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert len(data["recommendations"]) == 0

    def test_invalid_file_skipped_with_warning(self, tmp_path):
        bad = tmp_path / "not_json.json"
        bad.write_text("not valid json")
        runner = CliRunner()
        result = runner.invoke(main, [
            "improve", str(bad), str(FIXTURES_DIR / "eval_result_good.json"),
            "--format", "json",
        ])
        assert result.exit_code == 0
        assert "skipping" in result.output.lower() or "Warning" in result.output

    def test_all_invalid_files_exit_1(self, tmp_path):
        bad = tmp_path / "garbage.json"
        bad.write_text("{{{")
        runner = CliRunner()
        result = runner.invoke(main, ["improve", str(bad)])
        assert result.exit_code == 1

    def test_recommendations_are_actionable(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "improve",
            str(FIXTURES_DIR / "eval_result_bad.json"),
            str(FIXTURES_DIR / "eval_result_bad.json"),
            str(FIXTURES_DIR / "eval_result_bad.json"),
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        for rec in data["recommendations"]:
            assert len(rec["suggestion"]) > 20, "Recommendations should be substantive"
            assert rec["title"], "Recommendations must have a title"

    def test_judge_files_with_eval(self, tmp_path):
        jf = tmp_path / "judge1.json"
        jf.write_text(JudgeResult(
            trace_id="t1", overall_score=0.2, model="test",
            dimensions=[JudgeDimension(name="task_completion", score=1)],
        ).model_dump_json())
        runner = CliRunner()
        result = runner.invoke(main, [
            "improve", str(FIXTURES_DIR / "eval_result_good.json"),
            "--judge-files", str(jf),
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "judge:task_completion" in data["metric_summary"]
        assert "step_efficiency" in data["metric_summary"]

    def test_judge_only_without_eval_files(self, tmp_path):
        jf = tmp_path / "judge1.json"
        jf.write_text(JudgeResult(
            trace_id="t1", overall_score=0.6, model="test",
            dimensions=[JudgeDimension(name="task_completion", score=3)],
        ).model_dump_json())
        runner = CliRunner()
        result = runner.invoke(main, [
            "improve",
            "--judge-files", str(jf),
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "judge:task_completion" in data["metric_summary"]
        assert len(data["metric_summary"]) == 1

    def test_no_files_at_all_exits_1(self):
        runner = CliRunner()
        result = runner.invoke(main, ["improve"])
        assert result.exit_code != 0

    def test_judge_files_merged_with_eval(self, tmp_path):
        jf1 = tmp_path / "j1.json"
        jf2 = tmp_path / "j2.json"
        for i, (f, score) in enumerate([(jf1, 1), (jf2, 1)]):
            f.write_text(JudgeResult(
                trace_id=f"t{i}", overall_score=score / 5, model="test",
                dimensions=[JudgeDimension(name="reasoning_quality", score=score)],
            ).model_dump_json())
        runner = CliRunner()
        result = runner.invoke(main, [
            "improve", str(FIXTURES_DIR / "eval_result_bad.json"),
            "--judge-files", str(jf1), "--judge-files", str(jf2),
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["num_evaluations"] >= 3
        assert "judge:reasoning_quality" in data["metric_summary"]
        judge_findings = [f for f in data["findings"] if f["metric"] == "judge:reasoning_quality"]
        assert len(judge_findings) > 0


class TestAnnotateDefaultDimensions:
    def test_annotate_defaults_to_all_dimensions(self, tmp_path):
        out = tmp_path / "ann.jsonl"
        runner = CliRunner()
        result = runner.invoke(main, [
            "annotate", str(FIXTURES_DIR / "simple_trace.json"),
            "--output", str(out),
        ], input="5\n4\n3\n4\n5\n")
        assert result.exit_code == 0
        lines = [ln for ln in out.read_text().splitlines() if ln.strip()]
        assert len(lines) == 5
        dims_saved = [json.loads(ln)["dimension"] for ln in lines]
        assert set(dims_saved) == set(ALL_DIMENSIONS)


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

    def test_details_flag_shows_details_columns(self):
        trace = str(FIXTURES_DIR / "simple_trace.json")
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", trace, trace, "--details",
        ])
        assert result.exit_code == 0
        assert "Details" in result.output
        col_count = result.output.count("Details")
        assert col_count >= 2, f"Expected 2+ 'Details' (baseline + current), got {col_count}"

    def test_no_details_flag_hides_columns(self):
        trace = str(FIXTURES_DIR / "simple_trace.json")
        runner = CliRunner()
        result = runner.invoke(main, ["compare", trace, trace])
        assert result.exit_code == 0
        assert "Details" not in result.output

    def test_details_flag_shows_metric_info(self):
        trace = str(FIXTURES_DIR / "simple_trace.json")
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", trace, trace, "--details",
        ])
        assert result.exit_code == 0
        assert "total_ste" in result.output or "failed=0" in result.output

    def test_details_flag_with_json_format_ignored(self):
        trace = str(FIXTURES_DIR / "simple_trace.json")
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", trace, trace, "--format", "json", "--details",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "metric_deltas" in data

    def test_details_flag_with_markdown_format_ignored(self):
        trace = str(FIXTURES_DIR / "simple_trace.json")
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare", trace, trace, "--format", "markdown", "--details",
        ])
        assert result.exit_code == 0
        assert "| Metric |" in result.output

    def test_similarity_threshold_flag_flows_through(self):
        trace = str(FIXTURES_DIR / "loop_trace.json")
        runner = CliRunner()
        exact = runner.invoke(main, [
            "compare", trace, trace, "--format", "json",
        ])
        fuzzy = runner.invoke(main, [
            "compare", trace, trace, "--format", "json",
            "--similarity-threshold", "0.5",
        ])
        assert exact.exit_code in (0, 1)
        assert fuzzy.exit_code in (0, 1)
        exact_data = json.loads(exact.output)
        fuzzy_data = json.loads(fuzzy.output)
        assert "metric_deltas" in exact_data
        assert "metric_deltas" in fuzzy_data
        exact_loop = next(d for d in exact_data["metric_deltas"] if d["name"] == "loop_detection")
        fuzzy_loop = next(d for d in fuzzy_data["metric_deltas"] if d["name"] == "loop_detection")
        assert exact_loop["delta"] == 0.0, "Same trace should have zero delta"
        assert fuzzy_loop["delta"] == 0.0, "Same trace should have zero delta"
        assert exact_loop["baseline_score"] != fuzzy_loop["baseline_score"], "Different thresholds should produce different scores"


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
        lines = [ln for ln in out.read_text().splitlines() if ln.strip()]
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
        lines = [ln for ln in out.read_text().splitlines() if ln.strip()]
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


class TestInputFormat:
    """CLI integration tests for --input-format option across all trace-reading commands."""

    CLAWDBOT_FIXTURE = FIXTURES_DIR / "clawdbot_session.jsonl"

    def test_eval_auto_detects_jsonl_as_clawdbot(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(self.CLAWDBOT_FIXTURE),
            "--format", "json", "--threshold", "0.1",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "overall_score" in data
        assert "metrics" in data

    def test_eval_auto_detects_json_as_json(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json", "--threshold", "0.1",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["passed"] is True

    def test_eval_explicit_clawdbot_format(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(self.CLAWDBOT_FIXTURE),
            "--input-format", "clawdbot",
            "--format", "json", "--threshold", "0.1",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "overall_score" in data

    def test_eval_explicit_json_format(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--input-format", "json",
            "--format", "json", "--threshold", "0.1",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["passed"] is True

    def test_eval_clawdbot_produces_different_trace_id(self):
        runner = CliRunner()
        clawdbot_result = runner.invoke(main, [
            "eval", str(self.CLAWDBOT_FIXTURE),
            "--format", "json", "--threshold", "0.1",
        ])
        json_result = runner.invoke(main, [
            "eval", str(FIXTURES_DIR / "simple_trace.json"),
            "--format", "json", "--threshold", "0.1",
        ])
        assert clawdbot_result.exit_code == 0, clawdbot_result.output
        assert json_result.exit_code == 0, json_result.output
        clawdbot_data = json.loads(clawdbot_result.output)
        json_data = json.loads(json_result.output)
        assert clawdbot_data["trace_id"] != json_data["trace_id"]
        assert len(clawdbot_data["metrics"]) > 0
        assert len(json_data["metrics"]) > 0

    def test_compare_mixed_formats(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare",
            str(FIXTURES_DIR / "simple_trace.json"),
            str(self.CLAWDBOT_FIXTURE),
            "--format", "json",
        ])
        assert result.exit_code in (0, 1)
        data = json.loads(result.output)
        assert "metric_deltas" in data
        assert "overall_delta" in data

    def test_compare_both_clawdbot(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare",
            str(self.CLAWDBOT_FIXTURE),
            str(self.CLAWDBOT_FIXTURE),
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["has_regression"] is False

    def test_compare_explicit_clawdbot_format(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "compare",
            str(self.CLAWDBOT_FIXTURE),
            str(self.CLAWDBOT_FIXTURE),
            "--input-format", "clawdbot",
            "--format", "json",
        ])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["has_regression"] is False

    def test_annotate_with_clawdbot_format(self, tmp_path):
        out = tmp_path / "ann.jsonl"
        runner = CliRunner()
        result = runner.invoke(main, [
            "annotate", str(self.CLAWDBOT_FIXTURE),
            "--output", str(out),
            "--dimensions", "task_completion",
        ], input="4\n")
        assert result.exit_code == 0
        assert "Saved 1 annotation" in result.output

    def test_annotate_explicit_clawdbot_format(self, tmp_path):
        out = tmp_path / "ann.jsonl"
        runner = CliRunner()
        result = runner.invoke(main, [
            "annotate", str(self.CLAWDBOT_FIXTURE),
            "--input-format", "clawdbot",
            "--output", str(out),
            "--dimensions", "task_completion",
        ], input="4\n")
        assert result.exit_code == 0
        assert "Saved 1 annotation" in result.output

    @patch("trajeval.cli.judge")
    def test_judge_with_clawdbot_format(self, mock_judge):
        mock_judge.return_value = JudgeResult(
            trace_id="clawdbot-test-001",
            dimensions=[JudgeDimension(name="task_completion", score=4, explanation="good")],
            overall_score=0.8,
            model="test-model",
        )
        runner = CliRunner()
        result = runner.invoke(main, [
            "judge", str(self.CLAWDBOT_FIXTURE),
            "--input-format", "clawdbot",
            "--threshold", "0.7",
        ])
        assert result.exit_code == 0
        assert mock_judge.call_count == 1

    @patch("trajeval.cli.judge")
    def test_judge_auto_detects_clawdbot(self, mock_judge):
        mock_judge.return_value = JudgeResult(
            trace_id="clawdbot-test-001",
            dimensions=[JudgeDimension(name="task_completion", score=4, explanation="good")],
            overall_score=0.8,
            model="test-model",
        )
        runner = CliRunner()
        result = runner.invoke(main, [
            "judge", str(self.CLAWDBOT_FIXTURE),
            "--threshold", "0.7",
        ])
        assert result.exit_code == 0
        assert mock_judge.call_count == 1

    def test_eval_malformed_jsonl_exits_1(self, tmp_path):
        bad = tmp_path / "bad.jsonl"
        bad.write_text('{"type":"session"}\n{bad json}\n')
        runner = CliRunner()
        result = runner.invoke(main, ["eval", str(bad)])
        assert result.exit_code == 1
        assert "Error" in result.output

    def test_eval_empty_jsonl_exits_1(self, tmp_path):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("")
        runner = CliRunner()
        result = runner.invoke(main, ["eval", str(empty)])
        assert result.exit_code == 1
        assert "Error" in result.output
