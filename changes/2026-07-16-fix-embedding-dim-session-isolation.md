# 修复两个 P0 存储层 bug：语义检索维度 + session 隔离

对应 `doc/refactor/systems/database.md` 的 P0-1、P0-2（系统摸底发现的活 bug，本次优先修复）。

## 改动摘要

- **P0-1 语义检索静默失效**：`bytes_to_vec` 默认维度写死 512，而生产库全部 BLOB 为 1024 维 → 每次解码抛 `ValueError` 被 `except: pass` 吞掉 → 语义分恒为 0，混合检索（语义 0.6 + 关键词 0.4）实际一直在纯关键词模式下运行，日志无一字提及。此为 2026-06-01 就立案的 RT-007，本次修复。
- **P0-2 跨 session 数据泄漏**：`get_similar_facts()` 无 `session_id` 过滤，consolidation 矛盾检测命中后可经 `deactivate_fact()` 按 id 软删**别的角色**的事实。

## 涉及文件

- `memory/embeddings.py`
  - `bytes_to_vec(data, dim=None)`：`dim=None` 时按 BLOB 实际长度推断；传入 dim 才校验，维度不符抛 `ValueError`（失败显性化，不再靠默认值猜）
- `memory/retrieval.py`
  - `_hybrid_score()` / `_search_experiences_semantic()` 两个调用点显式传 `dim=len(qvec)`——查询向量的长度就是点积的硬性要求
  - 静默 `except: pass` 改为逐条 debug + 每次检索一条汇总 warning（`N/M embeddings unusable`），「静默 0 分」变「日志可见」
- `storage/repository.py`
  - `get_similar_facts()` 加 `AND session_id = ?`（与同文件其他查询对齐）
  - `deactivate_fact()` 加 `AND session_id = ?`，`rowcount == 0` 时记 warning（跨 session id 写不进去，且留下痕迹）
- `tests/test_retrieval.py`
  - `TestBytesToVecDim`：1024 维 roundtrip、显式 dim 匹配/不匹配
  - `TestHybridScoreSemanticDim`：1024 维语义分真正参与排序（对齐向量排第一）；维度不符时 warning + 安全降级不崩溃
- `tests/test_repository.py`
  - `test_get_similar_facts_session_isolated`：他 session 事实不泄漏
  - `test_deactivate_fact_other_session_noop`：他 session 的 id 无法被本 session 软删

## 顺带发现（未修，已记录）

1. **`user_facts` 唯一约束缺 session_id**：schema 为 `UNIQUE(category, fact_key)`（`storage/database.py:113`），两个 session 写同一 key 会触发 `ON CONFLICT` 把**另一个 session 的行**原地覆盖。修复需迁移唯一约束为 `(category, fact_key, session_id)`，属 schema 变更，留待 database.md P0-3 备份落地后一起做。
2. **Experience 的语义检索路径是死代码**：`insert_experience` 写入了 embedding 列，但 `_row_to_experience`（`storage/repository.py:604`）从不读回，`retrieval.py` 的 `hasattr(exp, 'embedding')` 恒为 False。向量写了没人用——要么接线，要么停止写入，归 Layer 1 二期决策。
3. **其余按 id 写的方法未加 session 校验**：`update_fact_confidence` / `update_fact_score` / `increment_fact_recall` / facts_v2 三个写方法（database.md 增强方案第 3 条），本次只堵了危害最大的 `deactivate_fact`。

## 未做（database.md P0 剩余项）

- 启动自检（open 后抽样 BLOB 与 `encode_single` 点积验证）
- `embedding_version` 接线（版本不匹配的行跳过 + 滚动重嵌入）
- 数据库自动备份（P0-4，必须先于 Layer 1 二期旧表迁移）

## 测试

- 新增 7 个回归测试全部通过
- 全量：`python -m pytest tests --ignore=tests/real_api -q` → **408 passed, 2 skipped**（基线 401）
