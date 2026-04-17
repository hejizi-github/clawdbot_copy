## 评审结果

**Verdict**: PASS

**各维度评分**:
- 方向正确性 (30%): 9/10 — 修复 loop detection 双重计算和 `passed` fail-open 默认值都是核心指标的正确性问题，直接提升 trajeval 的评估可靠性
- 完成度 (25%): 9/10 — 两个修复均完整实现：n-gram 去重包含模式子序列检测 + 位置覆盖计算两层机制，`passed` auto-compute 逻辑与 CLI 一致；+7 测试覆盖了关键场景（子序列移除、独立保留、penalty 减少、单 n-gram、auto pass/fail/override）
- 准确性 (20%): 9/10 — 数学验证正确：`A B A B A B` 修复后 repeated_positions = {2,3,4,5}（4 个），score = 1 - 4/6 ≈ 0.333，合理反映冗余；`_is_subpattern` 同长度互不覆盖的边界处理正确；`passed=None` auto-compute 使用 `result.overall_score >= threshold` 与 CLI 行为一致
- 一致性 (15%): 9/10 — 与 project-proposal.md 中 loop detection "n-gram matching of repeated sequences" 的设计意图一致；与 frontier-tech-research.md 中 "step-level tracing is the solved half" 的评估哲学协调
- 副作用 (10%): 9/10 — 316 测试全绿，0 回归；`_positions` 字段通过 `pop()` 在输出前清理，不泄露到外部 API；fixture 测试断言从 `bigrams` 改为 `patterns` 是因 dedup 使原断言不再稳定的合理调整

**加权总分**: 9/10

**做得好的地方**:
- 问题分析精准：准确识别了 n-gram 交叉大小导致的双重计算根因，并用具体数值（12 repeated steps / 6 total → capped 0.9）量化了问题严重性
- 修复方案分层合理：先做模式去重（`_is_subpattern` 移除被长模式覆盖的短模式），再做位置覆盖（set union 消除位置级重复），两层互补
- `passed` 默认值修复体现了 API 设计意识：从 fail-open (`True`) 到 fail-closed (`None` → auto-compute)，且保持了 CLI 显式传参路径不受影响
- 测试设计覆盖了关键对立面：subsumed vs independent bigrams, auto-compute pass vs fail vs explicit override

**需要改进的地方**:
- `_is_subpattern` 的 docstring 写 "repeated" 有歧义，实际只检查单次连续子序列包含关系，建议改为 "Check if short is a contiguous subsequence of long"
- 位置计算中 `positions[1:]` 跳过首次出现是正确的（首次不算浪费），但缺少注释解释这个 "为什么"，新读者可能会疑惑为什么不是 `positions[:]`
- 可以考虑增加一个边界测试：当所有 n-gram 大小的 pattern 互相独立时（没有任何子序列关系），确认 penalty 是所有位置的正确并集而非简单累加

**下次 session 的建议**:
- 当前 loop detection 的 dedup 只处理"短模式是长模式的连续子序列"的情况。如果一个 2-gram `(A,B)` 反复出现但不被任何 3-gram 包含，它仍然可能和 3-gram 覆盖相同的位置——位置覆盖计算已经处理了这种情况，但可以加一个测试明确验证
- 考虑为 `_deduplicate_loops` 和位置覆盖逻辑添加 property-based testing（hypothesis），用随机 trace 验证 `total_repeated_steps <= len(names)` 恒成立
- 如果 Phase 3 继续优化指标，可以考虑 loop detection 的下一步：检测"近似循环"（如 `A B C` → `A B D` → `A B C`，中间有微小变异的循环模式）
