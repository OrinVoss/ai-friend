# 修复 MessageHandler 审查遗留问题

## 问题

`doc/known-issues.md` 第 5 节中，2026-07-14 第一批修复后仍遗留四项问题：

1. 未引入状态机抽象
2. 未拆分 `ToolExecutionResult` dataclass
3. 工具注册表隔离不完整（工具实例引用外部状态）
4. Agent 2 重试循环缺少请求级/阶段级超时

本次修复前 3 项；超时控制因涉及 provider/tool 调用链路，留待后续统一处理。

## 改动

### 1. 轻量级状态机

文件：`core/message_handler.py`

- 新增 `MessageHandlerState` 枚举：`IDLE`、`ASSESSING`、`EXECUTING_TOOLS`、`HANDLING_INTENT`、`GENERATING_RESPONSE`、`ERROR_FALLBACK`、`DONE`。
- `MessageHandler.__init__` 初始化 `_state = IDLE`。
- 新增 `_transition(state)` 与 `current_state` 属性。
- `handle_message()` 与 `_handle_agent3_intent()` 在关键阶段调用 `_transition()`，使运行流程可观测、可测试。

### 2. `ToolExecutionResult` dataclass

文件：`core/message_handler.py`

- 新增 `ToolExecutionResult` dataclass，字段包括 `records_text`、`total_calls`、`success_count`、`has_error`、`error_message`、`elapsed_ms`。
- 新增类方法 `from_records()` 统一处理格式化、截断、错误摘要注入。
- 提取 `_run_agent2(user_input, drive_result)`：负责 Agent 2 多轮循环，返回 `ToolExecutionResult`。
- 提取 `_run_agent2_single_round(user_input, drive_result)`：供 `_handle_agent3_intent()` 使用。
- `handle_message()` 不再手动拼接 `tool_records` 字符串，直接复用 `exec_result.records_text`。

### 3. 工具注册表隔离

文件：`core/message_handler.py`

- `_make_internal_registry()` 改为使用 `a.retriever` 和 `a.ltm` 创建全新的 `RecallTool` / `RememberTool` 实例，不再从主注册表复制实例。
- 新增 `_make_external_registry()`，按 `EXTERNAL_TOOL_NAMES` 从主注册表复制外部工具实例，传给 `ToolAgent`，减少 `ToolAgent` 对全局常量列表的隐式依赖。

### 4. 测试

文件：`tests/test_message_handler.py`

- 新增 `test_state_machine_transitions_no_tools`：验证正常对话结束后状态为 `DONE`。
- 新增 `test_run_agent2_returns_tool_execution_result`：验证 `_run_agent2` 返回的统计字段正确。
- 新增 `test_internal_registry_isolation`：验证内部注册表只含 `recall`/`remember` 且为独立实例。

### 5. 文档

文件：`doc/known-issues.md`

- 更新第 5 节状态为「已修复（2026-07-14）」，仅保留超时控制作为遗留项。
- 添加 2026-07-14 后续修复记录。

## 验证

```bash
python -m pytest tests/test_message_handler.py -v
# 21 passed

python -m pytest tests --ignore=tests/real_api -q
# 377 passed, 2 skipped
```

## 相关文件

- `core/message_handler.py`
- `tests/test_message_handler.py`
- `doc/known-issues.md`
- `changes/2026-07-14-fix-message-handler-remaining-review.md`
