# 重构：Agent 2 错误元数据化 + 可配置常量（#1 / #2）

日期：2026-07-22

## #1 Agent 2 系统级错误不再混入 user message

问题：`MessageHandler._run_agent2` 在超时或异常时把 `agent2_error` 直接 prepend 到 `ToolExecutionResult.records_text`，随后 `_run_agent3` 把整段 `tool_records` 以 `role="user"` 插入 prompt。模型可能把系统错误误认为是用户输入。

修正：
- `ToolExecutionResult.from_records` 不再把 `error_message` 混入 `records_text`。
- `_run_agent3` 新增 `agent2_error` 参数；若存在，以 `[系统状态] ...` 形式附加到 **system prompt** 末尾。
- 两处调用点（主路径 / intent 路径）改为 `agent2_error=exec_result.error_message`。

结果：错误信息明确来自系统，Agent 3 的语气/表情不再被 user message 里的方括号提示带偏。

## #2 `_OUTPUT_CAP` 与 `STREAM_MAX_BYTES` 移入 Config

问题：`core/dispatcher.py` 的 `_OUTPUT_CAP = 2000` 和 `core/provider.py` 的 `STREAM_MAX_BYTES = 1_048_576` 是硬编码模块常量，无法按模型或部署调整。

修正：
- `config.py` 新增：
  - `dispatcher_output_cap: int = 2000`
  - `stream_max_bytes: int = 1_048_576`
- `format_tool_results(results, output_cap=None)`：可覆盖，未覆盖时回退模块默认 `_OUTPUT_CAP`。
- `ToolAgent` 接收 `output_cap`，在 `format_for_phase2` 时传给 `format_tool_results`。
- `core/agent_wiring.py` 用 `agent.config.dispatcher_output_cap` 初始化 `ToolAgent`。
- `core/agent.py` 的 ReAct 循环用 `self.config.dispatcher_output_cap` 调用 `format_tool_results`。
- `DeepSeekProvider.__init__` 接收 `stream_max_bytes`，流式读取时用实例值代替模块常量。
- `core/session_factory.py` 的 `build_provider` 传入 `config.stream_max_bytes`。
- `config.example.json` 与 `doc/config-reference.md` 同步更新。

## 测试

- `tests/test_dispatcher.py`、`tests/test_provider.py`、`tests/test_message_handler.py`、`tests/test_config.py`：125 passed。
- 全量测试：`841 passed, 2 skipped`。
