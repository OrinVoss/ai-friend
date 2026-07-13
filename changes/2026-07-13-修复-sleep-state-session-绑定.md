# 修复 sleep state 未按角色/session 隔离

## 问题

Web 模式下 `WebAgent` 创建 `Agent` 时没有传入 `session_id`，`core/agent.py` 里睡眠状态文件一直使用 `config.session_id`（未设置时回退到 `"default"`），导致：

- 所有角色/会话共用同一个 `data/.sleep_state.default`
- 与「一个角色一个 session」的设计冲突
- 日志出现 `Failed to read sleep state: ... data\.sleep_state.default` 警告

## 修复

- `core/agent.py`
  - `Agent.__init__` 新增 `session_id` 参数，默认值 `"default"`
  - 睡眠状态文件名使用传入的 `session_id`，不再依赖 `config.session_id`
- `web/session.py`
  - 创建 `Agent` 时传入 `session_id=self.session_id`，使睡眠状态文件与角色/session 一一对应
- `core/sleep_manager.py`
  - 文件不存在时由 `warning` 降级为 `debug`，避免首次运行/新角色时产生无意义警告

## 验证

- `python -m py_compile core/agent.py web/session.py core/sleep_manager.py` 通过
- 新角色首次连接时睡眠状态文件路径变为 `data/.sleep_state.{role_id}`
- 文件缺失时不再输出 WARNING
