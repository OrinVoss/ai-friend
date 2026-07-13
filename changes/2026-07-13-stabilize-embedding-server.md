# 提升 Embedding Server 启动稳定性

## 问题
启动时 embedding server 经常 30 秒内没响应，系统回退到关键词搜索：

```
[embed] starting embedding server...
[embed] server did not respond within 30s, falling back to keyword search
```

导致记忆检索失去语义匹配能力。

## 改动
- `core/embedding_server.py`
  - 等待超时从 30 秒延长到 **90 秒**（`MAX_WAIT_SECONDS = 90`）。
  - 每 10 秒输出一次加载进度日志，避免看起来卡死。
  - 将 `llama-server.exe` 的 `stdout`/`stderr` 重定向到 `logs/embedding_server.log`，便于诊断启动失败原因。
  - 增加进程存活检查：如果 server 进程提前退出，立即停止等待并提示查看日志。
  - 增加最终兜底检查：90 秒后如果进程仍在运行但未就绪，记录警告而不是直接 fallback。

## 效果
- 给模型加载更充足的时间，减少因启动慢导致的 fallback。
- 启动失败时有日志可查。

## 验证
- `python -m py_compile core/embedding_server.py` 通过。
- 重启服务后观察 `logs/embedding_server.log` 和主日志，确认 server 正常启动或失败原因可见。
