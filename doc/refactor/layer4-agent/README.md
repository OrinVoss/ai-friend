# Layer 4: Agent Runtime 解耦

## 目标

解决 `MessageHandler` 直接操作 `Agent` 内部属性、状态管理混乱、异常处理不完整、魔法数字过多等问题。

## 当前状态

**部分已完成**：

- [x] 状态机抽象：`MessageHandlerState` enum + `_transition()`
- [x] `ToolExecutionResult` dataclass
- [x] 魔法数字提取为类常量：`MAX_AGENT2_ROUNDS`、`TOOL_RECORDS_MAX_LENGTH`、`TOOL_HISTORY_MAX_SIZE`、`MAX_INPUT_LENGTH`、`CONV_HIST_MAX_TOKENS`
- [x] Agent 1 工具注册表隔离：`_make_internal_registry()` 仅保留 recall/remember
- [x] Agent 2 外部工具注册表：`_make_external_registry()`
- [x] `_run_agent2()` / `_run_agent2_single_round()` 职责分离

## 关键提交

- `7126df9` — refactor(message_handler): state machine, ToolExecutionResult, tool registry isolation

## 关键类

```python
class MessageHandlerState(Enum):
    IDLE = auto()
    ASSESSING = auto()
    EXECUTING_TOOLS = auto()
    HANDLING_INTENT = auto()
    GENERATING_RESPONSE = auto()
    ERROR_FALLBACK = auto()
    DONE = auto()

@dataclass
class ToolExecutionResult:
    records_text: str
    total_calls: int
    success_count: int
    has_error: bool
    error_message: str
    elapsed_ms: float
```

## 剩余工作

- [ ] `MessageHandler` 仍直接访问 `a._tool_call_history` 等内部属性，需要为 `Agent` 添加公开方法
- [ ] 异常处理：错误时应向用户体现，而不是静默吞掉
- [ ] 全局请求超时控制
- [ ] 依赖注入：`MessageHandler` 直接构造 `InnerDriveAgent` / `ToolAgent`，测试不便
- [ ] `_sanitize_input` 过于简单，无法防御变体注入

## 设计文档

- `proactive-think-loop.md` — Agent 1 主动沉思循环设计（待实现）：主动路径加有界思考循环，响应路径不动
- `inner-drive-state.md` — 内驱状态设计（待实现）：Agent 的「内心世界」，挂念/好奇/反思/计划/灵感的类型化生命周期管理
- `solo-activity.md` — 独处活动与内化（待实现）：explore 等独处活动结束后生成第一人称感悟，沉淀为记忆/谈资/情绪

## 依赖

- Layer 3 确定不同 Agent 的 Context 边界后，状态机与注册表隔离才能更彻底
