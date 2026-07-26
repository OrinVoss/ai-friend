# 2026-07-26 修复 embedding 服务端口冲突

## 修改原因

运行日志中 `[embed] llama-server exited early` 且后续 `/v1/embeddings` 404，语义检索退化为关键词模式。
查 `logs/embedding_server.log`：`couldn't bind HTTP server socket, port: 8080`。
`netstat` 确认 8080 被 `steamwebhelper.exe`（Steam）占用。

## 修改的文件

- `config.json`（不入库）

## 修改内容摘要

- 新增 `"embedding_endpoint": "http://localhost:18080/v1/embeddings"`。
- 依据 H-04 设计（`core/embedding_server.py`）：llama-server 启动端口与客户端请求地址都从
  `embedding_endpoint` 派生，改这一个键即可同时生效；也可用环境变量
  `AI_FRIEND_EMBEDDING_ENDPOINT` 覆盖。

## 备注

- 备选方案：退出 Steam 释放 8080，保持默认配置。
- 重启 `python web_main.py` 后生效。
