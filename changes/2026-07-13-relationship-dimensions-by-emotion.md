# 关系指标四个维度均随情绪状态更新

## 问题
关系指标历史变化中长期以来只有 `familiarity` 在变化：

```
trust: --
familiarity: 0.32
intimacy: --
fun: --
```

原因是 `MemoryConsolidator._update_relationship()` 里只写了 `familiarity` 的固定增量、`intimacy` 的自我袒露增量、`trust` 的积极 sentiment 增量，而 `playfulness`（前端显示为 `fun`）完全没有更新逻辑。

## 改动
- `memory/consolidation.py` 的 `_update_relationship()`
  - 保留原有 `familiarity` 增长逻辑。
  - 基于当前主导情绪 `personality.emotion.dominant_emotion` 更新四个维度：
    - `trust`：`trusting` 情绪或 `sentiment > 0.3` 时增加；负面情绪时小幅降低。
    - `intimacy`：用户自我袒露时增加；`content` / `engaged` / `trusting` 情绪时小幅增加。
    - `playfulness`（`fun`）：`joyful` / `excited` / `surprised` 时增加；负面情绪时小幅降低。
  - 不改动 consolidation 触发间隔，仍由原有逻辑决定。

## 效果
每次 consolidation 触发时，四个关系维度至少有一个会根据当前情绪变化，历史变化面板不再只有一条线。

## 验证
- `python -m py_compile memory/consolidation.py` 通过。
- 重启服务后对话，触发 consolidation 时 `relationship_metrics` 中 `trust`、`intimacy`、`playfulness` 均出现非默认值。
