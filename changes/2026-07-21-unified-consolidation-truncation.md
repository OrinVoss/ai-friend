# 修复：统一固化调用输出被 512 token 截断导致 INSIGHT 段丢失

日期：2026-07-21

## 现象

生产日志出现：

```
[api] response truncated: finish_reason=length (returning partial)
[consolidate] unified output missing INSIGHT section
Consolidate partial: 1 step(s) failed: ['reflections']
```

T3（#164）把 facts+experience+insight 合并为一次 LLM 调用后，输出变长，但仍走 provider 默认 `max_tokens=512`——末段（INSIGHT）被 `finish_reason=length` 截掉，L1 insight 在每批固化中静默丢失。

## 修复（三管齐下）

1. **预算**：`session_factory.llm_generate` 与 `MemoryConsolidator._call_llm` 增加可选 `max_tokens` 透传；`_consolidate_unified` 以 `max_tokens=1024` 调用。
2. **约束**：`CONSOLIDATION_UNIFIED_PROMPT` 加长度硬约束（FACT 值 ≤20 字、hypothesis ≤80 字、SUMMARY ≤60 字）。
3. **保险**：prompt 段序从 FACTS→EXPERIENCE→INSIGHT 调整为 FACTS→INSIGHT→EXPERIENCE——万一仍截断，牺牲最啰嗦、可下批再生的 EXPERIENCE，保住结构化的 INSIGHT。

## 测试

- `tests/test_consolidation_unified.py` 新增 `test_unified_call_uses_enlarged_token_budget`：断言统一调用 `max_tokens >= 1024`，防回归。
- 全量：`pytest tests --ignore=tests/real_api -q` → **810 passed**（807 + 新测试 1 + 此前 embedding 服务未运行而跳过的 2 个用例本次实际执行通过）。

## 备注

- 旧三次调用路径（L2/L3 批次与灰度回退）不受影响，仍用默认预算。
- 教训记录：本文件的防回归测试首次追加时误落在 `if __name__` 块内（缩进嵌套），pytest 静默漏收集——已修正并复核收集数（该文件 6→7 个用例）。
