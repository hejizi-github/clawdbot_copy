"""Batch evaluation: evaluate multiple traces and aggregate statistics."""

from __future__ import annotations

import math
from pathlib import Path

from pydantic import BaseModel, Field

from .ingester import IngestError, ingest_clawdbot_jsonl, ingest_json
from .metrics import EvalReport, MetricConfig, evaluate


class TraceEvalResult(BaseModel):
    trace_id: str
    file_path: str
    report: EvalReport


class MetricAggregate(BaseModel):
    name: str
    mean_score: float
    min_score: float
    max_score: float
    std_dev: float
    fail_count: int
    total: int
    fail_rate: float


class BatchResult(BaseModel):
    trace_results: list[TraceEvalResult] = Field(default_factory=list)
    metric_aggregates: list[MetricAggregate] = Field(default_factory=list)
    total_traces: int = 0
    passed_traces: int = 0
    failed_traces: int = 0
    overall_pass_rate: float = 0.0
    errors: list[dict] = Field(default_factory=list)


def discover_trace_files(directory: Path, input_format: str = "auto") -> list[Path]:
    """Find trace files in a directory."""
    files: list[Path] = []
    if input_format == "clawdbot":
        files = sorted(directory.glob("*.jsonl"))
    elif input_format == "json":
        files = sorted(directory.glob("*.json"))
    else:
        files = sorted(
            list(directory.glob("*.json")) + list(directory.glob("*.jsonl"))
        )
    return files


def batch_evaluate(
    directory: Path,
    config: MetricConfig | None = None,
    input_format: str = "auto",
) -> BatchResult:
    """Evaluate all trace files in a directory and aggregate results."""
    if config is None:
        config = MetricConfig()

    files = discover_trace_files(directory, input_format)
    if not files:
        return BatchResult()

    results: list[TraceEvalResult] = []
    errors: list[dict] = []

    for f in files:
        try:
            fmt = _resolve_format(f, input_format)
            trace = _load(f, fmt)
            report = evaluate(trace, config)
            results.append(TraceEvalResult(
                trace_id=report.trace_id,
                file_path=str(f),
                report=report,
            ))
        except (IngestError, Exception) as e:
            errors.append({"file": str(f), "error": str(e)})

    if not results:
        return BatchResult(errors=errors)

    passed = sum(1 for r in results if r.report.passed)
    failed = len(results) - passed

    aggregates = _compute_aggregates(results)

    return BatchResult(
        trace_results=results,
        metric_aggregates=aggregates,
        total_traces=len(results),
        passed_traces=passed,
        failed_traces=failed,
        overall_pass_rate=round(passed / len(results), 4),
        errors=errors,
    )


def _resolve_format(path: Path, input_format: str) -> str:
    if input_format != "auto":
        return input_format
    if path.suffix == ".jsonl":
        return "clawdbot"
    return "json"


def _load(path: Path, fmt: str):
    if fmt == "clawdbot":
        return ingest_clawdbot_jsonl(path)
    return ingest_json(path)


def _compute_aggregates(results: list[TraceEvalResult]) -> list[MetricAggregate]:
    """Compute per-metric aggregate statistics across all evaluated traces."""
    metric_scores: dict[str, list[float]] = {}
    metric_passed: dict[str, list[bool]] = {}

    for r in results:
        for m in r.report.metrics:
            metric_scores.setdefault(m.name, []).append(m.score)
            metric_passed.setdefault(m.name, []).append(m.passed)

    aggregates = []
    for name in metric_scores:
        scores = metric_scores[name]
        passed = metric_passed[name]
        n = len(scores)
        mean = sum(scores) / n
        variance = sum((s - mean) ** 2 for s in scores) / n
        std_dev = math.sqrt(variance)
        fail_count = sum(1 for p in passed if not p)

        aggregates.append(MetricAggregate(
            name=name,
            mean_score=round(mean, 4),
            min_score=round(min(scores), 4),
            max_score=round(max(scores), 4),
            std_dev=round(std_dev, 4),
            fail_count=fail_count,
            total=n,
            fail_rate=round(fail_count / n, 4),
        ))

    return aggregates
