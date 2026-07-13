# 修复睡眠状态路径与 embedding health 检查

## 问题 1：睡眠状态文件路径错误

重构后 personality 文件移动到 `personalities/{role_id}.json`，`core/agent.py` 仍用 `os.path.dirname(config.personality_file)` 作为睡眠状态目录，导致文件被错误地保存到 `personalities/.sleep_state.{session_id}`，且 `.gitignore` 只忽略项目根目录下的 `.sleep_state.*`。

## 修复 1

- `core/agent.py`
  - 睡眠状态目录改为 `os.path.dirname(os.path.abspath(config.db_path))`，即项目根目录，与数据库文件同级。

## 问题 2：embedding health 检查 URL 错误

`memory/embeddings.py` 与 `core/embedding_server.py` 中的 health 检查 URL 通过 `endpoint.rsplit("/", 1)[0] + "/health"` 计算，对于 `http://localhost:8080/v1/embeddings` 得到 `http://localhost:8080/v1/health`，不是 llama-server 真正的 `/health` 端点，导致健康检查失败并频繁回退到 POST `/v1/embeddings`，增加 400 错误概率。

## 修复 2

- `memory/embeddings.py`
  - `health_check()` 使用 `urllib.parse.urlparse` 提取 scheme 和 netloc，正确构造 `http://localhost:8080/health`。
- `core/embedding_server.py`
  - `_is_server_ready()` 同样使用 `urlparse` 正确构造 health URL。

## 验证

- `python -m py_compile core/agent.py memory/embeddings.py core/embedding_server.py` 通过。
- 重启 Web 服务后，睡眠状态文件会创建在项目根目录（`.sleep_state.{role_id}`）。
- `EmbeddingEngine.health_check()` 现在正确探测 `/health`，减少无意义的 POST fallback。
