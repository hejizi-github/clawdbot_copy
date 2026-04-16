"""CLI entry point for trajeval."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from . import __version__
from .ingester import IngestError, ingest_json
from .metrics import MetricConfig, evaluate

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
def eval(
    trace_file: Path,
    fmt: str,
    expected_steps: int | None,
    baseline_tokens: int | None,
    threshold: float,
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
