# 修复 issue #330：dispatcher 参数规范化/校验无异常防护

## 修改的文件
- `core/dispatcher.py`

## 修改原因
`_execute_single` 中 `tool.normalize_args()` 与 `tool.parameters_schema()` 不在任何 try 内。工具实现的这两个方法抛异常时，并行收集处 `f.result()` 把异常传播到 `execute_tool_calls` 调用方，同批已成功执行的工具结果全部丢失。

## 修改内容
- normalize/validate 段包 try/except，异常时记日志并返回该工具的 fail 结果（ERROR_TYPE_INTERNAL），不影响同批其他工具。
- 验证：`pytest -k "dispatcher or dispatch"` 50 passed。
