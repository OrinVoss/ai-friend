# A6：情绪按真实时间衰减（systems/emotion.md P0-3）

日期：2026-07-21

## 背景

`decay()` 此前只挂在按轮的 `apply_emotional_shift` 内部——不对话就不流逝。用户离开三天再回来，情绪原封不动，与「时间是刺激」的核心原则直接冲突。`Personality.decay_emotion()` 这个预留的时间衰减入口是死接口。

## 实现（读时结算，不加后台线程）

- `models/personality.py::EmotionalState` 新增持久化字段：
  - `last_decay_at: float = 0.0`（0 = 未初始化，首次结算视为 now，不回溯，向后兼容）
  - `turn_seconds: float = 300.0`（「一轮衰减」对应的真实秒数，可手改）
- 新增 `decay_elapsed(now=None) -> int`：`n = (now - last_decay_at) / turn_seconds`，clamp 到 [0, 50]，**循环执行 n 次现有 `decay()`**——逐次递推，与按轮衰减数学上完全一致，无公式分叉风险
- 结算点：`to_prompt_summary()` 开头（prompt 构建是最主要的读取路径，响应/主动/睡眠评估全部经过）
- 配置：`config.py` 新增 `emotion_turn_seconds: int = 300`，`core/session_factory.py` 装配时注入 `emotion.turn_seconds`；`config.example.json` 同步

## 测试（`tests/test_emotional_state.py::TestDecayElapsed`，+5）

- 首次调用只初始化不衰减
- 900s → 3 ticks，与手动 3 次 `decay()` 结果逐位一致
- 超上限 clamp 到 50
- 不足一轮不衰减
- `to_prompt_summary` 触发结算（2 小时前的时间戳 → valence 回落）

## 验证

- 全量 `pytest tests --ignore=tests/real_api -q`：**793 passed + 2 skipped**（788 → 793）

## 备注

- 挂机几天回来第一次 prompt 构建时一次性结算（上限 50 ticks ≈ 4 小时），之后恢复正常节奏——避免超长 idle 后一次性「情绪清零」。
- R5 的边界计数与 A6 兼容：decay_elapsed 走同一个 `shift`/`decay` 路径。
