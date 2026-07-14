# 新增并合并系统性解决方案文档

## 内容

把 `doc/known-issues.md` 中分散的 20+ 个问题收敛到一份统一的 v0.6/v1.0 架构蓝图中。

主要覆盖六层运行时：

1. **Layer 0: Identity & State** —— `role_id == session_id == memory_namespace`，一个角色一份完整状态。
2. **Layer 1: Memory Lifecycle** —— Observation → Fact → Insight → GC，记忆有出生、验证、衰减、死亡。
3. **Layer 2: Context & Prompt Budget** —— Token 预算分配，不同 Agent 不同上下文，Prompt 版本管理。
4. **Layer 3: Async Agent Runtime** —— 真实状态机 + 依赖注入 + 全局超时 + 错误恢复。
5. **Layer 4: Tool Runtime** —— 工具参数别名下沉、Registry 隔离、统一重试预算、工具结果摘要。
6. **Layer 5: Provider Abstraction** —— 真异步多 Provider 路由。
7. **Layer 6: Observability** —— source/metrics/结构化日志/可配置监控。

文档同时包含：

- 根因分析表
- 与 `doc/known-issues.md` 的完整映射表
- 五阶段实施路线图
- 验收标准
- A/B 两种推进方式

## 文件

- `doc/systematic-solution.md`（合并后的最终文档）
- `changes/2026-07-14-systematic-solution-plan.md`

## 备注

- 合并了早期概要草案 `doc/systematic-solution.md` 与详细蓝图 `doc/martian-manhunter-icon-valkyrie.md`。
- 临时文件 `doc/martian-manhunter-icon-valkyrie.md` 已删除。

## 推荐下一步

按文档中的 Phase 1 执行：**Layer 0 + Layer 3 骨架**（强制 `session_id = role_id` + 拆分 `Agent` 运行时）。
