# Layer 5: Tool Agent 精简

## 目标

把 Tool Agent Prompt 砍掉一半，只保留任务必需信息，减少 token 浪费和错误决策。

## 当前状态

**Prompt 精简已完成**：Tool Agent Prompt 不再包含人格、情绪、关系、共同回忆，只保留 Task / Available tools / Schema / Retry history。

**下一阶段**：工具系统增强（执行层与结果结构），见 `enhancement-plan.md`。

## 本目录文件

- `README.md` — 本说明
- `enhancement-plan.md` — 工具系统增强方案（ToolResult v2 / 错误感知重试 / 参数校验 / 超时 / 并行 / 智能截断 / 指标 / 权限）

## 已完成

- [x] 新建 `build_tool_agent_prompt()` 只接收工具相关上下文
- [x] 从 Tool Agent Prompt 中移除人格、情绪、关系、共同回忆、梦想
- [x] 保留 retry history 和 available tools schema

## 待完成

- [ ] P0：ToolResult v2（结构化错误）、错误感知重试、参数校验、统一超时
- [ ] P1：并行执行、统一且智能的输出截断
- [ ] P2：schema 给全参数细节、工具指标接入 monitor
- [ ] P3：新工具接入指南、订阅类信息源工具、权限强制执行

## 依赖

- Layer 4 完成 Agent Runtime 解耦，Tool Agent 的输入边界更清晰
