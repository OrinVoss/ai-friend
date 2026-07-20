# Layer 1 二期：结构化 Insight 替换 Reflection（直接切换）

**日期**：2026-07-20
**关联**：`doc/refactor/layer1-memory/plan.md`（§3.1 insights_v2、§5.3 INSIGHT_GENERATION_PROMPT）、`changes/2026-07-18-memory-layer1-full-launch.md`（一期 facts_v2 同构打法）

## 背景

旧 Reflection 是开放式结论文本（content + significance），没有假设/证据/置信度结构，无法验证也无法过期。按 plan.md 二期设计，用结构化 Insight（hypothesis + evidence_fact_ids + confidence + needs_more_evidence + expires_at + status）替换 Reflection。沿用一期 facts_v2 的「直接切换」打法：迁移旧数据 → 读路径经适配器切新表 → 旧表归档，不做双写过渡。

## schema v5 迁移（storage/database.py）

- `CURRENT_SCHEMA_VERSION` 4 → 5。P0-3 自动备份在版本落后时自动触发（`data/backups/`）。
- 仅当从 <5 升级且 `reflections` 表存在时执行（幂等，二次 open 时表已不存在，整块跳过）：
  1. **数据迁移**：`INSERT OR IGNORE INTO insights_v2 ... FROM reflections`。
  2. **旧表归档**：`ALTER TABLE reflections RENAME TO reflections_archive`。数据保留，代码不再读写，可日后手动 DROP。
- 全新库：创建 `insights_v2`，不再创建 `reflections`；`alterations` 白名单里 reflections 的条目保留（老库升级路径仍需要先补列再迁移），靠 sqlite_master 守卫在新库跳过。
- 索引：`idx_reflections_session` 不再创建，改 `idx_insights_v2_session(session_id, status, confidence)`。
- `ALLOWED_ALTERATIONS` 未加 insights_v2 条目：新表随 DDL 全列创建，无历史列补全需求。

### 迁移映射（有损）

| insights_v2 列 | reflections 来源 |
|---|---|
| `hypothesis` | `content` |
| `evidence_fact_ids` | 固定 `'[]'` —— **有损**：旧 Reflection 无证据链，迁来的一律空证据 |
| `insight_type` | 直取 |
| `confidence` | `COALESCE(significance, 0.5)` |
| `needs_more_evidence` | 固定 `1`（证据为空，待验证） |
| `expires_at` | `NULL` |
| `status` | `is_active=1 → 'active'`，`0 → 'expired'` |
| `created_by` | 固定 `'migration'` |
| `created_at` / `session_id` / `embedding` / `embedding_version` | 直取 |

## 适配器策略（读路径零改动）

保留旧方法名与 `Reflection` 返回形状，`storage/repository.py` 内部 SQL 全部改打 `insights_v2`（`memory/retrieval.py`、`memory/long_term.py`、`tools/memory_tools.py`、`prompts/system.py`、`models/conversation.py` 全部零改动）：

| Reflection 字段 | insights_v2 来源 |
|---|---|
| `content` | `hypothesis` |
| `significance` | `confidence` |
| `insight_type` | 直取 |
| `related_experience_ids` | 固定 `[]`（evidence 是 fact id，旧字段是 experience id，语义不同不回填） |
| `embedding` / `embedding_version` | 直取 |

重定向的方法：`get_recent_reflections`（status='active'）、`insert_reflection`（转 insert_insight）、`prune_reflections`（溢出按 confidence ASC 置 status='expired'，替代旧 is_active=0 软删）。#251 的相关度评分（语义 0.6 + 关键词 0.4）在 `retrieval.search_reflections` 原样保留，候选池现在来自 insights_v2。

新增 insights_v2 CRUD：`insert_insight` / `search_insights` / `get_active_insights` / `get_recent_insights` / `verify_insight`（confidence +0.1、needs_more_evidence=0、status='verified'）/ `expire_insight` / `update_insight_status` / `expire_due_insights`（GC 用）/ `_row_to_insight`。模型 `models/memory.py` 新增 `InsightV2`（confidence clamp + hypothesis 非空校验，风格同 FactV2）。

