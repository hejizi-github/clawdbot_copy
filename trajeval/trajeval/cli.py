"""CLI entry point for trajeval."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .calibration import AnnotationStore, HumanAnnotation, load_judge_results, compute_correlation
from .compare import compare_reports, format_markdown
from .ingester import IngestError, ingest_json
from .metrics import MetricConfig, evaluate
from .scorer import JudgeConfig, judge

console = Console()


@click.group()
@click.version_option(__version__, prog_name="trajeval")
def main():
    """trajeval — framework-agnostic agent trajectory evaluation."""


@main.command()
@click.argument("trace_file", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
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
def eval(
    trace_file: Path,
    fmt: str,
    expected_steps: int | None,
    baseline_tokens: int | None,
    threshold: float,
    recovery_window: int,
):
    """Evaluate an agent execution trace with deterministic metrics."""
    try:
        trace = ingest_json(trace_file)
    except IngestError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    config = MetricConfig(
        expected_steps=expected_steps,
        baseline_tokens=baseline_tokens,
        recovery_window=recovery_window,
        pass_threshold=threshold,
    )
    report = evaluate(trace, config)

    if fmt == "json":
        result = {
            "trace_id": report.trace_id,
            "overall_score": report.overall_score,
            "passed": report.passed,
            "metrics": [m.model_dump() for m in report.metrics],
        }
        click.echo(json.dumps(result, indent=2))
    else:
        _print_report(trace, report)

    sys.exit(0 if report.passed else 1)


@main.command(name="judge")
@click.argument("trace_file", type=click.Path(exists=True, path_type=Path))
@click.option("--model", default="claude-sonnet-4-6", help="Model for LLM judge")
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
@click.option(
    "--dimensions",
    default="task_completion,reasoning_quality",
    help="Comma-separated dimensions to evaluate",
)
@click.option(
    "--threshold", type=float, default=0.7, help="Pass/fail threshold (0.0-1.0, default 0.7)"
)
def judge_cmd(trace_file: Path, model: str, fmt: str, dimensions: str, threshold: float):
    """Evaluate an agent trace using an LLM-as-judge."""
    try:
        trace = ingest_json(trace_file)
    except IngestError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    config = JudgeConfig(
        model=model,
        dimensions=[d.strip() for d in dimensions.split(",")],
    )
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
        click.echo(json.dumps(output, indent=2))
    else:
        _print_judge_report(trace, result, threshold=threshold, passed=passed)

    sys.exit(0 if passed else 1)


@main.command()
@click.argument("baseline_file", type=click.Path(exists=True, path_type=Path))
@click.argument("current_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--format", "fmt", type=click.Choice(["table", "json", "markdown"]), default="table"
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
def compare(
    baseline_file: Path,
    current_file: Path,
    fmt: str,
    tolerance: float,
    expected_steps: int | None,
    baseline_tokens: int | None,
    threshold: float,
    recovery_window: int,
):
    """Compare two traces and detect metric regressions."""
    try:
        baseline_trace = ingest_json(baseline_file)
        current_trace = ingest_json(current_file)
    except IngestError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    config = MetricConfig(
        expected_steps=expected_steps,
        baseline_tokens=baseline_tokens,
        recovery_window=recovery_window,
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
    else:
        _print_comparison(result)

    sys.exit(1 if result.has_regression else 0)


@main.command()
@click.argument("trace_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output", "-o", type=click.Path(path_type=Path),
    default="annotations.jsonl", help="Annotations output file (JSONL)",
)
@click.option(
    "--dimensions",
    default="task_completion,reasoning_quality",
    help="Comma-separated dimensions to annotate",
)
@click.option("--annotator", default="default", help="Annotator identifier")
def annotate(trace_file: Path, output: Path, dimensions: str, annotator: str):
    """Interactively annotate a trace with human scores."""
    try:
        trace = ingest_json(trace_file)
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


def _print_comparison(result):
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
        table.add_row(
            d.name,
            f"{d.baseline_score:.2f}",
            f"{d.current_score:.2f}",
            f"[{delta_style}]{sign}{d.delta:.2f}[/{delta_style}]",
            status_str,
        )

    table.add_section()
    sign = "+" if result.overall_delta > 0 else ""
    overall_style = "red bold" if result.has_regression else "green bold"
    table.add_row(
        "[bold]Overall[/bold]",
        "",
        "",
        f"[{overall_style}]{sign}{result.overall_delta:.2f}[/{overall_style}]",
        "",
    )
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


def _print_report(trace, report):
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

    for m in report.metrics:
        status = "[green]PASS[/green]" if m.passed else "[red]FAIL[/red]"
        score_style = "green" if m.passed else "red"
        scores.add_row(m.name, f"[{score_style}]{m.score:.2f}[/{score_style}]", status)

    scores.add_section()
    overall_style = "green bold" if report.passed else "red bold"
    pass_label = "[green bold]PASS[/green bold]"
    fail_label = "[red bold]FAIL[/red bold]"
    overall_status = pass_label if report.passed else fail_label
    scores.add_row(
        "[bold]Overall[/bold]",
        f"[{overall_style}]{report.overall_score:.2f}[/{overall_style}]",
        overall_status,
    )
    console.print(scores)


if __name__ == "__main__":
    main()
