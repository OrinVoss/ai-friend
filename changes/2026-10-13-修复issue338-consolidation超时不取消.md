# 修复 issue #338：consolidation LLM 超时后 future 不取消

## 修改的文件
- `memory/consolidation.py`

## 修改原因
`_call_llm` 的 `future.result(timeout=...)` 超时后 LLM 调用仍在线程池里跑完，超时批次还会在下一次重试，可能造成 LLM 请求堆积。

## 修改内容
- TimeoutError 分支调用 `future.cancel()`（已在运行的无法取消，但未开始的可以）。
- 验证：`pytest -k consolidat` 45 passed。
