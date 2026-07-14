# Layer 1: Memory 生命周期重构 — 进度

## 状态

一期已完成并推送。

## 已完成

- [x] 新增 `observations` / `facts_v2` 表
- [x] schema version 升级到 2
- [x] 新增 `Observation` / `FactV2` 数据模型
- [x] 实现 `MemoryLifecycleManager`
  - [x] `observe()`
  - [x] `find_similar_observations()`
  - [x] `promote_fact()`
  - [x] `verify_fact()`
  - [x] `contradict_fact()`
  - [x] `decay()`
  - [x] `archive_old_observations()`
  - [x] `garbage_collect()`
- [x] `MemoryConsolidator` 双写 Observation + FactV2
- [x] 新增配置开关 `use_observation_fact`（默认 false）
- [x] 测试覆盖
  - `tests/test_memory_lifecycle.py`
  - 扩展 `tests/test_consolidation.py`
- [x] Changes 文档

## 待完成（二期）

- [ ] 新增 `insights_v2` 表
- [ ] 用 Insight 替换 Reflection
- [ ] Retrieval 切换到新表
- [ ] 完整 GC：merge / decay / obsolete / archive
- [ ] 删除旧 `user_facts` / `reflections` 表

## 验证项

- [ ] 同一喜好重复 3 次后，`verification_count >= 3` 且 `confidence` 上升
- [ ] 用户更正信息后，旧 FactV2 被标记为 `contradicted`
- [ ] 开启 `use_observation_fact=true` 运行一段时间，确认 `facts_v2` 数据质量

## 阻塞项

无。
