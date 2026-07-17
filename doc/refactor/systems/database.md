# 数据库系统增强方案

> 目标：让 SQLite 存储层配得上「唯一自我状态载体」的地位——语义检索真正生效、session 隔离不漏、数据可备份可回滚、存储有生命周期。
> 状态：设计文档，待实现。
> 归属：基础设施。不属于六层之一，是 Layer 1 记忆与 Layer 6 角色隔离共同的存储地基。

---

## 1. 现状盘点

| 组件 | 现状 |
|------|------|
| 连接层 | `storage/database.py`：单连接 aiosqlite，WAL 模式 + `busy_timeout=5000` + 启动 `integrity_check`（`database.py:47-63`） |
| Schema | 9 张表：schema_version / user_facts / experiences / reflections / relationship_metrics / relationship_snapshots / session_roles / conversation_turns + 新表 observations / facts_v2（`database.py:92-216`）；insights_v2 未建，属 Layer 1 三期（见 `../layer1-memory/plan.md`） |
| 迁移 | 每次 `open()` 自动执行：DDL 白名单校验（`database.py:11-29`，好实践）、逐列 ALTER 探测、#SR-002 session 合并（含 DELETE） |
| 读写层 | `storage/repository.py`：8 组 CRUD，显式 `commit()`；软删为主（is_active / is_archived / status） |
| embedding | 以 BLOB 存行内，`embedding_version` 字段存在；实测生产库 47+15+19 条 BLOB 均为 4096 字节（1024 维 float32） |
| 剪枝 | `prune_facts/experiences/reflections` 接在 consolidation 后（`consolidation.py:513-516`）；`prune_old_turns` 无调用方 |
| 备份 | **无**。`web/backups/` 只有三份前端静态文件 .bak（app.js / index.html / style.css），与数据库无关；人格文件有 PE-004 先备份再读（`core/personality.py:105-109`），DB 没有同等待遇 |
| 入口 | CLI（`main.py:39`）与 Web（`web/session.py:271`）打开同一个 `config.db_path`（默认 `data/ai_friend.db`，`config.py:49`），无单实例护栏 |
| data/ 实测 | db 3.9MB + **db-wal 3.8MB 滞留**（上次关闭未截断）；conversation_turns 396 行含 hist_test / md_test* 等孤儿 session；schema_version=1，新表尚未在生产库建立 |

---

## 2. 问题清单（按严重度排序）

### P0-1 语义检索静默失效：1024 维向量撞上 512 的默认值

> ✅ **已修复（2026-07-16，`changes/2026-07-16-fix-embedding-dim-session-isolation.md`）**：`bytes_to_vec` 改为 `dim=None` 按 BLOB 长度推断，两个调用点显式传 `dim=len(qvec)`；静默 `except: pass` 改为逐条 debug + 每次检索一条汇总 warning。启动自检未做。
>
> 🔴 **顺带发现**：`experiences` 表写入了 embedding 列，但 `_row_to_experience`（`repository.py:604`）从不读回，experience 语义检索路径是死代码——向量写了没人用，接线或停写归 Layer 1 二期决策。

`memory/embeddings.py:120` —— `bytes_to_vec(data, dim=512)` 维度写死 512；两个消费方 `memory/retrieval.py:148` 和 `retrieval.py:182` 调用时都不传 dim。生产库实测全部 BLOB 为 4096 字节 = 1024 维 → `bytes_to_vec` 抛 `ValueError`，被 `retrieval.py:150` 的 `except Exception: pass` 吞掉，`semantic = 0.0`。

后果：**混合检索（语义 0.6 + 关键词 0.4，`retrieval.py:132-133`）实际退化为纯关键词打分，且日志无一字提及**。`embedding_version` 本是为这类不一致准备的版本字段，但全项目只有写入和行映射引用它（`repository.py:601,632,647`、`models/memory.py:37,100,133`），**没有任何逻辑读取**——保险丝装了，没接线。

### P0-2 跨 session 数据泄漏：矛盾检测可以删掉别的角色的事实

