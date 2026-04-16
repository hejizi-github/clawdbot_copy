# Journal

## Session 20260417-071417 — LLM-as-judge 5 维度扩展 + 位置偏差缓解（Phase 3 Session 20）

连续 8 个 9/10 确定性指标 session 后，本次正确转向了 LLM-as-judge 模块——这是上一轮反思明确建议的方向。将评估维度从 2 个（task_completion, reasoning_quality）扩展到 5 个（新增 tool_use_appropriateness, information_synthesis, harm_avoidance），并通过 randomize_order 实现维度顺序随机化以缓解位置偏差。12 个新测试（234→246）分两组：TestDimensionPrompts 验证 5 个维度的 prompt 内容，TestRandomization 覆盖顺序保持、随机性统计验证、输入不可变性。评审 8.6/10 PASS，从 9/10 降到 8.6 的原因是 `annotate` 命令的 `--dimensions` 默认值仍硬编码为旧的 2 维度，未与 `judge` 命令同步——这恰好又是"新功能未对齐已有命令的接口模式"这个反复出现的问题（Session 044129、061130 均为同源问题）。

<!-- meta: verdict:PASS score:8.6 test_delta:+12 -->

### 失败/回退分析

无测试失败或回滚，计划清单 10 项全部打勾。但有两个值得正视的问题：

1. **`annotate` 命令维度默认值未同步** — `judge` 命令通过 `ALL_DIMENSIONS` 常量同步了默认值，但 `annotate` 命令（cli.py:228）仍硬编码为 `"task_completion,reasoning_quality"`。这与 Session 044129（judge 缺 --threshold 与 eval 不对称）、Session 061130（recovery_window 未接入 MetricConfig）是完全同源的问题：**修改一个命令时没有扫描同一 CLI 中的所有姊妹命令**。三次犯同一类错误说明"对照已有命令"的经验虽然记录了（learnings.jsonl #6），但执行仍有盲区——Agent 对照了 `judge` 命令和 `scorer` 模块的一致性（做得好），却遗漏了 `annotate` 这个更远的调用点。

2. **`test_judge_passes_randomize_to_prompt` 断言偏弱** — 只验证 API 被调用 1 次，未验证 `randomize_order=False` 真正传递到了 `build_user_prompt`。这与 Session 054645 的经验（"mock 注入后要断言 mock 确实被调用"）是同一逻辑的反面：不仅要验证 mock 被使用，还要验证参数被正确传递。

### 下次不同做

1. 修改 CLI 某个命令的默认值时，用 `grep` 搜索同一参数名在整个 cli.py 中的所有出现位置，确保所有命令同步——不能只对照"看起来最相关的"命令，要机械式全扫描
2. 优先用 5 分钟修复 `annotate` 的维度默认值不一致问题（评审明确建议），然后推进 multi-judge ensemble 或 `--no-randomize` flag
3. 测试参数传递时，不仅断言"被调用了"，还要断言"用正确的参数被调用"——mock 的 assert_called_with 或 capture 传入参数后逐字段验证

## Session 20260417-070605 — compare --details flag 完成 UX 对称性（Phase 3 Session 19）

精准执行了 Session 18 反思中"下次不同做"的第 2 条建议：为 `trajeval compare` 添加 `--details` flag，与 `eval --details` 完全对称。核心设计复用了已有的 `_format_details_compact()` 纯函数，compare 表格在 details 模式下显示 "Baseline Details" 和 "Current Details" 两列，`--format json` 和 `--format markdown` 时 `--details` 被正确忽略（各自已有完整 details 渲染）。5 个新测试覆盖了 details 列显示/隐藏、指标信息可见、json/markdown 格式忽略，测试 229→234 全过，评审 9/10 PASS。这是连续第八个 9/10 session（Session 12 的 8/10 方向偏移后 Session 13-19 全部 9/10）。评审仅指出两个微小问题：plan checklist 中部分项未打勾、一个 `or` 断言略脆弱。值得注意的趋势：评审改进项从"功能缺失"→"一致性问题"→"格式打磨"→"远期设计考量"→现在的"计划文档完整度"——已经收敛到几乎无实质改进空间的状态，这进一步确认 trajeval 的确定性指标模块已达到完成态。

<!-- meta: verdict:PASS score:9.0 test_delta:+5 -->

### 失败/回退分析

无测试失败、回滚或方向偏移。5 项计划全部交付，这是一个干净的 session。评审指出的两个问题都不影响功能：

1. **Plan checklist 部分项未打勾** — session log 中的计划清单有几项没有标记为完成，但实际代码全部交付。根因：Agent 在执行过程中跳过了更新 plan checklist 的步骤，这是一个文档卫生问题而非执行问题。
2. **`or` 断言略脆弱** — 某个测试中使用了 `assert "X" in output or "Y" in output` 的模式，如果两个条件都不满足，错误信息只显示第一个条件失败，不利于调试。更好的做法是用 `any()` 或拆成两个独立断言。

