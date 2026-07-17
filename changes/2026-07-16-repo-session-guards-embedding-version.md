# 存储层收尾：按 id 写方法 session 校验 + embedding_version 接线 + 启动自检 + 重嵌入死锁修复

`doc/refactor/systems/database.md` 的剩余小项（增强方案 1/2/3）一次清完，另挖出并修掉一个生产级死锁。

## 改动

### 1. 按 id 写方法全部加 session 校验（增强方案 3）

`storage/repository.py` 剩余 6 个裸 `WHERE id = ?` 的写方法补齐 `AND session_id = ?` + `rowcount == 0` warning：

- user_facts：`update_fact_score` / `increment_fact_recall` / `update_fact_confidence`
- facts_v2：`update_fact_v2_status` / `verify_fact_v2` / `decay_fact_v2`

至此按 id 写方法与查询方法的 session 隔离全部对齐（known-issues 条目 8 关闭）。

### 2. embedding_version 接线（增强方案 2）

- `models/memory.py` 新增单一常量 `EMBEDDING_VERSION = 1`（换模型/换维度时 +1，旧向量自动滚动重建）
- `storage/repository.py` 全部 6 处字面量 `1` 改用常量（upsert_fact、insert_experience、bulk_update_embeddings、insert_observation、upsert_fact_v2 ×2）
- `memory/retrieval.py` 两个解码点跳过版本不匹配的行（视同无向量，不打 warning——滚动重建期间的正常状态）
- `memory/consolidation.py` 重嵌入条件从 `WHERE embedding IS NULL` 扩为 `OR embedding_version != ?`

### 3. 启动自检（增强方案 1）

- `memory/embeddings.py` 新增 `verify_embedding_health()`：等 embedding server 就绪（最长 30s）→ 试编码 → 抽样一条库存 BLOB 解码点积，任何一步失败记 warning（把 RT-007 的「静默 0 分」变成「启动一句话」）
- `schedule_embedding_self_check()` 后台线程，`main.py` 与 `web/session.py` 启动时调用；`core/session_factory.py` 新增 `make_embedding_sampler()`

### 4. `_embed_new_items` 自死锁修复（新发现的生产 bug）

`_embed_new_items` 在持有外层 `db.cursor()` 的情况下调用 `bulk_update_embeddings`（要拿同一把连接锁）——**自死锁**，每批卡满 60s 超时后以空消息告警「batch encoding failed: 」。生产环境的批量重嵌入因此从未成功过。已改为「cursor 内读候选 → 释放 → 编码 → 批量写」，告警补异常类型。

### 5. Experience 的 embedding 读回（known-issues 条目 9 读侧）

`Experience` 模型补 `embedding` / `embedding_version` 字段，`_row_to_experience` 读回——`retrieval.py` 的 experience 语义分支与 Memory Agent 的 experience 向量召回随之激活。

## 测试

- 新增：2 个跨 session 写回归（user_facts / facts_v2）、版本 stamp、stale 版本跳过不重排、重嵌入批次（0.19s 秒过，此前卡 60s）、4 个启动自检
- 全量：`python -m pytest tests --ignore=tests/real_api -q` → **459 passed, 2 skipped**（基线 429）
