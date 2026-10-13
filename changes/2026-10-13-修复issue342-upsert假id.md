# 修复 issue #342：upsert_fact_v2 冲突更新返回假 id

## 修改的文件
- `storage/repository.py`

## 修改原因
ON CONFLICT 更新路径下 `c.lastrowid` 不可靠，可能不是冲突行的真实 id。`lifecycle.promote_fact` 把假 id 写进返回的 FactV2.id，后续按 id 更新会静默失败。

## 修改内容
- upsert 后按 `(session_id, category, fact_key)` 显式 SELECT 真实 id；查不到时记 warning 并回退 lastrowid。
- 验证：`pytest -k "repository or fact or lifecycle"` 122 passed。
