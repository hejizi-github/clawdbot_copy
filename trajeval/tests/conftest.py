"""Shared test fixtures."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def simple_trace_path():
    return FIXTURES_DIR / "simple_trace.json"


@pytest.fixture
def minimal_trace_path():
    return FIXTURES_DIR / "minimal_trace.json"


@pytest.fixture
def error_trace_path():
    return FIXTURES_DIR / "error_trace.json"


@pytest.fixture
def simple_trace_dict():
    return {
        "trace_id": "dict-trace-001",
        "agent_name": "dict-agent",
        "task": "Test task",
        "steps": [
            {
                "type": "llm_call",
                "name": "gpt-4",
                "input": {"prompt": "hello"},
                "output": {"response": "hi"},
                "duration_ms": 100.0,
                "tokens": {"prompt": 10, "completion": 5, "total": 15},
            }
        ],
        "final_output": "Done",
    }
