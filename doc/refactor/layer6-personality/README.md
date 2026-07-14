# Layer 6: Personality / Session / 记忆绑定

## 目标

一个 Session = 一个角色实例。每个角色有自己的 personality 文件、情绪状态、记忆、关系指标、睡眠状态。

## 当前状态

未开始。

## 关键问题

- `personality.json` 管理混乱
- 角色个性、情绪、session、记忆等未统一绑定
- 多角色切换时数据隔离是否完整待验证

## 预期方向

1. 角色定义文件：`personalities/{role_id}.json`
   - 包含 `id`、`config`（个性定义）、`emotional_state`（情绪状态）
2. Session 创建时绑定 `role_id`，之后不变
3. 所有数据表按 `session_id` 隔离
4. 新增角色管理接口（CLI / Web）

## 依赖

- Layer 1 Memory 生命周期完成，因为记忆是角色绑定的核心数据
- 需要先明确多角色的产品形态（是否允许同角色多 session）
