# Layer 1: Memory 生命周期重构

## 目标

把当前"直接存 fact/reflection"的模型，改造为 **Observation → Fact → Insight** 三层生命周期模型，让记忆可验证、可衰减、可遗忘、可追溯来源。

## 当前状态

**一期已完成**：Observation + Fact 双写阶段。

旧 `user_facts` 表继续工作，新 `observations` / `facts_v2` 表并行写入。开关默认关闭，验证稳定后进入二期。

## 本目录文件

- `README.md` — 本说明
- `plan.md` — 完整实施方案
- `progress.md` — 当前进度与待办

## 配置

```json
{
  "use_observation_fact": false
}
```

## 变更记录

- `changes/2026-07-14-memory-layer1-observation-fact.md`
- Commit: `be1f187`