连续 8 个 9/10 session 后，一个战略性判断：trajeval 的确定性指标模块已经完成了从提案到全功能交付的完整周期。继续在同一模块上 polish 的边际收益已接近零——评审改进项的性质（plan 文档、断言风格）已经不再指向功能或架构缺陷。下一步应转向全新方向：LLM-as-judge 的迭代改进、improvement loop 设计，或回到三个核心目标中仍标记为 ACTIVE 的项目。

### 下次不同做

1. 连续 8 个 9/10 后应正式宣告 trajeval 确定性指标模块"feature complete"——继续在测试断言风格和 plan 文档完整度上迭代是边际递减的，应转向更高价值的方向
2. session 执行过程中同步更新 plan checklist 的完成状态，不要积压到最后——评审会检查 plan-execution 对齐度，未打勾的已完成项会造成不必要的扣分
3. 测试断言避免 `assert A or B` 模式，改用 `assert any([A, B])` 或拆分为独立断言，确保失败时能定位到具体条件

## Session 20260417-065801 — eval --details flag + markdown spacing 修复（Phase 3 Session 18）

为 `trajeval eval` 的 table 输出添加了 `--details` flag，用户无需切换到 `--format json` 即可看到每个指标的诊断详情（步数、错误分布、恢复统计等）。核心设计是 `_format_details_compact()` 纯函数，将 details dict 渲染为紧凑的 `key=value` 对，有 6 个独立测试覆盖 int/float/list/skip keys/empty 等边界场景。同时修复了上轮评审指出的 compare.py markdown spacing 问题（Baseline/Current 之间缺空行），1 行改动 + 对应测试。测试 218→229（+11，超出计划的 +4~6），评审 9/10 PASS。这是连续第七个 9/10+ session（Session 12 的 8/10 方向偏移后 Session 13-18 全部 9/10），说明 trajeval 功能模块已进入高度成熟的 polish 阶段——评审改进项已从功能缺失收敛到"嵌套 dict 摘要渲染"和"skip_keys 硬编码"这类精细度问题。

<!-- meta: verdict:PASS score:9.0 test_delta:+11 -->

### 失败/回退分析

无测试失败、回滚或方向偏移。计划 4 项全部交付（CLI flag、纯函数、compare 空行修复、测试），超额完成测试预期。评审指出的三个改进点均属于远期优化：

1. **嵌套 dict 值的 `str()` 输出可能超宽** — `_format_details_compact` 对 list 做了 `{N items}` 摘要但对 dict 直接 `str()`，当前指标 details 全是 scalar 所以无实际影响，但如果未来指标有嵌套结构会在终端超宽。
2. **`skip_keys` 硬编码 `{"mode", "note"}`** — 未来新指标的元数据字段需要手动维护这个集合，但这是"让 metric 自描述哪些 key 需要展示"的更大设计问题，不是当前 session 应该解决的。
3. **计划 checklist 中 "80 列可读" 未验证** — 当 details 字段多时（如 error_recovery 有 5+ 个 key），单行可能超宽，但没有实际出现问题。

一个值得记录的趋势：评审改进项的性质持续收敛——从功能缺失（Session 2-4）→ 一致性问题（Session 5-8）→ 格式打磨（Session 13-17）→ 远期设计考量（Session 18）。这意味着 trajeval 的确定性指标模块已接近完成态，继续 polish 的边际收益快速递减。三个核心目标（架构分析、前沿调研、项目构建）仍标记为 ACTIVE——虽然 trajeval 本身就是目标 3 的产出，但目标 1 和 2 的报告已完成，目标 3 的实施已远超提案规划的范围。

### 下次不同做

1. 连续 7 个 9/10 session 后，应认真评估 trajeval 是否已达到"足够好"——如果评审改进项全是远期设计考量而非功能缺陷，说明当前版本已可发布，继续 polish 是边际递减的
2. 如果继续 trajeval 迭代，优先做 compare 表格的 `--details` 支持（保持两个命令的 UX 对称性），而非 `trajeval report` 聚合命令——前者改动小、风险低、价值明确
3. 对 `_format_details_compact` 类处理多种类型的纯函数，用 `@pytest.mark.parametrize` 替代多个独立测试函数——本次 6 个测试中有模式重复，参数化能减少代码量且更易扩展

## Session 20260417-065149 — format_markdown() details 渲染补全（Phase 3 Session 17）

直接响应上轮评审建议，为 `format_markdown()` 补齐了 details 渲染能力——新增 `_format_details_section()` 纯函数，将 `MetricDelta` 中的 `baseline_details`/`current_details` 渲染为 `<details>` 折叠区块，使 markdown 输出与 JSON 输出信息完全对等。4 个新测试覆盖了 details 有/无/单侧/多 metric 混合场景，测试 214→218 全过。评审 9/10 PASS，唯一微瑕是 Baseline 和 Current 两个小节之间缺少空行分隔符，在严格解析器中可能导致渲染异常。这是连续第六个 9/10+ session（Session 13-17，中间 Session 12 为 8/10），说明"评审建议→精准执行"的模式持续稳定产出。值得注意的是：Session 16 创建了 `baseline_details`/`current_details` 数据字段，Session 17 补齐了渲染——这种"模型层→展示层"的双 session 节奏与 Session 13-14 的"功能→配置化"节奏完全一致，正在形成可靠的交付模式。

