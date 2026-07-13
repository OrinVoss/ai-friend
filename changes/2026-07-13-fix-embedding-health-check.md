# 修复 embedding server 健康检查误报未就绪

## 问题
虽然 `llama-server` 实际上已经启动并可以接受请求，但 `auto_start_embedding()` 的健康检查一直返回失败，导致：
1. 主线程被阻塞在长达 90 秒的等待循环中，`uvicorn` 迟迟无法启动。
2. 最终超时后 fallback 到关键词搜索，语义检索无法使用。

根本原因是原来的 `_is_server_ready()` 对 `/v1/embeddings` 端点发送 **GET** 请求，而 `llama-server` 的 `/v1/embeddings` 只接受 **POST**，因此永远返回 `404 Not Found`。

## 改动
- `core/embedding_server.py`
  - `_is_server_ready()` 改为先探测 `/health` 端点（GET），失败后再用 POST 探测 `/v1/embeddings`。
  - `auto_start_embedding()` 改为**非阻塞启动**：启动 `llama-server` 子进程后立即返回，由后台守护线程等待其就绪。
  - 这样主服务（`uvicorn`）可以立即启动，用户不用等待模型加载。

## 效果
- 启动日志现在显示：
  ```
  [embed] starting embedding server in background...
  Starting AI Friend Web: ...
  [embed] server ready (1s)
  ```
- 语义嵌入检索现在可以正常工作。

## 验证
- `python -m py_compile core/embedding_server.py` 通过。
- 重启后 `curl http://localhost:8080/health` 返回 `{"status":"ok"}`。
- 主服务在 1 秒内启动并响应 `/api/status`。
