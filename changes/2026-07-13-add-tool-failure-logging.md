# 2026-07-13 增强工具调用失败日志

## 修改原因

`notify` 工具修复 content 别名后，线上日志仍只能看到
`executed 1 tools, 0 ok, 1 failed`，看不到具体失败原因。
增加参数解析日志和工具失败日志，方便线上排查。

## 修改文件

- `tools/notify_tool.py`
  - `execute` 中增加 debug 日志，打印原始参数和解析后的 title/message。
- `core/dispatcher.py`
  - `execute_tool_calls` 中对每个失败工具打印警告日志，包含工具名和前 200 字符错误信息。

## 验证

```bash
python -m pytest tests/test_notify_tool.py tests/test_dispatcher.py -v
# 43 passed
```
