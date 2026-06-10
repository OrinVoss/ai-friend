# 2026-06-10 — 自动启动嵌入服务器

## 修改文件

- **main.py** — 新增 `_auto_start_embedding()`：启动时检测嵌入服务器，未运行则自动启动 llama-server
- **web_main.py** — 同上，新增 `_auto_start_embedding()`

## 效果

启动 CLI 或 Web 时，自动检查 `http://localhost:8080` 上嵌入服务是否运行：
- ✅ 已运行 → 直接使用，无延迟
- ✅ 未运行但二进制/模型存在 → 后台启动，等待 10s
- ✅ 二进制/模型缺失 → 跳过，使用纯关键词搜索降级

不再需要手动执行 `start_embedding_server.bat`。
