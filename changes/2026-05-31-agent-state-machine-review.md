# 修改记录：Agent 状态机数据流与状态转换深度审查

## 修改文件

- `doc/round02-agent-state-machine.md`（新增）

## 修改原因

执行第2轮代码审查，聚焦 Agent 状态机（BOOT→IDLE→PERCEIVE→THINK→ACT→REFLECT→SHUTDOWN）的完整数据流与状态转换路径。

## 修改内容摘要

- 读取并分析了 8 个核心文件（core/agent.py, core/cli_controller.py, ui/cli.py, core/message_handler.py, core/inner_drive.py, core/tool_agent.py, web/server.py, web/session.py）
- 绘制了 CLI 端、Web 端、ReAct 内循环、主动对话路径的 ASCII 状态机图
- 识别出 1 个严重问题、6 个高风险问题、5 个中等风险问题、8 个低风险问题
- 关键发现：
  1. CLI 端 `_on_reflect()` 完全缺失 `_process_emotion()` 调用，情绪系统在 CLI 路径下是"死的"
  2. Web 端完全绕过 `AgentState`，状态机枚举成为 CLI 专用实现
  3. `turn_count` 在 Web 端 session 恢复后未同步，导致数据库 turn 编号冲突
  4. CLI/Web  proactive 路径的历史记录策略不一致，存在记忆黑洞
  5. ReAct 状态在异常路径下未清理，存在状态泄漏风险
