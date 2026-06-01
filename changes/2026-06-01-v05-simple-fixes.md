# 2026-06-01 — v0.5 简单修复批次

## 修改文件

- **storage/repository.py** — 9 个写方法加 `await self.db.commit()`（update_fact_score, increment_fact_recall, deactivate_fact, update_fact_confidence, insert_experience, update_experience_score, insert_reflection, prune_experiences, prune_reflections）
- **memory/long_term.py** — 删除重复 `store_fact` 前向引用定义（#193）
- **memory/short_term.py** — `add_turn` Turn 构造移入 `with self._lock` 内（#245）
- **tools/notify_tool.py** — PowerShell 转义修正为双单引号（#240）+ 异常加 `logger.warning`（#264）

## 解决的 issue

| # | 优先级 | 修复 |
|---|--------|------|
| #201 | P0 | repo 写方法全部加 commit() |
| #193 | P1 | 删除重复 store_fact 定义 |
| #245 | P1 | turn_id 竞态修复 |
| #240 | P1 | PowerShell 注入修复 |
| #264 | P2 | notify 异常日志 |
