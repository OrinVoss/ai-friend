# 修复 issue #364：WS handler request_id_var 只 set 不 reset

## 修改的文件
- `web/server.py`

## 修改原因
WS handler 每条 message 帧 `request_id_var.set(...)` 但从不 reset，同一协程反复 set 覆盖旧值。

## 修改内容
- set 持 token，message 分支 finally 中 reset（continue 路径也覆盖）。
- 验证：`pytest -k "web or server"` 41 passed, 2 skipped。
