# Batch 4 修复：6 个 P1 剩余 bug

## B4-1 合并记录长度上限（#179 partial）
- `core/message_handler.py` — `combined_records` 和 `tool_records` 添加 3000 字符上限，超出截断并提示

## B4-2 Consolidation LLM 超时（#184 partial）
- `memory/consolidation.py` — 添加 `timeout` 参数（默认 60s）；添加 `_call_llm()` 包装方法（使用 `_EXECUTOR.submit` + `future.result(timeout)`），替换全部 6 处 `self.llm()` 调用

## B4-3 连接超时与读取超时分离（#174）
- `core/provider.py` — `timeout=self.timeout` 改为 `timeout=(10, self.timeout)`（连接 10s，读取保持配置值）

## B4-4 Sleep cooldown 机制（#167 partial）
- `core/sleep_manager.py` — 添加 `_last_transition_time` + `_MIN_SLEEP_INTERVAL=600s`，在 critical section 开头检查；所有 4 个过渡点记录时间戳

## B4-5 ToolRegistry 权限元数据（#183）
- `tools/traits.py` — `Tool` 基类添加 `required_permissions: list[str] = []`；`ToolRegistry` 添加 `check_permission(name, user_role)` 方法

## B4-6 schema_version + SQL 白名单（#215）
- `storage/database.py` — 添加 `ALLOWED_ALTERATIONS` 集合做白名单校验；`initialize()` 中读取 `SELECT MAX(version) FROM schema_version` 检查版本

## 验证
- 全部 6 文件通过 `py_compile`
- 测试通过

## 关闭 Issue
#179（partial）、#184（partial）、#174、#167（partial）、#183、#215
