# 修复方案：Inner Drive 过度推理 + Agent 3 心理咨询化 + Memory 粒度 + 情绪顶格 + Prompt 瘦身（第一批）

> 来源：2026-07-21 监控日志架构 Review 中**确认成立**的五项（其余条目经代码核实为误报，不处理）。
> 面向执行者：每项给出根因（文件/行/现状代码）、修法、测试与验收。**严格按项执行，不要做清单之外的"顺手优化"。**
> 项目：D:/桌面/编程作品/AI朋友，Python 3.12，Windows。
> 回归基线：`python -m pytest tests --ignore=tests/real_api -q` → 当前 **810 passed**，全部改完后必须全绿。
> 完成后在 `changes/` 写变更记录（命名 `changes/2026-07-22-推理与prompt修复.md`）。

---

## 总览

| # | 问题 | 位置 | 性质 |
|---|------|------|------|
| R1 | Agent 1 心理分析泛滥（"用户在测试我"类推断，常被后续对话打脸） | `prompts/instructions.py` | prompt |
| R2 | Agent 3 被"你之前的判断"块带成心理咨询师（用户说"看不懂"） | `prompts/system.py:742-743` + `prompts/instructions.py` | prompt |
| R3 | 推断被当事实存（"性格特点：幽默自信…"入 facts） | `prompts/templates.py` | prompt |
| R4 | valence 长期钉死 +1.00（连续 9 轮 hard clamp） | `models/personality.py:200-211` | 代码 |
| R5 | Agent 3 prompt 单条约 15-19k chars，瘦身第一批 | `prompts/system.py` | prompt/代码 |

---

## R1：Agent 1 推理约束——只判需求，不判人格

### 根因

`prompts/instructions.py:9-16` `INNER_DRIVE_INTRO`：

```
"1. 用户表面在说什么？深层需求是什么？"
```

"深层需求"的开放式引导，导致 Agent 1 大量产出"用户其实在观察我/测试我/想让我…"的人格推断（生产日志多次出现，后续被"我打字慢"等事实打脸）。

### 修法

1. `INNER_DRIVE_INTRO` 第 1 条改为（保持 2、3 条不变）：

   ```
   1. 用户的意图是什么——他想让我【做什么】或【回答什么】？
   ```

2. 在 `INNER_DRIVE_DECISION_PRINCIPLES`（:35-41）末尾追加一条硬约束：

   ```
   - 只分析用户的意图、需求和缺失信息。不要推断用户的人格、心理动机或"潜台词"——
     "用户在测试我/观察我/其实想让我…"这类猜测既不可靠也不影响决策，禁止出现在 reasoning 里。
   ```

3. `INNER_DRIVE_OUTPUT_FORMAT`（:52-65）的 `reasoning` 字段说明同步改为：

   ```
   - reasoning: 决策依据（基于什么事实决定要不要工具/回忆），一两句话。
     不写心理分析，Agent 3 会看到这段文字
   ```

### 测试

- `tests/test_prompt_instructions.py` 新增：构建 Agent 1 prompt，断言含"不要推断用户的人格"类约束文案；现有用例不降级。

---

## R2：Agent 3 判断块裁剪 + 分析频率上限

### 根因（两处合力）

1. `prompts/system.py:742-743`：`blocks.append(f"=== 你之前的判断 ===\n{inner_drive_summary}")`——Agent 1 的结论原样注入，Agent 3 顺着继续脑补。
2. `prompts/instructions.py:93-104` `AGENT3_BASE_INSTRUCTIONS` 没有任何限制心理分析的规则——模型自由发挥成"我猜你…/你真正想…/其实你…"，用户直接反馈"看不懂"。

### 修法

1. **截断**：`prompts/system.py:743` 注入前对 `inner_drive_summary` 截断（保留前 300 字符，超出加 `…`），并改标题为 `=== 你刚才的分析（仅供参考，不要在回复里复述或展开）===`。
2. **规则**：`AGENT3_BASE_INSTRUCTIONS` 的要点列表追加两条：

   ```
   - 不要分析用户。不要说"我猜你…""你真正想…""其实你…"——她在跟你聊天，不是来做心理咨询
   - 她分享什么就接什么，拿不准就直接问，不要替她下结论
   ```

### 测试

- 构建 Agent 3 prompt：超长 inner_drive_summary 被截到 300 字符且带免责声明标题；指令块含"不要分析用户"文案。
- 现有 prompt 相关测试不降级（`tests/test_prompt_instructions.py`、`tests/test_message_handler.py`）。

---

## R3：fact/insight 存取口径——推断只能进 insight

### 根因

`prompts/templates.py:28` `FACT_EXTRACTION_PROMPT` 末行：

```
只输出明确出现或高度可推断的**用户自身信息**。
```

"高度可推断"是漏洞——"性格特点：幽默自信""用户喜欢观察"这类 LLM 画像被当 identity/preference 事实存进 facts_v2。`CONSOLIDATION_UNIFIED_PROMPT`（同文件 :199-226）的 FACTS 段约束（"只提取用户亲口说的"）较严但不统一。

### 修法

1. `FACT_EXTRACTION_PROMPT` 末行改为：

   ```
   只输出用户**亲口陈述**或可严格验证的事实（"我说了/我喜欢/我有/我做过"）。
   性格、心理、动机类画像（"用户很幽默""用户喜欢观察人"）**不是事实**，不要入 FACT——这类推断只属于 INSIGHT。
   不确定的置信度给低分(0.3-0.5)。如果对话中没有新的用户信息，输出空行即可。
   ```

   并在"不要提取"清单（:19-26）追加一条：

   ```
   - 性格/心理/动机画像（即使看起来总结得很准）——那是推断，不是事实
   ```

