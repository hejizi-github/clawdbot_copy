"""LLM-as-judge scorer for subjective trace evaluation."""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from .models import AgentTrace

RUBRIC_SYSTEM = """You are an expert evaluator of AI agent execution traces.

You will receive an agent's execution trace (the sequence of steps it took to complete a task)
and must evaluate it on the specified dimensions.

For each dimension, provide:
1. A score from 0 to 5 (integers only)
2. A brief explanation (1-2 sentences) justifying the score

Scoring guide:
- 0: Complete failure / not attempted
- 1: Minimal effort, mostly wrong
- 2: Partial attempt, significant issues
- 3: Adequate, meets basic expectations
- 4: Good, minor issues only
- 5: Excellent, no meaningful issues

IMPORTANT: Respond with valid JSON only. No markdown, no code fences, no extra text.

Response format:
{
  "dimensions": [
    {"name": "<dimension_name>", "score": <0-5>, "explanation": "<brief justification>"}
  ]
}"""

DIMENSION_PROMPTS = {
    "task_completion": (
        "Task Completion: Did the agent achieve the stated goal? "
        "Consider whether the final output addresses the original task, "
        "whether all requirements were met, and whether the result is usable."
    ),
    "reasoning_quality": (
        "Reasoning Quality: Are the agent's intermediate decisions logical and well-justified? "
        "Consider whether the agent's step-by-step approach makes sense, "
        "whether it adapted when encountering obstacles, "
        "and whether it avoided unnecessary detours."
    ),
}


class JudgeConfig(BaseModel):
    model: str = "claude-sonnet-4-6"
    dimensions: list[str] = Field(
        default_factory=lambda: ["task_completion", "reasoning_quality"],
    )
    temperature: float = 0.0
    max_tokens: int = 1024


class JudgeDimension(BaseModel):
    name: str
    score: int = Field(ge=0, le=5)
    explanation: str = ""


class JudgeResult(BaseModel):
    trace_id: str
    dimensions: list[JudgeDimension] = Field(default_factory=list)
    overall_score: float = Field(ge=0.0, le=1.0, default=0.0)
    model: str = ""
    error: str | None = None


def build_user_prompt(trace: AgentTrace, dimensions: list[str]) -> str:
    """Build the user message containing the trace and evaluation dimensions."""
    dim_descriptions = []
    for d in dimensions:
        desc = DIMENSION_PROMPTS.get(d, f"{d}: Evaluate this dimension.")
        dim_descriptions.append(f"- {desc}")

    steps_summary = []
    for i, step in enumerate(trace.steps):
        entry = f"  Step {i+1} [{step.type}] {step.name}"
        if step.input:
            input_str = json.dumps(step.input, ensure_ascii=False)
            if len(input_str) > 200:
                input_str = input_str[:200] + "..."
            entry += f"\n    Input: {input_str}"
        if step.output:
            output_str = json.dumps(step.output, ensure_ascii=False)
            if len(output_str) > 200:
                output_str = output_str[:200] + "..."
            entry += f"\n    Output: {output_str}"
        if step.duration_ms > 0:
            entry += f"\n    Duration: {step.duration_ms:.0f}ms"
        steps_summary.append(entry)

    return f"""Agent: {trace.agent_name}
Task: {trace.task or "(not specified)"}
Steps ({trace.step_count} total):
{chr(10).join(steps_summary)}

Final output: {trace.final_output or "(none)"}

Evaluate the following dimensions:
{chr(10).join(dim_descriptions)}"""


def _normalize_score(dimensions: list[JudgeDimension]) -> float:
    """Normalize 0-5 dimension scores to a 0-1 overall score."""
    if not dimensions:
        return 0.0
    total = sum(d.score for d in dimensions)
    max_possible = 5 * len(dimensions)
    return round(total / max_possible, 4)


def _parse_response(text: str, trace_id: str) -> list[JudgeDimension]:
    """Parse the LLM JSON response into JudgeDimension objects."""
    text = text.strip()
    text = re.sub(r"^```\w*\n", "", text)
    text = re.sub(r"\n```\s*$", "", text)

    data = json.loads(text)
    dims = data.get("dimensions", [])
    results = []
    for d in dims:
        results.append(JudgeDimension(
            name=d["name"],
            score=max(0, min(5, int(d["score"]))),
            explanation=d.get("explanation", ""),
        ))
    return results


def judge(trace: AgentTrace, config: JudgeConfig | None = None, client=None) -> JudgeResult:
    """Evaluate a trace using an LLM judge.

    Args:
        trace: The agent trace to evaluate.
        config: Judge configuration. Uses defaults if None.
        client: An anthropic.Anthropic client instance. If None, creates one.
    """
    if config is None:
        config = JudgeConfig()

    if client is None:
        try:
            import anthropic
            client = anthropic.Anthropic()
        except ImportError:
            return JudgeResult(
                trace_id=trace.trace_id,
                model=config.model,
                error="anthropic package not installed. Install with: pip install trajeval[judge]",
            )

    user_prompt = build_user_prompt(trace, config.dimensions)

    try:
        response = client.messages.create(
            model=config.model,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            system=[{
                "type": "text",
                "text": RUBRIC_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_prompt}],
        )

        text = response.content[0].text
        dimensions = _parse_response(text, trace.trace_id)

        return JudgeResult(
            trace_id=trace.trace_id,
            dimensions=dimensions,
            overall_score=_normalize_score(dimensions),
            model=config.model,
        )
    except json.JSONDecodeError as e:
        return JudgeResult(
            trace_id=trace.trace_id,
            model=config.model,
            error=f"Failed to parse judge response as JSON: {e}",
        )
    except Exception as e:
        return JudgeResult(
            trace_id=trace.trace_id,
            model=config.model,
            error=f"Judge API call failed: {e}",
        )
