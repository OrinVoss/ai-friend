# 记录 MessageHandler 三层编排审查问题

## 背景

对 `core/message_handler.py` 进行了一次代码审查，发现三层 Agent 编排实现虽然功能完整，但在封装性、错误恢复、可配置性、可测试性等方面存在改进空间。本次不修改代码，仅将审查结论写入 `doc/known-issues.md` 以便后续跟进。

## 记录内容

新增 `doc/known-issues.md` 第 5 节："MessageHandler 三层 Agent 编排的封装与错误恢复问题"。

主要问题包括：

1. **状态管理混乱**：`MessageHandler` 直接操作 `Agent` 内部属性（`_tool_call_history`、`short_term`、`ltm.repo` 等），破坏封装。
2. **异常处理不完整**：Agent 2 循环的 `except Exception` 仅记录日志并回退到 Agent 3，未向用户暴露错误。
3. **魔法数字过多**：`MAX_AGENT2_ROUNDS = 3`、截断长度 3000、工具历史 20 条等硬编码。
4. **`_run_agent3` 与 `_handle_agent3_intent` 职责重叠**：存在循环解析 JSON 意图的递归风险。
5. **`_build_messages` 效率问题**：每次调用重新遍历完整历史消息。
6. **工具注册表隔离不完整**：内部工具（recall/remember）与外部工具共享实例引用。
7. **`_sanitize_input` 过于简单**：仅匹配完全相等的注入模式。
8. **缺少超时控制**：Agent 2 重试循环无全局超时。

并给出改进建议：提取配置类、引入状态机、依赖注入、定义 `ToolExecutionResult`、添加 fallback 异常类型、收集性能指标等。

## 相关文件

- `doc/known-issues.md`
- `changes/2026-07-14-record-message-handler-review.md`

## 提交

```
docs: record MessageHandler review findings in known-issues.md
```
