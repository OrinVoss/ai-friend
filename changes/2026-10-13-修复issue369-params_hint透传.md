# 修复 issue #369：params_hint/suggested_tool 透传给 Agent 2

## 修改的文件
- `core/inner_drive.py`
- `core/message_handler.py`

## 修改原因
ToolRequest 的 `suggested_tool`/`params_hint` 解析后从不透传，Agent 2 只能靠自然语言重猜参数，多轮任务（如搜索后抓取）更易失败。

## 修改内容
- `ToolRequest.to_prompt_text()`：description + 建议工具 + 参数提示（JSON）拼成请求文本。
- Agent 2 的 `run_with_requests` 与内层重试路径都改用 `to_prompt_text()`。
- 验证：`pytest -k "inner_drive or message_handler or handler"` 126 passed, 2 skipped。
