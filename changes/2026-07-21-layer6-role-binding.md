# Layer 6 角色绑定收口（2026-07-21）

## 目标

实现并验证 `role_id == session_id == memory_namespace == emotion_namespace == sleep_namespace`。

## 现状核对

| 设计项 | 实施前 | 实施后 |
|--------|--------|--------|
| `personalities/{role_id}.json` 含个性+情绪 | ✅ 已落地 | ✅ 未改结构，统一入口 |
| session→role 绑定 | ⚠️ 软绑定 | ✅ 硬校验 |
| 记忆按 session 隔离 | ✅ 已落地 | ✅ 验证通过 |
| 睡眠状态 | ✅ 已按 session 文件隔离 | ✅ 随 role_id 命名 |
| `PersonalityManager` | ❌ 不存在 | ✅ 新建 |
| 根目录 `personality.json` | ⚠️ 遗留 | ✅ 已从 git 移除 |

## 关键改动

1. **新建 `core/personality_manager.py`**
   - `list_roles` / `role_exists` / `load_role` / `save_role` / `create_role`
   - `personalities/` 是唯一数据源；`.bak` 被排除在角色列表外。

2. **`core/session_factory.py::assemble_session`**
   - 移除 `personality` 参数，改为 `role_id + personality_manager`。
   - `role_id` 缺省等于 `session_id`；不一致时抛 `ValueError`。
   - 内部 `repo.session_id`、Agent、SleepManager、InnerDriveState 一律使用 `role_id`。

3. **`main.py` / `web/session.py` / `web/server.py`**
   - CLI/Web 入口改为传 `role_id`，由 `PersonalityManager` 加载角色。
   - Web `/api/roles` 改为调用 `PersonalityManager.list_roles()`。
   - `WebAgent._ensure_personality_file` 移除，改为 `PersonalityManager.create_role`。

4. **`web/session.py::SessionManager.get_or_create`**
   - 同时传入 `session_id` 与 `role_id` 且不一致时抛 `ValueError`。
   - 只传 `session_id` 时，若数据库中的旧映射不一致也抛 `ValueError`。

5. **废弃根目录 `personality.json`**
   - `git rm personality.json`
   - 代码中对根目录文件的引用已清零（`storage/database.py` 的一次性迁移代码除外）。
   - `README.md`、`doc/architecture.md`、`doc/config-reference.md` 同步更新。

6. **测试**
   - 新建 `tests/test_personality_manager.py`：角色列表、加载、创建、保存边界。
   - 新建 `tests/test_role_isolation.py`：facts / relationship / turns / insights / sleep state 多角色隔离。
   - 扩展 `tests/test_session_factory.py`：session_id/role_id 不一致抛错、缺省正常装配。
   - 扩展 `tests/test_session_manager.py`：Web 端不一致创建被拒。

## 强制绑定点

- `core/session_factory.py:114-117`
- `web/session.py:39-44`（WebAgent）
- `web/session.py:257-273`（SessionManager）

## 隔离验证结果

`tests/test_role_isolation.py` 6 项全部通过：

- `test_facts_isolated_by_role`
- `test_relationship_isolated_by_role`
- `test_turns_isolated_by_role`
- `test_insights_isolated_by_role`
- `test_session_factory_uses_role_id_for_namespace`
- `test_sleep_state_isolated_by_role`

## 回归基线

`python -m pytest tests --ignore=tests/real_api -q` 全绿（≥693 用例）。

## 明确不做

- 不改 personalities 文件顶层键名（代码实际使用 `personality`）。
- 不支持同角色多 session。
- 不做角色管理 Web UI（`list_roles` API 已够本期）。
- 不动 `session_roles` 迁移逻辑（#SR-002 已跑过）。
- 不做向量库跨角色共享（embedding 按 session 隔离现状已满足）。
