"""Tests for LLM-as-judge scorer (mock-based, no real API calls)."""

import json
from unittest.mock import MagicMock

import pytest

from trajeval.models import AgentTrace, TokenUsage, TraceStep
from trajeval.scorer import (
    JudgeConfig,
    JudgeDimension,
    JudgeResult,
    _normalize_score,
    _parse_response,
    build_user_prompt,
    judge,
)


@pytest.fixture
def sample_trace():
    return AgentTrace(
        trace_id="judge-test-001",
        agent_name="test-agent",
        task="Find the capital of France",
        steps=[
            TraceStep(
                type="llm_call",
                name="claude-3",
                input={"prompt": "What is the capital of France?"},
                output={"response": "The capital of France is Paris."},
                duration_ms=500.0,
                tokens=TokenUsage(prompt=20, completion=10, total=30),
            ),
            TraceStep(
                type="tool_call",
                name="search",
                input={"query": "capital of France"},
                output={"result": "Paris"},
                duration_ms=200.0,
            ),
        ],
        final_output="The capital of France is Paris.",
        total_tokens=TokenUsage(prompt=20, completion=10, total=30),
    )


@pytest.fixture
def mock_api_response():
    """A well-formed judge response."""
    return json.dumps({
        "dimensions": [
            {
                "name": "task_completion",
                "score": 5,
                "explanation": "The agent correctly identified Paris as the capital of France.",
            },
            {
                "name": "reasoning_quality",
                "score": 4,
                "explanation": "Logical approach but the search was redundant.",
            },
        ]
    })


def _make_mock_client(response_text: str) -> MagicMock:
    client = MagicMock()
    mock_content = MagicMock()
    mock_content.text = response_text
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    client.messages.create.return_value = mock_response
    return client


class TestBuildUserPrompt:
    def test_includes_trace_info(self, sample_trace):
        prompt = build_user_prompt(sample_trace, ["task_completion"])
        assert "test-agent" in prompt
        assert "Find the capital of France" in prompt
        assert "claude-3" in prompt
        assert "search" in prompt

    def test_includes_dimension_descriptions(self, sample_trace):
        prompt = build_user_prompt(sample_trace, ["task_completion", "reasoning_quality"])
        assert "Task Completion" in prompt
        assert "Reasoning Quality" in prompt

    def test_includes_step_details(self, sample_trace):
        prompt = build_user_prompt(sample_trace, ["task_completion"])
        assert "Step 1 [llm_call]" in prompt
        assert "Step 2 [tool_call]" in prompt
        assert "500ms" in prompt

    def test_includes_final_output(self, sample_trace):
        prompt = build_user_prompt(sample_trace, ["task_completion"])
        assert "Paris" in prompt

    def test_unknown_dimension_gets_generic_description(self, sample_trace):
        prompt = build_user_prompt(sample_trace, ["custom_metric"])
        assert "custom_metric" in prompt

    def test_truncates_long_io(self):
        trace = AgentTrace(
            trace_id="long-io",
            task="test",
            steps=[
                TraceStep(
                    type="tool_call",
                    name="big_tool",
                    input={"data": "x" * 500},
                    output={"result": "y" * 500},
                ),
            ],
        )
        prompt = build_user_prompt(trace, ["task_completion"])
        assert "..." in prompt


class TestParseResponse:
    def test_valid_json(self, mock_api_response):
        dims = _parse_response(mock_api_response, "t1")
        assert len(dims) == 2
        assert dims[0].name == "task_completion"
        assert dims[0].score == 5
        assert dims[1].name == "reasoning_quality"
        assert dims[1].score == 4

    def test_strips_code_fences(self):
        wrapped = '```json\n{"dimensions": [{"name": "x", "score": 3, "explanation": "ok"}]}\n```'
        dims = _parse_response(wrapped, "t1")
        assert len(dims) == 1
        assert dims[0].score == 3

    def test_clamps_score_range(self):
        raw = json.dumps({"dimensions": [
            {"name": "a", "score": -1, "explanation": "bad"},
            {"name": "b", "score": 99, "explanation": "overflow"},
        ]})
        dims = _parse_response(raw, "t1")
        assert dims[0].score == 0
        assert dims[1].score == 5

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_response("not json at all", "t1")

    def test_missing_explanation(self):
        raw = json.dumps({"dimensions": [{"name": "a", "score": 3}]})
        dims = _parse_response(raw, "t1")
        assert dims[0].explanation == ""


class TestNormalizeScore:
    def test_perfect_scores(self):
        dims = [JudgeDimension(name="a", score=5), JudgeDimension(name="b", score=5)]
        assert _normalize_score(dims) == 1.0

    def test_zero_scores(self):
        dims = [JudgeDimension(name="a", score=0), JudgeDimension(name="b", score=0)]
        assert _normalize_score(dims) == 0.0

    def test_mixed_scores(self):
        dims = [JudgeDimension(name="a", score=3), JudgeDimension(name="b", score=4)]
        assert _normalize_score(dims) == 0.7

    def test_empty_dimensions(self):
        assert _normalize_score([]) == 0.0

    def test_single_dimension(self):
        dims = [JudgeDimension(name="a", score=4)]
        assert _normalize_score(dims) == 0.8


class TestJudge:
    def test_successful_judge(self, sample_trace, mock_api_response):
        client = _make_mock_client(mock_api_response)
        result = judge(sample_trace, client=client)

        assert isinstance(result, JudgeResult)
        assert result.trace_id == "judge-test-001"
        assert result.error is None
        assert len(result.dimensions) == 2
        assert result.overall_score == 0.9  # (5+4) / 10

    def test_uses_config(self, sample_trace, mock_api_response):
        client = _make_mock_client(mock_api_response)
        config = JudgeConfig(model="claude-haiku-4-5-20251001", temperature=0.5)
        judge(sample_trace, config=config, client=client)

        call_kwargs = client.messages.create.call_args.kwargs
        assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
        assert call_kwargs["temperature"] == 0.5

    def test_prompt_caching_header(self, sample_trace, mock_api_response):
        client = _make_mock_client(mock_api_response)
        judge(sample_trace, client=client)

        call_kwargs = client.messages.create.call_args.kwargs
        system = call_kwargs["system"]
        assert system[0]["cache_control"] == {"type": "ephemeral"}

    def test_api_error_returns_error_result(self, sample_trace):
        client = MagicMock()
        client.messages.create.side_effect = RuntimeError("API down")
        result = judge(sample_trace, client=client)

        assert result.error is not None
        assert "API down" in result.error
        assert result.dimensions == []

    def test_malformed_response(self, sample_trace):
        client = _make_mock_client("not valid json {{{")
        result = judge(sample_trace, client=client)

        assert result.error is not None
        assert "JSON" in result.error

    def test_missing_anthropic_package(self, sample_trace, monkeypatch):
        """If anthropic is not installed and no client given, return helpful error."""
        real_import = __import__

        def mock_import(name, *args, **kwargs):
            if name == "anthropic":
                raise ImportError("No module named 'anthropic'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", mock_import)
        result = judge(sample_trace, client=None)
        assert result.error is not None
        assert "anthropic" in result.error

    def test_default_dimensions(self, sample_trace, mock_api_response):
        client = _make_mock_client(mock_api_response)
        config = JudgeConfig()
        judge(sample_trace, config=config, client=client)

        call_kwargs = client.messages.create.call_args.kwargs
        user_msg = call_kwargs["messages"][0]["content"]
        assert "Task Completion" in user_msg
        assert "Reasoning Quality" in user_msg
