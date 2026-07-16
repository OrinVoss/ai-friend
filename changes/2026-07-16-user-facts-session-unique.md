# user_facts 唯一约束迁移：UNIQUE(session_id, category, fact_key)（#UK-001）

对应 `doc/known-issues.md` 条目 7 与 `doc/refactor/systems/database.md` P0-2 的新发现。依赖 P0-3 自动备份（已于本次会话先行落地）。

## 问题

`user_facts` 建表时的唯一约束是 `UNIQUE(category, fact_key)`，`session_id` 列是后来 ALTER 补的，约束没有跟着迁移。两个 session 写入同一 `(category, fact_key)` 时，后写一方命中 `ON CONFLICT`，把另一个 session 的行原地覆盖——事实跨 session 串味。多角色共存（一角色一 session）落地后这是日常事故而非边缘情况。

## 改动

- `storage/database.py`
  - `CURRENT_SCHEMA_VERSION` 2 → 3（生产库当前为 v2，下次启动经 P0-3 通道**先自动备份再迁移**）
  - 新建库的 `CREATE TABLE user_facts` 直接采用完整列集 + `UNIQUE(session_id, category, fact_key)`（约束引用 session_id，列必须随表同建，不能再靠 ALTER 后补）
  - 新增 #UK-001 迁移块：检测 `sqlite_master` 中旧约束文本 → `RENAME` 旧表 → 新约束建表 → 全列显式搬迁（`COALESCE(session_id, 'default')`）→ 删旧表。旧约束下不可能存在跨 session 重复 key，搬迁必然安全
  - 迁移位于 ALTER 循环之后、索引重建之前，旧表索引随 DROP 消失、末尾脚本自动重建
- `storage/repository.py`
  - `upsert_fact` 两处 `ON CONFLICT(category, fact_key)` → `ON CONFLICT(session_id, category, fact_key)`（与约束列序一致）
- `tests/test_user_facts_unique_migration.py`（新建，3 用例）：
  - 新库直接带新约束
  - v2 旧库迁移后约束更新、数据保留、版本 stamp 为 3
  - 核心行为：两个 session 同 key 各自独立共存，B 降 confidence 不影响 A 的行（修复前会串）
- `doc/known-issues.md`：条目 7 标记已修复
- `doc/refactor/systems/database.md`：P0-2 新发现标记已修复

## 测试

- 新增 3 用例 + 相关 repository/backup 测试共 28 过
- 全量：`python -m pytest tests --ignore=tests/real_api -q` → **417 passed, 2 skipped**（基线 414）

## 影响面

- 单 session（当前实际使用）行为不变：同 session 同 key 仍然 upsert 合并
- 多 session 不再互相覆盖；`facts_v2` 本来就是这个约束，新旧两表语义对齐
