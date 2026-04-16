# trajeval

框架无关的 Agent 执行轨迹评估工具。从任意 Agent 框架导入执行轨迹，通过确定性指标 + LLM 裁判打分，输出 CI 可用的质量报告。

## 功能特性

- **确定性指标** — 步骤效率、工具准确率、循环检测、Token 效率、错误恢复、延迟预算
- **LLM 裁判** — 基于评分维度的 LLM-as-judge 评估（使用 Claude 模型）
- **回归检测** — 对比两条轨迹，标记指标退步
- **人工校准** — 人工标注轨迹后，计算与 LLM 裁判打分的相关性
- **CI 集成** — 通过/失败用 exit code 表示（0=通过，1=失败），支持 JSON 输出

## 安装

```bash
# 基础版（确定性指标 + CLI）
pip install trajeval

# 带 LLM 裁判（需要 ANTHROPIC_API_KEY）
pip install trajeval[judge]

# 带校准统计功能（scipy）
pip install trajeval[stats]

# 全部安装
pip install trajeval[all]
```

开发环境：

```bash
git clone <repo-url> && cd trajeval
pip install -e ".[dev]"
```

## 快速上手

**1. 创建轨迹文件** (`trace.json`)：

```json
{
  "trace_id": "demo-001",
  "agent_name": "my-agent",
  "task": "查询法国的首都",
  "steps": [
    {
      "type": "llm_call",
      "name": "claude-sonnet-4-6",
      "input": {"prompt": "法国的首都是什么？"},
      "output": {"text": "法国的首都是巴黎。"},
      "duration_ms": 450,
      "tokens": {"prompt": 12, "completion": 8, "total": 20}
    },
    {
      "type": "tool_call",
      "name": "verify_answer",
      "input": {"answer": "巴黎"},
      "output": {"verified": true},
      "duration_ms": 50
    }
  ],
  "final_output": "法国的首都是巴黎。"
}
```

**2. 运行评估：**

```bash
trajeval eval trace.json
```

输出示例：
```
┌─────────────────────────┐
│ Trace: demo-001         │
├─────────┬───────────────┤
│ Agent   │ my-agent      │
│ Task    │ 查询法国的首… │
│ Steps   │ 2             │
└─────────┴───────────────┘

┌───────────────────┬───────┬────────┐
│ Metric            │ Score │ Status │
├───────────────────┼───────┼────────┤
│ step_efficiency   │  1.00 │ PASS   │
│ tool_accuracy     │  1.00 │ PASS   │
│ loop_detection    │  1.00 │ PASS   │
│ token_efficiency  │  1.00 │ PASS   │
│ error_recovery    │  1.00 │ PASS   │
│ latency_budget    │  1.00 │ PASS   │
├───────────────────┼───────┼────────┤
│ Overall           │  1.00 │ PASS   │
└───────────────────┴───────┴────────┘
```

**3. 输出 JSON 用于 CI：**

```bash
trajeval eval trace.json --format json
echo $?  # 0 = 通过, 1 = 失败
```

## 轨迹格式

trajeval 使用简洁的 JSON 格式。除 `steps` 外所有字段均为可选：

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

| 字段 | 必填 | 说明 |
|------|------|------|
| `trace_id` | 否 | 唯一标识符（缺省时自动生成 UUID） |
| `agent_name` | 否 | Agent 名称（默认 "unknown"） |
| `task` | 否 | Agent 要完成的任务描述 |
| `steps` | **是** | 有序的执行步骤列表 |
| `steps[].type` | 否 | 步骤类型：`llm_call`、`tool_call`、`decision`、`error` |
| `steps[].name` | 否 | 工具名、模型名或步骤标签 |
| `steps[].tokens` | 否 | 该步骤的 Token 用量 |
| `final_output` | 否 | Agent 的最终输出 |
| `total_duration_ms` | 否 | 总耗时（缺省时自动从各步骤累加） |
| `total_tokens` | 否 | Token 总用量（缺省时自动从各步骤累加） |

