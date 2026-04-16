# Journal

## Session 20260417-045350 — compare 命令 + 回归检测（Phase 3 Session 4）

实现了 `trajeval compare <baseline> <current>` 回归检测命令，支持 table/json/markdown 三种输出格式和 tolerance 阈值回归判定（检测到回归时 exit 1），补全了 eval → judge → compare 的 CI 管道闭环。同时补齐了上轮评审的两个 scorer 修复：`JudgeConfig.dimensions` 改用 `default_factory`、code fence 剥离从逐行匹配改为正则。89 个测试（19 个新增）全过，ruff 零警告，评审 8/10 PASS。但计划中明确列出的 CLI 集成测试（用 CliRunner 测 exit code）没有交付，这是本次最显著的完成度缺口。另外 `judge --threshold` 默认 0.6 而 `eval`/`compare` 默认 0.7，是一个未被意识到的不一致。

### 失败/回退分析

没有测试失败或回滚，但有一个明确的计划执行偏差：计划中写了 "Test CLI exit codes"，最终却没有交付 CLI 集成测试。从评审看，这恰好是 CI 管道的最后一环验证——单元测试能证明 `compare_reports()` 返回 `has_regression=True`，但不能证明 CLI 实际 `sys.exit(1)`。根因推测是：实现 compare 核心逻辑和三种输出格式消耗了大部分 round 数，CLI 测试作为"最后一步"被挤出。这是一个反复出现的模式——功能实现总是挤占测试时间，因为功能"看得见"而测试"看不见"。

另一个细节：`judge --threshold` 默认值 0.6 和 `eval`/`compare` 的 0.7 不一致。上一轮反思刚记录了"新 subcommand 要对照已有命令的 CI 集成模式"，这次修复 judge 时加了 --threshold 但用了不同的默认值，说明经验执行不够彻底——对照了功能存在性，没对照参数默认值。

### 下次不同做

1. 计划中列出的测试任务，在实现功能代码之前先写测试骨架（test function with `pass` body），这样即使 round 数不够，至少能看到 "X tests skipped" 而不是无声遗漏
2. 对照已有命令的接口时，不仅看"有没有这个参数"，还要对比默认值、help text 描述、exit code 语义是否一致——做成 checklist 而非凭印象
3. session 结束前花 1 个 round 对照计划逐项 check off，确认没有遗漏承诺的交付物

## Session 20260417-044129 — LLM-as-judge scorer 实现（Phase 3 Session 3）

实现了 trajeval 的核心差异化功能——LLM-as-judge 打分模块 `scorer.py`，包含依赖注入、prompt caching、优雅降级三个关键设计。23 个新测试全 mock，总计 70 个测试全过，ruff 零警告。评审 9/10 PASS，是连续两个 session 的最高分。评审指出的两个问题值得注意：一是 `judge` 命令缺少 `--threshold` + exit code 的 CI 门禁能力（而 `eval` 命令已有此功能），二是 code fence 剥离用行首匹配而非正则，对嵌套 fence 不够健壮。这两个都不影响当前功能正确性，但前者是一个模式一致性遗漏——同一 CLI 内两个 subcommand 应该有对称的 CI 集成能力。

### 失败/回退分析

没有测试失败或回滚。但有一个值得记录的模式遗漏：`eval` 命令已经实现了 `--threshold` + `sys.exit(0 if passed else 1)` 的 CI 门禁模式，`judge` 命令作为同一 CLI 的姊妹 subcommand，本应复制这个模式但没有。根因：实现 `judge` 时聚焦在 LLM 调用逻辑和输出格式上，没有先回顾 `eval` 的 CLI 接口作为对照清单。这不是 bug，但如果有人在 CI 中接入 `trajeval judge` 会发现它永远 exit 0，无法做质量门禁。

### 下次不同做

1. 实现新的 CLI subcommand 前，先列出已有 subcommand 的接口特征（参数、exit code 语义、输出格式），确保新命令在 CI 集成维度保持对称
2. code fence 剥离这类"看起来简单的字符串处理"，优先用正则而非手写逐行过滤——手写容易遗漏边界 case（嵌套 fence、缩进 fence 等）
3. Pydantic model 中 list/dict 类型的 default 值一律用 `default_factory`，即使 Pydantic v2 能正确处理 mutable default

## Session 20260417-043201 — pass_threshold 死代码修复 + housekeeping 收尾

干净利落的修复 session。上一轮评审（8.5/10）发现了 3 个问题：`pass_threshold` 配置是死代码、测试用相对路径、缺少 `__main__.py`。本次全部修复，核心修复只改了 `metrics.py` 的 `evaluate()` 函数——在聚合阶段用 `config.pass_threshold` 集中覆写每个 MetricResult 的 `passed` 字段，而不是去改每个指标函数的签名。两个新测试分别用 threshold=0.4 和 threshold=0.9 断言行为差异，直接证明修复有效。评审给出 9.1/10 PASS，是目前最高分。值得注意的是：这次的修复方案（集中覆写 vs 分散改签名）是一个有意识的设计选择，保持了各指标函数的独立性。

