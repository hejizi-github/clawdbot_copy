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

console = Console()


@click.group()
@click.version_option(__version__, prog_name="trajeval")
def main():
    """trajeval — framework-agnostic agent trajectory evaluation."""


@main.command()
@click.argument("trace_file", type=click.Path(exists=True, path_type=Path))
@click.option("--format", "fmt", type=click.Choice(["table", "json"]), default="table")
def eval(trace_file: Path, fmt: str):
    """Evaluate an agent execution trace."""
    try:
        trace = ingest_json(trace_file)
    except IngestError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    if fmt == "json":
        result = {
            "trace_id": trace.trace_id,
            "agent_name": trace.agent_name,
            "task": trace.task,
            "step_count": trace.step_count,
            "tool_calls": len(trace.tool_calls),
            "llm_calls": len(trace.llm_calls),
            "errors": len(trace.errors),
            "total_duration_ms": trace.total_duration_ms,
            "total_tokens": trace.total_tokens.model_dump(),
        }
        click.echo(json.dumps(result, indent=2))
    else:
        _print_table(trace)


def _print_table(trace):
    table = Table(title=f"Trace: {trace.trace_id[:16]}...")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Agent", trace.agent_name)
    table.add_row("Task", trace.task or "(none)")
    table.add_row("Steps", str(trace.step_count))
    table.add_row("Tool calls", str(len(trace.tool_calls)))
    table.add_row("LLM calls", str(len(trace.llm_calls)))
    table.add_row("Errors", str(len(trace.errors)))
    table.add_row("Duration (ms)", f"{trace.total_duration_ms:.1f}")
    table.add_row("Tokens (total)", str(trace.total_tokens.total))

    console.print(table)


if __name__ == "__main__":
    main()