## CLI 命令参考

### `trajeval eval`

使用确定性指标评估轨迹。

```bash
trajeval eval trace.json
trajeval eval trace.json --format json
trajeval eval trace.json --threshold 0.8
trajeval eval trace.json --expected-steps 5 --baseline-tokens 1000
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--format` | `table` | 输出格式：`table` 或 `json` |
| `--threshold` | `0.7` | 通过/失败阈值（0.0-1.0） |
| `--expected-steps` | — | 期望步骤数基线（用于效率评分） |
| `--baseline-tokens` | — | Token 用量基线（用于效率评分） |
| `--recovery-window` | `3` | 错误后检查恢复的步骤窗口大小 |
| `--latency-budget` | — | 延迟预算（毫秒），用于速度评分 |

Exit code：所有指标通过返回 `0`，任一指标失败返回 `1`。

### `trajeval judge`

使用 LLM 裁判评估轨迹（需要 `pip install trajeval[judge]` 和 `ANTHROPIC_API_KEY`）。

```bash
trajeval judge trace.json
trajeval judge trace.json --model claude-sonnet-4-6
trajeval judge trace.json --dimensions task_completion,reasoning_quality
trajeval judge trace.json --format json --threshold 0.8
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--model` | `claude-sonnet-4-6` | 用于打分的 Anthropic 模型 |
| `--dimensions` | `task_completion,reasoning_quality` | 评估维度（逗号分隔） |
| `--format` | `table` | 输出格式：`table` 或 `json` |
| `--threshold` | `0.7` | 通过/失败阈值（0.0-1.0） |

内置维度：`task_completion`（任务完成度）、`reasoning_quality`（推理质量）。也可传入自定义维度名——裁判会使用通用评估 prompt。

Exit code：总分 >= 阈值返回 `0`，否则返回 `1`。

### `trajeval compare`

对比两条轨迹，检测指标回归。

```bash
trajeval compare baseline.json current.json
trajeval compare baseline.json current.json --tolerance 0.1
trajeval compare baseline.json current.json --format markdown
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--format` | `table` | 输出格式：`table`、`json` 或 `markdown` |
| `--tolerance` | `0.05` | 回归容忍度——分数下降超过此值会被标记 |
| `--threshold` | `0.7` | 指标通过/失败阈值 |
| `--expected-steps` | — | 期望步骤数基线 |
| `--baseline-tokens` | — | Token 用量基线 |
| `--recovery-window` | `3` | 错误后检查恢复的步骤窗口大小 |
| `--latency-budget` | — | 延迟预算（毫秒），用于速度评分 |

`markdown` 格式输出适合直接贴到 GitHub PR 评论中。

Exit code：无回归返回 `0`，存在回归返回 `1`。

### `trajeval annotate`

交互式人工标注轨迹（用于校准 LLM 裁判）。

```bash
trajeval annotate trace.json
trajeval annotate trace.json --output my-annotations.jsonl
trajeval annotate trace.json --dimensions task_completion,reasoning_quality --annotator alice
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--output` / `-o` | `annotations.jsonl` | 标注输出文件（JSONL 格式） |
| `--dimensions` | `task_completion,reasoning_quality` | 标注维度 |
| `--annotator` | `default` | 标注者标识 |

运行后会展示轨迹摘要，然后逐个维度提示输入 0-5 的整数评分。

### `trajeval calibrate`

计算人工标注与 LLM 裁判打分之间的 Spearman 秩相关系数。

```bash
trajeval calibrate annotations.jsonl judgments.jsonl
trajeval calibrate annotations.jsonl judgments.jsonl --format json
trajeval calibrate annotations.jsonl judgments.jsonl --threshold 0.8
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--format` | `table` | 输出格式：`table` 或 `json` |
| `--threshold` | 无 | Spearman ρ 最低通过阈值（0.0-1.0），低于此值 exit 1 |