## 生成路径变化（memory/consolidation.py + prompts/templates.py）

- `REFLECTION_PROMPT` / `REFLECTION_L2_PROMPT` / `REFLECTION_L3_PROMPT` 删除，替换为 `INSIGHT_GENERATION_PROMPT` / `INSIGHT_L2_PROMPT` / `INSIGHT_L3_PROMPT`：统一输出 JSON（hypothesis / insight_type / evidence / confidence / needs_more_evidence；JSON 示例花括号 doubled 以兼容 safe_format）。
- `_generate_reflection_l1/l2/l3` 方法名与层级节奏不变（L1 每次、L2 每 3 次、L3 每 10 次；既有分层测试零改动），内部改为：LLM 生成 JSON → `_store_insight_from_json` 解析 → `lifecycle.create_insight` 落 insights_v2。
- **解析兜底**：JSON 提取失败 / 非对象 / 缺 hypothesis → log warning 跳过，不写垃圾数据；confidence 门槛沿用旧 significance 门槛（L1>0.4、L2>0.3、L3>0.5）。
- evidence 只接受可解析为整数的 fact id（LLM 可能返回 `"fact_id_7"` 字符串，统一抽数字）。
- L2/L3 的 evidence 说明：L2 是基于近期 insight 的归纳、L3 是长期模式，prompt 允许 evidence 留空 `[]`（主要依据是体验/洞察而非事实时）；L2/L3 不引用 insight id 进 evidence 列（该列语义是 facts_v2 id），近期洞察以文本形式进 prompt 的 `{insights}`/`{patterns}` 变量。
- `memory/lifecycle.py` 新增 `create_insight`（带 embedding）/ `verify_insight` / `expire_insight`；`garbage_collect` 纳入 `expire_due_insights`（expires_at 到期的 active insight 置 expired）。
- `_embed_new_items` 表清单：`reflections` → `insights_v2`（文本列 `hypothesis`）。

## 测试

- 新增 `tests/test_insights_v2_v5_migration.py`（3 用例）：字段映射 + 归档、幂等二次 open、全新库不建 reflections。
- 新增 `tests/test_consolidation.py::TestInsightGeneration`（6 用例）：合法 JSON 字段正确（含 `"fact_id_7"` 抽数字）、markdown 包裹 JSON、坏 JSON 静默跳过、缺 hypothesis 跳过、低 confidence 门槛、L2 默认 pattern 类型。
- 新增 `tests/test_retrieval.py::TestSearchReflectionsInsightsV2`（2 用例，真实 :memory: 库）：切表后 Reflection 形状适配、expired 不可见 + 关键词排序。
- 扩展 `tests/test_memory_lifecycle.py`：create_insight / verify / expire 委托（2 用例）；GC 测试补 `expire_due_insights` mock。
- 存量更新：`tests/test_facts_v2_v4_migration.py`、`tests/test_user_facts_unique_migration.py` 的 schema version 断言 4 → 5。

## 验证

```
python -m pytest tests --ignore=tests/real_api -q
→ 664 passed（基线 651 passed，净增 13）
```

## 已知事项

- **有损迁移**：旧 Reflection 无证据链，迁入 insights_v2 的行 `evidence_fact_ids='[]'` 且 `needs_more_evidence=1`，语义上等于「待验证假设」，会参与检索但 confidence 即旧 significance。
- 归档表 `reflections_archive` 数据保留，确认线上稳定后可手动 `DROP TABLE`。
- `search_reflections` / `MemoryContext.reflections` / `prompts/system.py` 的「最近思考」渲染块名称未改（适配器策略，形状不变）；内容现在是 insights_v2 的 hypothesis。
- L2/L3 的 insight 可能 evidence 为空（依据是体验/模式而非事实），属设计允许；后续做证据链可视化时需要容忍空证据。
- `max_reflections` 配置名未改，现在约束的是 insights_v2 的 active 条数。
