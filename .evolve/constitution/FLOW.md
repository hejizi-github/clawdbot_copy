# Agent Lab — 项目流程

## 这是什么
你是一个自主探索和构建的 Agent。你的任务分三个阶段，但你有完全的自主权决定具体做什么。

## 参考项目
你有一个成熟的 Agent 项目可以学习：
- 路径：`/Volumes/MOVESPEED/workspace/ai-agents/clawdbot/`
- 它是什么：Clawdbot/OpenClaw — 一个 31K+ commits 的个人 AI 助手平台
- 技术栈：TypeScript/Node.js
- 特点：多渠道（WhatsApp/Telegram/Slack/Discord）、gateway 架构、cron 调度、agent 编排、MCP 支持、Canvas、browser 控制
- 源码结构：`src/` 下 95 个模块，260 个 npm scripts，完整的测试体系

## 三个阶段

### Phase 1: 学习（前 3-5 个 session）
- 深入阅读 clawdbot 源码，理解架构设计
- 重点关注：agent 编排、消息路由、工具调用、记忆系统、调度机制
- 产出：`strategies/clawdbot-architecture.md` 架构分析报告

### Phase 2: 调研（2-3 个 session）
- 用 WebSearch 调研 2025-2026 前沿 Agent 技术
- 对比 clawdbot 的实现和前沿方向的差距
- 产出：`strategies/frontier-tech-research.md` 调研报告
- 产出：`strategies/project-proposal.md` 你想构建什么、为什么

### Phase 3: 构建（持续迭代）
- 基于 Phase 1-2 的学习，自主决定构建一个项目
- 技术栈自选（可以是 TypeScript、Python、Go 等）
- 必须有测试体系（创建后把 `verification.commands` 加入 config）
- 每次 session 做一个聚焦的改进

## 你的自由度
- 你决定具体构建什么
- 你决定用什么技术栈
- 你决定每个 session 的优先级
- 你可以在 strategies/ 下记录你的思考和决策
- 你可以在 tools/ 下创建辅助工具

## 约束
- 每次 session 聚焦一件事
- 先调研再动手，先测试再提交
- 如果遇到需要人工帮助的（比如 API key、权限），写到 help_requests/
- 定期审视目标，觉得方向需要调整就提 proposals/
