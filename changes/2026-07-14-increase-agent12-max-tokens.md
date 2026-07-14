# 提高 Agent 1 / Agent 2 的 max_tokens

## 背景

Agent 1（Inner Drive）负责输出结构化的 JSON 决策，包括推理过程、工具请求、内部回忆查询等；Agent 2（Tool Agent）负责输出 JSON 格式的工具调用。

在复杂场景下（多工具请求、失败后重试、需要详细推理），512 tokens 容易不够用，导致 JSON 被截断或工具参数缺失。Agent 3（角色表达层）主要负责自然语言闲聊，512 tokens 已经足够。

## 修改

- `core/inner_drive.py`
  - `max_tokens_assess` 默认值从 `512` 提高到 `1024`
  - `max_tokens_review` 默认值从 `512` 提高到 `1024`
  - `max_tokens_proactive` 保持 `256` 不变（主动决策不需要长输出）

- `core/tool_agent.py`
  - `run()` 中的 `max_tokens` 从 `512` 提高到 `1024`
  - `run_with_request()` 中的 `max_tokens` 从 `512` 提高到 `1024`

## 验证

- 全量测试：`python -m pytest tests --ignore=tests/real_api -q` 通过（366 passed）。

## 提交

`779dfca` perf: 提高 Agent 1 / Agent 2 的 max_tokens
