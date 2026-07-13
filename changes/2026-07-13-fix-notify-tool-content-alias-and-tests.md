# 2026-07-13 修复通知工具 content 别名 + 同步 InnerDrive 测试

## 修改原因

1. `notify` 工具在 schema 中声明的参数名是 `message`，但 LLM 调用时经常写成 `content`。
   由于 `tools/notify_tool.py` 只读取 `message`，导致正文为空，连续触发
   "标题和内容不能为空" 失败。
2. `tests/test_inner_drive.py` 没有随 `InnerDrive` 改用 JSON Schema 输出同步，
   仍测试已删除的 `_parse_decision` / `_extract_tool_requests`，并 mock 自由文本
   响应，导致全量测试失败。

## 修改文件

- `tools/notify_tool.py`
  - `execute` 中 `message` 优先取 `message`，无值时兼容 `content` 别名。
- `tests/test_notify_tool.py`（新增）
  - 覆盖空标题/正文、content 别名、message 优先级、PowerShell 失败/超时、
    单引号转义等场景。
- `tests/test_inner_drive.py`
  - 将 `_parse_decision` 相关用例改为 `_parse_json_decision`，使用 JSON 响应。
  - 删除已不存在的 `_extract_tool_requests` 用例，改为验证 JSON 中
    `tool_requests` 数组解析。
  - 同步 `assess` / `re_decide` / `review` 的 mock 响应为 JSON。
  - 修复 `EXTERNAL_TOOL_NAMES` 导入路径为 `tools.traits`。

## 验证

```bash
python -m pytest tests/test_notify_tool.py tests/test_inner_drive.py -v
# 34 passed

python -m pytest tests --ignore=tests/real_api -q
# 343 passed, 2 skipped
```
