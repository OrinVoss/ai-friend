# 进一步缩小 Agent 3 的 max_tokens

## 背景

Agent 3（角色表达层）负责自然语言回复，不需要像 Agent 1 / Agent 2 那样输出长 JSON。之前的情绪映射上限偏高，导致 AI 兴奋时可能输出过长。

## 修改

- `core/agent.py` 的 `_max_tokens_for_emotion()`：
  - `excited` / `joyful`：`768` → `512`
  - `surprised`：`700` → `448`
  - 中性情绪（engaged / content / trusting / anticipating / neutral）：保持 `base`（即 `config.max_tokens`，默认 `512`）
  - `anxious` / `afraid`：`300` → `128`
  - `melancholy` / `sad` / `frustrated` / `angry` / `disgusted`：`256` → `128`

## 效果

- 兴奋时最多 512 tokens
- 日常中性情绪 512 tokens（由 `config.max_tokens` 决定，可进一步下调）
- 负面/低落情绪时压缩到 128 tokens

## 验证

- 全量测试：`python -m pytest tests --ignore=tests/real_api -q` 通过（366 passed）。

## 提交

`04040c5` perf: 缩小 Agent 3 情绪 max_tokens 映射
