# 更新文档：角色-Session-记忆绑定

## 更新内容

- `README.md`
  - 人格系统改为 `personalities/{role_id}.json`
  - 记忆系统增加 `relationship_snapshots` 与 `session_roles` 说明
  - 人格定制示例改为角色文件格式
  - Web 主题改为浅色响应式
  - 会话管理补充角色绑定说明
  - 项目结构增加 `personalities/` 目录

- `doc/architecture.md`
  - 自定义人格改为角色文件
  - 架构总览增加 `personalities/` 与 `session_roles` 映射
  - 记忆系统补充按 `session_id` 隔离的说明
  - 项目结构增加 `personalities/`

- `doc/api.md`
  - 端点总览增加 `/api/roles`、`/api/sessions`、`/api/chat/history`、`/api/logs`
  - WebSocket `init` 增加 `role_id`
  - `init_ok` 增加 `role_id`、`name`
  - 新增 `/api/roles` 与 `/api/sessions` 详细说明
  - 会话生命周期补充角色选择弹窗
  - Session 隔离表补充独立 EmotionalState 与 `session_roles`

- `doc/personality-guide.md`
  - 快速上手改为角色文件
  - 新增「多角色与切换人格」章节
  - 说明同一角色可开多个独立 session

- `doc/config-reference.md`
  - `personality_file` 默认值改为 `personalities/default.json`
  - 人格文件说明改为 `personalities/{role_id}.json`
  - 示例增加 `id` 字段

- `doc/deployment.md`
  - 数据文件与备份脚本改为 `personalities/*.json`

- `doc/message-flow.md`
  - 保存路径改为 `personalities/{role_id}.json`

- `doc/technical.md`
  - 数据文件改为 `personalities/*.json`

- `doc/prompt-reference.md`
  - 人格来源改为 `personalities/{role_id}.json`
