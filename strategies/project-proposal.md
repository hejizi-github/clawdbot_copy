# Project Proposal: trajeval — Agent Trajectory Evaluation

> Produced by agent-lab session 20260417-034008 (Phase 2: Proposal)
> Updated: session 20260417-040642 (renamed from trajeval to trajeval — PyPI name "trajeval" was taken)
> Based on: `clawdbot-architecture.md` (Phase 1) and `frontier-tech-research.md` (Phase 2)

---

## 1. What to Build

**trajeval** — a framework-agnostic agent evaluation system that ingests execution traces, scores them on trajectory and outcome metrics, and drives quality improvement loops.

### One-Line Pitch

"Framework-agnostic agent trajectory evaluation: ingest traces, score with deterministic metrics + LLM-as-judge, output CI-ready quality reports."

---

## 2. Why This Project

### The Gap

Agent evaluation is the **highest-impact, highest-feasibility opportunity** identified in our research (see `frontier-tech-research.md` Section 7):

| Opportunity | Impact | Feasibility |
|-------------|--------|-------------|
| **Agent evaluation framework** | ★★★★★ | ★★★★ |
| Hybrid memory engine | ★★★★★ | ★★★ |
| Stateful agent orchestrator | ★★★★ | ★★★★ |

**Industry evidence**:
- LangChain 2026 survey: 57% of orgs have agents in production; **quality is the #1 barrier (32%)**
- Gartner: 60% of teams will adopt eval/observability platforms by 2028 (18% in 2025)
- Clawdbot has **no formal evaluation system** — the most significant gap identified in Phase 1

### Why Not Use Existing Tools?

| Tool | Limitation |
|------|-----------|
| **DeepEval** | Python-only, tightly coupled to its own metric implementations, heavy dependency tree |
| **LangSmith** | Framework-locked to LangChain/LangGraph ecosystem |
| **Braintrust** | SaaS-first, commercial; not self-hostable for sensitive workloads |
| **EvalForge** | Very new (v0.3), basic metrics, no improvement loop or calibration |
| **MLflow** | Broad ML platform — agent eval is a small add-on, not the core focus |

**The gap none of them fill**: a lightweight, self-hosted, framework-agnostic tool that combines trajectory analysis + LLM-as-judge with calibration + actionable improvement recommendations. Something a solo developer or small team can run locally or in CI without SaaS dependencies.

---

## 3. Technical Design

### Architecture

```
┌─────────────────────────────────────────────────┐
│                    CLI / API                      │
│  trajeval eval <trace>  |  trajeval report     │
│  trajeval calibrate     |  trajeval compare    │
└──────────┬──────────────────┬────────────────────┘
           │                  │
┌──────────▼──────┐  ┌───────▼────────┐
│  Trace Ingester │  │  Report Engine │
│  - OTLP/JSON    │  │  - Terminal    │
│  - Custom JSON  │  │  - JSON/CI     │
│  - JSONL replay │  │  - Markdown    │
└──────────┬──────┘  └───────▲────────┘
           │                  │
┌──────────▼──────────────────┴────────────────────┐
│                  Scoring Engine                    │
│  ┌────────────┐  ┌────────────┐  ┌─────────────┐ │
│  │Deterministic│  │LLM-as-Judge│  │ Calibration │ │
│  │  Metrics    │  │  Scorer    │  │  Module     │ │
│  └────────────┘  └────────────┘  └─────────────┘ │
└──────────┬───────────────────────────────────────┘
           │
┌──────────▼──────────────────────────────────────┐
│              Storage (SQLite)                     │
│  traces • scores • baselines • calibration data  │
└─────────────────────────────────────────────────┘
```

### Core Components

#### 3.1 Trace Ingester
Accepts agent execution traces in multiple formats:
- **OpenTelemetry GenAI format** (primary) — standard `gen_ai.*` attributes
- **Simple JSON** — minimal `{steps: [{type, input, output, duration}]}` format
- **JSONL replay** — replay raw session logs (e.g., Clawdbot JSONL transcripts)

Normalizes all inputs into an internal `AgentTrace` representation:

