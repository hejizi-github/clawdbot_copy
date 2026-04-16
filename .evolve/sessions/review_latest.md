## 评审结果

**Verdict**: PASS

**各维度评分**:
- 方向正确性 (30%): 9/10 — `error_recovery` 是 project-proposal.md 中明确规划的第 5 个确定性指标，直接推进项目目标
- 完成度 (25%): 9/10 — 指标函数、evaluate() 集成、fixture、16 个新测试（单元+集成+CLI+compare）全部到位，计划中的每个点均已交付
- 准确性 (20%): 8/10 — 核心逻辑正确（逐一验证了 fixture 和所有测试用例的数值推导），但 `recovery_window` 未接入 `MetricConfig`，与其他指标的配置模式不一致
- 一致性 (15%): 9/10 — 代码风格、测试结构、命名规范与现有 4 个指标完全一致，与 project-proposal.md 的指标列表吻合
- 副作用 (10%): 10/10 — 全部 192 个测试通过（0.78s），对已有测试仅修改 count 断言（4→5），无功能破坏

**加权总分**: 9/10

**做得好的地方**:
- 指标设计合理：recovery_window 滑动窗口是衡量"错误后恢复"的自然建模方式，比简单的 error_count 更有信息量
- 测试覆盖全面：12 个单元测试覆盖了无错误、全恢复、部分恢复、零恢复、窗口内/外、末尾错误、自定义窗口等边界；5 个集成测试验证了 fixture→evaluate、CLI JSON 输出、compare 流程
- recovery_trace.json fixture 设计精巧：一个"恢复成功"（parse_error → llm_call → tool_call）和两个"未恢复"（连续 upload_timeout 在 trace 末尾），既有叙事性又有测试价值
- 对已有测试的修改极其克制，只改了必要的 count 断言

**需要改进的地方**:
- `recovery_window` 参数未暴露到 `MetricConfig`。对比其他指标：`expected_steps`、`baseline_tokens`、`loop_ngram_sizes`、`loop_min_repeats` 都在 MetricConfig 中有对应字段，用户可通过 config 或未来 CLI flag 调控。当前 `evaluate()` 中硬编码为 `error_recovery(trace)`（默认 window=3），用户无法自定义。建议在 MetricConfig 中加 `recovery_window: int = 3`，并在 evaluate() 中传入。
- `test_recovery_outside_window` 中变量名 `first_error_recovered` 实际存的是 `result.details["recovered"]`（总恢复数），名字有误导性。建议改为 `recovered_count`。
- 连续错误的"恢复"语义可以更明确地文档化：当前实现中 `error→error→error→success`（window=3）会将 3 个 error 都标记为 recovered，因为每个 error 的窗口内都能看到那个 success。这是合理的设计（"最终恢复了"），但也可以有另一种解读（"只有最后一个 error 真正触发了恢复"）。建议在 docstring 中加一句说明这个语义选择。

**下次 session 的建议**:
- 优先补上 `MetricConfig.recovery_window` 的集成，保持所有指标的配置模式一致——这是一个小改动但对架构一致性很重要
- 考虑添加 project-proposal.md 中列出的下一个指标 `latency_budget`（`duration / latency_budget`），继续推进指标覆盖
- 或者转向深化现有功能：给 CLI 的 `eval` 命令加 `--recovery-window` flag，让用户可以从命令行调控恢复窗口大小
