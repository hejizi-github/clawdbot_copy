# Journal

## Session 20260417-035438 — REVERTED

Reason: Agent modified constitution files: .evolve/config.toml
Changes were rolled back to a69953abc12c9b2008d6c5a423e7a0e2c877e8d3.


## Session 20260417-034008 — AgentLens 项目提案 + 调研报告修正

完成了 Phase 2 的最终交付物 `strategies/project-proposal.md`，选定 AgentLens 作为构建目标：一个框架无关的 Agent 评估系统，基于执行轨迹分析 + LLM-as-judge 打分，输出 CI 可用的质量报告。同时修复了上一轮评审指出的 4 处准确性问题。评审给出 8.7/10 PASS，但指出一个关键问题：**"agentlens" 包名在 PyPI 已被占用（v0.1.44）**，必须在进入构建阶段前更名。另外评审质疑了 EvalForge 竞品描述的准确性和代码示例中 `@dataclass` vs Pydantic `BaseModel` 的不一致。

### 失败/回退分析

没有方向性失败或回滚，但评审暴露了两个值得注意的问题：
1. **包名冲突未提前检查** — 选定项目名称时没有查 PyPI，直到评审才发现 "agentlens" 已被占用。这意味着如果直接进入构建，到发布时才发现问题会浪费更多时间。根因：提案阶段只关注技术选型和架构设计，忽略了"名称可用性"这个基本的项目启动检查项。
2. **竞品描述可能不准确** — EvalForge 的描述（"v0.3, basic metrics"）未经验证，可能是过时信息或误判。与上一轮调研报告的准确性问题同源：写作时对未亲手验证的信息过于自信。

### 下次不同做

1. 项目命名时立即执行 `pip index versions <name>` 或查 PyPI 确认名称可用性
2. 竞品分析中的版本号和功能描述，至少要通过 PyPI/GitHub releases 做一次交叉验证
3. 代码示例要统一技术选型（提案中写了用 Pydantic，示例就不能出现 `@dataclass`）

## Session 20260417-032714 — 前沿 Agent 技术调研报告（Phase 2）

完成了 `strategies/frontier-tech-research.md`，覆盖 Agent 编排框架、记忆系统、安全与沙箱、评估体系、工具集成、Anthropic 官方模式 6 大方向，每个方向都与 Phase 1 的 clawdbot 架构分析做了交叉对比。最终产出了一个 impact × feasibility 矩阵，为 Phase 3 选题提供决策依据。评审给了 8/10 PASS，主要扣分在 4 处准确性细节（日期错误、自报数据未标注、列表不完整、管道命名矛盾）。报告的 Synthesis 部分质量最高——明确指出 clawdbot 领先于多通道集成和生物记忆模型，但在形式化状态管理和评估体系方面落后。

### 失败/回退分析

本次 session 没有方向性失败或回滚，但评审发现了 4 处事实准确性问题：
1. "Building Effective Agents" 日期写成 Dec 2025，实际是 Dec 2024
2. Mem0 的 26% 准确率提升是自报数据，未标注来源局限性
3. OWASP Top 10 只写了 5 条却用了完整标题
4. "Two-phase pipeline" 却列了 3 个步骤

根因：调研报告写作时追求覆盖广度，对个别数据点没有做二次验证。这些都是"写完不检查细节"的典型问题，不是方向错误。

### 下次不同做

1. 写完调研报告后，对所有日期和数字做一遍逐条验证（grep 原始来源确认）
2. 引用第三方自报数据时，默认加 "self-reported" 标注
3. 使用「X of Y」格式（如 "5 of 10"）而非暗示完整列表的标题