```python
class TraceStep(BaseModel):
    type: str          # "llm_call" | "tool_call" | "decision" | "error"
    name: str          # tool name, model name, or decision label
    input: dict
    output: dict
    duration_ms: float = 0.0
    tokens: TokenUsage | None = None
    metadata: dict

class AgentTrace(BaseModel):
    trace_id: str
    agent_name: str = "unknown"
    task: str = ""
    steps: list[TraceStep]
    final_output: str = ""
    total_duration_ms: float = 0.0
    total_tokens: TokenUsage
    metadata: dict     # framework, model, version, etc.
```

#### 3.2 Scoring Engine — Deterministic Metrics

Computed without LLM calls (fast, free, reproducible):

| Metric | What It Measures | Formula/Logic |
|--------|-----------------|---------------|
| **Step efficiency** | Wasted steps | `optimal_steps / actual_steps` (baseline comparison) |
| **Tool accuracy** | Right tool selection | `correct_tool_calls / total_tool_calls` |
| **Error recovery** | Resilience | `recovered_errors / total_errors` |
| **Loop detection** | Stuck loops | Repeated step sequences (n-gram matching) |
| **Token efficiency** | Cost per task | `tokens_used / baseline_tokens` |
| **Latency budget** | Speed | `duration / latency_budget` |

#### 3.3 Scoring Engine — LLM-as-Judge

For subjective quality dimensions that require understanding:

| Dimension | What the Judge Evaluates |
|-----------|------------------------|
| **Task completion** | Did the agent achieve the stated goal? (0-5 rubric) |
| **Reasoning quality** | Are intermediate decisions logical and well-justified? |
| **Tool use appropriateness** | Were tools used when needed and avoided when not? |
| **Information synthesis** | Was retrieved information properly combined? |
| **Harm avoidance** | Did the agent avoid unsafe or harmful actions? |

Judge implementation:
- Structured rubric prompts (not open-ended "rate this")
- Rubric calibrated against human annotations (target: 0.80+ Spearman correlation)
- Position/length bias mitigation via randomized presentation order
- Multi-judge ensemble option (2-3 judges, majority vote) for high-stakes evals

#### 3.4 Calibration Module

The key differentiator — ensuring LLM judge scores are **meaningful**:

1. **Human annotation collection**: CLI command to annotate traces with human scores
2. **Correlation analysis**: Spearman/Pearson between human and LLM scores
3. **Rubric refinement**: Automated rubric adjustment when correlation drops below threshold
4. **Drift detection**: Alert when score distributions shift significantly between runs

#### 3.5 Report Engine

Multiple output formats:

- **Terminal**: Colored summary table with pass/fail per metric
- **JSON**: Machine-readable for CI exit codes and dashboards
- **Markdown**: Human-readable report for PR comments or documentation
- **Comparison**: Side-by-side diff between two evaluation runs (regression detection)

---

## 4. Technology Choices

### Language: Python

| Factor | Python | TypeScript | Go |
|--------|--------|-----------|-----|
| ML/eval ecosystem | ★★★★★ (numpy, scipy for stats) | ★★★ | ★★ |
| OpenTelemetry SDK maturity | ★★★★★ (v1.40.0) | ★★★★ | ★★★★ |
| Anthropic SDK | ★★★★★ (native) | ★★★★★ (native) | ★★★ (community) |
| Agent framework compat | ★★★★★ (LangChain, CrewAI, AutoGen all Python) | ★★★ | ★★ |
| CLI tooling | ★★★★ (click/typer) | ★★★★ (commander) | ★★★★★ |
| Target users | Data scientists, ML engineers | Web developers | Platform engineers |

**Decision**: Python. The agent evaluation ecosystem (benchmarks, metrics libraries, statistical tools) is overwhelmingly Python. Most agent frameworks are Python-first. The Anthropic SDK for LLM-as-judge is native Python.

### Key Dependencies (minimal)

| Dependency | Purpose | Why This One |
|------------|---------|-------------|
| `click` | CLI framework | Mature, composable, well-documented |
| `anthropic` | LLM-as-judge API calls | Direct SDK, prompt caching support |
| `sqlite3` | Storage | Zero-dependency, included in Python stdlib |
| `rich` | Terminal output | Beautiful tables and progress bars |
| `pydantic` | Data validation | Type-safe trace schemas |
| `scipy` | Calibration statistics | Spearman correlation, distribution tests |

No heavy frameworks. No LangChain dependency. No vector databases. Runs with `pip install trajeval`.

### Infrastructure: Zero

- **Storage**: SQLite (local file, no server)
- **Compute**: Local Python process
- **LLM**: Bring-your-own API key (Anthropic recommended, OpenAI supported)
- **CI**: Exit code 0/1 + JSON artifact — works with any CI system

