# 角色-Session-记忆绑定重构

## 问题

- `personality.json` 是全局共享文件，所有 session 共用同一个角色情绪状态，多角色会互相覆盖。
- `relationship_metrics` 主键只有 `dimension`，没有 `session_id`，导致新 session 写入时覆盖 `default` session 的数据。
- `relationship_snapshots` 没有 `session_id`，所有 session 的历史变化混在一起。
- 前端无法选择角色和切换 session。

## 设计决策

- 一个 Session = 一个角色实例。
- 每个角色有独立的 personality 文件：`personalities/{role_id}.json`。
- 同一个角色可以开多个 session，每个 session 的情绪、记忆、关系指标、睡眠状态相互独立。
- 角色 ID 使用角色名，例如 `小星`。

## 改动

### 1. 角色文件隔离

- 新建 `personalities/` 目录。
- 当前 `personality.json` 复制为 `personalities/小星.json`。
- 新增 `personalities/default.json` 作为通用模板（Luna）。
- `config.py` 与 `config.json` 的 `personality_file` 默认指向 `personalities/default.json`。

### 2. Session 绑定角色

- `web/session.py`：`WebAgent.__init__` 新增 `role_id` 参数，按角色加载/创建 personality 文件；保存时也写入对应角色文件。
- `SessionManager.get_or_create` 支持 `role_id`；已有 session 恢复时忽略 `role_id`。
- 新增 `session_roles` 表记录 `session_id → role_id` 映射。
- `WebSocket init` 协议支持 `role_id`。
- 新增 REST API：
  - `GET /api/roles`：列出所有角色。
  - `GET /api/sessions?role_id=xxx`：列出某角色下的历史 session。

### 3. 关系指标修复

- `relationship_metrics` 主键改为 `(session_id, dimension)`。
- `relationship_snapshots` 增加 `session_id` 列。
- `upsert_relationship` 冲突条件改为 `(session_id, dimension)`，快照写入带 `session_id`。
- `get_relationship_history` 按 `session_id` 过滤。
- 新 session 初始化时自动插入 4 个默认维度。
- 数据库自动迁移：检测到旧表结构时重建 `relationship_metrics`，并将旧数据归入 `default` session；`session_roles` 首次为空时把 `default` session 映射到 legacy `personality.json` 中的角色名。

### 4. 前端角色/会话选择

- `web/static/index.html` + `style.css`：新增角色选择、session 选择弹窗，浅色响应式样式。
- `web/static/app.js`：
  - 首次打开无角色 cookie 时显示角色选择。
  - 选择角色后显示该角色下的历史 session，可新建 session。
  - `init` 消息携带 `role_id` 与 `session_id`。
  - 状态面板关系指标缺失时显示 `--`（不再填充默认值）。

### 5. API 临时归一化移除

- `web/server.py` 的 `/api/status` 不再为缺失维度填充 0.3，只保留 `playfulness → fun` 映射。

## 验证

- `python -m py_compile web/server.py web/session.py storage/database.py storage/repository.py tests/test_web_agent.py`
- `python -m pytest tests/test_web_agent.py tests/test_context_manager.py tests/test_consolidation.py tests/test_cli_controller.py -q`：40 passed
- 数据库迁移脚本在临时旧 schema 上验证通过。
- 启动 `python web_main.py` 后：
  - `GET /api/roles` 返回 `default/Luna` 与 `小星`。
  - `GET /api/sessions?role_id=小星` 返回 `default` session。
  - `GET /api/status?session_id=default` 返回真实关系数据与历史。
  - 新建 session `newsess123` 的关系指标为独立默认值，历史为空。
  - WebSocket `init` 带 `role_id=小星` 成功创建新 session 并返回角色名。

## 风险

- 已有 `default` 之外的其他 session 因为之前没写入过 relationship 数据，迁移后只能按 `default` session 处理。
- 多角色情绪独立：同一角色开多个 session 时，每个 session 的情绪互不干扰。

## 关联

- 修复 `changes/2026-07-13-fix-sleep-message-persistence.md` 中提到的多 session 数据隔离问题（通过 session_roles + 按角色 personality 文件实现）。