> ⚠️ **部分修复（2026-07-16）**：`get_similar_facts()` 已加 `session_id` 过滤，`deactivate_fact()` 已加 session 校验 + 未命中 warning（`changes/2026-07-16-fix-embedding-dim-session-isolation.md`）。**剩余**：`update_fact_confidence` / `update_fact_score` / `increment_fact_recall` / facts_v2 写方法仍无 session 校验。
>
> ✅ **新发现已修复（2026-07-16，#UK-001）**：`user_facts` 唯一约束已迁移为 `UNIQUE(session_id, category, fact_key)`（schema v3，RENAME 旧表 → 新表 → 搬迁数据），`upsert_fact` 的 `ON CONFLICT` 同步加 session_id。生产库下次启动经 P0-3 通道先自动备份再迁移。见 `changes/2026-07-16-user-facts-session-unique.md`。

`storage/repository.py:137-145` —— `get_similar_facts()` 的 WHERE 没有 `session_id` 过滤（同文件其他查询都有）。consolidation 的矛盾检测（`memory/consolidation.py:262-269`）拿它找「相似旧事实」，命中后 `resolve()` 经 `deactivate_fact()` 按 id 直接置 `is_active=0`（`repository.py:117-124`，同样无 session 校验）。

后果：角色 A 的一次矛盾检测可以把角色 B 的事实软删。Layer 6 一角色一 session 落地（`../layer6-personality/README.md`）后多角色共存是常态，这个洞就从「潜在」变「日常」。

### P0-3 数据库零备份，而迁移在每次启动时自动执行

> ✅ **已修复（2026-07-16，`changes/2026-07-16-database-auto-backup.md`）**：`open()` 在 `initialize()` 前检测——文件非空且 `schema_version` 落后于 `CURRENT_SCHEMA_VERSION` 时自动 `VACUUM INTO` 快照到 `data/backups/`，按 mtime 滚动保留最近 `db_backup_keep`（默认 5）份；新库与已是最新版本的库不备份。配置 `db_backup_enabled` / `db_backup_keep`。

人格文件加载前先 `shutil.copy2` 备份（`core/personality.py:105-109`，PE-004），但 DB——唯一不可替代的自我状态载体——没有任何备份机制。同时 `initialize()`（`database.py:92`）在每次 `open()` 自动跑全部迁移，其中 #SR-002 含**不可逆的 DELETE**（`database.py:341-346`）。生产库当前 schema_version=1，下次启动就要一次性建两张新表 + 跑合并迁移——没有任何回滚点。后面 Layer 1 二期旧表数据迁移、三期删旧表（`../layer1-memory/plan.md` Step 7），每一步都是销毁性操作，都踩在同一条「先动手、无备份」的线上。

### P1-1 只增不删：无物理回收，无空间策略

- `prune_old_turns()`（`database.py:374-390`）**没有任何调用方**，且实现是全局保留最新 N 条、docstring 却写 "per session"——即使接上线，活跃角色也会把不活跃角色的 turns 挤出去
- `relationship_snapshots` 每次 `upsert_relationship` 插一行（`repository.py:443-446`），无任何清理
- 软删行（is_active=0 / is_archived=1 / status≠active）物理上永不删除，无 VACUUM
- 实证：生产库 conversation_turns 里躺着 hist_test / md_test3~6 等孤儿 session 的数据，session_roles 里没有对应角色，谁也读不到，谁也删不掉

「万物有生命周期」在 SQL 层只做到了「标记」，没做到「回收」。

### P1-2 CLI 与 Web 双进程同库，无护栏

`main.py:39` 与 `web/session.py:271` 打开同一个 `data/ai_friend.db`，全项目无单实例检查。WAL + busy_timeout 保证不损坏文件，但语义层没有保护：

- turn_number 靠 `get_max_turn_number()` + `insert_turn()` 两步非原子完成（`repository.py:516-525` → `491-501`），双进程并发可产生重复 turn_number
- 两个进程会各自跑一遍 initialize 的 #SR-002 合并迁移（含多语句 DELETE/UPDATE），互相 busy_timeout 或交错执行
- 同一角色两端同时在线时，consolidation 对同一批 turns 跑两遍

### P1-3 run_async 路径下连接锁失效

