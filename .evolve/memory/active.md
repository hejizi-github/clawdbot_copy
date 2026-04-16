# Active Learnings

Accumulated wisdom from optimization iterations.

---

## Recent (last 2 weeks)

### 调研报告的准确性验证不能省
**Date:** 2026-04-17 | **Session:** 20260417-032714

**Context:** Phase 2 调研报告评审发现 4 处事实错误（日期、数据来源、列表完整性、术语一致性），都是写作时追求广度而跳过细节验证导致的。

**Takeaway:** 调研报告写完后，必须对所有日期、数字、列表做逐条二次验证；引用第三方自报数据时默认标注 self-reported。

---

### 项目命名要在提案阶段就验证可用性
**Date:** 2026-04-17 | **Session:** 20260417-034008

**Context:** AgentLens 提案评审发现包名在 PyPI 已被占用(v0.1.44)，如果到构建阶段才发现会浪费更多时间。

**Takeaway:** 项目提案阶段确定名称后，立即检查 PyPI/npm/crates.io 等包注册表的名称可用性，将其作为提案 checklist 的标准项。

---

### 项目骨架搭建的高效模式：先解决阻塞项再写代码
**Date:** 2026-04-17 | **Session:** 20260417-040642

**Context:** Phase 3 Session 1 需要从提案进入构建阶段，但上一轮评审留下了包名冲突这个阻塞项。Session 先解决更名问题确认 trajeval 可用，再按计划搭建骨架，21 测试全过，评审 8.9/10。

**Takeaway:** 进入构建阶段前，先逐条清理上一轮评审的阻塞项（blocking issues），再开始写代码。这样避免写到一半发现前提假设不成立而返工。提案到代码的转化率高，说明分阶段（调研→提案→骨架→功能）的渐进式推进是有效的。

---

### 配置接口需要闭环测试验证其实际生效
**Date:** 2026-04-17 | **Session:** 20260417-041815

**Context:** metrics engine 暴露了 MetricConfig.pass_threshold 和 --threshold CLI 参数，但所有指标内部硬编码了 >= 0.7，配置是死代码。评审才发现。

**Takeaway:** 添加任何配置项/参数后，必须写一个测试用不同配置值断言行为差异（如 threshold=0.5 vs 0.9 应产生不同 passed 结果）。如果测试在任意配置值下都通过，说明配置没有被实际使用。

---

### 修复时优先找集中式覆写点而非逐处改签名
**Date:** 2026-04-17 | **Session:** 20260417-043201

**Context:** pass_threshold 死代码修复有两种方案：改每个指标函数的签名让它们接受 threshold 参数，或在 evaluate() 聚合时集中覆写 passed 字段。选了后者，改动面最小（4 行），保持了指标函数的独立性。

**Takeaway:** 修复跨多个函数的一致性问题时，先看有没有集中式覆写点（如聚合层、中间件、装饰器），避免 shotgun surgery。改动点越少，回归风险越低。

---

### 新 subcommand 要对照已有命令的 CI 集成模式
**Date:** 2026-04-17 | **Session:** 20260417-044129

**Context:** judge 命令实现时没有复制 eval 命令已有的 --threshold + exit code CI 门禁模式，导致 judge 在 CI 中永远 exit 0 无法做质量门。

**Takeaway:** 实现同一 CLI 的新 subcommand 前，先列出已有命令的接口清单（参数、exit code 语义、输出格式），作为新命令的对照 checklist，确保 CI 集成能力对称。
