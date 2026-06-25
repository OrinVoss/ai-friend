# 2026-06-25 Week 3 Day 5-6 + Week 4 P2/P3 批量修复

## 修改原因

完成 Week 3 模型/提示词层 16 项 + Week 4 P2/P3 核心层 ~18 项。
覆盖 models/prompts/provider/dispatcher/personality，低风险代码质量与数据模型加固。

## 修改文件与摘要

**模型层：**
- `models/memory.py` — MM-001 `runtime_score` 属性；MM-002 `__post_init__` 范围验证；
  MM-003 `fact_type` 用 `Literal`；MM-004/005 添加 `EmotionalTone`/`InsightType` 枚举；
  MM-006 `Reflection` 添加 `level`/`parent_ids` 字段。
- `models/conversation.py` — MC-001 `Turn.to_dict()` 序列化；MC-002 `role` 用 Literal；
  MC-003 `relationship` 默认空 dict。

**提示词层：**
- `prompts/system.py` — SY-012 `tc["success"]`→`.get()`；SY-014 `**kwargs`→显式参数；
  SY-003 `demo_turns_remaining` 参数（SY-002 高风险保留不修）。
- `prompts/templates.py` — TM-005 `EMOTION_ANALYSIS_PROMPT` 结果用 regex 提取 JSON；
  TM-001 .format() 调用点由调用方包裹 try/except（已由 consolidation.py 覆盖）。
- `memory/consolidation.py` — 配合 TM-005 实现 JSON 提取逻辑。

**P2/P3 批量：**
- `core/provider.py` — PR-001 max_tokens 默认对齐 512；PR-006 `time.monotonic()`；
  PR-013 流式响应 1MB 上限。
- `core/dispatcher.py` — DI-001 json.loads 10KB 上限；DI-005 `logger.exception()`；
  DI-006 工具输出 2000 字符截断；DI-007 补全别名映射。
- `models/personality.py` — PS-003 `Trait.__post_init__` clamp；PS-008 魔法数字命名常量；
  PS-013 `emotion_events` 用 `deque(maxlen=20)`；PS-015 `to_dict`/`from_dict` deque 兼容。
- `doc/v05-plan/week-3-completion.md` — 更新标记 ✅
- `doc/v05-plan/week-4-finalize.md` — 更新状态和保留项说明

## 验证

- `python -m py_compile models/memory.py models/conversation.py prompts/system.py core/provider.py core/dispatcher.py models/personality.py` ✅
- `python -m py_compile *.py core/*.py memory/*.py storage/*.py tools/*.py web/*.py models/*.py prompts/*.py ui/*.py` ✅（0 errors）
