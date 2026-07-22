# 修复方案：known-issues 验证后剩余项（#295 ContextManager / #293 余项 / #103 余项）

> 来源：2026-07-22 代码逐条验证（`doc/known-issues.md` 顶部索引）。**#166/#162 Provider 异步化不在本方案范围**（见文末「不实施项」）。
> 面向执行者：每项给出根因（文件/行/现状代码）、修法、测试与验收。严格按项执行，不要做清单之外的"顺手优化"。
> 项目：D:/桌面/编程作品/AI朋友，Python 3.12，Windows。
> 回归基线：`python -m pytest tests --ignore=tests/real_api -q` → 当前 **842 passed**，全部改完后必须全绿。
> 完成后在 `changes/` 写变更记录（命名 `changes/2026-07-22-context-and-review-fixes.md`）。

---

## 总览

| # | 问题 | 位置 | 工作量 |
|---|------|------|--------|
| T1 | `should_compress()` 不存在，压缩触发散在调用方 | `core/context_manager.py` | 小 |
| T2 | `estimate_tokens` 无缓存，每轮全量重算 | `core/context_manager.py` | 小 |
| T3 | 压缩策略粗暴：`content[:500]` 逐条截断 + `text[-8000:]` 截尾丢历史 | `core/context_manager.py:73-98` | 中 |
| T4 | 压缩摘要全量覆盖，无增量合并 | `core/context_manager.py:73-98` | 中 |
| T5 | review()/re_decide() 与 assess() 推理循环重复 | `core/inner_drive.py` | 中 |
| T6 | #103 余项核实：循环导入现状确认（只记录，不改） | 全库 | 小 |

---

## T1：ContextManager 提供 `should_compress()`

### 根因

压缩触发判断散在调用方（`core/message_handler.py::_build_messages` 内联比较 `running_total > COMPRESS_THRESHOLD`），ContextManager 作为"上下文窗口管理"模块却不提供判断入口（#295 审查意见 4）。

### 修法

`core/context_manager.py` 新增：

```python
def should_compress(self, estimated_tokens: int) -> bool:
    """#295: 由本模块统一判断是否需要压缩（此前阈值判断散在调用方）。"""
    return estimated_tokens >= COMPRESS_THRESHOLD
```

`message_handler.py::_build_messages` 的两处 `> COMPRESS_THRESHOLD` 比较改为调用 `agent._context.should_compress(...)`（先读代码确认 agent 上 ContextManager 的访问路径，保持现有 `overflow`/`compress_context` 语义不变）。

### 测试

- 阈值上下边界用例；`_build_messages` 行为不变（现有 overflow 测试不降级）。

---

## T2：`estimate_tokens` 加 LRU 缓存

### 根因

`estimate_tokens(text)`（context_manager.py:27-36）在 `_build_messages` 中对每条历史 turn 调用一次，tiktoken encode 是纯函数却每轮重算（#295/#103 共同余项）。

### 修法

模块级 LRU 缓存（`functools.lru_cache` 或手写 OrderedDict 均可，容量 2048）：

```python
from functools import lru_cache

@lru_cache(maxsize=2048)
def _estimate_tokens_cached(text: str) -> int:
    ...  # 原 estimate_tokens 函数体

def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    # 超长文本不缓存（避免单条大文本顶掉整个缓存）
    if len(text) > 4000:
        return _estimate_tokens_cached.__wrapped__(text)
    return _estimate_tokens_cached(text)
```

- tiktoken 不可用的降级分支逻辑保持原样，一并进缓存。
- 不要缓存对象级状态；`_get_tokenizer()` 的懒加载不变。

### 测试

- 同文本两次调用结果一致且第二次命中缓存（`cache_info()` 断言或计时宽松断言）；超长文本不缓存；现有 token 估算用例不降级。

---

## T3：压缩输入不再均匀截断（保留最近完整、远期递减排版）

### 根因

`_do_compress`（:76-87）对**每条**消息 `content[:500]` 均匀截断，再整体 `text[-8000:]` 截尾——远期消息丢关键信息、最早信息直接消失（#295 审查意见 1/5）。

### 修法

替换排版逻辑（:76-87），语义：**最近 K 条完整保留，更早的逐条短截断，仍受总预算约束**：

