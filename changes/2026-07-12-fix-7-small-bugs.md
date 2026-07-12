# 修复 7 个小工作量 bug

## #178 — DB 日志轮转 + 数据清理
- `storage/database.py` — 添加 `prune_old_turns(keep_max=1000)` 方法，按 session 保留最近 N 条对话记录

## #148 — Session 定期清理
- `web/server.py` — lifespan 中添加 `_periodic_cleanup()` 后台任务，每 5 分钟调 `cleanup_old()`

## #157 — DB 索引 + integrity_check
- `storage/database.py` — 修复 `PRAGMA integrity_check` 结果读取（之前只捕异常不读行）；添加 5 条 CREATE INDEX（session_id + 常用过滤列）

## #42 — 情绪极限检测
- `models/personality.py` — `shift()` 中情绪值到 ±1.0 硬阈值时记录 warning（`decay()` 自然恢复）

## #110 — 输入注入防护
- `core/message_handler.py` — 添加 `_sanitize_input()` 函数：过滤 system/assistant 角色覆盖尝试，限制最大 10000 字符

## #44 — 减少 personality.json 写盘频率
- `web/session.py` — 添加 `_save_personality_debounced()`，30s 内只写一次；替换全部 3 处直接 `personality.save()`

## #284 — 横切扫描
- 扫描结果：无 bare `except:`，全部使用 `except Exception:`

## 关闭 Issue
#178 #148 #157 #42 #110 #44 #284