`Database._get_lock()`（`database.py:39-45`）按 event loop id 缓存一把 `asyncio.Lock`；而 `run_async()`（`core/async_utils.py:29`）每次都 `asyncio.run()` 建一个**新** loop。Web 模式下 repo 调用大量走 run_async（如 `web/session.py:307`），锁几乎每次调用都被重建——4 线程池并发的 run_async 在同一个 aiosqlite 连接上没有任何互斥。aiosqlite 单 worker 线程保证单语句不交错，但「cursor() 执行 + commit()」这类多语句单元可以交错，方法级原子性形同虚设。

### P1-4 `bulk_update_embeddings` 没有 commit

> 🔴→✅ **更严重的同款问题已修复（2026-07-16）**：`_embed_new_items` 在持有外层 `db.cursor()` 的情况下调用 `bulk_update_embeddings`（后者要拿同一把连接锁）——**自死锁**，每批卡满 60s 超时后以空消息告警「batch encoding failed: 」，生产环境的批量重嵌入因此从未成功过。已改为「cursor 内读候选 → 释放 → 编码 → 批量写」，并有 `TestReembedStaleVersions` 钉住。无 commit 的问题仍待处理。

`repository.py:233-241` —— 全部写方法都显式 `await self.db.commit()`，唯独它没有。批量 embedding（`consolidation.py:551-555` 每批最多 150 行、要调外部 embedding 服务）的持久化取决于「下一个碰巧 commit 的方法」；进程在此之间退出，这批向量白算。同事务连接上后续谁 rollback 还会把它一起带走。

### P2-1 迁移无版本门控，每次启动全量探测

schema_version 表存在且已 stamp（`database.py:353-357`），但迁移不读它：ALTER 靠逐列 `PRAGMA table_info` 探测（`database.py:243-252`），#SR-002 靠扫 `session_roles` 数据探测（`database.py:309`）——一次性迁移在每次启动都重新进入、靠数据巧合幂等。迁移应当按版本差量执行，跑过的版本不再进入。

### P2-2 关闭路径 checkpoint 静默失败，WAL 无观测

`close()` 的 `wal_checkpoint(TRUNCATE)` 异常被裸 `except: pass` 吞掉（`database.py:394-397`）。实证：生产环境 `data/ai_friend.db-wal` 3.8MB 滞留两天未截断。数据不丢（SQLite 下次 open 会回放），但「关没关干净」无从得知；运行期也只有 `wal_autocheckpoint=1000`（`database.py:52`）一个策略，无任何 WAL 大小观测。

### P2-3 孤儿数据无清理通道

无 role 映射的 session 数据（测试残留、#SR-002 之前的旧 session）没有任何删除入口——没有 per-session 删除 API，没有清理脚本。只能靠手工 SQL。

---

## 3. 增强方案

### P0：正确性地基（纯 bug 修复 + 备份，无需灰度开关）

**1. 让语义检索真正生效**（✅ 核心修复已完成 2026-07-16；启动自检已完成 2026-07-16：`verify_embedding_health` + 两个入口后台线程自检，失败记 warning）

- `bytes_to_vec` 不再写死维度：按 BLOB 长度推断（`len(data) // 4`），或调用方传入当前引擎维度——二选一，全项目统一
- 加启动自检：open 后抽一条 BLOB 解码并与 `encode_single` 结果做点积，失败 `logger.warning`——把「静默 0 分」变成「启动一句话」
- 依赖：无。确定性修复，不动 schema

**2. 让 embedding_version 接线**（✅ 已完成 2026-07-16：`EMBEDDING_VERSION` 单一常量（models/memory.py），retrieval 跳过版本不匹配行，重嵌入条件扩为 `OR embedding_version != ?`）

- 定义单一常量（与 embedding 模型/维度绑定），替代散落在 `repository.py:44,160,218,238,321` 的字面量 `1`
- retrieval 只解码 version 匹配的行；不匹配的行视同无向量，并入批量重嵌入（`consolidation.py:536-537` 的 `WHERE embedding IS NULL` 扩为 `OR embedding_version != ?`）
- 换模型/换维度 = 常量 +1，旧向量自动滚动重建——这就是这个字段本来的使命

