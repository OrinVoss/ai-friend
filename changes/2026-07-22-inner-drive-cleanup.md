# 重构：InnerDriveAgent 清理（intent 映射单一出处 + MemoryContextProvider 抽离）

日期：2026-07-22

## 改进点

针对 review 中提到的 5 项可改进之处，执行 2 项低风险、高收益的清理。

### 1. intent→tool 魔法字符串归一（prompts/tools_description.py）

- 原 `core/inner_drive.py:806-812` 硬编码 `{"play_music": "music_play", ...}`。
- `prompts/tools_description.py` 已有 `_TOOL_INTENT_ALIASES`（tool→intent），现派生反向映射 `INTENT_TO_TOOL`。
- Agent 1 直接引用 `INTENT_TO_TOOL`，正反向映射永不同步漂移。

### 2. MemoryContextProvider 抽离（core/memory_context_provider.py）

- 把 `inner_drive.py` 中 `_build_context_summary` / `_memory_answer_for` / `_context_summary_for` / `_format_memory_answer` 共 ~50 行记忆检索+格式化逻辑抽到独立类。
- 职责：
  - `answer_for`：同消息 R1 memo 缓存，避免 assess/review/re_decide 重复调用 `memory_agent.answer()`。
  - `summary_for`：Agent 1 全量记忆上下文（memory_agent → retriever fallback）。
  - `build_summary`：Agent 3 轻量关系/记忆块格式化。
  - `format_memory_answer`：向后兼容的 `ContextBuilder` 包装。
- `InnerDriveAgent` 保留薄委托，外部调用点（`MessageHandler`、测试）零改动。

## 不做的 3 项

- **拆 ProactiveThinkLoop / CareSurfacer**：主动循环与挂念浮现共享 ~12 个状态/依赖，硬拆会退化为传 context 对象或大量回调，不带来真实边界收益。
- **`execute_tool_calls` 内部导入**：recall 与外部工具共用 dispatcher 的超时/错误分类/参数校验，是有意复用。
- **正则兜底优化**：主路径是 JSON Schema，正则只是失败降级，投入产出不成比例。

## 结果

- `core/inner_drive.py`：929 → 898 行。
- 全量测试：`841 passed, 2 skipped`。
