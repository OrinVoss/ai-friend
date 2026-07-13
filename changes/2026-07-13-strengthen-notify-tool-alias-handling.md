# 2026-07-13 强化 notify 工具参数兼容与错误提示

## 修改原因

notify 工具修复 content 别名后，线上仍可能因 LLM 使用 text/msg/body 等字段
或 title 为空而失败。错误提示仅"标题和内容不能为空"无法帮助 LLM 自查。

## 修改文件

- `tools/notify_tool.py`
  - `parameters_schema` 的 `message` 描述中明确告知 LLM 使用 `message` 字段，
    不要写成 content/text/msg。
  - `execute` 中正文兼容 `message` / `content` / `text` / `msg` / `body`。
  - title 和 message 分开校验，失败信息返回实际收到的参数，便于 LLM 调整。
- `tests/test_notify_tool.py`
  - 更新错误信息断言。
  - 新增 text/msg/body 别名兼容性测试。

## 验证

```bash
python -m pytest tests/test_notify_tool.py -v
# 9 passed
```
