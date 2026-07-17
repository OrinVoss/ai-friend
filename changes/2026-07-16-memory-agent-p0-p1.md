# Memory Agent P0+P1：确定性记忆推理管道

对应 `doc/refactor/layer1-memory/memory-agent.md` 的 P0（基础版）与 P1（交叉验证增强 + 最小睡眠巩固）。HMS 启发落地：存储与回忆分离、证据链、敢于承认记错。

## 定位

Memory Agent 是**确定性推理组件，不调用 LLM**（LLM 语义重构层可选，不属于本体）：

```
answer(query)
  ├── _extract_clues()      整句向量 + 时间规则→绝对日期 + 意图向量锚点（>0.65 阈值）
  ├── _retrieve_parallel()  facts_v2 / observations / experiences / relationship 并行召回
  ├── _cross_verify()       同 key 矛盾检测 + 一致性（批量编码余弦均值）
  └── _reconstruct()        MemoryAnswer：答案 + 置信度 + 证据链 + 矛盾 + 建议
```

## 改动

- `memory/memory_agent.py`（新建，约 600 行）
  - 数据模型：`MemoryClues` / `MemoryEvidence`（含 verification_count/similarity/标记位）/ `MemoryAnswer`
  - `answer()`：向量召回（不用关键词过滤）+ 时间 post-filter + 交叉验证 + 重构
  - `correct_fact()`：Observation 存档「旧值 → 新值」→ 旧 Fact contradicted → 新 Fact（confidence=1.0, created_by=user_correction）
  - `verify_fact()`：主动验证单条 Fact，FactChecker 语义矛盾一并参与
  - `batch_verify_facts()`（最小睡眠巩固）：最久未验证的先验，低置信度（<0.3）触发 `decay_fact_v2`
  - 置信度公式（verification.md 权重）：consistency .30 / verification .20 / source_quality .20 / freshness .15 / timeline .10 / contradiction .05；timeline 分类型（preference/identity/relationship 长跨度加分，event 减分）
  - 一致性从「聚类计数」改为**批量编码余弦均值**（实现时发现聚类版对单元素组恒为 1，失去区分度）
- `models/memory.py`：`Experience` 补 `embedding` / `embedding_version` 字段
- `storage/repository.py`：`_row_to_experience` 读回向量列（experience 向量召回的前置）
- `tests/test_memory_agent.py`（新建，21 用例）：
  - 时间解析（昨天/上周/上个月/年月/月日）、分类型 timeline、freshness
  - answer：命中/无证据/同 key 矛盾/时间过滤（动态日期，不随运行日期漂移）
  - correct_fact 流程参数、verify_fact 成立与未找到、batch_verify 衰减阈值
  - 意图锚点命中与阈值落空

## 尚未接入（Phase 2，按 memory-agent.md 7.1）

Memory Agent 目前是**独立能力**，未接入 `InnerDriveAgent.assess()`。接入走 `use_memory_agent` 灰度开关：替换点同时升级 Agent 1 决策依据和经 `context_summary` 传给 Agent 3 的记忆摘要，不改 Agent 3 调用侧。实测对比召回质量后再切默认。

## 测试

- 21 用例全部通过
- 全量：`python -m pytest tests --ignore=tests/real_api -q` → **459 passed, 2 skipped**
