# trajeval

Framework-agnostic agent trajectory evaluation. Ingest execution traces from any agent framework, score with deterministic metrics + LLM-as-judge, output CI-ready quality reports.

## Features

- **Deterministic metrics** — step efficiency, tool accuracy, loop detection, token efficiency
- **LLM-as-judge** — configurable rubric-based evaluation using Claude models
- **Regression detection** — compare two traces and flag metric regressions
- **Human calibration** — annotate traces manually, then compute correlation with LLM judge scores
- **CI-ready** — exit code 0 on pass, 1 on fail; JSON output for automation

## Installation

```bash
# Core (deterministic metrics + CLI)
pip install trajeval

# With LLM judge support (requires ANTHROPIC_API_KEY)
pip install trajeval[judge]

# With calibration/statistics support (scipy)
pip install trajeval[stats]

# Everything
pip install trajeval[all]
```

For development:

```bash
git clone <repo-url> && cd trajeval
pip install -e ".[dev]"
```

## Quick Start

**1. Create a trace file** (`trace.json`):

```json
{
  "trace_id": "demo-001",
  "agent_name": "my-agent",
  "task": "Find the capital of France",
  "steps": [
    {
      "type": "llm_call",
      "name": "claude-sonnet-4-6",
      "input": {"prompt": "What is the capital of France?"},
      "output": {"text": "The capital of France is Paris."},
      "duration_ms": 450,
      "tokens": {"prompt": 12, "completion": 8, "total": 20}
    },
    {
      "type": "tool_call",
      "name": "verify_answer",
      "input": {"answer": "Paris"},
      "output": {"verified": true},
      "duration_ms": 50
    }
  ],
  "final_output": "The capital of France is Paris."
}
```

**2. Run evaluation:**

```bash
trajeval eval trace.json
```

Output:
```
┌─────────────────────────┐
│ Trace: demo-001         │
├─────────┬───────────────┤
│ Agent   │ my-agent      │
│ Task    │ Find the ca…  │
│ Steps   │ 2             │
└─────────┴───────────────┘

┌───────────────────┬───────┬────────┐
│ Metric            │ Score │ Status │
├───────────────────┼───────┼────────┤
│ step_efficiency   │  1.00 │ PASS   │
│ tool_accuracy     │  1.00 │ PASS   │
│ loop_detection    │  1.00 │ PASS   │
│ token_efficiency  │  1.00 │ PASS   │
├───────────────────┼───────┼────────┤
│ Overall           │  1.00 │ PASS   │
└───────────────────┴───────┴────────┘
```

**3. Get JSON output for CI:**

```bash
trajeval eval trace.json --format json
echo $?  # 0 = pass, 1 = fail
```

## Trace Format

trajeval uses a simple JSON format. All fields except `steps` are optional:

