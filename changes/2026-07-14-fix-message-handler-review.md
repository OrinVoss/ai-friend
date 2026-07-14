# 修复 MessageHandler 审查问题

## 背景

`doc/known-issues.md` 第 5 节记录了对 `core/message_handler.py` 的审查结论。本次按优先级修复其中四项：封装性、错误恢复、魔法数字、输入清洗。

## 改动

### 1. `core/agent.py`：为 `Agent` 添加公开方法

避免 `MessageHandler` 直接操作 `Agent` 内部属性：

- `add_turn(role, content, metadata=None)` —— 同时写入 `short_term` 和 `ltm.repo`。
- `record_tool_call(name, success, output)` —— 追加工具调用记录并维护 20 条滚动窗口。
- `increment_turn_count()`
- `update_last_activity()`
- `set_current_input(user_input)`
- `get_compressed_summary()`
- `get_consecutive_negative()`
- `compress_context(messages)`

`Agent._react_loop()` 也改为调用这些公开方法。

### 2. `core/message_handler.py`：使用公开方法并提取常量

- 使用 `Agent` 公开方法替代对 `short_term`、`ltm.repo`、`_tool_call_history`、`_context` 的直接访问。
- 提取类常量：
  - `MAX_AGENT2_ROUNDS = 3`
  - `TOOL_RECORDS_MAX_LENGTH = 3000`
  - `TOOL_HISTORY_MAX_SIZE = 20`
  - `MAX_INPUT_LENGTH = 10000`
  - `CONV_HIST_MAX_TOKENS = 1800`

### 3. 改进 Agent 2 异常处理

Agent 2 多轮工具循环的 `except Exception` 不再只记录日志，而是生成错误摘要：

```
[工具执行阶段出现异常：XXXError，已降级为直接回复]
```

该摘要会被注入 Agent 3 的 `tool_records`，让最终回复能反映降级情况。

### 4. 增强 `_sanitize_input`

改用正则表达式匹配 prompt injection 模式，支持：

- `system:` / `assistant:` / `user:` 及其全角变体
- `ignore previous` / `from now on` / `forget previous` 等英文变体
- `忽略以上` / `忘记之前的` / `请忽略` 等中文变体

### 5. `_build_messages` 可读性

将 `a = self.a` 改为 `agent = self._agent`，并补充注释说明 token 预算耗尽即停止遍历。

## 测试

- `pytest tests/test_message_handler.py -v` → **18 passed**
- `pytest tests --ignore=tests/real_api -q` → **376 passed, 1 warning**

## 相关文件

- `core/agent.py`
- `core/message_handler.py`
- `tests/test_message_handler.py`
- `doc/known-issues.md`
- `changes/2026-07-14-fix-message-handler-review.md`

## 提交

```
refactor(message_handler): improve encapsulation, error recovery, constants, sanitization
```