**3. 补齐 session 隔离**（✅ 已完成 2026-07-16：`get_similar_facts` + 全部按 id 写方法（`deactivate_fact` / `update_fact_confidence` / `update_fact_score` / `increment_fact_recall` / facts_v2 三个）均已加 session 校验 + 未命中 warning）

- `get_similar_facts()` 加 `session_id = ?`（self.session_id 现成）
- 按 id 写的方法（`deactivate_fact` / `update_fact_confidence` / `update_fact_score` / `increment_fact_recall` / facts_v2 三个）加 `AND session_id = ?`，跨 session id 直接写不进去
- 依赖：无，越早越好——Layer 6 落地前必须把洞堵上

**4. 自动备份（先于一切销毁性操作）**（✅ 已完成 2026-07-16：迁移前 `VACUUM INTO` 快照 + 滚动保留 5 份；差异——按 mtime 滚动而非文件名排序，以兼容同秒碰撞后缀）

- `open()` 检测到有迁移要执行时，先 `VACUUM INTO 'data/backups/ai_friend.YYYYMMDD-HHMMSS.db'`——备份与空间回收一步完成，且 VACUUM INTO 产物是一致性快照
- 保留最近 5 份，滚动删除；配置 `db_backup_enabled` / `db_backup_keep`，默认开
- 对齐 PE-004 的「先备份再动」，只是对象从人格文件换成 DB
- 依赖：无；**必须早于 Layer 1 二期旧表迁移与三期删表**（`../layer1-memory/plan.md` Step 7）

### P1：生命周期与并发

**5. 物理回收，挂进睡眠 Stage 3（不另造调度）**

- `prune_old_turns` 改真 per-session（按 session 各留 N 条），接入睡眠循环 Stage 3 GC（`../layer1-memory/sleep-cycle.md`），同时删掉假 docstring
- `relationship_snapshots` 加保留窗（如 90 天）
- 超龄软删行物理 DELETE（如 is_active=0 且 30 天未动）——旧三表随 Layer 1 三期下线后此规则自然萎缩，新表 GC 语义归 Layer 1 管，这里只提供存储层原语
- 依赖：睡眠工作层；睡眠未落地前可临时挂 consolidation._prune 之后

**6. 单写者护栏**

- open 时在 db 同级创建 `.ai_friend.lock`（O_EXCL），退出删除；已存在则启动即报清晰错误「另一个实例可能正在使用此数据库」
- 文档化原则：同一 db_path 单进程写；CLI 与 Web 二选一，或各用各的 db_path
- 不引第三方锁库，存在性锁文件足够——要防的是「同时跑」，不是做分布式锁

**7. 连接锁与并发模型对齐**

- `Database` 的连接级互斥改用 `threading.Lock`（asyncio 临界区只 await 不阻塞的特性下安全），替代按 loop id 重建的 asyncio.Lock——锁语义与 run_async 线程池模型一致
- 依赖：无；改完 Web 模式下多语句单元恢复原子性

**8. `bulk_update_embeddings` 补 commit**

一行修复，与同文件所有写方法对齐。

### P2：可观测与整洁

**9. 迁移版本门控**

schema_version 升级为迁移台账：每个迁移（ALTER 批次 / #RM-001 / #SR-001 / #SR-002 / 后续）登记 id，启动只跑「当前版本 → 目标版本」差量；#SR-002 这类一次性合并跑过即不再进入。

**10. 存储观测**

- close() checkpoint 失败记 warning 不吞
- 启动 log：db 大小、WAL 大小、各表行数（一条日志的事）
- 睡眠报告（`../layer1-memory/sleep-cycle.md`）附带 GC 物理删除行数——「回收了多少」可见

**11. 孤儿数据清理**

一次性 CLI 命令/脚本：删除 session_roles 中无 role 的 session 在各表的数据（hist_test / md_test* 即此类）。作为 #SR-002 的补丁，跑完即弃，不进常驻代码。

---

## 4. 与现有设计的关系

