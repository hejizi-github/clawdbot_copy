# Active Learnings

Accumulated wisdom from optimization iterations.

---

## Recent (last 2 weeks)

### Theme: 新模块必须对齐已有模式——机械式全扫描，不靠人工判断
**Sessions:** 20260417-041815, 044129, 061130, 071417, 072246 | **Date:** 2026-04-17

**Context:** 同一类问题跨五个 session、三个抽象层反复出现——配置值（pass_threshold 死代码）、CLI 参数（judge 缺 --threshold + exit code）、指标参数（recovery_window 未接入 MetricConfig）、CLI 默认值（annotate 硬编码旧 2 维度）、输入校验（aggregation 用裸 str，--judges 允许 0 和负数）。根因一致：聚焦新逻辑时忽略已有模式的对齐，且"对照已有命令"时凭判断选择性对照，有盲区。

**Takeaway:**
- 实现新指标/命令/配置前，列出已有同类模块的完整暴露清单（MetricConfig 字段、CLI 参数、exit code、输出格式）作为对照 checklist
- 修改 CLI 参数默认值或新增常量时，用 grep 搜索参数名/旧默认值在整个 cli.py 中的所有出现位置——三次同类错误证明人工判断不可靠，机械式全扫描才能覆盖盲区
- 添加任何配置项后，写测试用不同值断言行为差异——任意值下都通过说明是死代码
- Pydantic 有限选项 str 字段用 Literal 类型，CLI 数值参数用 click.IntRange/FloatRange，作为 code review checklist 固定项

---

### Theme: 测试纪律——可见性、断言强度、语义契约、专项 session
**Sessions:** 20260417-045350, 050311, 053849, 054645, 081828, 082740 | **Date:** 2026-04-17

**Context:** 测试任务反复被功能开发挤出（045350），专项清理 session 补回效果最好（050311: 18/9 超额交付，9/10）。集成测试 mock 粒度不一致且缺少"确实被调用"断言。更危险的是弱断言测试：--similarity-threshold 测试只验证参数能传入而非改变输出，metrics 测试用 if 守卫保护断言导致行为变化时静默跳过。测试名与实际断言语义矛盾（名称暗示生成 medium priority，实际断言不生成）。

**Takeaway:**
- 写功能代码前先创建测试函数骨架（函数名+pass），让遗漏可见
- 功能 session 聚焦核心逻辑 + 基础测试，评审后开专项清理 session 补齐
- 集成测试 mock 策略各层一致：优先注入 fake 依赖，至少 patch 到最低外部依赖层
- 任何 mock 注入加断言验证其确实被调用（call_count > 0），防止重构导致 mock 被绕过
- 写测试后回读断言，问：(1) 被测行为完全改变时测试会失败吗？(2) 参数值换成另一个断言还通过吗？两个都是"会"说明虚假覆盖
- CLI flow-through 测试必须用不同参数值对比输出差异，测试中禁止 if 守卫保护断言
- 修改 fixture/阈值后必须重读测试名和注释确认语义一致——测试名是最强文档，名字撒谎比断言偏弱危害更大

---

### Theme: 经验闭环——记录 ≠ 执行，评审循环需主动切断
**Sessions:** 20260417-051214, 052244, 060431, 070605, 084030 | **Date:** 2026-04-17

**Context:** CLI 测试缺失跨 4 个 session 未关闭，期间 learnings.jsonl 记录了 3 条相关经验但仍重复遗漏。最终驱动修复的是评审 Priority 1。连续高分后 Agent 选低风险任务，方向分降至 7/10。进一步，连续三个 session 在确定性指标模块上迭代，评审改进项收敛到断言强度层面，形成自我强化循环，预设战略目标完全未执行。但评审改进项性质变化本身是模块完成度的最佳信号。

**Takeaway:**
- 被动经验记录对预防重复错误效果有限——将经验升级为 plan 模板的 checkpoint（如"[ ] 测试骨架已创建"），让检查变成流程
- 评审是最有效的外部强制检查点，比"记住并下次注意"可靠
- 连续高分时警惕"安全选择"陷阱——优先推进核心目标 ACTIVE 项
- 当评审改进项连续两个 session 收敛到同一类别（断言质量、命名精确度），是模块成熟信号。主动终止迭代，切换到更高价值方向
- 判断模块是否 feature complete：看改进项性质，从"功能缺失"收敛到"文档/风格/远期考量"时，继续迭代边际收益接近零
- Session 开始时先检查预设目标，如果当前工作与预设目标不一致，第一个 round 就 flag 并重新对齐

---

### Theme: 修复质量——对照基准与根因追溯
**Sessions:** 20260417-063051, 064141 | **Date:** 2026-04-17

**Context:** 同一 session 中新功能测试（latency_budget）正确实现了 flow-through 验证，但修复旧测试（recovery_window）只做了重命名。跨 4 个 session 在测试层面反复修补，最终追溯到 MetricDelta 模型不携带 details 字段才彻底解决。

**Takeaway:**
- 同一 session 既做新功能又修旧问题时，用新实现的测试作为旧问题修复的对照基准——断言深度必须对等
- 当同一测试质量问题跨多个 session 反复出现时，停止在测试层面修补，检查被测数据模型是否携带验证所需的全部信息

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

**Context:** Phase 3 需要从提案进入构建阶段，但上一轮评审留下了包名冲突。先解决更名确认 trajeval 可用，再搭建骨架，21 测试全过，评审 8.9/10。

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