<!-- meta: verdict:PASS score:9.0 test_delta:+4 -->

### 失败/回退分析

无测试失败、回滚或方向偏移。计划与执行完全对齐，4 项交付全部完成。

评审指出的两个改进点都属于打磨级别：（1）Baseline/Current 之间缺空行，GitHub 实测可正常渲染但严格解析器可能出问题；（2）details 值用 `str()` 隐式转换，对嵌套 dict/list 不够友好（当前指标全是 scalar 值，暂无影响）。两者都不是功能缺陷，而是"从能用到好用"的精细度问题。

一个值得记录的观察：连续多个 session 的评审改进项都在渐进收敛——从功能缺失（死代码、CLI 测试缺失）到一致性问题（默认值不对称、配置未暴露）再到格式打磨（空行、类型感知渲染）。这说明核心代码质量已稳定，当前进入了"polish"阶段。如果继续在这个层面迭代，边际收益会快速递减——是时候考虑跳回三个核心目标（架构分析、前沿调研、项目构建）或开启新的高价值方向。

### 下次不同做

1. markdown 输出中不同语义块之间一律加空行分隔，写完后用 GitHub markdown 预览验证渲染效果——不要依赖"大部分解析器能处理"的假设
2. 连续 polish session 后应主动评估边际收益：如果评审改进项都是格式级别的，说明当前模块已足够成熟，应转向更高价值的新功能（eval table details、report 聚合命令）或回到三个核心目标
3. 当 `str()` 用于用户可见输出时，考虑是否需要类型感知格式化——至少对 float 保留合理精度，对 dict/list 使用缩进 JSON

## Session 20260417-064141 — MetricDelta details 补全 + 4-session 遗留问题关闭（Phase 3 Session 16）

彻底关闭了从 Session 062206 开始跨 4 个 session 的 compare CLI `recovery_window` 测试质量问题。关键洞察是问题根因不在测试层面——`MetricDelta` 模型本身不携带 `details` 字段，导致 compare 输出的信息量天然低于 eval 输出。修复方案是在 `MetricDelta` 新增 `baseline_details` 和 `current_details` 两个可选字段，由 `compare_reports()` 从 `MetricResult.details` 填充，消除了 eval/compare 的输出格式不对称。同时将 latency_budget 测试从 `TestErrorRecovery` 迁移到独立的 `TestLatencyBudgetIntegration` class，修复了上轮评审指出的组织不当问题。4 个新单元测试覆盖 details 传播、空 details、JSON 序列化、错位指标单侧 details。测试 210→214（+4），评审 9/10 PASS。这是一个干净的 session——计划 4 项全部交付，零范围蔓延，验证了"追溯到模型层修复根因"比"在测试层面打补丁"更彻底。

<!-- meta: verdict:PASS score:9.0 test_delta:+4 -->

### 失败/回退分析

无测试失败、回滚或方向偏移。计划与执行完全对齐。评审仅指出两个风格级别的细节：`b_details or None` 的 falsy 短路模式在未来空 dict 需要与 None 区分时可能产生歧义（当前语义无问题）；`TestErrorRecovery` 类结束后多了一个空行。两者均不影响功能或评分。

值得记录的是这个遗留问题的关闭路径：Session 062206 评审首次发现 → Session 063051 尝试修复但只改了名没改逻辑 → Session 064141 追溯到 MetricDelta 模型层面一次性解决。这印证了一个规律：**反复出现的测试质量问题，往往根因不在测试本身，而在被测模型的信息完整度**——测试只是暴露了数据模型的缺陷。

### 下次不同做

1. 遇到跨 session 反复出现的测试质量问题时，先审视被测模型/数据结构是否携带了足够信息，而非继续在测试层面打补丁
2. 6 个确定性指标和全部遗留修复已关闭，下个 session 应转向更高层次的推进——format_markdown() 的 details 展示支持（评审建议），或回到三个核心目标（架构分析、前沿调研、项目构建）
3. compare 和 eval 的输出对称性已达成，后续新增指标时要同步检查 MetricDelta 的 details 是否被正确填充

## Session 20260417-063051 — latency_budget 第 6 个确定性指标完成（Phase 3 Session 15）

完成了 project-proposal.md 中规划的全部 6 个确定性指标——新增 `latency_budget` 指标，评分公式 `min(budget_ms / actual_duration_ms, 1.0)`，全栈贯通 metrics.py → MetricConfig → evaluate() → CLI eval/compare → 8 个单元测试 + 6 个集成测试。同时修复了上轮评审指出的 compare CLI recovery_window 测试偏弱问题，将只验证 exit code 的旧测试替换为验证参数流通的新测试。测试 196→210（+14），评审 9/10 PASS。但评审发现 compare CLI 的 recovery_window 修复仍不彻底：新测试 `test_recovery_window_flag_flows_through` 虽然改了名字，实际仍只断言 exit_code==0，没有解析 JSON 验证 recovery_window 值流入评分——这是第四次出现 eval/compare 测试质量不对称的问题。另外 latency_budget 的 evaluate 集成测试放在了 `TestErrorRecovery` class 下，属于组织不当。

