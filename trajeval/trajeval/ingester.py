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


def ingest_otlp_json(source: str | Path) -> AgentTrace:
    """Ingest an OpenTelemetry OTLP JSON trace export into AgentTrace.

    Supports the standard OTLP JSON format with GenAI semantic conventions:
    - gen_ai.operation.name (chat, text_completion) → llm_call
    - execute_tool spans → tool_call
    - Status code 2 → error
    """
    path = Path(source)
    if not path.exists():
        raise IngestError(f"File not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise IngestError(f"Invalid JSON in {path}: {e}") from e

    resource_spans = data.get("resourceSpans", [])
    if not resource_spans:
        raise IngestError("No resourceSpans found in OTLP JSON")

    all_spans: list[dict] = []
    agent_name = "unknown"
    trace_id = ""

    for rs in resource_spans:
        resource_attrs = _otlp_attrs_to_dict(rs.get("resource", {}).get("attributes", []))
        if "service.name" in resource_attrs and agent_name == "unknown":
            agent_name = resource_attrs["service.name"]

        for ss in rs.get("scopeSpans", []):
            for span in ss.get("spans", []):
                all_spans.append(span)
                if not trace_id and span.get("traceId"):
                    trace_id = span["traceId"]

    all_spans.sort(key=lambda s: int(s.get("startTimeUnixNano", "0") or "0"))

    steps: list[TraceStep] = []
    task = ""

    for span in all_spans:
        attrs = _otlp_attrs_to_dict(span.get("attributes", []))
        step = _otlp_span_to_step(span, attrs)
        if step is None:
            continue

        if attrs.get("gen_ai.agent.name") and agent_name == "unknown":
            agent_name = attrs["gen_ai.agent.name"]

        if not task and attrs.get("gen_ai.operation.name") == "invoke_agent":
            task = str(attrs.get("gen_ai.agent.description", ""))

        steps.append(step)

    total_tokens = _aggregate_tokens(steps, None)
    total_duration = sum(s.duration_ms for s in steps)

    final_output = ""
    for step in reversed(steps):
        if step.type == "llm_call" and step.output.get("text"):
            final_output = step.output["text"][:500]
            break

    return AgentTrace(
        trace_id=trace_id or str(uuid.uuid4()),
        agent_name=agent_name,
        task=task,
        steps=steps,
        final_output=final_output,
        total_duration_ms=total_duration,
        total_tokens=total_tokens,
        metadata={"source_format": "otlp_json"},
    )


def _otlp_attrs_to_dict(attributes: list[dict]) -> dict:
    """Convert OTLP attribute list to a flat dict."""
    result = {}
    for attr in attributes:
        key = attr.get("key", "")
        value = attr.get("value", {})
        result[key] = _otlp_value(value)
    return result


def _otlp_value(value: dict):
    """Extract a Python value from an OTLP attribute value object."""
    if "stringValue" in value:
        return value["stringValue"]
    if "intValue" in value:
        return int(value["intValue"])
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "boolValue" in value:
        return value["boolValue"]
    if "arrayValue" in value:
        return [_otlp_value(v) for v in value["arrayValue"].get("values", [])]
    return str(value)


_LLM_OPERATIONS = {"chat", "text_completion", "generate_content", "embeddings"}


def _otlp_span_to_step(span: dict, attrs: dict) -> TraceStep | None:
    """Convert a single OTLP span to a TraceStep, or None if not relevant."""
    operation = attrs.get("gen_ai.operation.name", "")
    span_name = span.get("name", "")
    status_code = span.get("status", {}).get("code", 0)

    start_ns = int(span.get("startTimeUnixNano", "0") or "0")
    end_ns = int(span.get("endTimeUnixNano", "0") or "0")
    duration_ms = (end_ns - start_ns) / 1_000_000 if end_ns > start_ns else 0.0

    input_tokens = attrs.get("gen_ai.usage.input_tokens", 0)
    output_tokens = attrs.get("gen_ai.usage.output_tokens", 0)
    tokens = None
    if input_tokens or output_tokens:
        p = int(input_tokens) if input_tokens else 0
        c = int(output_tokens) if output_tokens else 0
        tokens = TokenUsage(prompt=p, completion=c, total=p + c)

    if status_code == 2:
        error_msg = span.get("status", {}).get("message", "")
        error_type = attrs.get("error.type", "unknown_error")
        return TraceStep(
            type="error",
            name=error_type,
            input={},
            output={"error": error_msg or error_type},
            duration_ms=duration_ms,
            tokens=tokens,
            metadata=_span_metadata(span, attrs),
        )

    if operation in _LLM_OPERATIONS:
        model = attrs.get("gen_ai.request.model", "") or attrs.get("gen_ai.response.model", "")
        name = model or span_name
        output_text = ""
        output_messages = attrs.get("gen_ai.output.messages")
        if isinstance(output_messages, str):
            output_text = output_messages[:500]
        elif isinstance(output_messages, list) and output_messages:
            first = output_messages[0]
            if isinstance(first, dict):
                output_text = str(first.get("content", ""))[:500]
            elif isinstance(first, str):
                output_text = first[:500]

        return TraceStep(
            type="llm_call",
            name=name,
            input={"messages": attrs.get("gen_ai.input.messages", "")},
            output={"text": output_text},
            duration_ms=duration_ms,
            tokens=tokens,
            metadata=_span_metadata(span, attrs),
        )

    if operation == "execute_tool" or span_name.startswith("execute_tool "):
        tool_name = attrs.get("gen_ai.tool.name", "")
        if not tool_name and span_name.startswith("execute_tool "):
            tool_name = span_name[len("execute_tool "):]
        tool_args = attrs.get("gen_ai.tool.call.arguments", "")
        tool_result = attrs.get("gen_ai.tool.call.result", "")
        return TraceStep(
            type="tool_call",
            name=tool_name or "unknown_tool",
            input={"arguments": tool_args} if tool_args else {},
            output={"text": str(tool_result)} if tool_result else {},
            duration_ms=duration_ms,
            tokens=tokens,
            metadata=_span_metadata(span, attrs),
        )

    if operation == "invoke_agent" or operation == "create_agent":
        return TraceStep(
            type="decision",
            name=attrs.get("gen_ai.agent.name", span_name),
            input={},
            output={},
            duration_ms=duration_ms,
            tokens=tokens,
            metadata=_span_metadata(span, attrs),
        )

    if operation:
        return TraceStep(
            type="decision",
            name=span_name or operation,
            input={},
            output={},
            duration_ms=duration_ms,
            tokens=tokens,
            metadata=_span_metadata(span, attrs),
        )

    return None


def _span_metadata(span: dict, attrs: dict) -> dict:
    """Extract metadata from an OTLP span."""
    meta: dict = {}
    if span.get("spanId"):
        meta["span_id"] = span["spanId"]
    if span.get("parentSpanId"):
        meta["parent_span_id"] = span["parentSpanId"]
    provider = attrs.get("gen_ai.provider.name")
    if provider:
        meta["provider"] = provider
    tool_call_id = attrs.get("gen_ai.tool.call.id")
    if tool_call_id:
        meta["tool_call_id"] = tool_call_id
    return meta


def _aggregate_tokens(steps: list[TraceStep], explicit: dict | None) -> TokenUsage:
    if explicit:
        return TokenUsage(**explicit)
    prompt = sum(s.tokens.prompt for s in steps if s.tokens)
    completion = sum(s.tokens.completion for s in steps if s.tokens)
    return TokenUsage(prompt=prompt, completion=completion, total=prompt + completion)
