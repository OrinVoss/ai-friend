# Layer 5: Tool Agent 精简

## 目标

把 Tool Agent Prompt 砍掉一半，只保留任务必需信息，减少 token 浪费和错误决策。

## 当前状态

未开始。

## 关键问题

- Tool Agent Prompt 包含人格、关系、情绪、共同回忆、梦想等无关信息
- 实际只需要：Task、Available tools、Schema、Retry history

## 预期方向

1. 新建 `build_tool_agent_prompt()` 只接收工具相关上下文
2. 从 Tool Agent Prompt 中移除人格、情绪、关系、共同回忆、梦想
3. 保留 retry history 和 available tools schema

## 依赖

- Layer 4 完成 Agent Runtime 解耦，Tool Agent 的输入边界更清晰
