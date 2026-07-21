# A8：归档表物理删除（schema v6）+ A 批收尾

日期：2026-07-21

## 背景

Layer 1 两次切换（v4 user_facts→facts_v2、v5 reflections→insights_v2）各留了一张归档表（`user_facts_archive` / `reflections_archive`）供观察期回滚。数据已全部迁移到新表且生产验证通过，观察期结束，物理删除。

## 改动

- `storage/database.py`：`CURRENT_SCHEMA_VERSION` 5 → 6。v6 迁移块：版本落后时 `DROP TABLE IF EXISTS` 两张归档表。
  - **安全性**：P0-3 在版本落后时先自动 `VACUUM INTO` 备份到 `data/backups/`，归档数据有副本；新表数据已生产验证。
  - **踩坑**：v6 块必须重新查 `sqlite_master`——v4/v5 的 RENAME 在本次 `initialize()` 内才发生，开头的 `existing_tables` 快照里还没有 `_archive` 名字，用旧快照会静默跳过 DROP（迁移测试抓到）。
- 迁移测试断言同步 v6 语义（归档表不存在 + version=6）：`test_facts_v2_v4_migration.py`、`test_insights_v2_v5_migration.py`、`test_user_facts_unique_migration.py`。
- 文档同步：README（表清单 + 生命周期段）、`doc/architecture.md`（9 表段）、`doc/refactor/progress.md`（GC 完整 + DROP 打勾）。

## 验证

- 三个迁移测试文件 9 用例全绿
- 全量 `pytest tests --ignore=tests/real_api -q`：**793 passed + 2 skipped**

## A 批（剩余问题处理）全部完成

| 项 | commit | 内容 |
|----|--------|------|
| A1 | f14293e | Web 可选 token 鉴权 |
| A2 | cc76933 | Provider 截断显式化（TruncatedResponseError + monitor 字段） |
| A3 | ce253ab | request_id 全链路（ContextVar + run_async 传播 + monitor 关联） |
| A4 | 7a05049 | 人格校验器 + .bak last-known-good 时机 |
| A5 | 1d51e78 | GC 语义近重复合并（merge_duplicates） |
| A6 | f6daa07 | 情绪按真实时间衰减（读时结算） |
| A7 | （文档关闭） | Agent 3 prompt 块按 L2-3 结论全保留，代码已一致 |
| A8 | 本次 | 归档表物理 DROP（schema v6） |
