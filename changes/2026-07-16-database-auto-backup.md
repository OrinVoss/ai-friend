# 数据库自动备份（P0-3）：迁移前 VACUUM INTO 快照

对应 `doc/refactor/systems/database.md` 的 P0-3（问题清单「数据库零备份，而迁移在每次启动时自动执行」）与增强方案第 4 条。这是唯一约束迁移、Layer 1 二期旧表迁移、三期删表等一切销毁性操作的前置。

## 改动摘要

`Database.open()` 在执行 `initialize()`（自动迁移）之前检测：数据库文件在连接前已存在且非空、且 `schema_version` 落后于 `CURRENT_SCHEMA_VERSION`（即本次启动确定要跑迁移）时，先自动 `VACUUM INTO` 一份一致性快照到 `data/backups/`。新库和已是最新版本的库正常打开、不产生备份。

## 涉及文件

- `storage/database.py`
  - 新增类常量 `CURRENT_SCHEMA_VERSION = 2`，`initialize()` 的版本 stamp 改为引用它（消除硬编码 2 与备份判断漂移的风险）
  - `Database.__init__` 新增 `backup_enabled: bool = True`、`backup_keep: int = 5`
  - `open()` 在 `aiosqlite.connect` **之前**记录文件是否已存在且非空（connect 会即时创建文件，之后才检查会把新库误判为旧库——已踩过并修复）
  - 新增 `_backup_before_migration(pre_existing)`：enabled + 文件库 + 预先存在 + 版本落后 → 备份
  - 新增 `backup()`：`VACUUM INTO '<db_dir>/backups/<stem>.YYYYMMDD-HHMMSS.db'`（备份与空间回收一步完成，产物是一致性快照）；同秒文件名碰撞自动加 `-1/-2` 后缀
  - 新增 `_rotate_backups()`：按 **mtime** 排序滚动删除超出 `backup_keep` 的最旧备份（碰撞后缀不按字典序排，故不用文件名排序）
- `config.py`：新增 `db_backup_enabled: bool = True`、`db_backup_keep: int = 5`（不进 env_map——现有 env 加载对 bool 字符串转换有坑，与 `use_observation_fact` 同样仅走 config.json）
- `main.py` / `web/session.py`：装配时把备份配置传入 `Database`
- `config.example.json`：新增两个键
- `tests/test_database_backup.py`（新建，6 用例）：
  - 旧版本库 open 触发备份；备份是迁移前快照（含旧表、不含新表）
  - 版本最新不备份；禁用不备份；`:memory:` 不备份不报错
  - 连续备份滚动保留最新 N 份
- `doc/refactor/systems/database.md`：P0-3 标记已修复；顺手修正编号不一致（备份在「关系/相关文档」节被误写为 P0-4、session 隔离被误写为 P0-3）
- `doc/config-reference.md`：记忆系统表新增两个字段
- `README.md`：其他特性新增一条

## 设计说明

- **为什么按版本而不是每次 open 都备份**：备份的意义是给销毁性迁移一个回滚点。版本落后的 open == 即将执行迁移，此时备份；版本最新说明无迁移风险，日常启动不产生冗余文件。
- **为什么用 `VACUUM INTO`**：单语句产出独立的、已压缩的一致性快照，WAL 模式下安全；同时顺带完成空间回收。
- **失败行为**：备份失败只记 warning 并继续启动（备份是保险丝，不应成为启动阻塞点）；旧库无 `schema_version` 表按 version 0 处理，保证第一次迁移前一定有备份。

## 测试

- 新增 6 用例全部通过
- 全量：`python -m pytest tests --ignore=tests/real_api -q` → **414 passed, 2 skipped**（基线 408）

## 后续（解锁项）

- `user_facts` 唯一约束迁移为 `UNIQUE(category, fact_key, session_id)`（schema 变更，已有回滚点）
- Layer 1 二期旧表数据迁移、三期删旧表
