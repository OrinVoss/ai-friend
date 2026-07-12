# Batch 1-3 修复：9 个 issue

## Batch 1：低风险

### 睡眠丢消息（#185）
- `core/message_handler.py` — 睡眠时记录用户输入到 short_term + DB，不再丢弃

### DB 关闭遗漏（#27）
- `web/session.py` — `shutdown()` 末尾添加 `await self.db.close()`

### CLI catch-all 缺 _reset_react（#29）
- `core/cli_controller.py` — `run()` except 块添加 `a._reset_react()`

### add_to_history=False 仍写 DB（#182）
- `core/agent.py` — `_react_loop()` 中 `insert_turn_sync` + `turn_count++` 移入 `if add_to_history:` 块

### ConversationBuffer 无大小限制（#176）
- `memory/short_term.py` — 添加 `MAX_TURN_LENGTH=10000`，超长截断

## Batch 2：中风险

### Rate limit 副作用前置（#239）
- `core/proactivity.py` — `check_rate_limit()` 拆为只读检查 + `record_rate_limit()` 发送后调用
- `web/server.py` — `_proactive_loop` 在成功发送后调 `record_rate_limit()`

### Tool 基类 async/sync LSP 破坏（#242）
- `tools/traits.py` — 基类 `execute` 改为 `def`（同步）
- `core/dispatcher.py` — 删 `inspect.iscoroutinefunction` 分支，移 `import inspect`，删除未使用的 `import run_async`

### Prompt .format() 安全（#243）
- `prompts/templates.py` — 添加 `safe_format()`（try/except 保护），修正 FACT 格式描述
- `memory/consolidation.py` — 全部 4 处 `.format()` 替换为 `safe_format()`
- `memory/retrieval.py` — 1 处替换

## Batch 3：小改进

### 梦境事件被挤出（#105）
- `models/personality.py` — `record_emotion_event()` 超过 20 条时优先删除非梦境事件

### max_tool_iterations 可配置（#152）
- `config.py` — 添加 `max_tool_iterations: int = 5` 字段 + 环境变量映射
- `core/agent.py` — 从 config 读取，默认 5

## 已关闭 Issue
#185 #27 #29 #176 #239 #242 #243 #105 #152