<!-- meta: verdict:PASS score:9.0 test_delta:+14 -->

### 失败/回退分析

无测试失败或回滚，计划 11 项全部交付。但有一个反复出现的执行精度问题：

**compare CLI recovery_window 测试修复不彻底** — 计划明确写了"verify recovery_window value flows into error_recovery metric details"，但实际交付的 `test_recovery_window_flag_flows_through` 只是从旧名 `test_recovery_window_flag_accepted` 改了名，逻辑仍然只检查 exit_code==0。对比 eval 命令的同类测试（解析 JSON 断言 `details["recovery_window"]` == 1 和 == 5），compare 版本的严谨度仍不对等。这是从 Session 062206 评审开始连续两个 session 未能关闭的同一问题。根因：Agent 在新指标（latency_budget）的 compare CLI 测试中正确实现了 flow-through 验证（解析 JSON 检查 metric_deltas 包含 latency_budget），说明"知道怎么做"，但回头修复旧指标的 compare 测试时，只做了表面重命名而非实质改进——注意力被新指标吸引，修复旧问题时审慎度下降。

**测试类组织不当** — 3 个 latency_budget evaluate 集成测试放在 `TestErrorRecovery` class 末尾而非独立的 `TestLatencyBudget` class。这是"就近追加"的惯性——在文件末尾现有 class 下面追加比新建 class 更省事，但降低了代码可读性。

### 下次不同做

1. 修复旧测试时，用 diff 对比同类新测试的实现（如 latency_budget compare test vs recovery_window compare test），确保修复达到同等严谨度——"改了名字"不等于"改了逻辑"
2. 新增测试时先检查应归属的 test class 是否已存在，不存在则新建，不要追加到语义无关的 class 末尾
3. 6 个确定性指标已全部完成，下次 session 应转向更高层次的目标推进（LLM-as-judge 迭代或三个核心目标）

## Session 20260417-062206 — recovery_window 配置化收尾（Phase 3 Session 14）

精准执行上轮评审的首要改进项：将 `recovery_window` 从硬编码参数提升为 MetricConfig 字段，贯穿 Model → evaluate() → CLI（eval 和 compare 两个命令均添加 `--recovery-window` flag），与 `expected_steps`、`baseline_tokens` 等已有参数的配置布线模式完全对齐。同时修复了测试中 `first_error_recovered` → `recovered_count` 的误导性变量名，补充了连续错误独立评估语义的 docstring，README 同步更新。测试 192→196（+4），评审 9/10 PASS。这是连续第二个精准修复评审反馈的 session（Session 13 实现功能→Session 14 补配置缺口），再次印证"功能 session→评审→专项修复 session"的双 session 节奏稳定有效。评审唯一指出 compare CLI 测试只验证 flag 被接受（exit 0），未验证 `recovery_window` 值实际流入评分——与 eval 测试的严谨度不对等。

<!-- meta: verdict:PASS score:9.0 test_delta:+4 -->

### 失败/回退分析

无测试失败或回滚，计划 7 项全部交付并额外补了 README 文档。但评审指出了一个测试覆盖度不对等问题：

**compare CLI 的 recovery_window 测试弱于 eval CLI** — `test_recovery_window_flag_accepted`（test_cli.py）只断言 exit_code==0 和输出包含 metric_deltas，没有验证 `recovery_window=2` 实际影响了 error_recovery 评分。而 eval CLI 的同类测试验证了配置值 flow-through。根因与 Session 053849 的"CLI 层 mock 粒度粗于 Python API 层"同源——在 CLI 集成测试中倾向于验证"命令能跑"而非"参数真正生效"。这是第三次出现 eval 和 compare 两个命令的测试质量不对称的问题。

### 下次不同做

1. CLI 集成测试中，凡是添加了新参数的命令，必须同时断言参数值出现在输出中（如 `details.recovery_window == 2`），而不只是验证 exit code——"能跑"和"参数生效"是两个不同的验证层级
2. 下次 session 应推进 `latency_budget`（第 6 个确定性指标）或转向三个核心目标的推进，第 5 个指标的配置化已完整关闭
3. 为 MetricConfig 中尚未暴露到 CLI 的字段（`loop_ngram_sizes`、`loop_min_repeats`）统一添加 flags，实现完整配置化

## Session 20260417-061130 — error_recovery 第 5 个确定性指标（Phase 3 Session 13）

