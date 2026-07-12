# Batch 6 修复：P2/P3 Storage + Memory（6 个）

## B6-1 repository.py session_id 过滤（#248）
- `storage/repository.py` — `insert_experience`/`insert_reflection` 添加 `session_id`；`search_experiences`/`get_recent_experiences`/`get_recent_reflections` 添加 `AND session_id = ?`；`get_all_relationships`/`upsert_relationship` 添加 `session_id`；`prune_facts`/`prune_experiences`/`prune_reflections` 添加 `AND session_id = ?`

## B6-2 database.py WAL 自动检查点（#247）
- `storage/database.py` — 添加 `PRAGMA wal_autocheckpoint=1000`

## B6-3 embeddings TOCTOU 竞态（#253 partial）
- `memory/embeddings.py` — `EmbeddingEngine` 添加 `_encode_lock`；`encode()` 内持有锁后委托 `_encode_locked()`，防止并发 cache-miss → API 重复请求

## B6-4 consolidation 内部 import 提升（#252）
- `memory/consolidation.py` — 将 `FactChecker`、`EmbeddingEngine`、`UserFact`、`run_async` 从局部导入提升到模块顶部；删除 4 处重复/局部 import

## B6-5 / B6-6 long_term / short_term 清理
- 代码当前已较干净，无重大清理项

## 验证
- 全部 4 文件通过 `py_compile`

## 关闭 Issue
#248、#247、#253（partial）、#252
