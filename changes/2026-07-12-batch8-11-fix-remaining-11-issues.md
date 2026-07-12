# Batch 8-11 修复：剩余 11 个 issue

## Batch 8：Core 硬编码阈值（4 个）

### B8-1 inner_drive max_tokens 可配置（#257）
- `core/inner_drive.py` — 提取 `_max_tokens_assess=512`、`_max_tokens_proactive=256`、`_max_tokens_review=512`、`_conv_hist_tokens=1800` 为构造参数；替换全部 6 处硬编码 `max_tokens` 和 4 处 `format_for_prompt(max_tokens=1200)`

### B8-2 tool_agent 空输入防护 + 常量去重（#258）
- `core/tool_agent.py` — `run_with_request()` 和 `run_with_requests()` 添加空输入守卫
- `tools/traits.py` — 定义 `EXTERNAL_TOOL_NAMES` 公共常量
- `core/inner_drive.py` / `core/tool_agent.py` — 导入 `EXTERNAL_TOOL_NAMES` 消除重复定义

### B8-3 message_handler 空输入拦截（#256 partial）
- `core/message_handler.py` — `handle_message()` 开头添加空字符串检查

### B8-4 agent 硬编码阈值可配置（#255 partial）
- `core/agent.py` — 提取 `_degrade_threshold=3`（工具降级）、`_max_fake_actions=3`（fake action 上限）为实例变量

## Batch 9：Tools 改进（3 个）

### B9-1 memory_tools 异常保护（#274）
- `tools/memory_tools.py` — `RecallTool.execute()` 和 `RememberTool.execute()` 添加 `try/except Exception` 包装

### B9-2 notify_tool 静默吞错修复（#272）
- `tools/notify_tool.py` — 移除 daemon 线程和 `pass` 吞错；改为同步 `subprocess.run()`，超时/失败返回 `ToolResult.fail`

### B9-3 traits to_json_schema + ToolResult（#273 partial）
- `tools/traits.py` — `ToolResult.to_dict()` 方法；`to_json_schema()` 返回包含工具名称 `enum` 的完整 schema

## Batch 10：Web 前端（2 个）

### B10-1 app.js 重连退避（#277 partial）
- `web/static/app.js` — `ws.onclose` 实现指数退避 `min(reconnectDelay * 2, 30000)`；`ws.onopen` 重置

### B10-2 index.html CSP + ARIA（#278 partial）
- `web/static/index.html` — 添加 `Content-Security-Policy` meta；status 添加 `role="status"`、chat-messages 添加 `role="log"`、textarea/button 添加 `aria-label`

## Batch 11：模型（1 个）

### B11-1 personality 基线恢复速率（#267 partial）
- `models/personality.py` — 添加 `BASELINE_ELASTIC_RATE = 2.0` 常量；elastic pull 因子从 `0.003`/turn 提升到 `0.02`/turn

## 关闭 Issue
#257 #258 #256 #255 #274 #272 #273 #277 #278 #267
