# 记忆 Layer 1（Observation → Fact）完整上线：双写灰度结束，切换 facts_v2

**日期**：2026-07-18
**关联**：ML-001、`changes/2026-07-14-memory-layer1-observation-fact.md`（一期双写）、`doc/refactor/layer1-memory/plan.md`

## 背景

Layer 1 一期（2026-07-14）以 `use_observation_fact` 开关（默认 false）控制双写灰度：旧 `user_facts` 表继续读写，新 `observations` / `facts_v2` 表并行写入。本次跳过灰度直接完整上线：读路径切到 facts_v2、写入单写 facts_v2、旧表数据迁移后归档、开关删除。

## 总体策略：适配器重定向

保留旧的读 API 方法名与 `UserFact` 返回形状（`memory/retrieval.py`、`memory/long_term.py`、`tools/memory_tools.py`、`prompts/`、`web/` 全部零改动），repository 内部 SQL 全部改打 `facts_v2`：

| UserFact 字段 | facts_v2 来源 |
|---|---|
| `composite_score` | `ROUND(0.5*confidence + 0.3*importance + 0.2*freshness, 4)`（SQL 计算，排序语义同旧 composite 降序） |
| `recall_count` | `verification_count` |
| `is_active` | `status == 'active'` |
| `fact_type` | 固定 `'user_fact'` |
| `importance` / `confidence` | 直取 |
| `source_turn` | 无对应列，返回 `None` |

写入入口映射：

| 旧方法 | 新语义 |
|---|---|
| `upsert_fact` | 转 `upsert_fact_v2`（stability=0.5, freshness=1.0, created_by='consolidation'），`fact_type`/`source_turn` 参数保留但忽略 |
| `store_facts_bulk` | 同样 SQL 打 facts_v2，保持单 cursor 单事务（末尾一次 commit） |
| `deactivate_fact` | `update_fact_v2_status(id, 'contradicted')`（FactChecker 软删语义） |
| `update_fact_confidence` | 更新 facts_v2.confidence + updated_at（composite 改为读取时计算，不再同步写回） |
| `update_fact_score` | 目标分映射为相对当前 composite 的衰减系数，走 `decay_fact_v2`（旧调用语义均为降级/衰减，比例映射最接近原语义） |
| `increment_fact_recall` | `verify_fact_v2`（recall_count → verification_count） |
| `prune_facts` | COUNT status='active'；溢出行按计算 composite 升序取 id，单条 UPDATE 做 freshness/confidence × 0.1（等价于逐条 `decay_fact_v2(id, 0.1)`，避免 N 次 commit） |

`upsert_fact_v2` 的 ON CONFLICT 补充了 `status = 'active'`——#217 复活语义：被软删（contradicted/decayed）的同名事实在用户重述时恢复可见。

## schema v4 迁移（storage/database.py）

- `CURRENT_SCHEMA_VERSION` 3 → 4。P0-3 的自动备份在版本落后时自动触发（`data/backups/`）。
- 仅当从 <4 升级且 `user_facts` 表存在时执行（幂等，二次 open 跳过）：
  1. **数据迁移**：`INSERT OR IGNORE INTO facts_v2 ... FROM user_facts WHERE fact_type = 'user_fact'`。只迁 user_fact 类型；`is_active=1→'active'`、`0→'obsolete'`；stability=0.5、freshness=1.0、verification_count=1、created_by='migration'；UNIQUE(session_id, category, fact_key) 冲突跳过（双写期间 facts_v2 的数据更新鲜）。
  2. **旧表归档**：`ALTER TABLE user_facts RENAME TO user_facts_archive`。数据保留，代码不再读写，可日后手动 DROP。
- 全新数据库：不再创建 `user_facts` 表，仍创建 `observations` / `facts_v2`。
- 兼容守卫：`alterations` 列表、`#UK-001` 重建块、`#SR-002` 会话合并块都引用 user_facts——执行前查 `sqlite_master`，表不存在（新库/已归档）则跳过，老库升级路径行为不变。
- 索引：不再创建 `idx_user_facts_session`。

## consolidation 单写 + 开关移除（memory/consolidation.py）

- 构造函数无条件创建 `MemoryLifecycleManager`，删除 `use_observation_fact` 判断。
- 每批合并无条件写入一条 Observation；每 5 次合并无条件执行一次 lifecycle GC。
- `_extract_facts` 删除旧表 `store_facts_bulk` 写入（#161 批量写由 promote 逐条写替代——每批事实数量小，可接受）。写入顺序保持「FactChecker 矛盾检测在前、promote 落库在后」，与旧流程（先检测后批量写）语义一致，避免新事实先入表干扰自身的矛盾检测。
- `_embed_new_items` 表清单移除 user_facts（保留 facts_v2 / observations / experiences / reflections）。
- `core/session_factory.py` 的 embedding 启动自检采样从 user_facts 改到 facts_v2。

## 配置变更

- `config.py` 删除 `use_observation_fact` 字段；`config.example.json` 同步删除。
- config 加载器对未知 key 容忍（hasattr 过滤），stale config.json 里的旧 key 无害。

## 测试

- 更新 `tests/test_consolidation.py`：开关测试改为「lifecycle 无条件创建」；`store_facts_bulk` 断言改为 promote 路径（`repo.upsert_fact_v2`）；embedding 用例改插 facts_v2。
- 更新 `tests/test_repository.py`：`DELETE FROM user_facts` → `facts_v2`；`bulk_update_embeddings` 目标表改 facts_v2；facts_v2 首次写入 verification_count=1（promote 即首次验证），相应断言从 0 改为 1。
- 重写 `tests/test_user_facts_unique_migration.py`：验证 v2 老库升级链路（UK-001 重建 → v4 数据迁入 facts_v2、旧表归档、version=4）；新库不再创建 user_facts。
- 新增 `tests/test_facts_v2_v4_migration.py`（3 用例）：只迁 user_fact 类型 + status 映射、与 facts_v2 既有数据冲突跳过、幂等（二次 open 不重复迁移）。
- 全量结果见下方「验证」。

## 验证

```
python -m pytest tests --ignore=tests/real_api -q
→ 638 passed, 2 skipped
```

（基线 635 passed + 2 skipped；净增 3 个 v4 迁移用例，重写/合并了部分旧用例。）

## 已知事项

- 迁移只迁 `fact_type='user_fact'` 的行；agent_fact / system_fact 留在归档表不迁。
- promote 逐条写替代 #161 批量写：每批提取的事实数量小（个位数），N 次 commit 可接受；`store_facts_bulk` 接口保留（facts_v2 版）供其他调用方。
- 归档表 `user_facts_archive` 数据保留，确认线上稳定后可手动 `DROP TABLE`。
- stale config.json 里的 `use_observation_fact` key 无害（加载器忽略未知字段）。
- facts_v2 首次写入即 `verification_count=1`（promote 即首次验证），与旧表 `recall_count` 初始 0 语义略异，属预期。
