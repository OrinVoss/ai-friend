# 修复：prompt 花括号冲突（L1 insight/care clue 生产失效）+ 事实提取张冠李戴

日期：2026-07-20

## 起因

用户提供生产日志（17:48-17:49，session=小星），暴露三个问题。

## Bug 1（P0）：safe_format 花括号冲突——两个功能在生产上一直是死的

**现象**：日志反复出现 `safe_format failed: '"hypothesis"'` 和 `'"clues"'`，随后 `L1 insight missing hypothesis, skipped`。

**根因**：`safe_format` 用 `str.format()` 渲染模板，`INSIGHT_GENERATION_PROMPT` 的 R3 约束行（`输出 {"hypothesis": ""}`）和 `CARE_CLUE_PROMPT` 的 JSON 示例（`{"clues": [...]}`）是**单花括号**——format() 把 `{"hypothesis"` 当字段名抛 KeyError，safe_format 兜底**返回未渲染的原模板**，LLM 拿到的是带 `{facts}`/`{text}` 占位符的空模板，只能输出垃圾。即：L1 Insight 生成和 care clue 提取自上线起在生产上从未成功过（L2/L3 模板花括号是 doubled 的，正常）。

**修复**：两处单花括号全部改 doubled（`{{ }}`）。新增**系统性防线** `tests/test_prompt_instructions.py::TestTemplateBraceSafety`：遍历 `prompts/templates.py` 所有 `*_PROMPT`，用 `string.Formatter().parse` 检查花括号合法性 + 哨兵值验证占位符真正被替换——防任何模板再犯。

## Bug 2（P0）：事实提取把 AI 的回复当成用户陈述

**现象**：用户问「你对我的认识」，AI 回复了一段用户画像（435 字）。consolidation 随即把 **AI 的这段回复**当成用户陈述提取出 8 条 confidence=1.00 的「用户事实」（自称云指导/喜欢吉森信/随缘作息/喜欢摄影…），体验总结也写成「**用户**以幽默调侃的方式总结了云指导的个人特征」（主体实际是 AI）。FactChecker 再用这些二手事实把 8 条真实事实 decay 到 0.3+。

**根因**：`_format_turns` 有角色标签（`用户:`/`你:`），`FACT_EXTRACTION_PROMPT` 的排除清单覆盖了「AI 的行为/承诺/评价」，但**没有覆盖「AI 对用户的复述/画像」**——AI 用第二人称总结用户时，LLM 把它转换成了第一人称用户事实。

**修复**（`prompts/templates.py`）：

- `FACT_EXTRACTION_PROMPT` 排除清单新增：「AI 对用户的复述/画像/总结——第二人称描述是 AI 的转述，不是用户亲口说的。**只有『用户：』开头的行才能提取**；即使 AI 的总结内容是对的，也不要从 AI 的回复里提取」
- `EXPERIENCE_SUMMARIZATION_PROMPT` 新增主体区分提示：「『你：』是 AI，『用户：』才是用户——不要把 AI 做的事记到用户头上」

## Bug 3（已修）：FactChecker 候选矛盾经 LLM 复核

**现象**：日志中 8 条真实事实被 decay（'云指导' vs '自称"云指导"' sim=0.92 → 0.90→0.36）——单一 embedding 相似度分不出「复述/近义」和「真矛盾」。

**修复**（方案 B：LLM 复核）：

- `memory/fact_checker.py::detect_contradiction` 新增 `verify_fn` 参数——**只作用于 embedding 语义判定层**：检出候选后先过复核，否决则保留旧事实（`[fact_check] LLM rejected contradiction (paraphrase): '...' kept`）；复核异常时保持原判定（向后兼容）。同键不同值的直接判定（更新语义）不经过复核。
- `memory/consolidation.py::_verify_contradiction_llm`：新增 `CONTRADICTION_VERIFY_PROMPT`（`prompts/templates.py`），判定标准「复述/近义/补充/更具体 → NOT_CONTRADICT；互斥不能同时成立 → CONTRADICT」，temperature=0.0。
- `memory_agent.verify_fact` 的矛盾检测不传 verify_fn（它是报告用途，从严无害），行为不变。
- 成本：每个候选矛盾一次小 LLM 调用（多数批次为 0 次）。

**测试**（`tests/test_fact_checker.py::TestContradictionVerifyFn`，+4）：复核否决→保留、复核通过→decay、复核异常→保持原判定、直接判定绕过复核。

## 验证

- 模板花括号安全测试：20 passed（含新守卫）
- 全量 `pytest tests --ignore=tests/real_api -q`：**691 passed + 2 skipped**