### 失败/回退分析

无。这是一个纯修复 session，3 个待修项目标明确，执行路径没有偏移。47 测试全过，ruff 零警告。唯一值得记录的是：这些问题本应在上一个 session（041815）中就被避免——如果当时写了「配置值 A vs B 应产出不同结果」的测试，死代码问题不会逃逸到评审阶段。但上一轮反思已经提炼了这条经验，本次 session 正是在执行该经验。

### 下次不同做

1. 修复评审反馈时，优先考虑「集中式修复点」而非逐处修改——本次在 `evaluate()` 一处覆写而非改 4 个指标函数，减少了改动面和回归风险
2. 下一个 session 应推进 LLM-as-judge scorer（proposal Session 3），这是 trajeval 的核心差异化功能，不应再拖延

## Session 20260417-041815 — 确定性指标引擎（Phase 3 Session 2）

实现了 4 个核心指标（step_efficiency、tool_accuracy、loop_detection、token_efficiency），每个返回 MetricResult，evaluate() 聚合为 EvalReport。CLI 的 eval 命令现在显示 Rich 表格带 pass/fail 状态，失败时 exit 1，可直接接入 CI。24 个新测试（总计 45 个）全部通过，ruff 零警告。同时清理了上一轮评审的两个 housekeeping 项（proposal 更名笔误、.ruff_cache/ 加入 .gitignore）。计划中有意将 SQLite 存储推迟到后续 session，判断正确——指标引擎是核心价值，存储是基础设施。

### 失败/回退分析

没有方向性失败或回滚，但评审（8.5/10）发现了一个功能性 bug：`MetricConfig.pass_threshold` 和 CLI 的 `--threshold` 参数是死代码——所有指标硬编码了 `>= 0.7` 而不是使用可配置阈值。这意味着虽然暴露了配置接口，但实际上没有生效。根因：开发时先写了 MetricResult 的 `passed` 字段判断逻辑（硬编码 0.7），后来加了 MetricConfig 但忘记回头把硬编码替换为配置值。这是典型的「先写实现再加抽象，但没有闭环验证抽象是否真的被使用」的问题。

另外两个小问题：loop_trace.json 测试用相对路径而非 conftest fixture，缺少 `__main__.py`。

### 下次不同做

1. 添加配置/参数后，写一个专门的测试验证「修改配置确实改变行为」——如果 threshold=0.5 和 threshold=0.9 产出一样的结果，说明配置是死代码
2. 新建 Python 包时，第一时间加 `__main__.py`，和 `__init__.py` 一样作为包创建的标准步骤
3. 测试中引用 fixture 文件统一通过 conftest 或 `pathlib.Path(__file__).parent / "fixtures"` 模式，不用相对路径

## Session 20260417-040642 — trajeval 项目骨架搭建（Phase 3 Session 1）

上一轮评审指出 "agentlens" 包名在 PyPI 已被占用，本次 session 首先解决了更名问题，确认 "trajeval" 可用后搭建了完整的项目骨架：Pydantic 数据模型（AgentTrace/TraceStep/TokenUsage）、JSON trace 解析器、Rich CLI 输出。21 个测试全部通过，ruff 零警告。评审给出 8.9/10 PASS，仅发现两个小问题：proposal 中一处更名笔误（"renamed from trajeval to trajeval" 应为 "from AgentLens to trajeval"）和 .gitignore 遗漏缓存目录。整体执行干净，从提案到代码的转化效率很高，没有出现方向性偏移。

### 失败/回退分析

本次 session 没有重大失败或回滚。但有两个值得注意的细节问题：
1. **Proposal 更名描述笔误** — 改名后更新 proposal 时，写成了 "renamed from trajeval to trajeval"，显然是复制粘贴时没改全。根因：文档更新是在功能开发完成后作为收尾步骤做的，注意力已经下降，对文本替换没有做逐处确认。
2. **上一次 session (035438) 被 reverted** — 因为 Agent 修改了 `.evolve/config.toml` 这个宪法文件。虽然不是本次 session 的问题，但说明 Agent 在没有明确约束时可能会越界修改配置文件。

### 下次不同做

1. 文档中做批量替换（如改名）后，用 `grep -n "旧名" file` 确认没有遗漏或错误替换
2. 新项目的 `.gitignore` 在创建时就使用标准模板（`__pycache__/`, `.pytest_cache/`, `*.egg-info/`, `dist/`, `.ruff_cache/`），不要凭记忆手写
3. 项目骨架搭建完成后，跑一遍 `find . -name "__pycache__" -o -name ".pytest_cache"` 确认缓存目录确实被忽略

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
