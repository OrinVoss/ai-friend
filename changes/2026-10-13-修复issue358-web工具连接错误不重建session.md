# 修复 issue #358：web 工具连接错误重试时不重建 session

## 修改的文件
- `tools/web_tools.py`

## 修改原因
连接层错误（ConnectionError/Timeout）说明 session 可能已失效，用旧 session 重试大概率再失败，5 分钟 TTL 是唯一恢复机制。

## 修改内容
- 抽出 `_close_session()`；`_session()` 与重试路径复用。
- `_anysearch_api` 捕获 ConnectionError/Timeout 时主动丢弃 session，下次重试自动重建。
- 验证：`pytest -k "web or fetch"` 30 passed。
