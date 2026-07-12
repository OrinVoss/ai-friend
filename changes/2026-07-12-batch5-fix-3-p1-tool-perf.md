# Batch 5 修复：P1 工具层 + 性能（3 个）

## B5-1 Glob/Grep 缓存（#172）
- `tools/search_tools.py` — 添加模块级 `_SEARCH_CACHE`（TTL 60s，最大 20 条）；GlobTool 和 GrepTool 执行前查缓存，执行后存缓存

## B5-2 工具结果格式统一（#175）
- `core/tool_agent.py` — `format_for_phase2()` 改为调用 `dispatcher.format_tool_results()`，消除两种格式并存问题

## B5-3 estimate_tokens 误差修复 + O(k²) 消除（#168）
- `core/context_manager.py` — CJK 系数从 `cjk / 1.5` 改为 `cjk * 1.5`（约 1.5 token/字符）
- `core/message_handler.py` — `_build_messages()` 中 `messages.insert(1, ...)` 循环改为 `history_messages.append()` + 单次 `messages[1:1] = reversed(history_messages)`，O(k²) → O(k)

## 验证
- 全部 4 文件通过 `py_compile`
- 测试 71 passed in 0.22s

## 关闭 Issue
#172、#175、#168
