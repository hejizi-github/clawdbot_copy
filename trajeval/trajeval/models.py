"""Core data models for agent execution traces."""

from __future__ import annotations

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    prompt: int = 0
    completion: int = 0
    total: int = 0


class TraceStep(BaseModel):
    type: str = Field(description="Step type: llm_call, tool_call, decision, error")
    name: str = Field(description="Tool name, model name, or decision label")
    input: dict = Field(default_factory=dict)
    output: dict = Field(default_factory=dict)
    duration_ms: float = 0.0
    tokens: TokenUsage | None = None
    metadata: dict = Field(default_factory=dict)


class AgentTrace(BaseModel):
    trace_id: str
    agent_name: str = "unknown"
    task: str = ""
    steps: list[TraceStep] = Field(default_factory=list)
    final_output: str = ""
    total_duration_ms: float = 0.0
    total_tokens: TokenUsage = Field(default_factory=TokenUsage)
    metadata: dict = Field(default_factory=dict)

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def tool_calls(self) -> list[TraceStep]:
        return [s for s in self.steps if s.type == "tool_call"]

    @property
    def llm_calls(self) -> list[TraceStep]:
        return [s for s in self.steps if s.type == "llm_call"]

    @property
    def errors(self) -> list[TraceStep]:
        return [s for s in self.steps if s.type == "error"]
