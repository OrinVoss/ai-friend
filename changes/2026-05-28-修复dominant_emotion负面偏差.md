# 修复 dominant_emotion 负面情绪偏差

**时间**：2026-05-28

## 修改文件

- `models/personality.py` — `dominant_emotion()` 增加 valence-based bias

## 修改原因

当 anger=0.91、sadness=0.91 但 trust=0.975 时，dominant_emotion 显示 "trusting"，但 AI 实际在生气怼人。需要让负面 valence 时负面情绪优先显示。

## 修改内容

在 `dominant_emotion()` 的 `max(scores)` 之前增加 bias：

- valence < -0.2：负面情绪 ×1.3，正面情绪 ×0.8
- valence > 0.2：正面情绪 ×1.1，负面情绪 ×0.9

测试：anger 0.91→1.18，trust 0.975→0.78，dominant 从 "trusting" 变为 "sad"
