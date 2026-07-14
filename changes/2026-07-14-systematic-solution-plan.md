# 新增系统性解决方案文档

## 内容

新增 `doc/systematic-solution.md`，把 `doc/known-issues.md` 中分散的技术债务归纳为一套统一、可落地的架构改造方案。

主要覆盖：

1. **记忆系统重构**：Observation / Fact / Insight 三层拆分、生命周期管理、来源追踪、Memory GC。
2. **Prompt 与 Agent 认知架构**：CognitiveState 摘要、PromptTemplate、Token Budget、分 Agent Retrieval。
3. **Agent 运行时重构**：AgentRuntime、CognitiveStateMachine、依赖注入、渐进式异步化。
4. **工具层统一改造**：取消 dispatcher 全局别名、统一 RetryBudget、工具结果摘要。
5. **会话/角色模型最终统一**：一个角色一个 session，彻底隔离记忆与情绪。

并给出四阶段实施路线图、风险与回滚策略，以及与 `doc/known-issues.md` 的完整对应关系。

## 文件

- `doc/systematic-solution.md`
- `changes/2026-07-14-systematic-solution-plan.md`

## 推荐下一步

按文档中的阶段一执行：**Memory 系统重构**。
