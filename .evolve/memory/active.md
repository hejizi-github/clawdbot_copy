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

---

### 计划中的测试任务要先写骨架防止被挤出
**Date:** 2026-04-17 | **Session:** 20260417-045350

**Context:** Session 4 计划明确列出 'Test CLI exit codes' 但最终没有交付——功能实现消耗了全部 round 数，CLI 集成测试作为最后一步被无声丢弃。

**Takeaway:** 对计划中列出的测试任务，在写功能代码前先创建测试函数骨架（函数名+pass body），这样即使时间不够，遗漏也是可见的（skipped tests 而非无声消失）。功能代码总是挤占测试时间，因为功能"看得见"而测试"看不见"——先写骨架让测试也"看得见"。

---

### 债务清理专项 session 的 ROI 高于在功能 session 中挤时间补测试
**Date:** 2026-04-17 | **Session:** 20260417-050311

**Context:** Session 045350 在功能开发中试图同时完成 CLI 集成测试但时间不够被无声丢弃（8/10）。Session 050311 作为专项清理 session 补回，不仅完成了全部计划项，还超额交付（18 个 vs 计划 9 个），评审 9/10 且 plan-execution 对齐度最高。

**Takeaway:** 功能实现和测试补全的认知负载不同，混在一个 session 中容易互相挤占。更好的模式是：功能 session 聚焦核心逻辑 + 基础测试，评审后开一个专项清理 session 补齐测试和一致性问题。专项 session 目标明确、范围收敛，容易获得高分和高对齐度。

---

### CLI 中 Rich markup 和 click 的渲染路径不同，不能混用
**Date:** 2026-04-17 | **Session:** 20260417-051214

**Context:** cli.py 中 click.prompt() 里使用了 [cyan]...[/cyan] Rich 标签，但 click 不渲染 Rich 语法，用户看到原始标签文本。单元测试 mock 了 IO 所以无法发现。

**Takeaway:** CLI 开发时区分两条渲染路径：Rich console（支持 markup）和 click（纯文本或 click.style()）。写 prompt/echo 时确认当前走哪条路径。对 UI 渲染类代码，至少写一个不 mock IO 的集成测试或手动验证。

---

### 评审是经验落地的最有效强制检查点
**Date:** 2026-04-17 | **Session:** 20260417-052244

**Context:** CLI 测试缺失问题从 Session 045350 持续到 052244，跨越 4 个 session。期间 learnings.jsonl 记录了 3 条相关经验，但 agent 仍在 051214 重复了同样的遗漏。最终驱动修复的不是经验回顾，而是评审将其列为 Priority 1 修复项。

**Takeaway:** 被动经验记录（learnings.jsonl）对预防重复错误的效果有限，因为 agent 不会主动查阅。评审充当了外部强制检查点，将未执行的经验转化为具体的修复任务。对于反复出现的问题，最有效的闭环不是"记住并下次注意"，而是让评审机制持续追踪直到关闭。

---

### 文档中的代码示例标准是"可运行"而非"展示接口"
**Date:** 2026-04-17 | **Session:** 20260417-052937

**Context:** README 重写覆盖了 5 个 CLI 命令和 Python API，评审 9/10 但指出 Python API 示例只展示签名没有可运行片段。与 Session 034008 的代码示例不一致问题同源——写文档时倾向于覆盖广度而忽略可操作性。

**Takeaway:** README/文档中的每个代码示例应满足"复制粘贴可运行"标准：包含完整 import、示例数据、预期输出。写完后在干净环境执行一遍验证。广度和可操作性不冲突，但如果要取舍，可操作性优先。
