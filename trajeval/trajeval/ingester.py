"""Trace ingestion: parse various trace formats into AgentTrace."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from .models import AgentTrace, TokenUsage, TraceStep


class IngestError(Exception):
    pass


def ingest_json(source: str | Path | dict) -> AgentTrace:
    """Ingest a trace from a JSON file path, JSON string, or dict."""
    raw = _load_raw(source)
    return _parse_simple_json(raw)


def _load_raw(source: str | Path | dict) -> dict:
    if isinstance(source, dict):
        return source

    source = str(source)

    if source.strip().startswith("{"):
        try:
            return json.loads(source)
        except json.JSONDecodeError as e:
            raise IngestError(f"Invalid JSON string: {e}") from e

    path = Path(source)
    if not path.exists():
        raise IngestError(f"File not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise IngestError(f"Invalid JSON in {path}: {e}") from e


def _parse_simple_json(raw: dict) -> AgentTrace:
    """Parse the simple JSON trace format.

    Expected format:
    {
        "trace_id": "...",       # optional, auto-generated if missing
        "agent_name": "...",     # optional
        "task": "...",           # optional
        "steps": [
            {"type": "llm_call", "name": "claude-3", "input": {...}, "output": {...}, ...},
            ...
        ],
        "final_output": "...",   # optional
        "metadata": {...}        # optional
    }
    """
    if not isinstance(raw, dict):
        raise IngestError(f"Expected dict, got {type(raw).__name__}")

    steps_raw = raw.get("steps", [])
    if not isinstance(steps_raw, list):
        raise IngestError(f"'steps' must be a list, got {type(steps_raw).__name__}")

    steps = [_parse_step(s, i) for i, s in enumerate(steps_raw)]

    total_duration = raw.get("total_duration_ms", sum(s.duration_ms for s in steps))
    total_tokens = _aggregate_tokens(steps, raw.get("total_tokens"))

    return AgentTrace(
        trace_id=raw.get("trace_id", str(uuid.uuid4())),
        agent_name=raw.get("agent_name", "unknown"),
        task=raw.get("task", ""),
        steps=steps,
        final_output=raw.get("final_output", ""),
        total_duration_ms=total_duration,
        total_tokens=total_tokens,
        metadata=raw.get("metadata", {}),
    )


def _parse_step(raw: dict, index: int) -> TraceStep:
    if not isinstance(raw, dict):
        raise IngestError(f"Step {index}: expected dict, got {type(raw).__name__}")

    step_type = raw.get("type", "unknown")
    name = raw.get("name", f"step_{index}")

    tokens = None
    if "tokens" in raw and raw["tokens"] is not None:
        tokens = TokenUsage(**raw["tokens"])

    return TraceStep(
        type=step_type,
        name=name,
        input=raw.get("input", {}),
        output=raw.get("output", {}),
        duration_ms=raw.get("duration_ms", 0.0),
        tokens=tokens,
        metadata=raw.get("metadata", {}),
    )


def _aggregate_tokens(steps: list[TraceStep], explicit: dict | None) -> TokenUsage:
    if explicit:
        return TokenUsage(**explicit)
    prompt = sum(s.tokens.prompt for s in steps if s.tokens)
    completion = sum(s.tokens.completion for s in steps if s.tokens)
    return TokenUsage(prompt=prompt, completion=completion, total=prompt + completion)
