# 修复 issue #352：MonitorBuffer max_size=0 无界增长

## 修改的文件
- `core/monitor.py`

## 修改原因
`max_size<=0` 曾意为"不限制"，但记录的是完整请求/响应 JSON，长跑进程下是确定性内存泄漏。

## 修改内容
- `__init__` 与 setter 中 `max_size<=0` 记 warning 并回落默认值 200。
- 更新模块 docstring。
- 验证：`pytest -k monitor` 2 passed。