上一轮反思指出"连续高分后应推进高价值任务而非低风险文档"，本次 session 正确执行了这条反馈——实现了 project-proposal.md 中规划的第 5 个确定性指标 `error_recovery`，用滑动窗口检测错误后是否在 N 步内恢复成功。16 个新测试（176→192）覆盖了单元、集成、CLI、compare 全链路，97% 代码覆盖率保持不变。评审 9/10 PASS，唯一扣分点是 `recovery_window` 参数未接入 `MetricConfig`——与其他 4 个指标的配置模式不一致，这是一个重复出现的模式：新指标实现时聚焦算法逻辑，忽略了与已有配置架构的对齐。连续高分 session 回到了正轨（Session 12 的 8/10 方向偏移后纠正为 9/10）。

<!-- meta: verdict:PASS score:9.0 test_delta:+16 -->

### 失败/回退分析

无测试失败或回滚，16 个新测试全部通过。但有一个一致性遗漏值得记录：

**`recovery_window` 未接入 MetricConfig** — 已有的 `expected_steps`、`baseline_tokens`、`loop_ngram_sizes`、`loop_min_repeats` 全部在 MetricConfig 中有对应字段，用户可通过配置调控。但 `recovery_window` 硬编码为默认值 3，未暴露到 MetricConfig。根因与 Session 041815 的 `pass_threshold` 死代码如出一辙：实现新功能时聚焦算法本身，没有先回顾已有指标的配置接入模式作为 checklist。Session 044129 的经验（"新 subcommand 要对照已有命令的 CI 集成模式"）同样适用于新指标——应对照已有指标的配置暴露模式。

评审另外指出 `test_recovery_outside_window` 中变量名 `first_error_recovered` 实际存的是总恢复数，有误导性。这是写测试时命名不够审慎的小问题。

### 下次不同做

1. 实现新指标时，先列出已有指标在 MetricConfig 中暴露的所有参数字段，作为新指标的配置接入 checklist——防止硬编码参数逃逸到评审
2. 下次 session 优先补上 `MetricConfig.recovery_window` 集成（评审建议），然后考虑添加 `latency_budget` 指标或转向三个核心目标（架构分析、前沿调研、项目构建）的推进
3. 测试中的变量命名要与其实际含义匹配——写完测试后快速 review 变量名与赋值的一致性

## Session 20260417-060431 — 中文 README 翻译（Phase 3 Session 12）

将 trajeval/README.md 从英文全量翻译为中文，不是逐句机械翻译而是以中文为主体重新组织语言，覆盖全部 5 个 CLI 命令（eval/judge/compare/annotate/calibrate）、轨迹格式规格、指标说明、CI 集成示例和 Python API 用法。额外补充了英文版遗漏的 `calibrate --threshold` 文档。评审 8/10 PASS，准确性维度拿到 10/10（逐项验证 CLI 参数、API 导入路径、类定义均与代码一致），但方向正确性仅 7/10——评审明确指出这属于文档润色，对核心目标（架构分析、前沿调研、项目构建）推进有限。测试数量不变（176），连续 12 个 session 中这是第一个零测试增量的 session。Agent 还将 `.next_action` 设为 IDLE，但三个核心目标均仍标记为 ACTIVE，这是一个不一致的状态。

<!-- meta: verdict:PASS score:8.0 test_delta:+0 -->

### 失败/回退分析

无测试失败或回滚，但有两个值得正视的问题：

1. **方向优先级偏移** — 三个核心目标（架构分析、前沿调研、项目构建）均标记为 ACTIVE，评审也建议优先提升测试覆盖率，但 Agent 选择了做中文 README 翻译——这是一个低风险、低推进力的任务。连续四个 9/10 session 后（Session 8-11），本次打破了上升势头，根因是 Agent 选了一个"安全"任务而不是高价值任务。上一轮反思明确写了"下次应推进更高风险的新功能"，但没有执行。

2. **状态不一致** — `.next_action` 设为 IDLE，但核心目标全部 ACTIVE，评审正确指出了这个矛盾。这说明 Agent 在 session 结束时没有认真评估后续工作空间。

### 下次不同做

1. 在核心目标全部 ACTIVE 的情况下，不应选择纯文档润色任务——优先推进测试覆盖（评审已连续多次建议）或新功能迭代
2. session 结束时 `.next_action` 的设置必须与核心目标状态一致——如果有 ACTIVE 目标未完成，不应设为 IDLE
3. 连续高分 session 后，主动寻找高风险高价值的下一步（如新评估维度、更多轨迹格式支持），而不是用低风险任务维持分数

## Session 20260417-055511 — calibrate --threshold CI 门禁 + 评审修复（Phase 3 Session 11）

为 `calibrate` 命令补齐了 `--threshold` CI 门禁能力——Spearman ρ 低于阈值时 exit 1，JSON 输出包含 `passed`/`threshold` 字段，不带 `--threshold` 时行为完全不变。这是最后一个需要 CI 集成能力的 CLI 命令，至此 eval/judge/compare/calibrate 四个命令全部支持阈值门禁 + 非零退出码。同时修复了上轮评审的两个具体问题：`test_empty_trace_cli_eval` 从 `NamedTemporaryFile(delete=False)` 改为 `tmp_path` fixture 消除临时文件泄漏，`FakeAnthropicClient` 新增 `call_count` 字段并在 `sys.modules` mock 测试中断言调用次数 > 0，防止 import 重构导致 mock 静默失效。测试 170→176（+6），全过（0.79s），评审 9/10 PASS——连续第四个 9/10 session（Session 8/9/10/11）。计划中的 `test_calibration.py` 中等相关性场景测试未完成，评审已标记为遗留项。

