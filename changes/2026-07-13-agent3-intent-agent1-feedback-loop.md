# 加强 Agent 1 判断力 + Agent 1/Agent 3 反馈循环

## 变更摘要

实现 Agent 3 条件性 JSON 意图输出：Agent 3 正常回复保持普通文本，只有在主动提议执行外部动作时才输出 JSON 意图；Agent 1 负责评估该意图并决定是否调用工具。Agent 3 仍然不直接执行工具。

## 背景

原三阶段架构中：
- Agent 1 判断是否需要外部工具
- Agent 2 执行外部工具
- Agent 3 只做角色化表达

问题是 Agent 1 偶尔会漏判需要工具的场景，而 Agent 3 没有外部工具权限，只能基于已有信息硬回。本次改动让 Agent 3 在合适的时候主动“提建议”，但把最终决策权交回 Agent 1。

## 主要改动

### 1. `prompts/system.py`

- 重写 `build_inner_drive_prompt` 的内驱推理段落：
  - 强调 Agent 1 不是被动等待指令，而是主动判断信息缺口
  - 新增“内驱检查清单”
  - 明确“用户指令优先”“宁可多调一次工具也不要猜测”
  - 细化各类外部工具的触发场景
- `build_system_prompt` 新增 `final_response` 参数：
  - `final_response=False`：允许 Agent 3 输出 JSON 意图
  - `final_response=True`：工具已执行完毕，必须输出自然语言
- 新增 Agent 3 输出规则 block：
  - 默认直接输出自然语言
  - 主动提议动作时必须输出 JSON，包含 `reply_to_user`、`intent`、`intent_description`、`intent_target`
  - `intent` 限定为 `play_music`、`send_notify`、`search_web`、`fetch_url`、`read_file`
  - 禁止编造工具结果

### 2. `core/inner_drive.py`

- 新增 `assess_agent3_intent(user_input, intent, intent_description, intent_target)` 方法：
  - Agent 3 提出意图后，Agent 1 用完整上下文重新评估
  - 输出标准 `InnerDriveResult`（`needs_external_tools` + `tool_requests`）
  - 给出 intent 到实际工具名的建议映射
  - 解析失败时默认不执行，保证安全

### 3. `core/message_handler.py`

- `_run_agent3` 新增 `final_response` 参数，控制 Agent 3 输出规则
- 新增 `_parse_agent3_output(text)`：区分普通文本与 JSON 意图
- 新增 `_handle_agent3_intent(...)`：
  - 解析 Agent 3 输出
  - 普通文本 → 直接返回
  - JSON 意图 → 交给 Agent 1 评估
  - Agent 1 同意 → 调用 Agent 2 执行 → Agent 3 生成最终普通文本
  - Agent 1 否决 → 返回 Agent 3 的 `reply_to_user`
  - 设置最大循环次数，防止无限循环
- `handle_message` 调整：
  - Agent 1 判断不需要工具时，先让 Agent 3 生成初步回复，再进入意图处理
  - Agent 1 判断需要工具并执行后，Agent 3 最终回复强制 `final_response=True`

### 4. 测试

- `tests/test_inner_drive.py`
  - 新增 `assess_agent3_intent` 同意/拒绝/解析失败三种场景测试
- `tests/test_message_handler.py`
  - 新增 `_parse_agent3_output` 普通文本/JSON 意图/非法 JSON 测试
  - 新增 `_handle_agent3_intent` 普通文本/拒绝/同意执行测试

## 验证

```bash
python -m pytest tests/test_inner_drive.py tests/test_message_handler.py -v
# 45 passed

python -m pytest tests --ignore=tests/real_api -q
# 357 passed
```

## 影响范围

- 只影响主动进入 Agent 3 的回复路径（正常聊天和 Agent 1 直接判定需要工具的路径不受影响）
- Agent 3 不直接执行工具的约束保持不变
- Agent 1 仍拥有最终决策权
