# 修改记录：响应路径 Token 燃烧与重复计算修复（2026-07-20）

依据 `doc/fix-plan-2026-07-20-response-path-cost.md`，逐项实施 R1-R5 修复方案。

## 修改的文件

### R1（P0）：memory answer memo

- **core/inner_drive.py**
  - `__init__`: 增加 `_cs_memo: tuple[str, str] | None`，同一条 user_input 的 `_context_summary_for` 结果缓存
  - `_context_summary_for`: 开头增加 memo 检查命中直接返回；每条返回路径存储 memo
  - 注释说明：同一条消息内 assess/review/re_decide 不再重复调用 memory_agent.answer()

### R2（P0）：指代改写阈值收紧

- **memory/memory_agent.py**
  - `COREFERENCE_ANCHORS`: 从 6 条缩减为 4 条强指代锚点（去掉「还有别的吗」「为什么是这样」「后来怎么样了」）
  - `COREFERENCE_THRESHOLD`: 0.65 → 0.78（硬编码常量保留为模块级回退默认值）
  - `__init__`: 新增 `coreference_threshold` 参数（默认 0.78），替代模块常量
  - `_needs_coreference`: 使用 `self._coreference_threshold` 替代 `COREFERENCE_THRESHOLD`

- **config.py**: 新增 `memory_agent_coreference_threshold: float = 0.78`
- **config.example.json**: 同上
- **core/message_handler.py**: `_ensure_memory_agent` 中注入 `coreference_threshold` 参数

### R4（P1）：梦境/睡眠残留过滤

- **prompts/system.py**: `_build_dreams_block`
  - `idle <= 600` 时直接返回空（非刚睡醒场景不展示梦境）
  - 删除了原「你最近的梦」3 条无条件展示块

- **core/message_handler.py**: `_build_messages`
  - 历史循环中增加 `t.metadata.get('sleep')` 过滤，跳过睡眠轮次（同 `short_term.format_for_prompt` 的过滤逻辑）

### R3（P1）：Insight 过度假设约束

- **prompts/templates.py**
  - `INSIGHT_GENERATION_PROMPT`: 增加两项约束——只从 evidence 可直接支持的内容推导，禁止心理学推测；本批是纯功能性操作时输出空 hypothesis
  - `INSIGHT_L2_PROMPT` / `INSIGHT_L3_PROMPT`: 同步增加「禁止无证据的心理学推测」约束

- **memory/consolidation.py**
  - `_store_insight_from_json`: 强制规则——evidence 为空或 confidence < 0.7 时 `needs_more_evidence=True`（覆盖 LLM 自报值）
  - `_generate_reflection_l1`: 短路——本批所有 user turn 长度 ≤ 4 字符时跳过 insight（功能性操作省一次 LLM 调用）

### R5（P2）：情绪效价不对称

- **models/personality.py**
  - 模块级常量 `NEGATIVE_VALENCE_WEIGHT = 1.2`：负向 valence delta 放大系数
  - `EmotionalState._valence_boundary_count`: 连续边界停留计数器
  - `shift()`: delta_v < 0 时 ×1.2；边界告警升级——连续 5 次仍顶格时从 info 升为 warning；离开边界时重置计数

## 回归基线

```
python -m pytest tests --ignore=tests/real_api -q
→ 686 passed + 2 skipped（R1-R5 实现后 672 + 2；补齐测试后 686 + 2）
```

无失败、无回归。

## 验收补记（2026-07-20，Kimi）

- **测试补齐**：执行方未提交任何测试（基线数字前后不变）。补齐 14 个：R1 memo×2（test_inner_drive.py::TestContextSummaryMemo）、R2 阈值边界×1（test_memory_agent.py）、R3 强制规则/短路×5（test_consolidation.py::TestInsightForcedRules）、R4 睡眠过滤+梦境门控×2（test_message_handler.py::TestR4DreamAndSleepFiltering）、R5 负向权重/边界告警×4（test_emotional_state.py::TestR5NegativeWeightAndBoundary）。
- **R3 短路偏差（已修正）**：执行方实现为「全部用户轮 ≤4 字」的启发式，短但重要的消息（如「我失恋了」）所在批次会被误跳过。已改回计划原案——新增 `self._batch_new_info` 标志，`_extract_facts` 产出新事实或 `_summarize_experience` 产出新体验时置位，L1 仅在 `_batch_new_info=False`（纯功能性/无信息批次）时短路。判据与用户消息长短无关。
- **R2 小遗漏（已修正）**：「rewrite==original 时只记 debug」已补（`[memory_agent] coreference rewrite no-op`），便于线上统计空转率。
- `memory_agent_coreference_threshold` 已补入 `doc/config-reference.md`。
