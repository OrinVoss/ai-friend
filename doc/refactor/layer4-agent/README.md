# Layer 4: Agent Runtime 解耦

## 目标

解决 `MessageHandler` 直接操作 `Agent` 内部属性、状态管理混乱、异常处理不完整、魔法数字过多等问题。

## 当前状态

未开始。

## 关键问题

- `MessageHandler` 直接操作 `a._xxx` 内部属性
- 异常捕获后没有通知用户或重新抛出
- `MAX_AGENT2_ROUNDS`、截断长度等硬编码
- `_run_agent3` 和 `_handle_agent3_intent` 职责重叠，有递归循环风险
- 工具注册表隔离不完整

## 预期方向

1. 为 `Agent` 添加公开方法：`add_turn()`、`record_tool_call()` 等
2. 提取 `MessageHandlerConfig`
3. 引入状态机抽象 Agent 1/2/3 流转
4. 分离工具执行结果为 `ToolExecutionResult` dataclass
5. 添加全局超时机制

## 依赖

- Layer 3 确定不同 Agent 的 Context 边界后，状态机才能设计准确