```python
RECENT_FULL_TURNS = 6        # 最近 6 条完整保留
OLDER_SNIPPET = 120          # 更早的每条截断到 120 字符
MAX_COMPRESS_INPUT = 12000   # 压缩输入总字符预算（原 8000 上调）

non_system = [m for m in messages if m["role"] != "system"]
recent = non_system[-RECENT_FULL_TURNS:]
older = non_system[:-RECENT_FULL_TURNS] if len(non_system) > RECENT_FULL_TURNS else []
parts = []
for m in older:
    content = m["content"][:OLDER_SNIPPET]
    parts.append(f"{'用户' if m['role'] == 'user' else '你'}: {content}")
for m in recent:
    parts.append(f"{'用户' if m['role'] == 'user' else '你'}: {m['content']}")
text = "\n".join(parts)
if len(text) > MAX_COMPRESS_INPUT:
    text = text[-MAX_COMPRESS_INPUT:]  # 仍有总预算兜底
```

- 常量提为模块级（风格跟随 COMPRESS_THRESHOLD）。
- `CONTEXT_COMPRESS_PROMPT` 文案不动。

### 测试

- 长对话（>6 条）压缩时：最近 6 条完整出现在压缩输入中，更早的被短截断；短对话全部完整；现有压缩测试不降级。

---

## T4：压缩摘要增量合并

### 根因

每次压缩用新摘要**整体覆盖** `_compressed_summary`（:94），早期摘要信息丢失（#295 审查意见 2 的务实版——不做完整分层摘要，做增量合并）。

### 修法

`_do_compress` 中，已有旧摘要时改为"合并压缩"：

```python
if self._compressed_summary:
    compress_input = f"【已有历史摘要】\n{self._compressed_summary}\n\n【新增对话】\n{text}"
else:
    compress_input = text
```

- prompt 模板 `CONTEXT_COMPRESS_PROMPT` 不动（其"保留重要信息"的指令对合并输入同样适用）；若现有模板措辞对"已有摘要+新增对话"结构明显不合，可微调模板一句说明，但保持第三人称 2000-2500 字约束。
- 压缩失败时旧摘要必须保留（现状：失败只 warning，不清空——确认保持）。

### 测试

- 已有摘要 + 新消息压缩：LLM 收到的输入同时含旧摘要与新对话；无旧摘要时行为同现状。

---

## T5：inner_drive 推理循环抽公共方法

### 根因

`core/inner_drive.py`：`assess()`（:230-330 附近）与 `review()`（:617-680 附近）、`re_decide()`（:700-760 附近）各自实现同一套"构 prompt → 调 LLM → JSON 决策 → recall 子循环"流程，仅 prompt 构建与兜底文案不同（#293 P1-2 审查意见）。

### 修法

抽取私有方法 `_decision_loop(messages, *, max_rounds, on_parse_failed, source) -> InnerDriveResult`（签名为示意，执行时按三方公共部分归纳）：

- 公共：JSON 解析失败兜底、recall_query 子循环（execute_tool_calls + 结果喂回）、max iterations 处理。
- 各方保留：prompt 构建、日志 tag、兜底文案。
- `assess` / `review` / `re_decide` 改为薄壳调用。

**红线**：纯结构抽取，三个方法的现有行为（日志文本、返回字段、recall 轮次）逐条不变；`assess_proactive` 与 `assess_agent3_intent` 不动。

### 测试

- 现有 `tests/test_inner_drive.py` 全部不降级（行为等价即过）；无需新增用例，但若公共方法有独立逻辑可补 1-2 条直接测试。

---

## T6：#103 循环导入现状确认（只记录）

- `changes/2026-07-22-context-and-review-fixes.md` 中记录一次全库循环导入扫描结果（可用 `python -X dev -c "import core.agent, web.server, memory.consolidation"` 及 grep import 链人工核对），确认现存的 lazy import 点（agent ↔ cli_controller、short_term ↔ context_manager 等）是否仍必要。
- **不改代码**，只在变更记录里给结论。

---

## 收尾

1. 全量测试 842 + 新增 ≥ 全绿；`py_compile` 全模块。
2. `changes/2026-07-22-context-and-review-fixes.md` 逐项列改动；同步更新 `doc/known-issues.md` 顶部索引中 #295/#293/#103 的状态行（#295 主体完成后可标 ✅，注明"分层摘要仍推迟"）。
3. GitHub issue #295 已关闭，无需操作。

## 不实施项（明确排除）

- **#166 Provider 异步化 / #162 全面异步**：改 httpx.AsyncClient 牵动全部调用方（同步语义遍布 core/memory/storage），收益仅是并发上限（当前 run_in_executor 已不阻塞事件循环）。归 Layer 5 单独立项，不在本方案。
- **#295 的完整分层摘要（Recent→Daily→Long-term）**：T4 增量合并已覆盖 80% 价值，完整分层是独立特性。
- **Token Budget / ContextAllocator**：Layer 2 立项项，见 cognitive-state 方案 Phase 3。
- **#2 控制台乱码**：用户已确认不是 bug，不动。
