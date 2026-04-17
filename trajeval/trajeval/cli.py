"""CLI entry point for trajeval."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .batch import BatchResult, batch_evaluate
from .calibration import AnnotationStore, HumanAnnotation, compute_correlation, load_judge_results
from .ci_output import format_compare_ci, format_eval_ci, format_judge_ci
from .compare import compare_reports, format_markdown
from .improvement import ImprovementReport, Priority, analyze_judge_results, analyze_results
from .ingester import IngestError, ingest_clawdbot_jsonl, ingest_json, ingest_otlp_json
from .metrics import MetricConfig, evaluate
from .scorer import ALL_DIMENSIONS, EnsembleConfig, EnsembleResult, JudgeConfig, JudgeResult, ensemble_judge, judge
from .storage import DEFAULT_DB_PATH, TrajevalDB

console = Console()


@click.group()
@click.version_option(__version__, prog_name="trajeval")
def main():
    """trajeval — framework-agnostic agent trajectory evaluation."""


def _resolve_input_format(trace_file: Path, input_fmt: str) -> str:
    """Resolve 'auto' format by inspecting the file."""
    if input_fmt != "auto":
        return input_fmt
    if trace_file.suffix == ".jsonl":
        return "clawdbot"
    return "json"


def _load_trace(trace_file: Path, input_format: str):
    if input_format == "clawdbot":
        return ingest_clawdbot_jsonl(trace_file)
    if input_format == "otlp":
        return ingest_otlp_json(trace_file)
    return ingest_json(trace_file)


@main.command()
@click.argument("trace_file", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["table", "json", "ci"]), default="table")
@click.option(
    "--input-format", "input_fmt",
    type=click.Choice(["auto", "json", "clawdbot", "otlp"]), default="auto",
    help="Trace input format: auto (detect), json (simple), clawdbot (JSONL transcript)",
)
@click.option("--expected-steps", type=int, default=None, help="Baseline step count for efficiency")
@click.option(
    "--baseline-tokens", type=int, default=None, help="Baseline token count for efficiency"
)
@click.option(
    "--threshold", type=float, default=0.7, help="Pass/fail threshold (0.0-1.0, default 0.7)"
)
@click.option(
    "--recovery-window", type=int, default=3,
    help="Steps after an error to check for recovery (default 3)",
)
@click.option(
    "--latency-budget", type=float, default=None,
    help="Latency budget in milliseconds for speed scoring",
)
@click.option(
    "--similarity-threshold", type=float, default=1.0,
    help="Loop similarity threshold (0.0-1.0, default 1.0). Below 1.0 enables near-duplicate loop detection.",
)
@click.option(
    "--details", is_flag=True, default=False,
    help="Show metric details in table output",
)
@click.option(
    "--save", is_flag=True, default=False,
    help="Persist evaluation result to local SQLite history",
)
@click.option(
    "--db", type=click.Path(path_type=Path), default=None,
    help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
)
def eval(
    trace_file: Path,
    fmt: str,
    input_fmt: str,
    expected_steps: int | None,
    baseline_tokens: int | None,
    threshold: float,
    recovery_window: int,
    latency_budget: float | None,
    similarity_threshold: float,
    details: bool,
    save: bool,
    db: Path | None,
):
    """Evaluate an agent execution trace with deterministic metrics."""
    try:
        resolved_fmt = _resolve_input_format(trace_file, input_fmt)
        trace = _load_trace(trace_file, resolved_fmt)
    except IngestError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    config = MetricConfig(
        expected_steps=expected_steps,
        baseline_tokens=baseline_tokens,
        recovery_window=recovery_window,
        latency_budget_ms=latency_budget,
        loop_similarity_threshold=similarity_threshold,
        pass_threshold=threshold,
    )
    report = evaluate(trace, config)

    if save:
        with TrajevalDB(db) as store:
            store.save_eval(report, agent_name=trace.agent_name)
            click.echo(f"Saved to {store.path}", err=True)

    if fmt == "json":
        result = {
            "trace_id": report.trace_id,
            "overall_score": report.overall_score,
            "passed": report.passed,
            "metrics": [m.model_dump() for m in report.metrics],
        }
        click.echo(json.dumps(result, indent=2))
    elif fmt == "ci":
        click.echo(format_eval_ci(report, threshold=threshold))
    else:
        _print_report(trace, report, show_details=details)

    sys.exit(0 if report.passed else 1)


@main.command()
@click.argument("directory", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["table", "json", "ci"]), default="table")
@click.option(
    "--input-format", "input_fmt",
    type=click.Choice(["auto", "json", "clawdbot"]), default="auto",
    help="Trace input format: auto (detect), json (simple), clawdbot (JSONL transcript)",
)
@click.option(
    "--threshold", type=float, default=0.7, help="Pass/fail threshold (0.0-1.0, default 0.7)"
)
@click.option("--expected-steps", type=int, default=None, help="Baseline step count for efficiency")
@click.option(
    "--baseline-tokens", type=int, default=None, help="Baseline token count for efficiency"
)
@click.option(
    "--recovery-window", type=int, default=3,
    help="Steps after an error to check for recovery (default 3)",
)
@click.option(
    "--latency-budget", type=float, default=None,
    help="Latency budget in milliseconds for speed scoring",
)
@click.option(
    "--similarity-threshold", type=float, default=1.0,
    help="Loop similarity threshold (0.0-1.0, default 1.0)",
)
def batch(
    directory: Path,
    fmt: str,
    input_fmt: str,
    threshold: float,
    expected_steps: int | None,
    baseline_tokens: int | None,
    recovery_window: int,
    latency_budget: float | None,
    similarity_threshold: float,
):
    """Evaluate all traces in a directory and report aggregate statistics."""
    config = MetricConfig(
        expected_steps=expected_steps,
        baseline_tokens=baseline_tokens,
        recovery_window=recovery_window,
        latency_budget_ms=latency_budget,
        loop_similarity_threshold=similarity_threshold,
        pass_threshold=threshold,
    )
    result = batch_evaluate(directory, config=config, input_format=input_fmt)

    if result.total_traces == 0:
        console.print("[yellow]No trace files found in directory[/yellow]")
        sys.exit(1)

    if fmt == "json":
        output = {
            "total_traces": result.total_traces,
            "passed_traces": result.passed_traces,
            "failed_traces": result.failed_traces,
            "overall_pass_rate": result.overall_pass_rate,
            "metric_aggregates": [a.model_dump() for a in result.metric_aggregates],
            "traces": [
                {
                    "trace_id": r.trace_id,
                    "file": r.file_path,
                    "overall_score": r.report.overall_score,
                    "passed": r.report.passed,
                }
                for r in result.trace_results
            ],
            "errors": result.errors,
        }
        click.echo(json.dumps(output, indent=2))
    elif fmt == "ci":
        _print_batch_ci(result)
    else:
        _print_batch_report(result)

    sys.exit(0 if result.failed_traces == 0 else 1)


@main.command(name="judge")
@click.argument("trace_file", type=click.Path(exists=True, path_type=Path))
@click.option("--model", default="claude-sonnet-4-6", help="Model for LLM judge")
@click.option("--format", "fmt", type=click.Choice(["table", "json", "ci"]), default="table")
@click.option(
    "--input-format", "input_fmt",
    type=click.Choice(["auto", "json", "clawdbot", "otlp"]), default="auto",
    help="Trace input format: auto (detect), json (simple), clawdbot (JSONL transcript)",
)
@click.option(
    "--dimensions",
    default=",".join(ALL_DIMENSIONS),
    help="Comma-separated dimensions to evaluate",
)
@click.option(
    "--threshold", type=float, default=0.7, help="Pass/fail threshold (0.0-1.0, default 0.7)"
)
@click.option(
    "--no-randomize", "no_randomize", is_flag=True, default=False,
    help="Disable dimension order randomization (for reproducible evaluations)",
)
@click.option(
    "--judges", type=click.IntRange(min=1), default=1,
    help="Number of judges for ensemble evaluation (default 1, use 3+ for high-stakes)",
)
@click.option(
    "--aggregation", type=click.Choice(["median", "mean"]), default="median",
    help="Aggregation method for ensemble scoring (default median)",
)
def judge_cmd(
    trace_file: Path, model: str, fmt: str, input_fmt: str, dimensions: str,
    threshold: float, no_randomize: bool, judges: int, aggregation: str,
):
    """Evaluate an agent trace using an LLM-as-judge."""
    try:
        resolved_fmt = _resolve_input_format(trace_file, input_fmt)
        trace = _load_trace(trace_file, resolved_fmt)
    except IngestError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    config = JudgeConfig(
        model=model,
        dimensions=[d.strip() for d in dimensions.split(",")],
        randomize_order=not no_randomize,
    )

    if judges > 1:
        ensemble_config = EnsembleConfig(num_judges=judges, aggregation=aggregation)
        result = ensemble_judge(trace, config=config, ensemble_config=ensemble_config)
    else:
        if aggregation != "median":
            console.print(f"[yellow]Warning:[/yellow] --aggregation {aggregation} is ignored with a single judge")
        result = judge(trace, config=config)

    if result.error:
        console.print(f"[red]Judge error:[/red] {result.error}")
        sys.exit(1)

    passed = result.overall_score >= threshold

    if fmt == "json":
        output = {
            "trace_id": result.trace_id,
            "overall_score": result.overall_score,
            "passed": passed,
            "threshold": threshold,
            "model": result.model,
            "dimensions": [d.model_dump() for d in result.dimensions],
        }
        if isinstance(result, EnsembleResult):
            output["ensemble"] = {
                "num_judges": result.num_judges,
                "aggregation": result.aggregation,
                "agreement": {d.name: round(d.std_dev, 4) for d in result.dimension_stats},
                "individual_scores": [r.overall_score for r in result.individual_results],
            }
        click.echo(json.dumps(output, indent=2))
    elif fmt == "ci":
        click.echo(format_judge_ci(result, threshold=threshold, passed=passed))
    else:
        if isinstance(result, EnsembleResult):
            _print_ensemble_report(trace, result, threshold=threshold, passed=passed)
        else:
            _print_judge_report(trace, result, threshold=threshold, passed=passed)

    sys.exit(0 if passed else 1)


@main.command()
@click.argument("baseline_file", type=click.Path(exists=True, path_type=Path))
@click.argument("current_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format", "fmt", type=click.Choice(["table", "json", "markdown", "ci"]), default="table"
)
@click.option(
    "--input-format", "input_fmt",
    type=click.Choice(["auto", "json", "clawdbot", "otlp"]), default="auto",
    help="Trace input format: auto (detect), json (simple), clawdbot (JSONL transcript)",
)
@click.option(
    "--tolerance",
    type=float,
    default=0.05,
    help="Regression tolerance (0.0-1.0, default 0.05). Score drops beyond this are flagged.",
)
@click.option("--expected-steps", type=int, default=None, help="Baseline step count for efficiency")
@click.option(
    "--baseline-tokens", type=int, default=None, help="Baseline token count for efficiency"
)
@click.option(
    "--threshold", type=float, default=0.7, help="Metric pass/fail threshold (0.0-1.0, default 0.7)"
)
@click.option(
    "--recovery-window", type=int, default=3,
    help="Steps after an error to check for recovery (default 3)",
)
@click.option(
    "--latency-budget", type=float, default=None,
    help="Latency budget in milliseconds for speed scoring",
)
@click.option(
    "--similarity-threshold", type=float, default=1.0,
    help="Loop similarity threshold (0.0-1.0, default 1.0). Below 1.0 enables near-duplicate loop detection.",
)
@click.option(
    "--details", is_flag=True, default=False,
    help="Show metric details in table output",
)
def compare(
    baseline_file: Path,
    current_file: Path,
    fmt: str,
    input_fmt: str,
    tolerance: float,
    expected_steps: int | None,
    baseline_tokens: int | None,
    threshold: float,
    recovery_window: int,
    latency_budget: float | None,
    similarity_threshold: float,
    details: bool,
):
    """Compare two traces and detect metric regressions."""
    try:
        baseline_fmt = _resolve_input_format(baseline_file, input_fmt)
        current_fmt = _resolve_input_format(current_file, input_fmt)
        baseline_trace = _load_trace(baseline_file, baseline_fmt)
        current_trace = _load_trace(current_file, current_fmt)
    except IngestError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    config = MetricConfig(
        expected_steps=expected_steps,
        baseline_tokens=baseline_tokens,
        recovery_window=recovery_window,
        latency_budget_ms=latency_budget,
        loop_similarity_threshold=similarity_threshold,
        pass_threshold=threshold,
    )
    baseline_report = evaluate(baseline_trace, config)
    current_report = evaluate(current_trace, config)

    result = compare_reports(baseline_report, current_report, tolerance=tolerance)

    if fmt == "json":
        output = {
            "baseline_trace_id": result.baseline_trace_id,
            "current_trace_id": result.current_trace_id,
            "overall_delta": result.overall_delta,
            "has_regression": result.has_regression,
            "tolerance": result.tolerance,
            "metric_deltas": [d.model_dump() for d in result.metric_deltas],
        }
        click.echo(json.dumps(output, indent=2))
    elif fmt == "markdown":
        click.echo(format_markdown(result))
    elif fmt == "ci":
        click.echo(format_compare_ci(result))
    else:
        _print_comparison(result, show_details=details)

    sys.exit(1 if result.has_regression else 0)


@main.command()
@click.argument("trace_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output", "-o", type=click.Path(path_type=Path),
    default="annotations.jsonl", help="Annotations output file (JSONL)",
)
@click.option(
    "--input-format", "input_fmt",
    type=click.Choice(["auto", "json", "clawdbot", "otlp"]), default="auto",
    help="Trace input format: auto (detect), json (simple), clawdbot (JSONL transcript)",
)
@click.option(
    "--dimensions",
    default=",".join(ALL_DIMENSIONS),
    help="Comma-separated dimensions to annotate",
)
@click.option("--annotator", default="default", help="Annotator identifier")
def annotate(trace_file: Path, output: Path, input_fmt: str, dimensions: str, annotator: str):
    """Interactively annotate a trace with human scores."""
    try:
        resolved_fmt = _resolve_input_format(trace_file, input_fmt)
        trace = _load_trace(trace_file, resolved_fmt)
    except IngestError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    console.print(f"\n[bold]Trace:[/bold] {trace.trace_id[:24]}")
    console.print(f"[bold]Agent:[/bold] {trace.agent_name}")
    console.print(f"[bold]Task:[/bold] {trace.task or '(none)'}")
    console.print(f"[bold]Steps:[/bold] {trace.step_count}\n")

    for i, step in enumerate(trace.steps):
        console.print(f"  [dim]Step {i+1}[/dim] [{step.type}] {step.name}")

    console.print(f"\n[bold]Final output:[/bold] {trace.final_output or '(none)'}\n")

    dim_list = [d.strip() for d in dimensions.split(",")]
    store = AnnotationStore(output)
    annotations = []

    for dim in dim_list:
        while True:
            score_str = click.prompt(
                f"Score for {click.style(dim, fg='cyan')} (0-5)", type=str,
            )
            try:
                score = int(score_str)
                if 0 <= score <= 5:
                    break
                console.print("[red]Score must be 0-5[/red]")
            except ValueError:
                console.print("[red]Enter an integer 0-5[/red]")

        annotations.append(HumanAnnotation(
            trace_id=trace.trace_id,
            dimension=dim,
            human_score=score,
            annotator=annotator,
        ))

    store.save_batch(annotations)
    console.print(f"\n[green]Saved {len(annotations)} annotations to {output}[/green]")


@main.command()
@click.argument("annotations_file", type=click.Path(exists=True, path_type=Path))
@click.argument("judgments_file", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.option(
    "--threshold", type=float, default=None,
    help="Minimum Spearman ρ to pass (0.0-1.0). Exit 1 if below. Omit to skip pass/fail check.",
)
def calibrate(annotations_file: Path, judgments_file: Path, fmt: str, threshold: float | None):
    """Compute correlation between human annotations and LLM judge scores."""
    store = AnnotationStore(annotations_file)
    annotations = store.load()
    if not annotations:
        console.print("[red]No annotations found[/red]")
        sys.exit(1)

    try:
        judge_results = load_judge_results(judgments_file)
    except Exception as e:
        console.print(f"[red]Error loading judgments:[/red] {e}")
        sys.exit(1)

    if not judge_results:
        console.print("[red]No judge results found[/red]")
        sys.exit(1)

    result = compute_correlation(annotations, judge_results)
    passed = result.overall_spearman_rho >= threshold if threshold is not None else None

    if fmt == "json":
        output = result.model_dump()
        if threshold is not None:
            output["passed"] = passed
            output["threshold"] = threshold
        click.echo(json.dumps(output, indent=2))
    else:
        _print_calibration(result, threshold=threshold, passed=passed)

    if threshold is not None:
        sys.exit(0 if passed else 1)


@main.command()
@click.argument("eval_files", nargs=-1, required=False, type=click.Path(exists=True, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.option(
    "--judge-files", multiple=True, type=click.Path(exists=True, path_type=Path),
    help="LLM judge result JSON files to include in analysis",
)
def improve(eval_files: tuple[Path, ...], fmt: str, judge_files: tuple[Path, ...]):
    """Analyze multiple evaluation results and suggest improvements."""
    if not eval_files and not judge_files:
        console.print("[red]Error: provide at least one eval file or --judge-files[/red]")
        sys.exit(1)

    from .metrics import EvalReport

    reports = []
    for f in eval_files:
        try:
            data = json.loads(f.read_text())
            reports.append(EvalReport(**data))
        except Exception as e:
            console.print(f"[yellow]Warning: skipping {f.name}: {e}[/yellow]")

    judge_results = []
    for f in judge_files:
        try:
            data = json.loads(Path(f).read_text())
            judge_results.append(JudgeResult(**data))
        except Exception as e:
            console.print(f"[yellow]Warning: skipping judge file {Path(f).name}: {e}[/yellow]")

    if not reports and not judge_results:
        console.print("[red]No valid evaluation results found[/red]")
        sys.exit(1)

    eval_report = analyze_results(reports) if reports else None
    judge_report = analyze_judge_results(judge_results) if judge_results else None

    if eval_report and judge_report:
        merged = ImprovementReport(
            num_evaluations=eval_report.num_evaluations + judge_report.num_evaluations,
            findings=eval_report.findings + judge_report.findings,
            recommendations=sorted(
                eval_report.recommendations + judge_report.recommendations,
                key=lambda r: (0 if r.priority == Priority.HIGH else 1 if r.priority == Priority.MEDIUM else 2),
            ),
            metric_summary={**eval_report.metric_summary, **judge_report.metric_summary},
        )
    else:
        merged = eval_report or judge_report  # type: ignore[assignment]

    if fmt == "json":
        click.echo(json.dumps(merged.model_dump(), indent=2))
    else:
        _print_improvement_report(merged)


def _print_improvement_report(report):
    console.print(f"\n[bold]Improvement Analysis[/bold] ({report.num_evaluations} evaluations)\n")

    if report.metric_summary:
        summary_table = Table(title="Metric Summary")
        summary_table.add_column("Metric", style="cyan")
        summary_table.add_column("Mean", justify="right")
        summary_table.add_column("Fail Rate", justify="right")
        summary_table.add_column("Std Dev", justify="right")
        summary_table.add_column("Trend", justify="right")

        for name, s in sorted(report.metric_summary.items()):
            scale = s.get("scale", 1.0)
            normalized = s["mean_score"] / scale if scale > 0 else s["mean_score"]
            score_color = "green" if normalized >= 0.7 else "yellow" if normalized >= 0.5 else "red"
            fail_color = "green" if s["fail_rate"] == 0 else "yellow" if s["fail_rate"] < 0.3 else "red"
            trend_val = s.get("trend")
            if trend_val is not None:
                norm_trend = trend_val / scale if scale > 0 else trend_val
                trend_color = "green" if norm_trend > 0.05 else "red" if norm_trend < -0.05 else "dim"
                trend_str = f"[{trend_color}]{trend_val:+.2f}[/{trend_color}]"
            else:
                trend_str = "[dim]-[/dim]"
            summary_table.add_row(
                name,
                f"[{score_color}]{s['mean_score']:.2f}[/{score_color}]",
                f"[{fail_color}]{s['fail_rate']:.0%}[/{fail_color}]",
                f"{s['std_dev']:.2f}",
                trend_str,
            )
        console.print(summary_table)

    if report.findings:
        console.print(f"\n[bold]Findings ({len(report.findings)})[/bold]")
        for f in report.findings:
            sev = f.severity
            icon = "[red]●[/red]" if sev == Priority.HIGH else (
                "[yellow]●[/yellow]" if sev == Priority.MEDIUM else "[dim]●[/dim]"
            )
            console.print(f"  {icon} [{f.severity.value}] {f.metric}: {f.evidence}")

    if report.recommendations:
        console.print(f"\n[bold]Recommendations ({len(report.recommendations)})[/bold]")
        for i, r in enumerate(report.recommendations, 1):
            pri = r.priority
            icon = "[red]![/red]" if pri == Priority.HIGH else (
                "[yellow]![/yellow]" if pri == Priority.MEDIUM else "[dim]![/dim]"
            )
            console.print(f"  {icon} {i}. {r.title}")
            console.print(f"     {r.suggestion}")
    else:
        console.print("\n[green]No actionable recommendations — all metrics look healthy![/green]")

    console.print()


def _print_calibration(result, threshold: float | None = None, passed: bool | None = None):
    table = Table(title="Calibration: Human vs LLM-Judge")
    table.add_column("Dimension", style="cyan")
    table.add_column("Spearman ρ", justify="right")
    table.add_column("p-value", justify="right")
    table.add_column("Samples", justify="right")

    for dim in result.dimensions:
        if dim.spearman_rho >= 0.7:
            rho_color = "green"
        elif dim.spearman_rho >= 0.4:
            rho_color = "yellow"
        else:
            rho_color = "red"
        sig = "green" if dim.p_value < 0.05 else "yellow"
        table.add_row(
            dim.dimension,
            f"[{rho_color}]{dim.spearman_rho:.4f}[/{rho_color}]",
            f"[{sig}]{dim.p_value:.6f}[/{sig}]",
            str(dim.sample_size),
        )

    table.add_section()
    if result.overall_spearman_rho >= 0.7:
        rho_color = "green bold"
    elif result.overall_spearman_rho >= 0.4:
        rho_color = "yellow bold"
    else:
        rho_color = "red bold"
    table.add_row(
        "[bold]Overall[/bold]",
        f"[{rho_color}]{result.overall_spearman_rho:.4f}[/{rho_color}]",
        f"{result.overall_p_value:.6f}",
        str(result.total_pairs),
    )
    console.print(table)

    if threshold is not None:
        label = "[green bold]PASS[/green bold]" if passed else "[red bold]FAIL[/red bold]"
        console.print(f"\nThreshold: ρ ≥ {threshold:.2f}  {label}")

    for w in result.warnings:
        console.print(f"[yellow]⚠ {w}[/yellow]")


def _print_comparison(result, show_details: bool = False):
    if result.has_regression:
        status = "[red bold]REGRESSION[/red bold]"
    else:
        status = "[green bold]OK[/green bold]"
    b_id = result.baseline_trace_id[:16]
    c_id = result.current_trace_id[:16]
    console.print(f"\nCompare: {b_id} vs {c_id}  {status}")
    console.print(f"Tolerance: {result.tolerance:.0%}\n")

    table = Table(title="Metric Comparison")
    table.add_column("Metric", style="cyan")
    table.add_column("Baseline", justify="right")
    table.add_column("Current", justify="right")
    table.add_column("Delta", justify="right")
    table.add_column("Status", justify="center")
    if show_details:
        table.add_column("Baseline Details", style="dim")
        table.add_column("Current Details", style="dim")

    for d in result.metric_deltas:
        sign = "+" if d.delta > 0 else ""
        if d.direction == "regressed":
            delta_style = "red"
            status_str = "[red]REGRESSED[/red]"
        elif d.direction == "improved":
            delta_style = "green"
            status_str = "[green]IMPROVED[/green]"
        else:
            delta_style = "dim"
            status_str = "[dim]unchanged[/dim]"
        row = [
            d.name,
            f"{d.baseline_score:.2f}",
            f"{d.current_score:.2f}",
            f"[{delta_style}]{sign}{d.delta:.2f}[/{delta_style}]",
            status_str,
        ]
        if show_details:
            row.append(_format_details_compact(d.baseline_details or {}))
            row.append(_format_details_compact(d.current_details or {}))
        table.add_row(*row)

    table.add_section()
    sign = "+" if result.overall_delta > 0 else ""
    overall_style = "red bold" if result.has_regression else "green bold"
    overall_row = [
        "[bold]Overall[/bold]",
        "",
        "",
        f"[{overall_style}]{sign}{result.overall_delta:.2f}[/{overall_style}]",
        "",
    ]
    if show_details:
        overall_row.extend(["", ""])
    table.add_row(*overall_row)
    console.print(table)


def _print_judge_report(trace, result, threshold: float = 0.7, passed: bool = True):
    info = Table(title=f"Judge: {trace.trace_id[:24]}", show_header=False)
    info.add_column("Field", style="dim")
    info.add_column("Value")
    info.add_row("Agent", trace.agent_name)
    info.add_row("Task", trace.task or "(none)")
    info.add_row("Model", result.model)
    info.add_row("Steps", str(trace.step_count))
    console.print(info)
    console.print()

    scores = Table(title="LLM Judge Scores")
    scores.add_column("Dimension", style="cyan")
    scores.add_column("Score", justify="right")
    scores.add_column("Explanation")

    for d in result.dimensions:
        score_color = "green" if d.score >= 4 else "yellow" if d.score >= 3 else "red"
        scores.add_row(d.name, f"[{score_color}]{d.score}/5[/{score_color}]", d.explanation)

    scores.add_section()
    overall_pct = f"{result.overall_score:.0%}"
    pass_label = "[green bold]PASS[/green bold]" if passed else "[red bold]FAIL[/red bold]"
    overall_color = "green bold" if passed else "red bold"
    scores.add_row(
        "[bold]Overall[/bold]",
        f"[{overall_color}]{overall_pct}[/{overall_color}]",
        f"{pass_label} (threshold: {threshold:.0%})",
    )
    console.print(scores)


def _print_ensemble_report(trace, result, threshold: float = 0.7, passed: bool = True):
    info = Table(title=f"Ensemble Judge: {trace.trace_id[:24]}", show_header=False)
    info.add_column("Field", style="dim")
    info.add_column("Value")
    info.add_row("Agent", trace.agent_name)
    info.add_row("Task", trace.task or "(none)")
    info.add_row("Model", result.model)
    info.add_row("Steps", str(trace.step_count))
    info.add_row("Judges", str(result.num_judges))
    info.add_row("Aggregation", result.aggregation)
    console.print(info)
    console.print()

    scores = Table(title=f"Ensemble Scores ({result.num_judges} judges, {result.aggregation})")
    scores.add_column("Dimension", style="cyan")
    scores.add_column("Score", justify="right")
    scores.add_column("Std Dev", justify="right")
    scores.add_column("Explanation")

    stat_map = {s.name: s for s in result.dimension_stats}
    for d in result.dimensions:
        score_color = "green" if d.score >= 4 else "yellow" if d.score >= 3 else "red"
        stat = stat_map.get(d.name)
        std_str = f"{stat.std_dev:.2f}" if stat else "-"
        std_color = "green" if stat and stat.std_dev < 0.5 else "yellow" if stat and stat.std_dev < 1.0 else "red"
        scores.add_row(
            d.name,
            f"[{score_color}]{d.score}/5[/{score_color}]",
            f"[{std_color}]{std_str}[/{std_color}]",
            d.explanation,
        )

    scores.add_section()
    overall_pct = f"{result.overall_score:.0%}"
    pass_label = "[green bold]PASS[/green bold]" if passed else "[red bold]FAIL[/red bold]"
    overall_color = "green bold" if passed else "red bold"
    individual = ", ".join(f"{r.overall_score:.0%}" for r in result.individual_results)
    scores.add_row(
        "[bold]Overall[/bold]",
        f"[{overall_color}]{overall_pct}[/{overall_color}]",
        "",
        f"{pass_label} (threshold: {threshold:.0%}) | individual: {individual}",
    )
    console.print(scores)


def _format_details_compact(details: dict) -> str:
    """Format a metric details dict as a compact one-line summary."""
    if not details:
        return ""
    skip_keys = {"mode", "note"}
    parts = []
    for k, v in details.items():
        if k in skip_keys:
            continue
        if isinstance(v, float):
            parts.append(f"{k}={v:.1f}")
        elif isinstance(v, list):
            parts.append(f"{k}={len(v)}")
        else:
            parts.append(f"{k}={v}")
    return ", ".join(parts)


def _print_report(trace, report, show_details: bool = False):
    info = Table(title=f"Trace: {trace.trace_id[:24]}", show_header=False)
    info.add_column("Field", style="dim")
    info.add_column("Value")
    info.add_row("Agent", trace.agent_name)
    info.add_row("Task", trace.task or "(none)")
    info.add_row("Steps", str(trace.step_count))
    info.add_row("Tool calls", str(len(trace.tool_calls)))
    info.add_row("LLM calls", str(len(trace.llm_calls)))
    info.add_row("Errors", str(len(trace.errors)))
    info.add_row("Duration (ms)", f"{trace.total_duration_ms:.1f}")
    info.add_row("Tokens (total)", str(trace.total_tokens.total))
    console.print(info)
    console.print()

    scores = Table(title="Metric Scores")
    scores.add_column("Metric", style="cyan")
    scores.add_column("Score", justify="right")
    scores.add_column("Status", justify="center")
    if show_details:
        scores.add_column("Details", style="dim")

    for m in report.metrics:
        status = "[green]PASS[/green]" if m.passed else "[red]FAIL[/red]"
        score_style = "green" if m.passed else "red"
        row = [m.name, f"[{score_style}]{m.score:.2f}[/{score_style}]", status]
        if show_details:
            row.append(_format_details_compact(m.details))
        scores.add_row(*row)

    scores.add_section()
    overall_style = "green bold" if report.passed else "red bold"
    pass_label = "[green bold]PASS[/green bold]"
    fail_label = "[red bold]FAIL[/red bold]"
    overall_status = pass_label if report.passed else fail_label
    overall_row = [
        "[bold]Overall[/bold]",
        f"[{overall_style}]{report.overall_score:.2f}[/{overall_style}]",
        overall_status,
    ]
    if show_details:
        overall_row.append("")
    scores.add_row(*overall_row)
    console.print(scores)


@main.command()
@click.option("--agent", default=None, help="Filter by agent name")
@click.option("--limit", type=int, default=20, help="Maximum results to show (default 20)")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.option(
    "--db", type=click.Path(path_type=Path), default=None,
    help=f"SQLite database path (default: {DEFAULT_DB_PATH})",
)
def history(agent: str | None, limit: int, fmt: str, db: Path | None):
    """List saved evaluation results from local history."""
    store = TrajevalDB(db)
    try:
        evals = store.list_evals(agent_name=agent, limit=limit)
    finally:
        store.close()

    if not evals:
        console.print("[dim]No evaluation history found.[/dim]")
        return

    if fmt == "json":
        rows = []
        for e in evals:
            rows.append({
                "trace_id": e.trace_id,
                "overall_score": e.overall_score,
                "passed": e.passed,
                "timestamp": e.timestamp,
                "num_metrics": len(e.metrics),
            })
        click.echo(json.dumps(rows, indent=2))
    else:
        import datetime

        table = Table(title=f"Evaluation History ({len(evals)} results)")
        table.add_column("Trace ID", style="cyan")
        table.add_column("Score", justify="right")
        table.add_column("Status", justify="center")
        table.add_column("Metrics", justify="right")
        table.add_column("Date", style="dim")

        for e in evals:
            status = "[green]PASS[/green]" if e.passed else "[red]FAIL[/red]"
            score_style = "green" if e.passed else "red"
            ts = datetime.datetime.fromtimestamp(e.timestamp).strftime("%Y-%m-%d %H:%M") if e.timestamp else "-"
            table.add_row(
                e.trace_id[:24],
                f"[{score_style}]{e.overall_score:.2f}[/{score_style}]",
                status,
                str(len(e.metrics)),
                ts,
            )
        console.print(table)


def _print_batch_report(result: BatchResult):
    status = "[green bold]ALL PASS[/green bold]" if result.failed_traces == 0 else "[red bold]FAILURES[/red bold]"
    console.print(f"\n[bold]Batch Evaluation[/bold]  {status}")
    console.print(
        f"Traces: {result.total_traces} total, "
        f"[green]{result.passed_traces} passed[/green], "
        f"[red]{result.failed_traces} failed[/red]  "
        f"(pass rate: {result.overall_pass_rate:.0%})\n"
    )

    agg_table = Table(title="Metric Aggregates")
    agg_table.add_column("Metric", style="cyan")
    agg_table.add_column("Mean", justify="right")
    agg_table.add_column("Min", justify="right")
    agg_table.add_column("Max", justify="right")
    agg_table.add_column("Std Dev", justify="right")
    agg_table.add_column("Fail Rate", justify="right")

    for a in result.metric_aggregates:
        mean_color = "green" if a.mean_score >= 0.7 else "yellow" if a.mean_score >= 0.5 else "red"
        fail_color = "green" if a.fail_rate == 0 else "yellow" if a.fail_rate < 0.3 else "red"
        agg_table.add_row(
            a.name,
            f"[{mean_color}]{a.mean_score:.2f}[/{mean_color}]",
            f"{a.min_score:.2f}",
            f"{a.max_score:.2f}",
            f"{a.std_dev:.2f}",
            f"[{fail_color}]{a.fail_rate:.0%}[/{fail_color}]",
        )
    console.print(agg_table)

    if result.failed_traces > 0:
        console.print(f"\n[bold]Failed Traces[/bold]")
        for r in result.trace_results:
            if not r.report.passed:
                failed_metrics = [m.name for m in r.report.metrics if not m.passed]
                console.print(
                    f"  [red]FAIL[/red] {Path(r.file_path).name} "
                    f"(score: {r.report.overall_score:.2f}, failed: {', '.join(failed_metrics)})"
                )

    if result.errors:
        console.print(f"\n[bold]Errors ({len(result.errors)})[/bold]")
        for e in result.errors:
            console.print(f"  [yellow]SKIP[/yellow] {Path(e['file']).name}: {e['error']}")

    console.print()


def _print_batch_ci(result: BatchResult):
    lines = [
        f"BATCH_TOTAL={result.total_traces}",
        f"BATCH_PASSED={result.passed_traces}",
        f"BATCH_FAILED={result.failed_traces}",
        f"BATCH_PASS_RATE={result.overall_pass_rate}",
        f"BATCH_ERRORS={len(result.errors)}",
    ]
    for a in result.metric_aggregates:
        key = a.name.upper()
        lines.append(f"METRIC_{key}_MEAN={a.mean_score}")
        lines.append(f"METRIC_{key}_FAIL_RATE={a.fail_rate}")
    click.echo("\n".join(lines))


if __name__ == "__main__":
    main()