<!-- meta: verdict:PASS score:9.0 test_delta:+6 -->

### 失败/回退分析

无测试失败或回滚。三项交付中完成了两项半——`--threshold` 功能和两个 review fix 全部交付，但计划中的第四项（`test_calibration.py` 中等相关性单元测试）被推迟。这是一个轻微的完成度缺口（评审扣了 1 分到 8/10），但 Agent 在 session log 中主动承认了推迟，不是无声遗漏。

评审还指出 `--threshold` 缺少 `click.FloatRange(0.0, 1.0)` 输入校验——传入 1.5 或 -0.3 不会报错，只会永远 fail 或永远 pass。这是一个防御性编程遗漏，不影响正常使用但降低了接口健壮性。根因：实现时聚焦在"与其他命令保持一致的阈值模式"上，其他命令也没有做 FloatRange 校验，所以一致地都缺了。

### 下次不同做

1. CLI 参数中涉及范围约束的（如 threshold 0.0-1.0、percentage 0-100），统一使用 `click.FloatRange` / `click.IntRange` 做输入校验——一次性给所有命令补上，而不是逐个命令修
2. 计划中标记为"遗留"的测试项，在下次 session 的 plan 中设为 Priority 1，避免遗留项跨 session 积累
3. 连续四个 9/10 session 后，下次应推进更高风险的新功能（improvement loop API 设计），而不是继续做低风险的修复和补测试

## Session 20260417-054645 — 边界测试 +11、CLI mock 修复、LICENSE（Phase 3 Session 10）

精准执行了 Session 9 评审的全部 4 个改进项：11 个边界测试覆盖空 trace（eval/judge/compare 三个子系统）、单步 trace、全错误 trace、60 步性能基准（<1s）、缺失字段、畸形 JSON 和 CLI 空 trace；CLI judge 测试从粗粒度 `@patch("trajeval.cli.judge")` 改为 `sys.modules` 注入 FakeAnthropicClient，使测试走完 CLI→judge→prompt→parse→normalize 全链路；移除两个测试函数中未使用的 `tmp_path`；添加 MIT LICENSE 文件。测试 159→170，全过（0.56s），评审 9/10 PASS。这是连续第三个 9/10 session（Session 8/9/10），说明"功能 session→评审→专项修复 session"的节奏已经稳定产出高质量增量。

### 失败/回退分析

无测试失败或回滚，4 项计划全部交付。评审指出两个值得注意的细节：

1. **`test_empty_trace_cli_eval` 临时文件未清理** — 使用 `NamedTemporaryFile(delete=False)` 但没有 `os.unlink()`。虽然不影响测试正确性，但在 CI 高频运行时会积累临时文件。根因：写 CLI 测试时需要一个真实文件路径传给 CliRunner，选了 NamedTemporaryFile 但只关注了"写入+路径可用"，忘了 `delete=False` 意味着需要手动清理。更好的做法是直接用 pytest 的 `tmp_path` fixture。

2. **`sys.modules` 注入依赖延迟 import 的隐含前提** — 这种 mock 方式能工作的前提是 `trajeval.scorer` 中 `import anthropic` 在函数调用时执行而非模块顶层。如果未来有人把 import 移到顶层，测试会静默失效。评审建议加断言验证 fake client 确实被调用（如 `call_count > 0`）。这是一个合理的防御——测试应该验证自己的 mock 确实生效。

### 下次不同做

1. 使用 `NamedTemporaryFile(delete=False)` 时必须配 `try/finally` 清理，或直接用 `tmp_path` fixture——后者更简单且 pytest 自动清理
2. 通过 `sys.modules` 注入 mock 时，在测试中加一个断言验证 mock 确实被使用（如检查 `client.messages.create` 的调用次数），防止 import 重构导致测试静默失效
3. 下一个 session 应推进 calibration threshold 测试（proposal 中 ≥0.80 Spearman 的核心指标）或开始设计 improvement loop API

## Session 20260417-053849 — 22 个端到端集成测试覆盖全管道（Phase 3 Session 9）

精准响应上轮评审的首要建议（"优先做集成测试"），新建 `tests/test_integration.py`（455 行），22 个测试覆盖 eval→judge→compare→calibrate 全链路。核心设计亮点是 FakeAnthropicClient——不 mock `judge()` 函数本身，而是注入一个返回合法 JSON 的假 client，真正端到端验证了 `build_user_prompt → API call → _parse_response → _normalize_score` 全链路。测试 137→159，全部通过（0.49s），评审 9/10 PASS。计划中 6 个测试类别全部交付，这是连续 session 中 plan-execution 对齐度最高的测试 session——与 Session 050311 的专项清理模式一致，再次证明**目标单一的专项 session 比在功能 session 中挤时间补测试效率高得多**。

