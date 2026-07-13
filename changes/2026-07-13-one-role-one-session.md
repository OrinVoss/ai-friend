# 一个角色 = 一个 Session = 一份记忆/情绪

## 目标

把「一个角色可开多个 session」改为「一个角色只有一个 session」，实现真正的角色级持久化。

## 设计

- `session_id = role_id`
- 每个角色的记忆、情绪、关系指标、睡眠状态完全按角色隔离
- 前端只保留角色选择，不再选择/新建 session

## 改动

### 1. 后端：`session_id = role_id`

- `web/session.py`：`SessionManager.get_or_create`
  - 传了 `role_id` 时，`sid = role_id`
  - 没传 `role_id` 但传了 `session_id` 时，`sid = session_id`
  - 都没传时，`sid = "default"`
- `web/server.py`：WebSocket `init_ok` 增加 `role_id` 字段

### 2. 数据库迁移：合并旧 session

- `storage/database.py` 新增 `#SR-002` 迁移：
  - 读取 `session_roles` 中 `session_id != role_id` 的记录
  - 对每个角色，选择对话轮次最多的旧 session 作为「权威数据」
  - 把权威数据从旧 `session_id` 迁移到 `session_id = role_id`
  - 丢弃同一角色下的其他陈旧 session 数据
  - 处理 `relationship_metrics` 复合主键冲突：先删除目标角色的旧指标，再迁移

### 3. 前端：移除 session 选择

- `web/static/index.html`：删除 `#session-modal` 弹窗
- `web/static/style.css`：删除 `.session-list`、`.session-card`、`.new-session-btn` 样式
- `web/static/app.js`：
  - 删除 `openSessionModal`、`selectSession`、`startNewSession`
  - `selectRole` 直接把 `sessionId` 设为 `roleId` 并写入 cookie
  - `initApp` 不再打开 session 弹窗

### 4. API 调整

- `storage/repository.py`：`get_sessions_by_role` 直接返回 `[role_id]`
- `doc/api.md`：`GET /api/sessions` 说明更新为返回唯一 session

### 5. 文档更新

- `README.md`：会话管理说明改为「角色与 session 严格一一对应」
- `doc/architecture.md`：记忆隔离说明补充 `session_id = role_id`
- `doc/api.md`：连接生命周期图更新，去掉 session 选择步骤
- `doc/personality-guide.md`：多角色说明改为一个角色一份记忆

## 验证

- `python -m py_compile web/server.py web/session.py storage/database.py storage/repository.py tests/test_web_agent.py` 通过
- `python -m pytest tests/test_web_agent.py tests/test_context_manager.py tests/test_consolidation.py tests/test_cli_controller.py -q`：40 passed
- 临时旧 schema 迁移测试通过：权威 session 数据正确合并到 `session_id = role_id`
- 启动 `python web_main.py` 后：
  - `GET /api/roles` 返回 `default/Luna`、`小星`
  - `GET /api/sessions?role_id=小星` 返回 `["小星"]`
  - WebSocket `init` 带 `role_id=小星` 后，`session_id` 与 `role_id` 均为 `小星`
  - REST `/api/chat` 使用 `session_id=小星` 可正常对话

## 风险

- 同一角色若存在多个旧 session，非权威 session 的数据会被丢弃。
- 角色名作为 session_id 不能包含文件系统/SQLite 特殊字符（中文名正常）。
