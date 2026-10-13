# 修复 issue #361：CLI 退出不关闭 HTTP session 连接池

## 修改的文件
- `main.py`

## 修改原因
Provider 与 EmbeddingEngine 各持有一个带连接池的 requests.Session；Web 端 shutdown 已关闭共享 provider，但 CLI 退出路径只关 DB，连接池靠 GC 清理。

## 修改内容
- CLI finally 块中关闭 provider 与 embed_engine 的 session（异常仅记 warning，不影响 db.close）。
- 验证：`pytest -k "main or cli"` 42 passed。
