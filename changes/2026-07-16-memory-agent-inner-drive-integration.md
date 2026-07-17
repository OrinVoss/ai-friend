# Memory Agent 接入 InnerDrive（use_memory_agent 灰度开关）

对应 `doc/refactor/layer1-memory/memory-agent.md` 7.1 的集成方案。Memory Agent 从「独立能力」变为「对话管线的记忆来源」——开关默认 false，灰度模式。

## 改动

- `config.py` / `config.example.json` / `doc/config-reference.md`：新增 `use_memory_agent: bool = false`
- `core/inner_drive.py`
  - `InnerDriveAgent` 新增可选参数 `memory_agent`
  - `assess()`：开关开启时一次 `memory_agent.answer(user_input)` 同时喂两个消费方——Agent 1 prompt 的记忆块（经 `build_inner_drive_prompt(memory_context_summary=...)`）和传给 Agent 3 的 `context_summary`；短输入路径同样走 MemoryAgent
  - 新增 `_context_summary_for()`：MemoryAgent 失败或返回空时**自动回退**到 `retriever.retrieve_for_query()` 旧路径（每次调用独立回退，不永久关停）
  - 新增 `_format_memory_answer()`：答案文本 + 显式置信度/矛盾标记（`⚠️ 矛盾记忆…需用户确认`、`证据不足，当作待确认信息`），让 Agent 1/3 把不确定的记忆当不确定处理
- `prompts/system.py`：`build_inner_drive_prompt` 新增 `memory_context_summary` 参数（与 `build_system_prompt` 的同款参数对齐）；提供时替换 relationship/memory 两个慢变块，`memory_context` 可为 None
- `core/message_handler.py`：`_ensure_memory_agent()` 装配（ltm + 新建 MemoryLifecycleManager + retriever + consolidator 的 embed），仅当 `use_memory_agent=true` 时注入 InnerDriveAgent
- `tests/test_memory_agent_integration.py`（新建，7 用例）：
  - 开关开：context_summary 与 Agent 1 prompt 都带 MemoryAnswer，retriever 不再被调
  - MemoryAgent 异常 → 自动回退 retriever
  - 开关关：旧路径不变
  - 短输入路径同样走 MemoryAgent（不调 LLM）
  - 格式化标记（矛盾/待确认）；MessageHandler 装配开关行为

## 灰度验证建议

`config.json` 设 `use_memory_agent: true` 后对比同一批问题（「我喜欢吃什么」「我们上次聊了什么」）在新旧路径下的回答质量，重点看：置信度标记是否合理、矛盾记忆是否被显式标注而非当作事实、回答是否更「有根据」。

## 测试

- 新增 7 用例全部通过
- 全量：`python -m pytest tests --ignore=tests/real_api -q` → **466 passed, 2 skipped**（基线 459）
