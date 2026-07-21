# A7：Agent 3 prompt 块压缩——按 L2-3 结论关闭（不改代码）

日期：2026-07-21

## 结论

L2-3 块级评估（`doc/refactor/layer2-prompt/progress.md`）对 Agent 3 prompt 全部 14 个块的结论是**全部保留**——每个块都有明确必要性且多数已静态/慢变缓存，没有可删的浪费块。本项按结论关闭，不改代码。

## 代码与结论一致性核对（已验证）

| 结论 | 代码现状（`prompts/system.py::_build_memory_block`） | 一致 |
|------|------|------|
| facts 上限 10 | `memory_context.facts[:10]`（:548） | ✅ |
| experiences 上限 5 | `memory_context.experiences[:5]`（:552） | ✅ |
| reflections 上限 3 | `memory_context.reflections[:3]`（:558） | ✅ |
| dreams 条件注入 | R4：`idle≤600` 不注入 + sleep 轮过滤 | ✅ |
| 梦境标记 | F4：tags 含 dream → 【梦境，非真实事件】前缀 | ✅ |

## 未来重启本项的触发条件（记录在案）

1. 监控显示 react prompt 总长持续接近上下文限制 → 优先压缩 experiences 到 3 条或按 significance 排序截断
2. 评估 reflections 与 experiences 合并为「洞察与回忆」一块（需先评估对角色感的影响）

两项均需人工确认后立项，不在本次执行范围。
