# 修复 #160：系统提示词重复构建与 Agent 1 固定调用

## 问题

Issue #160 指出单次请求会重复构建系统提示词 3-5 次（Agent 1、Agent 2、Agent 3、探索模式），导致：

- `build_system_prompt()` 单次调用涉及人格序列化、情绪描述、关系数据、长期记忆等，字符量 15000-40000。
- Agent 1 / Agent 2 / Agent 3 各自重建完整人格/情绪/记忆上下文。
- Agent 1 即使面对"你好"等简单输入也发起完整 LLM 调用。
- 静态对话示例每轮重复发送，占 system prompt 约 25.6%。

## 改动

### 新增分层提示词缓存

- 新建 `core/prompt_cache.py`：
  - 键：`(session_id, personality_version, component_name)`
  - `personality_version` 取 personality 文件 `mtime:size:path`，角色文件修改自动失效缓存。
  - 静态块（identity、examples、instructions、tools）无 TTL。
  - 慢变块（relationship、memory）TTL 可配置，默认 60 秒。
  - 动态块不缓存。

### 拆分 `prompts/system.py`

- `build_system_prompt()` 拆分为内部组件函数：
  - 静态：`_build_identity_block`、`_build_examples_block`、`_build_internal_tools_block`、`_build_output_rules_block`
  - 慢变：`_build_relationship_block`、`_build_memory_block`
  - 动态：`_build_emotion_block`、`_build_resentment_block`、`_build_emotion_events_block`、`_build_dreams_block`、`_build_tool_history_block`、`_build_consecutive_negative_block`、`_build_instructions_block`
- `build_inner_drive_prompt()` 同样拆分，静态/慢变块与 Agent 3 共享缓存。
- `build_system_prompt()` 新增可选参数：`session_id`、`prompt_cache`、`personality_file`、`prompt_cache_ttl`、`memory_context_summary`、`demo_turns_remaining`。
- `_build_examples_block()` 仅在 `demo_turns_remaining > 0` 时注入示例，保留 `None` 时向后兼容（始终显示）。

### 改造 `core/inner_drive.py`

- `InnerDriveResult` 新增 `context_summary: str` 字段。
- `InnerDriveAgent` 新增参数：`session_id`、`prompt_cache`、`prompt_cache_ttl`、`short_input_threshold`。
- `assess()` 新增短输入快速返回逻辑 `_should_skip_llm()`：
  - 输入长度 < `agent1_short_input_threshold`
  - 不含工具关键词（URL、搜索、文件、音乐、通知等）
  - 最近 2 轮无成功工具调用
  - 满足时直接返回 `needs_external_tools=false`，跳过 LLM。
- `assess()` / `review()` / `re_decide()` / `assess_agent3_intent()` 复用 `prompt_cache`。
- `assess()` 返回前把慢变块格式化结果写入 `context_summary`。

### 改造 `core/message_handler.py`

- `MessageHandler` 初始化时创建进程级 `PromptCache` 实例。
- `_ensure_inner_drive()` 向 `InnerDriveAgent` 传入 `session_id`、`prompt_cache`、`prompt_cache_ttl`、`short_input_threshold`。
- `_run_agent3()` 接收 `drive_result.context_summary`：
  - 非空时直接作为 Agent 3 的关系/记忆块，不再调用 `retriever.retrieve_for_query()`。
  - 空时保持原逻辑。
- `handle_message()` / `handle_proactive()` / `handle_explore()` 调用 `build_system_prompt()` 时传入 `session_id`、`prompt_cache`、`personality_file`、`prompt_cache_ttl`、`demo_turns_remaining`。

### Web 层

- `web/session.py`：创建 Agent 后设置 `agent.personality_path = self.personality_path`，使缓存失效键准确对应当前角色文件。

### 配置

- `config.py` 新增字段：
  - `prompt_cache_ttl_seconds: int = 60`
  - `agent1_short_input_threshold: int = 20`
  - `conversation_examples_max_turns: int = 3`
- 新增环境变量覆盖：
  - `AI_FRIEND_PROMPT_CACHE_TTL`
  - `AI_FRIEND_AGENT1_SHORT_INPUT_THRESHOLD`
  - `AI_FRIEND_CONVERSATION_EXAMPLES_MAX_TURNS`
- `config.json` 与 `config.example.json` 同步新增上述配置项。

### 测试

- 新建 `tests/test_prompt_cache.py`：
  - 静态块无 TTL
  - 慢变块 TTL 过期后重建
  - personality 文件变更后缓存失效
  - invalidate / clear
- 修改 `tests/test_inner_drive.py`：
  - 短输入直接跳过 LLM
  - 含 URL 的短输入不跳过
  - 最近有工具调用时短输入不跳过
  - `context_summary` 非空
- 修改 `tests/test_message_handler.py`：
  - Agent 3 收到 `drive_result.context_summary` 后不再重复检索记忆
  - 示例块在超过阈值后被省略

### 文档

- `doc/architecture.md`：新增"提示词缓存与 Agent 上下文复用"小节。
- `doc/config-reference.md`：新增三个配置项说明及环境变量。
- `doc/known-issues.md`：#160 标记为已修复，并附修复记录。

## 验证

- 单元测试：`pytest tests/test_prompt_cache.py tests/test_inner_drive.py tests/test_message_handler.py -v` → 55 passed
- 全量测试：`pytest tests --ignore=tests/real_api -q` → 376 passed, 1 warning

## 相关文件

- `core/prompt_cache.py`（新建）
- `prompts/system.py`
- `core/inner_drive.py`
- `core/message_handler.py`
- `web/session.py`
- `config.py`
- `config.json`
- `config.example.json`
- `tests/test_prompt_cache.py`（新建）
- `tests/test_inner_drive.py`
- `tests/test_message_handler.py`
- `doc/architecture.md`
- `doc/config-reference.md`
- `doc/known-issues.md`
- `changes/2026-07-14-fix-160-prompt-cache.md`

## 提交

```
fix #160: hierarchical prompt cache + Agent 1 context summary + short input skip
```