- **自我系统（`../self-system.md`）**：记忆是自我状态四组件之一，SQLite 是其唯一载体。本方案不动状态模型，只让载体可靠——备份对应「状态唯一」前提下的「状态不丢」，物理回收对应「万物有生命周期」的存储层兑现
- **Layer 1（`../layer1-memory/plan.md`）**：新旧表双写、旧表迁移与删除路线归 Layer 1，本方案不重复；P0-3 备份已落地（2026-07-16），二期/三期的销毁性操作已有回滚点
- **睡眠循环（`../layer1-memory/sleep-cycle.md`）**：Stage 3 GC 是物理回收的统一窗口，本方案提供 per-session prune / 快照保留窗 / 物理 DELETE 三个存储原语给它调用
- **Layer 6（`../layer6-personality/README.md`）**：P0-2 session 隔离是角色隔离的存储前提；P1-6 单写者护栏与「一角色一 session」互补
- **Memory Agent / 检索（`../layer1-memory/memory-agent.md`、`../layer3-retrieval/README.md`）**：P0-1/P0-2 修好后，向量召回与置信度设计才建立在真实语义分之上，否则上层所有排序都在吃关键词的残羹
- **工具系统增强（`../layer5-tool/enhancement-plan.md`）**：同为基础设施层增强，无依赖，可并行

---

## 5. 改动文件

| 文件 | 改动 | 期 |
|------|------|----|
| `memory/embeddings.py` | `bytes_to_vec` 维度推断/传参 | P0 |
| `memory/retrieval.py` | 调用点传维度；version 不匹配跳过 | P0 |
| `storage/repository.py` | session 过滤补齐、按 id 写加 session 校验、bulk commit、embedding_version 常量、snapshots 保留窗、物理 DELETE 原语 | P0/P1 |
| `storage/database.py` | 备份（VACUUM INTO + 滚动）、启动自检、threading 锁、锁文件、prune_old_turns per-session、迁移版本门控、checkpoint 告警、启动观测日志 | P0/P1/P2 |
| `memory/consolidation.py` | 重嵌入条件加 version 过滤；GC 物理回收挂载点 | P0/P1 |
| `config.py` | `db_backup_enabled` / `db_backup_keep` | P0 |
| `tests/test_repository.py` / 新增 `tests/test_database.py` | 各期覆盖 | 各期 |

---

## 6. 测试与验收

测试：

1. 1024 维 `vec_to_bytes` → `bytes_to_vec` 不抛异常，`_hybrid_score` 对带向量候选给出 semantic > 0 的分 ✅（`tests/test_retrieval.py::TestBytesToVecDim` / `TestHybridScoreSemanticDim`，2026-07-16）
2. embedding_version 不匹配的行不参与打分，且出现在重嵌入批次里 ✅（`tests/test_retrieval.py::test_stale_version_skipped`、`tests/test_consolidation.py::TestReembedStaleVersions`，2026-07-16）
3. `get_similar_facts` 只返回本 session 行；用他 session 的 id 调 `deactivate_fact` 不生效 ✅（`tests/test_repository.py`，2026-07-16）
4. 触发迁移的 open 先生成备份文件；第 6 份备份产生时最旧被删 ✅（`tests/test_database_backup.py`，2026-07-16）
5. per-session prune：session A 刷 1200 条 turns，session B 的 100 条原样保留
6. 锁文件存在时第二个 `Database.open()` 报清晰错误
7. 两个线程经 run_async 各 upsert 100 次，最终行数与值正确（锁修复后）
8. 全量 `pytest tests --ignore=tests/real_api -q` 不降级

验收：

- 日志可观测到 semantic 分 > 0（或启动自检通过）
- `data/backups/` 存在滚动备份，迁移日志第一行是「已备份到 …」
- 双开 CLI + Web 得到明确的单实例报错而非静默并行
- 睡眠/启动日志能看到各表行数与 GC 物理删除数

---

## 7. 相关文档

- `../self-system.md` — 统一架构：记忆是自我状态组件，本文档是其存储地基
- `../layer1-memory/plan.md` — 新旧表双写与旧表删除路线（本方案 P0-3 是其前置，已完成）
- `../layer1-memory/sleep-cycle.md` — Stage 3 GC：物理回收的统一调度窗口
- `../layer1-memory/memory-agent.md` — 向量召回的消费方，依赖 P0-1 修复后的真实语义分
- `../layer6-personality/README.md` — 角色/session 绑定，依赖 P0-2 的存储层隔离
