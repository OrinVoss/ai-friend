# A5：GC 语义近重复合并（merge_duplicates 实现）

日期：2026-07-21

## 背景

`memory/lifecycle.py::merge_duplicates` 此前是占位 pass——`UNIQUE(session_id, category, fact_key)` 只防精确重复，同一事实的不同表述（「最爱食物：披萨」vs「喜欢的食物：披萨」）会作为两条独立 fact 长期并存，稀释置信度、干扰检索。这是 GC 的最后一块拼图。

## 实现（`memory/lifecycle.py` + `storage/repository.py`）

- **分组**：按 category 分组（不同分类永不合并）；组内 `key value` 文本批量编码，余弦相似度 ≥ `MERGE_SIM_THRESHOLD = 0.88` 的用并查集并为一簇。阈值取高——只合并「同一事实的不同表述」，不合并「相关但不同的事实」。
- **合并**：每簇保留 `(verification_count, confidence)` 最强的一条，其余经新 repo 方法 `merge_facts_v2(keeper_id, absorbed_ids, added_verification)` 单事务标 `status='merged'`，被吸收方的 verification_count 并入保留方。
- 无 embedding 时整步跳过（精确重复已由 UNIQUE 兜底）；编码/读写失败按簇隔离，不影响 GC 其他步骤。
- 触发节奏：随 `garbage_collect`（每 5 次 consolidation 一次）。

## 测试（`tests/test_memory_lifecycle.py::TestMergeDuplicates`，+4）

- 近重复合并进最强者（keeper 选择 + 计数并入）
- 不同事实不合并
- 无 embedding 跳过
- 三条一簇单 keeper、计数求和正确

## 验证

- 全量 `pytest tests --ignore=tests/real_api -q`：**788 passed + 2 skipped**（784 → 788）

## 备注

- 阈值 0.88 是起点值，生产上按 `[lifecycle] merged N near-dup fact(s)` 日志观察误并情况后调。
- Layer 1 GC 至此完整：decay / obsolete / archive / expire_due_insights / **merge**。
