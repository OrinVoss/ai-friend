# 修复 issue #355：logs SSE 阻塞式 readline 在事件循环上

## 修改的文件
- `web/server.py`

## 修改原因
`/api/logs` SSE 生成器里 `readlines()`/`readline()` 是阻塞式文件 IO 直接在事件循环上执行，网络文件系统下会卡住整个 loop。

## 修改内容
- 读历史尾部改用 `asyncio.to_thread` 一次性读取（随读随关，不再整连接期持有该句柄）。
- tail 循环用独立句柄 seek 到末尾，readline 走 `asyncio.to_thread`。
- 验证：`pytest -k "web or server"` 41 passed, 2 skipped。