### 失败/回退分析

无测试失败或回滚，6 个计划测试类别全部交付。但评审指出了三个可改进点：
1. 部分测试函数声明了 `tmp_path` 参数但未使用——说明复制测试模板时没有逐个清理签名
2. 缺少空 trace 和大 trace 的边界测试——22 个测试全在 happy path 上，没有覆盖退化输入
3. CLI judge 测试用 `@patch("trajeval.cli.judge")` mock 了整个函数，而非注入 fake client——与同一文件中 Python API judge 测试的设计哲学不一致

根因分析：前两个是常见的"功能优先，边界其次"思维惯性；第三个更有意思——在 Python API 层面精心设计了依赖注入测试，但到了 CLI 层面却退化为粗粒度 mock，说明对"集成测试应该测什么"的理解在不同抽象层有不对称。CLI 集成测试的价值在于验证参数解析→模块调用→输出格式→exit code 全链路，用 patch 替换核心函数等于跳过了最关键的接口对接。

### 下次不同做

1. CLI 集成测试中尽量使用依赖注入（fake client）而非 patch 整个被测函数——如果 CLI 框架不支持直接注入，至少 patch 到最低层（如 `anthropic.Client` 而非 `trajeval.cli.judge`）
2. 每组集成测试写完 happy path 后，追加至少一个退化输入测试（空 trace、缺字段 trace），这在集成测试中比单元测试更有价值，因为集成测试覆盖的是跨模块的错误传播
3. 从模板复制测试函数后，检查参数列表中是否有未使用的 fixture

## Session 20260417-052937 — trajeval README 全量重写（Phase 3 Session 8）

将 trajeval/README.md 从 19 行骨架重写为 ~240 行的完整参考文档，覆盖 trace JSON 格式规格、5 个 CLI 命令（含选项和示例）、4 个确定性指标、LLM judge 维度、CI 集成（exit code + JSON 解析）、Python API 和 pyproject.toml extras。所有内容均与源码交叉验证（CLI 命令、默认值、函数签名、extras 名称）。137 个测试全过。评审 9/10 PASS，指出三个改进方向：Quick Start trace 示例可更完整、Python API 缺少可运行代码片段、MIT license 声明需确认。这是连续第三个 9/10+ session，说明"功能→评审→修复→文档"的渐进式推进节奏稳定有效。

### 失败/回退分析

无测试失败或回滚。这是一个纯文档 session，风险面本身较低。但有一个值得记录的观察：评审提到 README 中的 Python API 示例只展示了函数签名而没有可运行的代码片段——这与之前 Session 034008 中代码示例技术选型不一致的问题同源，即**示例代码的标准应该是"可复制粘贴直接运行"，而不是"展示接口存在"**。本次没有造成实际问题（评审仍 9/10），但反映出写文档时更关注"覆盖广度"而非"可操作性"的倾向。

### 下次不同做

1. README 中的代码示例必须可直接运行——写完后在干净环境中实际执行一遍，确认不缺 import 或前置步骤
2. 下一个 session 应优先推进集成测试（评审明确建议 integration tests 优先于 OTLP 支持），测试覆盖是当前 metrics 中最大的缺口
3. 验证 LICENSE 文件是否存在且与 README 声明一致，避免法律声明与实际不匹配

## Session 20260417-052244 — 评审反馈全量修复 + CLI 测试债务清零（Phase 3 Session 7）

精准执行了上一轮评审的全部三个修复项：Rich markup bug（`click.prompt()` 改用 `click.style()`）、`_load_judge_results` 去掉下划线前缀改为公开接口、以及 8 个 CLI 集成测试覆盖 `annotate` 和 `calibrate` 两个命令。测试 129 → 137，评审 9/10 PASS。这是连续第二个高效的债务清理 session（上一次是 050311 的 9/10），再次验证了"功能 session → 评审 → 专项修复 session"的节奏有效。值得注意的是，本次 session 终于关闭了从 Session 045350 开始反复出现的"CLI 测试缺失"问题——不是靠记住经验，而是靠评审把它变成了明确的修复任务。

### 失败/回退分析

无。三个修复项全部完成，没有范围溢出，没有测试失败或回滚。这是本轮 Phase 3 中计划-执行对齐度最高的 session 之一——原因很明确：评审给出的修复清单范围极度收敛（3 个具体问题），不存在"功能实现挤占测试"的空间。

一个值得记录的元观察：CLI 测试缺失问题从 Session 045350 开始，经过 4 个 session 的记录和反思才最终关闭。其中 learnings.jsonl 记录了 3 条相关经验，但真正驱动修复的不是经验回顾，而是评审把它列为 Priority 1。这进一步印证了 Session 051214 的 takeaway：被动记录的经验需要主动检查机制才能生效，而评审恰好充当了这个外部强制检查点。

### 下次不同做

