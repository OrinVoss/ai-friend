# 修复 issue #336：_process_emotion 的 get_all()[-1] 无空防护

## 修改的文件
- `core/agent.py`

## 修改原因
`_process_emotion` 中 `self.short_term.get_all()[-1]` 无空防护；proactive 路径或 short_term 被清空时会 IndexError。

## 修改内容
- 取 turns 后判空，空则记 debug 并跳过本次 consolidation 触发。
- 验证：`pytest -k agent` 144 passed。
