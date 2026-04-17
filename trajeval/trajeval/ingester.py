"""Trace ingestion: parse various trace formats into AgentTrace."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from .models import AgentTrace, TokenUsage, TraceStep


class IngestError(Exception):
    pass


def ingest_clawdbot_jsonl(source: str | Path) -> AgentTrace:
    """Ingest a Clawdbot/OpenClaw JSONL session transcript into AgentTrace."""
    path = Path(source)
    if not path.exists():
        raise IngestError(f"File not found: {path}")

    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise IngestError(f"Empty JSONL file: {path}")

    entries = []
    for i, line in enumerate(raw.split("\n")):
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise IngestError(f"Invalid JSON at line {i + 1}: {e}") from e

    if not entries:
        raise IngestError(f"No entries in JSONL file: {path}")

    header = entries[0] if entries[0].get("type") == "session" else None
    message_entries = [e for e in entries if e.get("type") == "message"]

    steps: list[TraceStep] = []
    tool_call_index: dict[str, int] = {}
    first_user_content = ""
    last_user_content = ""

    for entry in message_entries:
        msg = entry.get("message", {})
        role = msg.get("role")
        ts = msg.get("timestamp", 0)

        if role == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                text = " ".join(c.get("text", "") for c in content if c.get("type") == "text")
            else:
                text = str(content)
            last_user_content = text
            if not first_user_content:
                first_user_content = text

        elif role == "assistant":
            _ingest_assistant_message(
                msg, ts, last_user_content, steps, tool_call_index,
            )

        elif role == "toolResult":
            _merge_tool_result(msg, steps, tool_call_index)

        elif role == "bashExecution":
            steps.append(TraceStep(
                type="tool_call",
                name="bash",
                input={"command": msg.get("command", "")},
                output={
                    "stdout": msg.get("output", ""),
                    "exit_code": msg.get("exitCode"),
                    "cancelled": msg.get("cancelled", False),
                    "truncated": msg.get("truncated", False),
                },
                metadata={"timestamp": ts},
            ))

    _compute_durations_from_timestamps(steps)

    metadata: dict = {"source_format": "clawdbot_jsonl"}
    if header:
        metadata["session_id"] = header.get("id", "")
        metadata["session_version"] = header.get("version", 0)
        metadata["cwd"] = header.get("cwd", "")

    total_tokens = _aggregate_tokens(steps, None)

    final_output = ""
    for step in reversed(steps):
        if step.type == "llm_call" and step.output.get("text"):
            final_output = step.output["text"][:500]
            break

    return AgentTrace(
        trace_id=header.get("id", str(uuid.uuid4())) if header else str(uuid.uuid4()),
        agent_name="clawdbot",
        task=first_user_content,
        steps=steps,
        final_output=final_output,
        total_duration_ms=sum(s.duration_ms for s in steps),
        total_tokens=total_tokens,
        metadata=metadata,
    )


def _ingest_assistant_message(
    msg: dict,
    ts: int,
    last_user_content: str,
    steps: list[TraceStep],
    tool_call_index: dict[str, int],
) -> None:
    content_items = msg.get("content", [])
    if isinstance(content_items, str):
        content_items = [{"type": "text", "text": content_items}]

    usage = msg.get("usage", {})
    model = msg.get("model", "unknown")
    tokens = TokenUsage(
        prompt=usage.get("input", 0),
        completion=usage.get("output", 0),
        total=usage.get("totalTokens", usage.get("input", 0) + usage.get("output", 0)),
    )
    cost_info = usage.get("cost", {})

    text_parts = []
    tool_calls = []
    for item in content_items:
        if item.get("type") == "text":
            text_parts.append(item.get("text", ""))
        elif item.get("type") == "toolCall":
            tool_calls.append(item)

    steps.append(TraceStep(
        type="llm_call",
        name=model,
        input={"user_message": last_user_content} if last_user_content else {},
        output={
            "text": "\n".join(text_parts),
            "tool_calls_count": len(tool_calls),
        },
        tokens=tokens,
        metadata={
            "provider": msg.get("provider", ""),
            "api": msg.get("api", ""),
            "stop_reason": msg.get("stopReason", ""),
            "timestamp": ts,
            "cost": cost_info.get("total", 0) if cost_info else 0,
        },
    ))

    for tc in tool_calls:
        tc_id = tc.get("id", "")
        tool_call_index[tc_id] = len(steps)
        steps.append(TraceStep(
            type="tool_call",
            name=tc.get("name", "unknown_tool"),
            input=tc.get("arguments", {}),
            output={},
            metadata={"tool_call_id": tc_id, "model": model, "timestamp": ts},
        ))


def _merge_tool_result(
    msg: dict,
    steps: list[TraceStep],
    tool_call_index: dict[str, int],
) -> None:
    tc_id = msg.get("toolCallId", "")
    if tc_id not in tool_call_index:
        return
    idx = tool_call_index[tc_id]
    result_content = msg.get("content", [])
    if isinstance(result_content, list):
        output_text = " ".join(
            c.get("text", "") for c in result_content if c.get("type") == "text"
        )
    else:
        output_text = str(result_content)
    steps[idx].output = {
        "text": output_text,
        "is_error": msg.get("isError", False),
    }
    if msg.get("toolName"):
        steps[idx].metadata["tool_name"] = msg["toolName"]


def _compute_durations_from_timestamps(steps: list[TraceStep]) -> None:
    for i in range(len(steps)):
        ts = steps[i].metadata.get("timestamp", 0)
        if i + 1 < len(steps):
            next_ts = steps[i + 1].metadata.get("timestamp", 0)
            if ts and next_ts and next_ts > ts:
                steps[i].duration_ms = float(next_ts - ts)


def ingest_otlp_json(source: str | Path | dict) -> AgentTrace:
    """Ingest an OpenTelemetry (OTLP) JSON export into AgentTrace.

    Supports the standard OTLP JSON format with resourceSpans → scopeSpans → spans.
    """
    raw = _load_raw(source) if not isinstance(source, dict) else source

    resource_spans = raw.get("resourceSpans", [])
    if not resource_spans:
        raise IngestError("No resourceSpans found in OTLP JSON")

    all_spans: list[dict] = []
    resource_attrs: dict[str, str] = {}

    for rs in resource_spans:
        resource = rs.get("resource", {})
        resource_attrs.update(_flatten_otlp_attributes(resource.get("attributes", [])))
        for ss in rs.get("scopeSpans", []):
            for span in ss.get("spans", []):
                all_spans.append(span)

    if not all_spans:
        raise IngestError("No spans found in OTLP JSON")

    all_spans.sort(key=lambda s: int(s.get("startTimeUnixNano", "0")))

    trace_id = all_spans[0].get("traceId", str(uuid.uuid4()))
    agent_name = resource_attrs.get("service.name", "unknown")

    steps: list[TraceStep] = []
    for span in all_spans:
        step = _otlp_span_to_step(span)
        steps.append(step)

    total_tokens = _aggregate_tokens(steps, None)
    total_duration = sum(s.duration_ms for s in steps)

    final_output = ""
    for step in reversed(steps):
        text = step.output.get("text", "")
        if text:
            final_output = text[:500]
            break

    task = resource_attrs.get("agent.task", "")
    if not task:
        for step in steps:
            if step.type == "llm_call" and step.input.get("user_message"):
                task = step.input["user_message"]
                break

    return AgentTrace(
        trace_id=trace_id,
        agent_name=agent_name,
        task=task,
        steps=steps,
        final_output=final_output,
        total_duration_ms=total_duration,
        total_tokens=total_tokens,
        metadata={
            "source_format": "otlp_json",
            **resource_attrs,
        },
    )


def _flatten_otlp_attributes(attrs: list[dict]) -> dict[str, str]:
    """Convert OTLP attribute array to a flat dict."""
    result: dict[str, str] = {}
    for attr in attrs:
        key = attr.get("key", "")
        value = attr.get("value", {})
        if "stringValue" in value:
            result[key] = value["stringValue"]
        elif "intValue" in value:
            result[key] = str(value["intValue"])
        elif "doubleValue" in value:
            result[key] = str(value["doubleValue"])
        elif "boolValue" in value:
            result[key] = str(value["boolValue"])
    return result


_OTLP_SPAN_KIND_MAP = {
    0: "unspecified",
    1: "internal",
    2: "server",
    3: "client",
    4: "producer",
    5: "consumer",
}


def _classify_otlp_span(span: dict, attrs: dict[str, str]) -> str:
    """Map OTLP span to a TraceStep type."""
    name_lower = span.get("name", "").lower()
    kind = span.get("kind", 0)

    status_code = span.get("status", {}).get("code", 0)
    if status_code == 2:
        return "error"

    if "llm" in name_lower or "chat" in name_lower or "completion" in name_lower:
        return "llm_call"
    if attrs.get("gen_ai.system") or attrs.get("llm.system"):
        return "llm_call"

    if "tool" in name_lower or kind == 1:
        return "tool_call"
    if attrs.get("tool.name"):
        return "tool_call"

    if kind == 3:
        return "llm_call"

    return "tool_call"


def _otlp_span_to_step(span: dict) -> TraceStep:
    """Convert a single OTLP span to a TraceStep."""
    attrs = _flatten_otlp_attributes(span.get("attributes", []))
    step_type = _classify_otlp_span(span, attrs)
    name = span.get("name", "unknown")

    start_ns = int(span.get("startTimeUnixNano", "0"))
    end_ns = int(span.get("endTimeUnixNano", "0"))
    duration_ms = (end_ns - start_ns) / 1_000_000 if end_ns > start_ns else 0.0

    input_data: dict = {}
    output_data: dict = {}

    if attrs.get("gen_ai.prompt") or attrs.get("llm.prompts"):
        input_data["user_message"] = attrs.get("gen_ai.prompt", attrs.get("llm.prompts", ""))
    if attrs.get("gen_ai.completion") or attrs.get("llm.completions"):
        output_data["text"] = attrs.get("gen_ai.completion", attrs.get("llm.completions", ""))
    if attrs.get("tool.name"):
        name = attrs["tool.name"]
    if attrs.get("tool.parameters"):
        input_data["parameters"] = attrs["tool.parameters"]

    tokens = None
    prompt_tokens = int(attrs.get("gen_ai.usage.prompt_tokens", "0") or "0")
    completion_tokens = int(attrs.get("gen_ai.usage.completion_tokens", "0") or "0")
    if prompt_tokens or completion_tokens:
        tokens = TokenUsage(
            prompt=prompt_tokens,
            completion=completion_tokens,
            total=prompt_tokens + completion_tokens,
        )

    status = span.get("status", {})
    if status.get("code") == 2:
        output_data["error"] = status.get("message", "error")

    metadata: dict = {
        "span_id": span.get("spanId", ""),
        "parent_span_id": span.get("parentSpanId", ""),
        "span_kind": _OTLP_SPAN_KIND_MAP.get(span.get("kind", 0), "unknown"),
    }
    for k, v in attrs.items():
        if k not in ("gen_ai.prompt", "gen_ai.completion", "llm.prompts",
                      "llm.completions", "tool.name", "tool.parameters",
                      "gen_ai.usage.prompt_tokens", "gen_ai.usage.completion_tokens"):
            metadata[k] = v

    return TraceStep(
        type=step_type,
        name=name,
        input=input_data,
        output=output_data,
        duration_ms=round(duration_ms, 2),
        tokens=tokens,
        metadata=metadata,
    )


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
