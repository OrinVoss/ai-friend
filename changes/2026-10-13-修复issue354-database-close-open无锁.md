# 修复 issue #354：Database.close/open 无锁无防重入

## 修改的文件
- `storage/database.py`

## 修改原因
`close()` 无锁，可在别的线程 cursor 持锁执行中关闭连接；`open()` 重复调用静默覆盖 `self.conn`，泄漏旧连接。

## 修改内容
- `open()` 防重入：已打开时 raise RuntimeError。
- `close()` 持 `_lock` 执行，确保无进行中的事务。
- 验证：`pytest -k "database or backup or repository"` 45 passed。
