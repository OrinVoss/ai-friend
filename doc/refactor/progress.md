# 重构进度总览

> 最后更新：2026-07-14

## 整体架构六层方案

来源：`doc/systematic-solution.md`

```
Layer 1: Memory 生命周期（Observation → Fact → Insight）
Layer 2: Prompt 分层与静态化
Layer 3: 多阶段 Retrieval
Layer 4: Agent Runtime 解耦
Layer 5: Tool Agent 精简
Layer 6: Personality / Session / 记忆绑定
```

## 各 Layer 进度

### Layer 1: Memory 生命周期

**状态**：一期已完成并推送

**已完成**：
- [x] 新增 `observations` / `facts_v2` 表
- [x] 新增 `Observation` / `FactV2` 数据模型
- [x] 实现 `MemoryLifecycleManager`（observe / promote / verify / contradict / decay / gc）
- [x] `MemoryConsolidator` 双写 Observation + FactV2
- [x] 新增配置开关 `use_observation_fact`（默认 false）
- [x] 测试覆盖（19 个新测试 + 全量 401 passed）
- [x] Changes 文档：`changes/2026-07-14-memory-layer1-observation-fact.md`

**待完成（二期）**：
- [ ] 用 Insight 替换 Reflection
- [ ] Retrieval 切换到 `facts_v2` + `insights_v2`
- [ ] 完整 GC：merge / decay / obsolete / archive
- [ ] 删除旧 `user_facts` / `reflections` 表

**阻塞项**：无

---

### Layer 2 ~ 6

状态：未开始，等待 Layer 1 验证稳定后按优先级推进。

## 近期待办

1. 运行 `use_observation_fact=true` 一段时间，验证 `facts_v2` 数据质量
2. 同一喜好重复 3 次后，确认 `verification_count >= 3` 且 `confidence` 上升
3. 用户更正信息后，确认旧 FactV2 被标记为 `contradicted`
4. 根据验证结果，决定是否启动 Layer 1 二期

## 相关文档

- `doc/refactor/layer1-memory.md`
- `doc/systematic-solution.md`
- `changes/2026-07-14-memory-layer1-observation-fact.md`
