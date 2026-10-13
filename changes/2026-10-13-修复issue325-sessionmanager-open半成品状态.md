# 修复 issue #325：SessionManager.open() 失败留下半成品 db

## 修改的文件
- `web/session.py`

## 修改原因
`open()` 先 `self.db = Database(...)` 赋值再 `await self.db.open()`；若后者抛异常，`self.db` 已非 None，而后续初始化判断都以 `self.db is None` 为准，导致永远不再重试，所有请求在坏 db 上持续报错。

## 修改内容
- 先把 Database 放进局部变量，`db.open()` 成功后再赋给 `self.db`。
- 验证：`pytest -k "session or web"` 77 passed。
