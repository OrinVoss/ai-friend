# 修复 issue #320：grep 缓存键缺失 context 参数

## 修改的文件
- `tools/search_tools.py`

## 修改原因
`GrepTool.execute` 的搜索结果缓存键不含 `context_lines`，但输出内容（匹配行上下文行）由它决定。同一 pattern 先以 context=2 搜索，60 秒内再以 context=0 搜索会命中缓存返回带上下文的错误结果。

## 修改内容
- 将 `context_lines` 加入 grep 缓存键（tools/search_tools.py:253）。
