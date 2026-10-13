# 修复 issue #356：asyncio.get_event_loop() 已弃用

## 修改的文件
- `web/server.py`

## 修改原因
`web/server.py:190,542` 使用 Python 3.12+ 已弃用的 `asyncio.get_event_loop()`。

## 修改内容
- 两处改为 `asyncio.get_running_loop()`（都在 async 上下文内，语义更正确）。
- 验证：`pytest -k "web or server"` 41 passed, 2 skipped。
