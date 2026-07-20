# 指代解析 prompt 强化 + 对话历史过滤睡眠轮

日期：2026-07-20

## 背景

用户案例：AI 在 turn 117 结尾主动说「要不我给您念段《国际歌》当BGM？」，用户接「本地有这个歌吗」，Agent 1 却判断「未指明歌名」，Agent 3 也反问「没告诉我歌名叫啥」。

排查结论：turn 117 的回复**当时在 20 条窗口和 prompt 里**（用 DB 重建缓冲复现验证），管线没有数据缺失——是模型没把「这个歌」回指到自己上一句。两个 Agent 漏了同一个近在咫尺的指代，属模型中文回指理解短板，用 prompt 引导缓解。

排查中顺带确认两个事实：`short_term_capacity` 实际是 500（不是 20），真正的瓶颈是 `conv_hist_tokens` 预算和垃圾轮次（睡眠/梦话/刷屏）占额度。

## 改动

### prompt 指代解析指令（`prompts/instructions.py`）

- `INNER_DRIVE_CHECKLIST`（Agent 1）：原「这个/那个 → 结合上文推断是否继续或重试」过于笼统（只说「继续或重试」，没说回看自己的回复）。新增专门条目：用户用指代词时先回看最近几轮对话（**尤其是你自己的上一条回复**）确定指代对象，能确定就当已知信息决策，不要说「未指明」；确认上文没有才反问。
- `OUTPUT_RULES_FOOTER`（Agent 3）：新增同款规则——先回指，不要反问用户其实已经给过的信息。

### 对话历史过滤（`memory/short_term.py`）

`format_for_prompt` 两处提质，只影响 prompt 输出，缓冲内容（consolidation 等消费方）不变：

- 跳过 `metadata.sleep=True` 的轮次——「zzzz」「我去午睡一会儿」对理解用户输入没有帮助，却占 token 预算把真正的对话挤出窗口。
- 连续重复消息（刷屏「你好」×4）合并为一条；非连续重复保留。

### 上下文预算（`core/inner_drive.py`）

`conv_hist_tokens` 默认值 1800 → 3600（配合 500 条容量与 API 低成本，让有效历史真正进 prompt）。

## 测试（`tests/test_short_term.py`，+5）

- 睡眠轮被 prompt 过滤但仍在缓冲里
- 连续重复合并、非连续重复保留
- assistant 标签与《国际歌》案例形态回归

## 验证

- 全量 `pytest tests --ignore=tests/real_api -q`：**651 passed**（646 → 651）

## 备注

- prompt 引导只能缓解不能根治——deepseek-v4-flash 的回指理解有上限；若仍频发，根治方向是 Memory Agent P2 的指代解析（把「这个 X」先解析成具体实体再检索）。
- 用户本地缓冲容量（`short_term_capacity=500`）本就够大，无需调整。
