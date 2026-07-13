# 2026-07-13 InnerDrive 改用 JSON Schema 替代关键词/正则解析

## 现象

用户要求 AI 调用外部工具时，Agent 1（InnerDrive）的输出为角色扮演
文本（"哈哈哈哈哈哈云爸爸！！"），其中偶然包含"glob"、"music_play"
等工具名。_parse_decision() 通过关键词匹配误判为"需要外部工具"，
_extract_tool_requests() 找不到结构化请求后把整段角色扮演文本当作
tool_request 传给 Agent 2，导致 Agent 2 无法解析出 JSON 工具调用
（每次仅输出 6 token 即失败）。

## 根因

InnerDrive 的决策输出使用自由文本格式，依赖 _parse_decision() 的
关键词匹配 + _extract_tool_requests() 的正则提取来推测意图。这
种"先写废话再猜"的方式在面对 LLM 进入角色扮演状态时完全失效。

## 修复

将 InnerDrive 的输出改为 JSON Schema 驱动（response_format），
与 Agent 2（ToolAgent）保持一致：

1. 定义 `INNER_DRIVE_SCHEMA` 常量，包含字段：
   - needs_external_tools（boolean）
   - reasoning（推理过程，Agent 3 可见）
   - summary（给 Agent 3 的简洁摘要）
   - recall_query（内部回忆查询，可选）
   - tool_requests（结构化的工具请求数组）

2. assess() / review() / re_decide() 均使用
   `response_format=INNER_DRIVE_SCHEMA` 调用 LLM，输出即
   结构化 JSON，无需关键词/正则解析。

3. 新增 `_parse_json_decision()` 直接解析 JSON 为
   InnerDriveResult，保留 JSON 失败时的兜底逻辑（查找 {} 回退）。

4. 删除 `_parse_decision()` 和 `_extract_tool_requests()`。

5. `prompts/system.py` 的 `build_inner_drive_prompt()` 输出格式
   说明从自然语言格式改为 JSON Schema 字段描述。

## 效果

- LLM 被强制输出合法 JSON（response_format 层级约束），
  角色扮演文本无法混入 tool_requests
- tool_requests 直接从 JSON 数组解析，不依赖正则猜谜
- recall_query 嵌入同一 JSON，无需分离的 ReAct 循环

## 修改文件

- `core/inner_drive.py` — 核心改造
- `prompts/system.py` — prompt 更新
- `changes/` — 本记录
