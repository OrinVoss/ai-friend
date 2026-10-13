# 修复 issue #339：RuntimeDriver.stop() 线程未死即置 None

## 修改的文件
- `core/runtime_driver.py`

## 修改原因
`stop()` 只 `join(timeout=3)`，但循环里 `asyncio.sleep` 最长 30s（TICK_ASLEEP），stop 返回时线程常未死，随后 `self._thread = None`；此时 `start_in_thread()` 会再启一个循环，两个 driver 并发 tick 同一 engine → 重复主动消息、rate-limit 竞争。

## 修改内容
- 新增 `_interruptible_sleep`：tick 内所有长 sleep 改为 ≤1s 切片，stop 后线程 ≤1s 内退出。
- `stop()` 在线程仍存活时保留引用并告警（`start_in_thread` 的非 None 守卫继续挡住重启）。
- `start_in_thread()` 遇到已死的旧线程引用时清理并重启。
- 验证：`pytest -k "runtime or driver"` 11 passed。
