# 修复：prompt 历史污染三件套（重复注入 / 兜底文案 / 决策温度）

日期：2026-07-22
来源：2026-07-21 监控 Review 核实后成立的三项（另三项经核实为误报或设计如此，见文末）。

## 1. 同一用户输入在 prompt 中重复出现

**根因**：`handle_message` 先把当前输入 `add_turn` 入短期记忆（:317），`_build_messages` 又把全部历史（含这条）塞进 messages，末尾再以 `用户输入：{input}` 追加一次——同一句话在每条 react prompt 里出现两次，模型会误判用户在刷屏/重复强调。

**修复**：`core/message_handler.py::_build_messages` 遍历时跳过倒序首个元素中的当前输入（role=user 且内容包含于末尾输入串）。用户连发两遍同样的话时旧轮次保留，只去当前这份。

## 2. 错误兜底文案污染对话历史

**根因**：`_react_loop` 的降级文案（"抱歉，我暂时无法处理…"）作为普通 assistant turn 写入历史。API 故障期（07-20 12:17 断连）产生大量此类记录，后续 prompt 把它们当真实对话，污染情绪与人格一致性。

**修复**：
- `core/agent.py`：新增模块常量 `_FALLBACK_TEXTS`（四处兜底文案），`add_turn` 时命中即标 `metadata.error_fallback=True`（DB 与聊天界面照常保留）。
- `core/message_handler.py::_build_messages`：跳过带 `error_fallback` 元数据的 turn（与 sleep/is_tool_claim 过滤同列）。

## 3. Agent 1 决策温度统一 0.8 → 0.3

**根因**：`DeepSeekProvider.generate()` 没有 per-call 温度参数，全部调用用实例默认 0.8——JSON 结构化决策（assess/review/re_decide/assess_intent/think loop）在高温下易格式抖动。

**修复**：
- `core/provider.py`：`generate()`（ABC + 实现）新增 `temperature: Optional[float] = None`，覆盖时写入 payload 与监控记录。
- `core/inner_drive.py`：8 处决策调用全部传 `temperature=0.3`。Agent 3 角色扮演保持 0.8 不变；consolidation 本就 0.2/0.3；tool_agent 本就 0.3。

## 测试

- `tests/test_message_handler.py::TestCurrentInputDedup`（3）：当前输入不重复、连发同样的话旧轮保留、error_fallback 被跳过。
- `tests/test_provider.py::TestPerCallTemperature`（2）：覆盖写入 payload、默认不变。
- 全量：`pytest tests --ignore=tests/real_api -q` → **813 passed + 2 skipped** 全绿。

## Review 中经核实不成立/不处理的条目

- **"工具幻觉"（声称搜索/放歌但无记录）**：误报。监控导出只含 LLM 调用记录，工具执行不经过 LLM（`music_play` 本地执行）；生产日志中 `web_search`（21:45:25）与 `music_play`（21:33:07）都有真实执行记录，Agent 3 的汇报基于真实注入的工具结果。
- **同一输入触发两次 inner_drive**：设计如此——`assess()` 的 recall 循环（先回忆再决策），最多 5 轮，是回忆能力的核心机制。
- **consolidation 输出非 JSON**：`FACT|` 行格式是设计格式，行解析，下游并不期望 JSON。