---

## 5. MVP Scope (Phase 3, Sessions 1-5)

### Session 1: Project skeleton + trace format
- Python project setup (pyproject.toml, pytest, ruff)
- Define `AgentTrace` / `TraceStep` data models with Pydantic
- Implement simple JSON trace ingester
- Write 5+ unit tests for trace parsing
- CLI skeleton: `trajeval eval <trace.json>`

### Session 2: Deterministic metrics engine
- Implement 4 core metrics: step efficiency, tool accuracy, loop detection, token efficiency
- SQLite storage for traces and scores
- Terminal report output (rich tables)
- 10+ unit tests covering metric edge cases

### Session 3: LLM-as-judge scorer
- Structured rubric prompts for task completion + reasoning quality
- Anthropic SDK integration with prompt caching
- JSON output mode for CI
- Mock-based tests (no real API calls in test suite)

### Session 4: Comparison + regression detection
- `trajeval compare <baseline> <current>` command
- Markdown report generation
- Statistical significance testing for score differences
- End-to-end test with sample traces

### Session 5: Calibration + polish
- Human annotation CLI (`trajeval annotate <trace>`)
- Correlation analysis between human and LLM scores
- OTLP trace format support (OpenTelemetry ingestion)
- README with usage examples

### What's Explicitly Out of MVP Scope
- Web UI / dashboard
- Multi-user collaboration
- Real-time streaming evaluation
- Custom metric plugin system
- Agent framework auto-instrumentation
- Cloud deployment / SaaS mode

---

## 6. Connection to Clawdbot

trajeval is designed to be useful standalone, but has a clear integration path with Clawdbot:

1. **JSONL transcript ingestion**: Clawdbot stores all sessions as JSONL — trajeval can ingest and evaluate these
2. **Quality metrics for cron jobs**: Evaluate whether scheduled agent tasks are completing successfully
3. **Dreaming quality**: Measure whether memory consolidation (light/deep/REM) actually improves agent performance
4. **A/B testing**: Compare agent performance across model versions, prompt changes, or config tweaks
5. **Three-agent harness pattern**: trajeval could serve as the "Evaluator" in Anthropic's Planner→Generator→Evaluator architecture

---

## 7. Success Criteria

### MVP (end of Session 5)
- [ ] `pip install` works, zero external services required
- [ ] Can evaluate a trace JSON and produce terminal + JSON reports
- [ ] 4+ deterministic metrics + 2+ LLM-as-judge dimensions
- [ ] Regression detection between two evaluation runs
- [ ] 30+ unit tests, all passing
- [ ] <5s evaluation time for a 50-step trace (excluding LLM calls)

### Post-MVP Quality Targets
- LLM-as-judge correlation with human annotations: ≥0.80 Spearman
- False positive rate on regression detection: <5%
- Able to evaluate Clawdbot JSONL transcripts without modification

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| LLM-as-judge unreliable (bias, inconsistency) | Medium | High | Calibration module; deterministic metrics as fallback; multi-judge ensemble |
| Trace format fragmentation (each framework is different) | High | Medium | Start with simple JSON; add formats incrementally; normalize early |
| Scope creep into "full observability platform" | Medium | High | MVP scope is explicit; no web UI, no streaming, no plugins |
| API costs for evaluation | Low | Low | Prompt caching; batch evaluation; deterministic metrics are free |

---

## 9. Decision Log

| Decision | Chosen | Alternatives Considered | Rationale |
|----------|--------|------------------------|-----------|
| Project focus | Agent evaluation | Memory engine, orchestrator, sandbox | Highest impact × feasibility; industry-wide gap; Clawdbot's weakest area |
| Language | Python | TypeScript, Go | ML/eval ecosystem, framework compatibility, statistical libraries |
| Storage | SQLite | PostgreSQL, files-only | Zero dependency; good enough for local/CI; can upgrade later |
| LLM-as-judge provider | Anthropic (primary) | OpenAI, open models | Best reasoning for rubric evaluation; prompt caching reduces cost |
| CLI-first vs API-first | CLI-first | REST API, library-only | CI/CD integration; matches target workflow; API can wrap CLI later |
| Trace format | Simple JSON (primary) | OTLP-only, custom binary | Lowest barrier to adoption; OTLP added in Session 5 |