需要 `pip install trajeval[stats]`（scipy）。每个维度至少需要 3 对配对数据，建议 10+ 对以获得可靠结果。

## 指标说明

### 确定性指标（`eval` 命令）

| 指标 | 衡量内容 | 计算方式 |
|------|----------|----------|
| **step_efficiency** | 有效步骤占总步骤的比例。如指定 `--expected-steps`，则计算实际 vs 期望。 | `min(expected/actual, 1.0)` 或 `productive/total` |
| **tool_accuracy** | 工具调用的成功率。紧跟 error 步骤或输出包含错误标志的工具调用视为失败。 | `successful/total` |
| **loop_detection** | 通过 n-gram 分析（bigram + trigram）检测重复步骤序列，惩罚重复模式。 | `1.0 - penalty`，penalty 与重复步骤数成正比 |
| **token_efficiency** | Token 使用效率。无 `--baseline-tokens` 时比较有效 Token vs 总量（error 步骤的 Token 算浪费）。 | `min(baseline/actual, 1.0)` 或 `productive/total` |
| **error_recovery** | 错误后恢复能力。对每个 error 步骤，检查后续 `--recovery-window` 步内是否有非 error 步骤。连续错误独立评估——每个 error 各自检查其窗口。 | `recovered/total_errors` |
| **latency_budget** | 是否在延迟预算内完成。无 `--latency-budget` 时默认通过。 | `min(budget/actual_duration, 1.0)` |

每个指标输出 0.0-1.0 的分数。分数 >= 阈值（默认 0.7）即为通过。

### LLM 裁判维度（`judge` 命令）

LLM 裁判对每个维度打 0-5 分：

| 维度 | 评估内容 |
|------|----------|
| **task_completion** | Agent 是否达成了目标？所有需求是否满足？结果是否可用？ |
| **reasoning_quality** | 中间决策是否合理？遇到障碍时是否调整策略？是否避免了不必要的弯路？ |

可传入自定义维度——裁判对未知维度使用通用评估 prompt。

## CI 集成

trajeval 专为 CI 流水线设计。所有产出通过/失败判定的命令都使用 exit code：

```bash
# 评估分数低于 80% 则构建失败
trajeval eval trace.json --threshold 0.8

# 指标出现回归则构建失败
trajeval compare baseline.json current.json --tolerance 0.05

# LLM 裁判分数低于 70% 则构建失败
trajeval judge trace.json --threshold 0.7

# 人工-LLM 相关性低于 0.8 则构建失败
trajeval calibrate annotations.jsonl judgments.jsonl --threshold 0.8
```

使用 `--format json` 程序化解析结果：

```bash
RESULT=$(trajeval eval trace.json --format json)
SCORE=$(echo "$RESULT" | python -c "import sys,json; print(json.load(sys.stdin)['overall_score'])")
```

## Python API

```python
from trajeval.ingester import ingest_json
from trajeval.metrics import MetricConfig, evaluate
from trajeval.scorer import JudgeConfig, judge

# 加载轨迹
trace = ingest_json("trace.json")
# 也可以从字典加载：
trace = ingest_json({"trace_id": "t1", "steps": [...]})

# 确定性评估
config = MetricConfig(pass_threshold=0.8, expected_steps=5)
report = evaluate(trace, config)
print(report.overall_score, report.passed)
for m in report.metrics:
    print(f"  {m.name}: {m.score:.2f} {'PASS' if m.passed else 'FAIL'}")

# LLM 裁判（需要 anthropic 包 + ANTHROPIC_API_KEY）
judge_config = JudgeConfig(
    model="claude-sonnet-4-6",
    dimensions=["task_completion", "reasoning_quality"],
)
result = judge(trace, config=judge_config)
if result.error:
    print(f"Error: {result.error}")
else:
    print(f"总分: {result.overall_score:.0%}")
    for d in result.dimensions:
        print(f"  {d.name}: {d.score}/5 — {d.explanation}")
```

## 许可证

MIT
