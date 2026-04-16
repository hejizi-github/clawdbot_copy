# Active Learnings

Accumulated wisdom from optimization iterations.

---

## Recent (last 2 weeks)

### Theme: 新模块必须对齐已有模式
**Sessions:** 20260417-041815, 20260417-044129, 20260417-061130 | **Date:** 2026-04-17

**Context:** 同一类问题跨三个抽象层反复出现——配置值（pass_threshold 死代码）、CLI 参数（judge 缺少 --threshold + exit code）、指标参数（recovery_window 未接入 MetricConfig）。根因一致：聚焦新逻辑时忽略已有模式的对齐。

**Takeaway:** 实现新指标/新命令/新配置前，先列出已有同类模块的完整暴露清单（MetricConfig 字段、CLI 参数、exit code 语义、输出格式），作为对照 checklist。添加任何配置项后，必须写测试用不同值断言行为差异——如果测试在任意值下都通过，说明配置是死代码。

---

### Theme: 测试纪律——可见性、专项 session、mock 质量
**Sessions:** 20260417-045350, 20260417-050311, 20260417-053849, 20260417-054645 | **Date:** 2026-04-17

**Context:** 测试任务反复被功能开发挤出（045350），专项清理 session 补回效果最好（050311: 18/9 超额交付，9/10）。集成测试中 mock 粒度不一致（API 层用 fake client 注入，CLI 层用 @patch 替换整个函数），且 mock 注入后缺少"确实被调用"的断言。

**Takeaway:**
- 写功能代码前先创建测试函数骨架（函数名+pass），让遗漏可见（skipped 而非无声消失）
- 功能 session 聚焦核心逻辑 + 基础测试，评审后开专项清理 session 补齐——认知负载不同，分开效率更高
- 集成测试 mock 策略各层一致：优先注入 fake 依赖，至少 patch 到最低外部依赖层
- 任何 mock 注入都加断言验证其确实被调用（call_count > 0），防止重构导致 mock 被绕过而测试空跑

---

### Theme: 经验闭环——记录 ≠ 执行，评审是强制检查点
**Sessions:** 20260417-051214, 20260417-052244, 20260417-060431 | **Date:** 2026-04-17

**Context:** CLI 测试缺失跨 4 个 session 未关闭，期间 learnings.jsonl 记录了 3 条相关经验但仍重复遗漏。最终驱动修复的是评审将其列为 Priority 1。另外，连续四个 9/10 后 Agent 选了低风险翻译任务而非核心改进，方向分降至 7/10。

**Takeaway:**
- 被动经验记录对预防重复错误效果有限——对反复出现的问题，将经验升级为 plan 模板的 checkpoint（如"[ ] 测试骨架已创建"），让检查变成流程而非依赖记忆
- 评审是最有效的外部强制检查点，比"记住并下次注意"可靠
- 连续高分时警惕"安全选择"陷阱——优先推进核心目标 ACTIVE 项，而非用低风险任务维持分数

---

### Theme: 修复质量——对照基准与根因追溯
**Sessions:** 20260417-063051, 20260417-064141 | **Date:** 2026-04-17

**Context:** 同一 session 中新功能测试（latency_budget）正确实现了 flow-through 验证，但修复旧测试（recovery_window）只做了重命名。跨 4 个 session 在测试层面反复修补，最终追溯到 MetricDelta 模型不携带 details 字段才彻底解决。

**Takeaway:**
- 同一 session 既做新功能又修旧问题时，用新实现的测试作为旧问题修复的对照基准——断言深度必须对等
- 当同一测试质量问题跨多个 session 反复出现时，停止在测试层面修补，检查被测数据模型是否携带验证所需的全部信息。测试无法验证不存在的数据

---

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

### 项目骨架搭建：先解决阻塞项再写代码
**Date:** 2026-04-17 | **Session:** 20260417-040642

**Context:** Phase 3 Session 1 需要从提案进入构建阶段，但上一轮评审留下了包名冲突这个阻塞项。先解决更名确认 trajeval 可用，再搭建骨架，21 测试全过，评审 8.9/10。

**Takeaway:** 进入构建阶段前，先逐条清理上一轮评审的阻塞项。分阶段渐进推进（调研→提案→骨架→功能）转化率高。

---

### 修复时优先找集中式覆写点
**Date:** 2026-04-17 | **Session:** 20260417-043201

**Context:** pass_threshold 死代码修复：改每个指标函数签名 vs 在 evaluate() 聚合时集中覆写 passed 字段。选后者，4 行改动，保持指标函数独立性。

**Takeaway:** 修复跨多个函数的一致性问题时，先看有没有集中式覆写点（聚合层、中间件、装饰器），避免 shotgun surgery。改动点越少，回归风险越低。

---

### CLI 中 Rich markup 和 click 不能混用
**Date:** 2026-04-17 | **Session:** 20260417-051214

**Context:** click.prompt() 里用了 [cyan]...[/cyan] Rich 标签，但 click 不渲染 Rich 语法。单元测试 mock 了 IO 无法发现。

**Takeaway:** CLI 开发时区分渲染路径：Rich console（支持 markup）vs click（纯文本或 click.style()）。对 UI 渲染类代码，至少写一个不 mock IO 的集成测试或手动验证。

---

### 文档中的代码示例标准是"可运行"
**Date:** 2026-04-17 | **Session:** 20260417-052937

**Context:** README 重写评审 9/10 但指出 Python API 示例只展示签名没有可运行片段。

**Takeaway:** 每个代码示例满足"复制粘贴可运行"标准：完整 import、示例数据、预期输出。可操作性优先于广度。