```json
{
  "trace_id": "string",
  "agent_name": "string",
  "task": "string",
  "steps": [
    {
      "type": "llm_call | tool_call | decision | error",
      "name": "string",
      "input": {},
      "output": {},
      "duration_ms": 0.0,
      "tokens": {
        "prompt": 0,
        "completion": 0,
        "total": 0
      },
      "metadata": {}
    }
  ],
  "final_output": "string",
  "total_duration_ms": 0.0,
  "total_tokens": {"prompt": 0, "completion": 0, "total": 0},
  "metadata": {}
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `trace_id` | No | Unique identifier (auto-generated UUID if missing) |
| `agent_name` | No | Name of the agent (default: "unknown") |
| `task` | No | Description of the task the agent was solving |
| `steps` | Yes | Ordered list of execution steps |
| `steps[].type` | No | One of: `llm_call`, `tool_call`, `decision`, `error` |
| `steps[].name` | No | Tool name, model name, or step label |
| `steps[].tokens` | No | Token usage for this step |
| `final_output` | No | The agent's final answer or result |
| `total_duration_ms` | No | Total wall-clock time (auto-summed from steps if missing) |
| `total_tokens` | No | Aggregate token usage (auto-summed from steps if missing) |

## CLI Reference

### `trajeval eval`

Run deterministic metrics on a trace.

```bash
trajeval eval trace.json
trajeval eval trace.json --format json
trajeval eval trace.json --threshold 0.8
trajeval eval trace.json --expected-steps 5 --baseline-tokens 1000
```

| Option | Default | Description |
|--------|---------|-------------|
| `--format` | `table` | Output format: `table` or `json` |
| `--threshold` | `0.7` | Pass/fail threshold (0.0-1.0) |
| `--expected-steps` | — | Baseline step count for efficiency scoring |
| `--baseline-tokens` | — | Baseline token count for efficiency scoring |

Exit code: `0` if all metrics pass, `1` if any metric fails.

### `trajeval judge`

Evaluate a trace using an LLM-as-judge (requires `pip install trajeval[judge]` and `ANTHROPIC_API_KEY`).

```bash
trajeval judge trace.json
trajeval judge trace.json --model claude-sonnet-4-6
trajeval judge trace.json --dimensions task_completion,reasoning_quality
trajeval judge trace.json --format json --threshold 0.8
```

| Option | Default | Description |
|--------|---------|-------------|
| `--model` | `claude-sonnet-4-6` | Anthropic model for judging |
| `--dimensions` | `task_completion,reasoning_quality` | Comma-separated evaluation dimensions |
| `--format` | `table` | Output format: `table` or `json` |
| `--threshold` | `0.7` | Pass/fail threshold (0.0-1.0) |

Built-in dimensions: `task_completion`, `reasoning_quality`. Custom dimension names are accepted — the judge uses a generic prompt for unknown dimensions.

Exit code: `0` if overall score >= threshold, `1` otherwise.

### `trajeval compare`

Compare two traces and detect metric regressions.

```bash
trajeval compare baseline.json current.json
trajeval compare baseline.json current.json --tolerance 0.1
trajeval compare baseline.json current.json --format markdown
```

| Option | Default | Description |
|--------|---------|-------------|
| `--format` | `table` | Output format: `table`, `json`, or `markdown` |
| `--tolerance` | `0.05` | Regression tolerance — score drops beyond this are flagged |
| `--threshold` | `0.7` | Metric pass/fail threshold |
| `--expected-steps` | — | Baseline step count |
| `--baseline-tokens` | — | Baseline token count |

The `markdown` format produces a report suitable for GitHub PR comments.

Exit code: `0` if no regressions, `1` if any metric regressed beyond tolerance.

### `trajeval annotate`

Interactively annotate a trace with human scores (for calibrating the LLM judge).

```bash
trajeval annotate trace.json
trajeval annotate trace.json --output my-annotations.jsonl
trajeval annotate trace.json --dimensions task_completion,reasoning_quality --annotator alice
```

| Option | Default | Description |
|--------|---------|-------------|
| `--output` / `-o` | `annotations.jsonl` | Output file for annotations (JSONL) |
| `--dimensions` | `task_completion,reasoning_quality` | Dimensions to annotate |
| `--annotator` | `default` | Annotator identifier |

The command displays the trace summary and prompts for integer scores (0-5) for each dimension.

### `trajeval calibrate`

Compute Spearman rank correlation between human annotations and LLM judge scores.

```bash
trajeval calibrate annotations.jsonl judgments.jsonl
trajeval calibrate annotations.jsonl judgments.jsonl --format json
```

| Option | Default | Description |
|--------|---------|-------------|
| `--format` | `table` | Output format: `table` or `json` |

Requires `pip install trajeval[stats]` for scipy. Needs at least 3 paired scores per dimension; 10+ recommended for reliable results.

## Metrics

### Deterministic Metrics (via `eval`)

| Metric | What it measures | Scoring |
|--------|-----------------|---------|
| **step_efficiency** | Ratio of productive (non-error) steps to total steps. With `--expected-steps`, scores actual vs expected instead. | `min(expected/actual, 1.0)` or `productive/total` |
| **tool_accuracy** | Tool call success rate. A tool call fails if followed by an error step or its output contains error indicators. | `successful/total` |
| **loop_detection** | Detects repeated step sequences via n-gram analysis (bigrams and trigrams). Penalizes repetitive patterns. | `1.0 - penalty` where penalty scales with repeated steps |
| **token_efficiency** | Token usage vs baseline. Without `--baseline-tokens`, scores productive tokens vs total (error tokens are waste). | `min(baseline/actual, 1.0)` or `productive/total` |

Each metric produces a score from 0.0 to 1.0. A metric passes if its score >= the threshold (default 0.7).

### LLM Judge Dimensions (via `judge`)

The LLM judge scores each dimension from 0 to 5:

| Dimension | What it evaluates |
|-----------|-------------------|
| **task_completion** | Did the agent achieve the stated goal? Are all requirements met? Is the result usable? |
| **reasoning_quality** | Are intermediate decisions logical? Did the agent adapt to obstacles? Did it avoid unnecessary detours? |

Custom dimensions can be specified — the judge uses a generic evaluation prompt for any dimension not in the built-in list.

## CI Integration

trajeval is designed for CI pipelines. All commands that produce a pass/fail verdict use exit codes:

```bash
# Fail the build if evaluation score drops below 80%
trajeval eval trace.json --threshold 0.8

# Fail the build on metric regression
trajeval compare baseline.json current.json --tolerance 0.05

# Fail the build if LLM judge score is below 70%
trajeval judge trace.json --threshold 0.7
```

Use `--format json` to parse results programmatically:

```bash
RESULT=$(trajeval eval trace.json --format json)
SCORE=$(echo "$RESULT" | python -c "import sys,json; print(json.load(sys.stdin)['overall_score'])")
```

## Python API

```python
from trajeval.ingester import ingest_json
from trajeval.metrics import MetricConfig, evaluate
from trajeval.scorer import JudgeConfig, judge

# Load a trace
trace = ingest_json("trace.json")
# or from a dict:
trace = ingest_json({"trace_id": "t1", "steps": [...]})

# Deterministic evaluation
config = MetricConfig(pass_threshold=0.8, expected_steps=5)
report = evaluate(trace, config)
print(report.overall_score, report.passed)
for m in report.metrics:
    print(f"  {m.name}: {m.score:.2f} {'PASS' if m.passed else 'FAIL'}")

# LLM-as-judge (requires anthropic package + ANTHROPIC_API_KEY)
judge_config = JudgeConfig(
    model="claude-sonnet-4-6",
    dimensions=["task_completion", "reasoning_quality"],
)
result = judge(trace, config=judge_config)
if result.error:
    print(f"Error: {result.error}")
else:
    print(f"Overall: {result.overall_score:.0%}")
    for d in result.dimensions:
        print(f"  {d.name}: {d.score}/5 — {d.explanation}")
```

## License

MIT
