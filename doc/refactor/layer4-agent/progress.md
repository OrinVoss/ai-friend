# Layer 4: Agent Runtime 解耦 — 进度

## 状态

部分已完成。

## 已完成

- [x] `MessageHandlerState` 状态机枚举
  - IDLE / ASSESSING / EXECUTING_TOOLS / HANDLING_INTENT / GENERATING_RESPONSE / ERROR_FALLBACK / DONE
- [x] `_transition()` 方法记录状态变化
- [x] `ToolExecutionResult` dataclass
  - 封装工具执行结果、统计信息、错误信息
  - `from_records()` / `with_elapsed()` 工厂方法
- [x] 魔法数字提取为类常量
  - `MAX_AGENT2_ROUNDS = 3`
  - `TOOL_RECORDS_MAX_LENGTH = 3000`
  - `TOOL_HISTORY_MAX_SIZE = 20`
  - `MAX_INPUT_LENGTH = 10000`
  - `CONV_HIST_MAX_TOKENS = 1800`
- [x] 工具注册表隔离
  - `_make_internal_registry()`：Agent 1 只能用 recall/remember
  - `_make_external_registry()`：Agent 2 使用完整外部工具
- [x] Agent 2 执行逻辑拆分
  - `_run_agent2()`
  - `_run_agent2_single_round()`

## 待完成

- [ ] 为 `Agent` 类添加公开方法，避免 `MessageHandler` 直接访问 `a._xxx`
- [ ] 改进异常处理，错误时向用户反馈
- [ ] 添加全局请求超时
- [ ] 依赖注入：`MessageHandler` 接收 `inner_drive` / `tool_agent` 实例
- [ ] 强化输入清洗 `_sanitize_input`

## 关键文件

- `core/message_handler.py`
- `core/inner_drive.py`
- `core/tool_agent.py`
- `tests/test_message_handler.py`

## 阻塞项

- Layer 3 Retrieval 确定各 Agent 的 Context 边界后，注册表隔离可进一步细化
