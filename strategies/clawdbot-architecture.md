# OpenClaw/Clawdbot Architecture Analysis

> Produced by agent-lab session 20260417-024920 (Phase 1: Learning)
> Source: `/Volumes/MOVESPEED/workspace/ai-agents/clawdbot/` — 6,477 TypeScript files, 61+ subsystems, 260+ npm scripts

---

## 1. System Overview

OpenClaw is a **multi-channel AI gateway** — a platform that connects LLM-powered agents to messaging channels (Discord, Slack, Telegram, WhatsApp, iMessage, etc.) through a unified architecture. It's not just a chatbot; it's an agent orchestration platform with scheduling, tool execution, memory consolidation, plugin extensibility, and multi-provider LLM support.

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI Layer                             │
│  entry.ts → cli/run-main.ts → commands/* (lazy-loaded)       │
└─────────────────────┬───────────────────────────────────────┘
                      │
┌─────────────────────▼───────────────────────────────────────┐
│                   Gateway Server                             │
│  HTTP + WebSocket + TLS                                      │
│  ├─ server.impl.ts (orchestrator)                            │
│  ├─ server-methods/*.ts (40+ method handlers)                │
│  ├─ server-ws-runtime.ts (WebSocket management)              │
│  └─ protocol/schema/ (21 Zod schemas)                        │
└──┬──────────┬──────────┬──────────┬─────────────────────────┘
   │          │          │          │
┌──▼──┐  ┌───▼───┐  ┌───▼───┐  ┌──▼──────────┐
│Route│  │Channel│  │ Agent │  │    Cron      │
│     │  │Manager│  │Harness│  │  Scheduler   │
└──┬──┘  └───┬───┘  └───┬───┘  └──┬──────────┘
   │         │          │          │
   │    ┌────▼─────┐  ┌─▼────────┐│
   │    │ Plugins  │  │ LLM/Chat ││
   │    │ (10+ ch) │  │ Provider ││
   │    └──────────┘  └─┬────────┘│
   │                    │          │
   │              ┌─────▼────┐    │
   │              │  Tools   │    │
   │              │  (50+)   │    │
   │              └──────────┘    │
   │                              │
┌──▼──────────────────────────────▼───────────────────────────┐
│                   Session / Memory Layer                      │
│  JSONL transcripts • Session keys • Memory dreaming          │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Entry Point & Bootstrap

**Key files**: `src/entry.ts`, `src/index.ts`, `src/bootstrap/`, `src/cli/run-main.ts`

### Startup Sequence

1. **entry.ts** — Shebang entry (`#!/usr/bin/env node`)
   - `isMainModule()` guard prevents import-as-dependency
   - Sets process title to "openclaw"
   - Enables Node.js compile cache
   - Parses CLI profile args (`--profile`, `--dev`)
   - Respawns or calls `runMainOrRootHelp()`

2. **cli/run-main.ts** — CLI dispatcher
   - Routes to command via `tryRouteCli()`
   - Loads config, validates, applies profile env overrides
   - Handles channel/model/plugin subcommands

3. **index.ts** — Dual-mode: library exports when imported, legacy CLI when run directly

4. **bootstrap/node-startup-env.ts** — TLS resolution, platform-aware cert loading

### Design Pattern: Lazy Loading Everywhere
Core logic is async-imported only when needed. This keeps CLI startup fast — you don't load the entire gateway just to run `openclaw --version`.

---

## 3. Gateway Architecture

**Key files**: `src/gateway/server.impl.ts` (350+ lines), `src/gateway/server.ts`
**Stats**: ~288 files, 19,935 LOC

### Gateway Startup (5 phases)

1. **Config Loading** — `loadGatewayStartupConfigSnapshot()`, auth token resolution
2. **Plugin Bootstrap** — Bundled + external plugins loaded
3. **Runtime Config** — Bind address resolution (loopback/LAN/Tailscale), HTTP endpoints
4. **Service Init** — Channel manager, cron, event subscriptions, WebSocket handlers
5. **Health & Readiness** — Health snapshots, presence tracking, version numbering

### Transport Layer

| Protocol | Path | Purpose |
|----------|------|---------|
| WebSocket | `/ws` | Primary bidirectional channel for real-time communication |
| HTTP POST | `/v1/chat/completions` | OpenAI-compatible chat API |
| HTTP POST | `/v1/responses` | Custom OpenResponses API |
| HTTP GET | `/ping` | Health check |
| TLS | configurable | Custom certs, strict transport security |

### Request Flow

```
WebSocket Message → Auth Check → Rate Limit → Message Parser
  → Route Resolution → Method Handler (40+ handlers in server-methods/)
    → Agent Execution → Outbound Serialization → Channel Adapter → Delivery
```

### Key Types

```typescript
type GatewayServer = {
  close: (opts?: { reason?: string; restartExpectedMs?: number | null }) => Promise<void>;
};

type GatewayServerOptions = {
  bind?: "loopback" | "lan" | "tailnet" | "auto";
  controlUiEnabled?: boolean;
  openAiChatCompletionsEnabled?: boolean;
  openResponsesEnabled?: boolean;
  auth?: GatewayAuthConfig;
};
```

---

## 4. Routing System

**Key files**: `src/routing/resolve-route.ts` (837 lines), `src/routing/session-key.ts`

### Multi-Tier Binding Match (8 priority levels)

1. **binding.peer** — Exact DM/group match
2. **binding.peer.parent** — Thread parent inheritance
3. **binding.peer.wildcard** — Wildcard kind matching (`discord:*`)
4. **binding.guild+roles** — Discord server + member roles
5. **binding.guild** — Server-wide default
6. **binding.team** — Workspace-wide default
7. **binding.account** — Account-scoped default
8. **default** — Channel-wide fallback

### Session Key Derivation

```
agentId:channel:accountId:peerKind:peerId:dmScope
→ "claude:discord:default:direct:user123:per-peer"
```

DM scope options: `main | per-peer | per-channel-peer | per-account-channel-peer`

### Caching

- WeakMap keyed on config object (prevents leaks)
- LRU eviction at 4,000 entries
- Cache key: `channel\taccount\tpeer\tguildId\tteamId\troleIds\tdmScope`
- Rebuilt on config changes

### Lesson: Multi-dimensional session keying
This is a powerful pattern — sessions are scoped by agent + channel + account + peer + DM scope simultaneously, enabling thread isolation, DM collapsing, and cross-platform consistency.

---

## 5. Channel System

**Key files**: `src/channels/plugins/types.ts`, `src/channels/plugins/bundled.ts`
**Stats**: ~127 plugin files

### Supported Channels

WhatsApp, Telegram, Slack, Discord, Google Chat, iMessage, SMS/Signal, Web Chat, IRC

### Channel Abstraction

Each channel is a plugin implementing capability adapters:

```typescript
type ChannelCapabilities = {
  messaging?: ChannelMessagingAdapter;     // Inbound message parsing
  outbound?: ChannelOutboundAdapter;       // Outbound serialization
  security?: ChannelSecurityAdapter;       // Rate limiting, gating
  commands?: ChannelCommandAdapter;        // Platform-specific commands
  pairing?: ChannelPairingAdapter;         // Account linking
  setup?: ChannelSetupAdapter;             // Auth & initialization
  // ... 20+ adapter types
};
```

### Message Capabilities

Channels declare supported features: text, rich text, markdown, attachments, reactions, threads, forwarding, edits, deletions, interactive elements (buttons, select menus, forms).

### Channel Lifecycle

Bootstrap → Configure (bindings applied) → Startup (channel manager) → Running (transport loop) → Graceful Stop (timeout + backoff)

### Lesson: Adapter Pattern for Channel Polymorphism
The ~20 adapter types create a fine-grained capability model — a channel can support messaging but not reactions, or commands but not threads. This is better than a monolithic interface.

---

## 6. Agent System

**Key files**: `src/agents/agent-scope.ts`, `src/agents/agent-command.ts`, `src/agents/acp-spawn.ts`

### Agent Configuration

Scope-based hierarchical config: Agent-level → Global defaults

```typescript
type ResolvedAgentConfig = {
  model?: string;
  embeddedPi?: { executionContract?: string };
  skills?: string[];
};
```

Each agent gets:
- Isolated workspace directory
- Configurable model (with fallback chains)
- Skill filter
- Execution contract

### Agent Execution Flow

1. `resolveAgentConfig(cfg, agentId)` — Load per-agent config
2. Resolve effective model (explicit → agent-level → default → fallbacks)
3. Build skill filter via `resolveAgentSkillsFilter`
4. Execute via `agentCommand(opts)` — the main orchestration function
5. Persist session state

### Subagent Orchestration

```typescript
type SpawnAcpParams = {
  task: string;
  agentId?: string;
  mode?: "run" | "session";       // One-shot or persistent
  sandbox?: "inherit" | "require";
  streamTo?: "parent";            // Stream output back
};
```

Coordination patterns:
- **Sequential**: Parent waits for subagent result
- **Parallel**: Multiple subagents spawned concurrently
- **Hierarchical**: Subagents can spawn children (depth tracked)

Session binding tracks `spawnedBy`, `spawnDepth`, `subagentRole` (orchestrator/leaf).

### Lesson: Hierarchical Agent Spawning
The ability for agents to spawn subagents with inherited or sandboxed contexts, with output streaming back to parents, is a key pattern for complex workflows.

---

## 7. LLM Integration

**Key files**: `src/agents/anthropic-transport-stream.ts`, `src/agents/model-catalog.ts`, `src/agents/model-selection.ts`

### Supported Providers

| Provider | Integration |
|----------|-------------|
| Anthropic | Direct SDK + streaming |
| Vertex AI | Anthropic via Google Cloud |
| Amazon Bedrock | Conditional cache support |
| OpenRouter | Multi-model proxy |
| OpenAI | Via provider plugins |
| Custom | Configurable API endpoints |

### Model Management

```typescript
type ModelRef = { provider: string; model: string; };
type ModelCatalogEntry = {
  id: string; name?: string; provider: string;
  contextWindow?: number; reasoning?: boolean;
  input?: ModelInputType[];
};
```

### Thinking Support

```typescript
type ThinkLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "adaptive";
// Maps to Anthropic "effort" parameter
```

### Cache Handling

- Anthropic direct: 5-minute TTL cache
- Bedrock: Conditional cache by model capability
- Custom: `isAnthropicFamilyCacheTtlEligible` check

### Lesson: Multi-Provider Abstraction with Fallbacks
The `ModelRef` + catalog + fallback chains pattern means the system degrades gracefully when a provider is down, and new providers can be added without changing core logic.

---

## 8. Tool System

**Key files**: `src/agents/tools/common.ts`, `src/agents/tools/*.ts` (50+ tools), `src/agents/bash-tools.exec.ts`

### Tool Categories

| Category | Examples | Purpose |
|----------|----------|---------|
| Code | bash, nodes, video-generate | Execution & generation |
| Data | web-fetch, web-search, pdf | Information retrieval |
| Session | sessions-send, sessions-spawn | Multi-agent coordination |
| Media | image-generate, music-generate, canvas | Content creation |
| Control | cron, gateway, message | Scheduling & messaging |

### Tool Definition

```typescript
type AgentTool<TParameters, TResult> = {
  name: string;
  description: string;
  parameters: TParameters;       // TypeBox schema
  execute(params): Promise<TResult>;
  ownerOnly?: boolean;
  displaySummary?: string;
};
```

### Execution Safety

- Parameter validation via TypeBox schemas
- `ownerOnly` authorization check
- Windows cmd.exe injection protection (`escapeForCmdExe`)
- npm/npx CVE-2024-27980 mitigation (resolve to node.exe + cli.js)

---

## 9. Memory & Session System

**Key files**: `src/memory-host-sdk/dreaming.ts`, `src/config/sessions/`, `src/sessions/`

### Session Storage

- **Format**: JSONL (one JSON object per line)
- **Organization**: agent → session → transcript file
- **Session key**: Multi-dimensional (agent:channel:account:peer:dmScope)
- **Update modes**: `"inline" | "file-only" | "none"`

### Memory Dreaming (Consolidation)

Three phases inspired by sleep neuroscience:

| Phase | Frequency | Depth | Purpose |
|-------|-----------|-------|---------|
| **Light** | Every 6 hours | 100 messages, 0.9 dedup | Recent context consolidation |
| **Deep** | Daily (3 AM) | 10 messages, recovery mode | Long-term pattern extraction |
| **REM** | Weekly | 10 patterns, 0.75 min strength | Cross-session pattern synthesis |

```typescript
type MemoryDreamingConfig = {
  enabled: boolean;
  frequency: string;    // Cron expression
  phases: {
    light: { sources: ["daily", "sessions", "recall"] };
    deep: { sources: ["daily", "memory", "sessions", "logs", "recall"] };
    rem: { sources: ["memory", "daily", "deep"] };
  };
};
```

### Lesson: Biological Memory Model
The light/deep/REM dreaming model is a clever approach — it mirrors how biological memory consolidation works, with different phases for different timescales and abstraction levels.

---

## 10. Plugin & Hook System

**Key files**: `src/plugin-sdk/`, `src/plugins/hook-types.ts`, `src/plugins/runtime/`

### 24 Lifecycle Hooks

```
Model/Prompt:    before_model_resolve, before_prompt_build, before_agent_start
Execution:       llm_input, llm_output, before_tool_call, after_tool_call, tool_result_persist
Message:         message_received, message_sending, message_sent
Session:         session_start, session_end
Subagent:        subagent_spawning, subagent_delivery_target, subagent_spawned
Special:         reply_dispatch, inbound_claim
```

### Plugin Sources

Bundled, npm packages, git repositories — all loaded via dynamic import with jiti loader.

### Plugin Runtime

Plugins receive a `PluginRuntime` with access to subagent spawning, channel operations, logger, gateway, model auth, media generation, etc.

### Lesson: Hook-Based Extensibility
24 hooks at every lifecycle point means plugins can modify almost any behavior without forking the core. This is the backbone of the system's extensibility.

---

## 11. Cron & Scheduling

**Key files**: `src/cron/service.ts`, `src/cron/schedule.ts`, `src/cron/types.ts`, `src/cron/isolated-agent/`

### Schedule Types

- `"at"` — Absolute time (one-shot)
- `"every"` — Interval-based
- `"cron"` — Cron expressions (via croner library, 512 expression cache)

### Delivery Modes

- `announce` — Send to messaging channel
- `webhook` — HTTP POST

### Isolated Execution

Jobs run in isolated sessions with:
- Model overrides per job
- Tool allowlists
- Thinking level control
- Session reaper for idle job sessions

### Job State Tracking

```typescript
type CronJob = {
  id: string;
  schedule: Schedule;
  payload: SystemEvent | AgentTurn;
  delivery: { mode: "announce" | "webhook"; target: string };
  nextRunAtMs: number;
  lastRunStatus: string;
  consecutiveErrors: number;
  failureAlert: { enabled: boolean; cooldownMs: number };
};
```

---

## 12. MCP Integration

**Key files**: `src/mcp/channel-bridge.ts`, `src/mcp/channel-server.ts`, `src/mcp/channel-tools.ts`

### Architecture

```typescript
class OpenClawChannelBridge {
  private server: McpServer;
  private queue: QueueEvent[];         // Up to 1,000 events
  private pendingApprovals: Map<string, PendingApproval>;
}
```

- Bidirectional: both inbound (tool→agent) and outbound (agent→tool)
- Queue-based async with timeout support
- Built-in approval workflows

---

## 13. Process Management & Daemon

**Key files**: `src/process/supervisor/`, `src/daemon/service.ts`

### Process Supervisor

Two spawn modes: `"child"` (native child_process) and `"pty"` (pseudo-terminal for interactive processes)

Features: scope-based cancellation, activity-based timeouts (`noOutputTimeoutMs`), PID tracking.

### Cross-Platform Daemon

| Platform | Implementation |
|----------|---------------|
| macOS | launchd plist files |
| Windows | schtasks (Task Scheduler) |
| Linux | systemd units with linger |

---

## 14. Security

**Key files**: `src/security/audit-*.ts`, `src/security/external-content.ts`, `src/security/approval-gateway-resolver.ts`

### Security Layers

1. **Config Auditing** — Flags elevated tool allowlists, wildcard permissions
2. **Channel Security** — Per-channel audit (Discord commands, Slack attack surface, Telegram bots)
3. **Execution Safety** — Safe binary whitelist, sandbox boundary checks, deep code inspection
4. **External Content Provenance** — Immutable tracking prevents untrusted injection
5. **Approval System** — Two-stage: exec approval → plugin approval (with fallback)

---

## 15. Configuration

**Key files**: `src/config/types.openclaw.ts`, `src/config/config.ts`, `src/config/validation.ts`
**Stats**: 110+ files

### Config Type (20+ sections)

```typescript
type OpenClawConfig = {
  auth?, agents?, bindings?, channels?, models?, plugins?,
  gateway?, session?, wizard?, commands?, skills?, ...
};
```

### Loading Flow

1. **Resolution** — Search paths (`~/.openclaw`, `$CWD`, env), parse YAML with env var substitution
2. **Validation** — 20+ Zod schemas, runtime coercion, detailed error hints
3. **Materialization** — Computed properties, defaults, config composition via includes
4. **Snapshots** — Redacted snapshots for logging (secrets filtered)

### Minimal Global State

Only two globals: `verbose` and `yes` flags. Everything else is config-driven or request-scoped.

---

## 16. Key Design Patterns Summary

| Pattern | Where Used | Why It Matters |
|---------|-----------|----------------|
| **Lazy Loading** | CLI, plugins, model catalog | Fast startup, minimal memory |
| **Plugin Runtime** | Channels, MCP, memory, skills | Uniform extensibility model |
| **Request Context Threading** | Gateway requests | Per-request isolation without globals |
| **Channel Manager Isolation** | Per-channel abort controllers | Fault isolation between channels |
| **Hierarchical Config** | Agent → Global defaults | Override inheritance without duplication |
| **Multi-Tier Binding Match** | Routing (8 levels) | Flexible message-to-agent mapping |
| **Session Key Scoping** | 5-dimensional keys | Thread safety + DM collapsing + isolation |
| **Hook Injection** | 24 lifecycle hooks | Plugin customization without forking |
| **Queue-Based Async** | MCP events (1K buffer) | Decoupled async coordination |
| **State Machine** | Process supervisor | Explicit lifecycle transitions |
| **Adapter Pattern** | 20+ channel adapters | Fine-grained capability model |
| **Factory/Builder** | buildProgram, createPluginRuntime | Composable construction |
| **Event Subscription** | Gateway runtime | Decoupled subsystem communication |

---

## 17. Lessons for Phase 2 & 3

### What Makes This System Work

1. **Everything is a plugin** — Channels, tools, providers, even memory strategies are pluggable. This means the core stays small while capabilities grow.

2. **Multi-dimensional session keys** — The `agent:channel:account:peer:dmScope` pattern is elegant and solves thread isolation, DM collapsing, and multi-agent conversations simultaneously.

3. **Gateway as central orchestrator** — All messages flow through the gateway, which handles auth, routing, rate limiting, and dispatch. This creates a single point of control.

4. **Biological memory model** — Light/deep/REM dreaming is not just clever naming; it maps to real needs (recent context, long-term patterns, cross-session synthesis).

5. **Security by default** — Approval workflows, safe binary whitelists, injection protection, and external content provenance tracking are built into the core, not bolted on.

### Areas to Research Further (Phase 2)

- **Agent orchestration patterns** — How do modern frameworks (LangGraph, CrewAI, AutoGen) compare to OpenClaw's hierarchical spawning model?
- **Memory systems** — How do vector-based RAG systems compare to OpenClaw's dreaming consolidation?
- **Tool execution sandboxing** — What are the state-of-the-art approaches beyond safe binary whitelists?
- **Multi-agent coordination** — OpenClaw supports sequential/parallel/hierarchical; what about more complex DAG-based workflows?
- **Evaluation & observability** — How to measure agent quality beyond simple pass/fail?

### What to Consider Building (Phase 3 direction)

Based on this analysis, interesting project directions could be:
- A **lightweight agent orchestration framework** focused on multi-agent DAG workflows with memory
- A **tool execution sandbox** with fine-grained capability control
- An **agent evaluation system** for measuring and improving agent quality
- A **memory consolidation engine** inspired by OpenClaw's dreaming model

These will be refined after Phase 2 research.

---

## Appendix: File Reference

| Component | Key Entry File | LOC (est.) |
|-----------|---------------|------------|
| Entry/CLI | `src/entry.ts` | 80 |
| Gateway | `src/gateway/server.impl.ts` | 350+ |
| Routing | `src/routing/resolve-route.ts` | 837 |
| Channels | `src/channels/plugins/types.ts` | 19,935 |
| Agents | `src/agents/agent-command.ts` | 10,000+ |
| Chat/LLM | `src/agents/anthropic-transport-stream.ts` | — |
| Memory | `src/memory-host-sdk/dreaming.ts` | — |
| MCP | `src/mcp/channel-bridge.ts` | — |
| Plugins | `src/plugins/hook-types.ts` | 8,000+ |
| Cron | `src/cron/service.ts` | — |
| Process | `src/process/supervisor/types.ts` | — |
| Security | `src/security/audit-*.ts` | — |
| Config | `src/config/types.openclaw.ts` | 8,000+ |
| **Total** | **6,477 TS files** | **~80,000+** |