2. `CONSOLIDATION_UNIFIED_PROMPT` 的 FACTS 段说明同步：

   ```
   （每行一条，没有则写 NONE；只提取用户亲口说的关于自身的事实；
   性格/心理/动机画像不要入 FACT，那类内容放 INSIGHT）
   ```

3. 注意 `{{ }}` 转义：模板经 `safe_format`/`str.format` 使用，JSON 示例的双花括号必须保留。

### 测试

- 用一段含 AI 画像对话的样例（如 AI 说"你真幽默"，用户未自述）跑 `_extract_facts`/`_consolidate_unified`，断言 prompt 中包含新约束文案；不强制 mock LLM 行为变化（prompt 级修复），重点是文案断言 + 现有测试不降级。

---

## R4：情绪边界收益递减

### 根因

`models/personality.py:200-211` `shift()`：

```python
self.valence = max(-1.0, min(1.0, self.valence + delta_v))
```

硬钳制。该用户对话 sentiment 持续为正（+0.1~+0.3），每轮 delta_v 累加 → valence 钉在 +1.00 连续 9 轮（生产日志 `valence at boundary for 9 consecutive shifts`），情绪失去分辨力；`decay()` 的回拉力度不足以抗衡每轮新输入。

### 修法

在 `shift()` 中把 valence/arousal 的更新改为**软边界**（接近边界收益递减），替换 :207-208 两行：

```python
# R4: 软边界——接近 ±1/1 时同向增量收益递减（反向不受影响），
# 防止 valence 长期钉死在硬钳制值上失去分辨力
def _soft_apply(current: float, delta: float, lo: float, hi: float) -> float:
    if delta > 0:
        delta *= max(0.15, 1.0 - (current - lo) / (hi - lo))
    elif delta < 0:
        delta *= max(0.15, 1.0 - (hi - current) / (hi - lo))
    return max(lo, min(hi, current + delta))

self.valence = _soft_apply(self.valence, delta_v, -1.0, 1.0)
self.arousal = _soft_apply(self.arousal, delta_a, 0.0, 1.0)
```

- 系数 0.15 保底：即使贴边也保留微小移动，不会完全冻住。
- `_soft_apply` 定义为模块级私有函数或 `shift` 内嵌函数均可，选改动最小的。
- hard clamp 的 info 日志（:209-211）保留——软边界后应明显更少触发。

### 测试

- `tests/test_personality_core.py` / `tests/test_emotional_state.py` 新增：
  1. valence=0.95 时再施 +0.3，结果 < 1.0（不再钉死）且 > 0.95（仍上移）；
  2. valence=0.95 时施 -0.3，正常下移不受递减影响；
  3. valence=0.5 中性区行为与改前一致（小增量基本无衰减）；
  4. 连续 10 次 +0.1 输入，valence 渐近但不到 1.0。
- 现有情绪测试不降级。

---

## R5：Agent 3 prompt 瘦身（第一批）

### 根因

生产日志 Agent 3 单条 `chars_in` 约 15k~19k。可快速回收的三处（完整 ContextBudget 属 Layer 2 P3，**本项不做**）：

1. `inner_drive_summary` 块（已在 R2 截断到 300 字符，本项复用该成果，不重复改）。
2. 慢变记忆块中 insight/reflection 条目：L1 二期后 insight 的 hypothesis 常达 200+ 字符，Agent 3 每次全量带 3 条。
3. `tool_call_history` 注入最近 5 条，含输出摘要，偏长。

### 修法

1. `prompts/system.py` 构建记忆/反思块的函数（`_build_memory_block` 或 context_summary 来源处，先读代码定位）：reflection/insight 条目注入 Agent 3 前**逐条截断到 120 字符**，且最多注入 **2 条**（原 3 条）。注意 memory_agent 的 context_summary 路径与 retriever 路径都要覆盖。
2. `tool_call_history` 注入条数 5 → 3（定位：`prompts/system.py` 的 `_build_tool_history_block` 或调用处），每条 output 摘要截断 100 → 60 字符。
3. 不改 facts/experiences 条数（10/5），不动静态块与对话示例逻辑。

### 测试

- 构造含 3 条长 insight 的记忆上下文，断言 Agent 3 prompt 中最多 2 条且每条 ≤120 字符（截断后缀保留）。
- 断言 tool history 块最多 3 条。
- 验收量化：用同一 mock 上下文构建改前/改后 prompt，`len(改后) <= len(改前) * 0.9`。

---

## 收尾（五项全完后执行）

1. 全量测试：`python -m pytest tests --ignore=tests/real_api -q`，810 + 新增 ≥ 全绿。
2. `python -m py_compile *.py core/*.py memory/*.py storage/*.py tools/*.py web/*.py models/*.py prompts/*.py ui/*.py`。
3. 写 `changes/2026-07-22-推理与prompt修复.md`（逐项列改动）。
4. 生产观察点（写进变更记录）：改后 Inner Drive 的 reasoning 是否还出现人格推断；Agent 3 回复中"我猜你/其实你"类句式是否消失；`valence at boundary` 警告频率是否下降。

## 不要做的事

- **不做**完整 ContextBudget/Token 预算系统（Layer 2 P3，单独立项）。
- 不要改 Agent 1 的结构化输出 schema（只改文案，字段名/格式一律不动）。
- 不要动 retrieve_for_query 的评分权重与 recall 链路（昨天刚修好）。
- 不要改 decay() 的半衰期表（R4 只动 shift 的软边界）。
- 不要给 Agent 3 删 inner_drive_summary 块（裁短 + 免责，不删除——它承载 Agent 1→3 的决策上下文）。
- 不要动 CONSOLIDATION_UNIFIED_PROMPT 的段序（昨天刚调过 FACTS→INSIGHT→EXPERIENCE）。