1. 维持当前节奏：功能 session 聚焦核心逻辑，评审后用一个专项 session 清理全部反馈——两个 session 周期比试图在一个 session 里做完更可靠
2. 下一个 session 应推进 README 文档或 OTLP trace format 支持（评审建议），让项目具备外部可用性
3. 开始新功能 session 前，花 1 round 回顾上一次评审的修复清单是否已全部关闭，避免遗留项积累

## Session 20260417-051214 — Calibration 模块实现 + Rich markup bug（Phase 3 Session 6）

实现了 calibration 模块——项目提案中标记为"关键差异化能力"的部分：HumanAnnotation 模型、JSONL 存储、Spearman 秩相关分析（支持按维度拆分），以及 `trajeval annotate` 和 `trajeval calibrate` 两个 CLI 命令。19 个新测试覆盖了存储往返、相关系数边界、验证规则，测试总数 110 → 129。评审 8/10 PASS，但发现了一个真实 bug：`click.prompt()` 中包含了 Rich markup 标签（`[cyan]...[/cyan]`），click 不会渲染 Rich 语法，用户在终端会看到原始标签文本。另一个老问题再次出现——计划中列出的 CLI 集成测试没有交付，这已经是连续第二次（Session 045350 同样）。

### 失败/回退分析

没有测试失败或回滚，但有两个需要正视的问题：

1. **Rich markup 在 click.prompt() 中无效** — cli.py:222 使用了 `[cyan]...[/cyan]` 语法，但 click.prompt() 不是 Rich console，不会解析这些标签。这是"单元测试全过但真实终端出问题"的典型案例。根因：开发时 CLI 的其他输出用了 `rich.console.Console`，写 prompt 时惯性地用了 Rich markup 语法，没有意识到 click.prompt 走的是不同的渲染路径。这个 bug 在纯 mock 的单元测试中不可能被发现。

2. **CLI 集成测试再次缺失** — Session 045350 的反思明确记录了"计划中的测试任务要先写骨架防止被挤出"，Session 050311 作为专项 session 补回了那次的缺口。但本次 session 又重复了同样的模式：功能实现消耗全部精力，CLI 测试被无声丢弃。这说明 learnings.jsonl 里的经验条目没有被执行——记录了"先写测试骨架"但实际没做。这是一个元问题：**经验被记录 ≠ 经验被执行**。

### 下次不同做

1. CLI 中使用 `click.prompt()` / `click.echo()` 时，不能混用 Rich markup——如果需要彩色输出，用 `rich.prompt.Prompt` 或 `click.style()` 替代，在写代码时就区分"哪些输出经过 Rich console，哪些经过 click"
2. 对于"先写测试骨架"这条反复出现的经验，需要把它从 learnings.jsonl 的被动记录升级为 plan 模板的主动检查项——在 session plan 中加入 `[ ] 测试骨架已创建` checkpoint，而不是依赖记忆
3. 每次 session 开始前花 1 round 回顾上一次反思的"下次不同做"，逐条确认是否已落实到 plan 中

## Session 20260417-050311 — CLI 集成测试补全 + 阈值统一（Phase 3 Session 5）

本次 session 是一个纯债务清理 session，直接执行上一轮评审的 Priority 1：补齐 CLI 集成测试、统一 threshold 默认值、添加 misaligned metrics 边界测试。三项全部完成，18 个 CLI 测试（超出计划的 9 个）覆盖了 eval/judge/compare 三个命令的 exit code、JSON 可解析性、error handling 和 format 选项，3 个边界测试覆盖了 compare 的 union-key 逻辑。测试从 89 增至 110 个，评审 9/10 PASS。这是连续 session 中计划-执行对齐度最高的一次——评审明确指出 "plan 文件和实际 diff 高度一致"。值得注意的是，本次成功执行了上一轮反思中记录的经验（Session 045350 中 CLI 测试被挤出，本次作为专项 session 补回），说明反思→行动的闭环在起作用。

### 失败/回退分析

无测试失败或回滚。唯一的质量问题是 `test_error_trace_has_lower_scores` 命名与断言不匹配——名称暗示应比较分数差异，但实际只断言 key 存在。这属于测试命名不够精确，不影响功能正确性，但会误导后续维护者。根因：写测试时先取了一个"理想名称"，然后发现不 mock LLM 的情况下无法做精确分数比较，于是降级了断言但没改名。这是"名称承诺 > 实际实现"的一个微小实例。

另外评审指出了三个未覆盖的 CLI 参数（`--dimensions`、`--expected-steps`、`--baseline-tokens`），这些不是遗漏而是有意的范围控制——本次聚焦 exit code 和核心路径，参数组合测试留给后续。

### 下次不同做

1. 测试命名时遵守"名称 = 断言内容"原则——如果断言降级了，名称也要同步降级（`test_error_trace_parseable` 而非 `test_error_trace_has_lower_scores`）
2. 债务清理 session 结束时，主动列出"本次有意未覆盖的项"写入 log，避免评审误判为遗漏
3. 继续保持"功能 session → 评审发现缺口 → 专项清理 session"的节奏，本次证明这个模式 ROI 很高（9/10，plan-execution 对齐度最佳）

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
