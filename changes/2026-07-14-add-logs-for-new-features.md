# 为新增功能补充日志

## 变更

- `core/message_handler.py`
  - 睡眠回复持久化后增加 `[msg] sleep reply persisted` 日志
  - Agent 3 输出被识别为 JSON 意图时增加 `[msg] agent3 intent detected` 日志
  - JSON 解析失败时增加 debug 日志

## 验证

```bash
python -m pytest tests/test_message_handler.py -v
# 16 passed
```
