# 修复 issue #353：backup() 在锁外 commit

## 修改的文件
- `storage/database.py`

## 修改原因
`backup()` 的 `await self.commit()` 在 cursor 锁外执行，可能把另一线程正在进行的写事务提交成半状态。

## 修改内容
- commit 移入 cursor 锁内，随后同一锁内执行 VACUUM INTO。
- 验证：`pytest -k "backup or database"` 10 passed。
