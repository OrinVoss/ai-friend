# 修复 issue #340：proactive driver 任务异常无人 retrieve

## 修改的文件
- `web/server.py`

## 修改原因
`asyncio.create_task(driver.run())` 后从不 await 也不挂 done-callback；`RuntimeDriver.run` 抛非 CancelledError 异常时只在 GC 时打印 "Task exception was never retrieved"，该 session 静默失去主动回复能力。

## 修改内容
- 为任务挂 done_callback：非 cancelled 的异常取出并记 error 日志（含 traceback）。
- 验证：`pytest -k "web or server"` 41 passed, 2 skipped。
