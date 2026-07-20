# 修复方案：主动思考空转烧 Token + 关联问题（2026-07-20）

> 依据：2026-07-20 日志分析（API 断连 + inner_drive 高频空转 + 情绪钳制 + 梦境污染 + 空查询虚假置信度）。
> 本文档面向执行者：每一项都给出根因（文件/行/现状代码）、修法、测试与验收标准。**严格按项执行，不要做清单之外的"顺手优化"。**
> 项目：D:/桌面/编程作品/AI朋友，Python 3.12，Windows。
> 回归基线：`python -m pytest tests --ignore=tests/real_api -q` → 当前 **642 passed + 2 skipped**，全部改完后必须全绿。

---

## 问题总览与修复优先级

| # | 问题 | 根因位置 | 优先级 |
|---|------|----------|--------|
| F1 | silent 决策无冷却，用户沉默越久思考越频繁，70 分钟烧约 3 万 tokens | `core/runtime_driver.py` + `core/proactivity.py` | **P0** |
| F2 | 沉思循环默认 3 轮，沉默期大多数决策首轮即 silent | `core/inner_drive.py` + `config.py` | P0 |
| F3 | proactive 路径用空字符串查 memory_agent，返回 0.74 虚假置信度 | `core/inner_drive.py:389` | P1 |
| F4 | 梦境被当真实记忆反复反刍 | `core/sleep_manager.py` → 检索/prompt 链 | P1 |
| F5 | 用户沉默期间情绪不衰减，arousal 高位使触发更频繁 | `core/proactivity.py:104` | P2 |
| F6 | API 断连重试间隔短（1/2/4s），各模块独立重试放大故障 | `core/provider.py` | P2 |

---

## F1（P0）：silent 决策加指数退避冷却

### 根因

`core/runtime_driver.py` 主循环（每 15s 一个 tick）：

```python
score = engine.calculate_proactivity(idle)      # :93
if random.random() < score:
    intent = await self._run_blocking(engine.decide_proactive_action, idle)  # :95 — 1~3 次 LLM 调用
    ...
    if response:                                # 只有真正发出消息才进这里
        engine.touch()
        engine.record_rate_limit(intent.action)
        cooldown = self.PROACTIVE_COOLDOWN_TICKS  # :113 — silent 永远走不到
```

- `decide_proactive_action` 即 InnerDrive 沉思循环（每次 1~3 次 LLM 调用）。
- `action="silent"` 时只在 :107 打一条 debug 日志，**不设置任何 cooldown**。
- `calculate_proactivity`（`core/proactivity.py:82-125`）的 `base = min(0.3, (idle - min_idle) / 900)` 随沉默时间单调增长，cap 0.8——**用户沉默越久，触发越频繁**。这就是日志里 13:15–14:24 每 15~30 秒一次 think loop 的机制。

### 修法

给"连续 silent"加指数退避，用户说话或真正发出主动消息后重置。

**第 1 步：`core/proactivity.py` 的 `ProactivityManager` 增加 silent 退避状态**

在 `__init__`（:22-24 附近）加：

```python
self._consecutive_silents: int = 0   # F1: 连续 silent 决策次数（退避用）
```

新增两个公开方法（放在 `record_rate_limit` 后面）：

```python
def record_silent(self) -> None:
    """F1: InnerDrive 决定沉默时调用，连续 silent 次数 +1。"""
    self._consecutive_silents += 1

def reset_silents(self) -> None:
    """F1: 用户说话或主动消息真正发出后调用，退避清零。"""
    self._consecutive_silents = 0

def silent_cooldown_seconds(self) -> float:
    """F1: 连续 n 次 silent 后的决策冷却秒数：60→120→240→…，封顶 1800s。"""
    if self._consecutive_silents <= 0:
        return 0.0
    return min(60.0 * (2 ** (self._consecutive_silents - 1)), 1800.0)
```

**第 2 步：`core/runtime_driver.py` 应用冷却**

- `__init__` 加实例属性 `self._next_decision_after: float = 0.0`（最早允许下次 LLM 决策的时间戳）。
- :93 的 `score = ...` 之前加门控（需要 `import time`，文件顶部检查是否已有）：

```python
if time.time() < self._next_decision_after:
    await asyncio.sleep(self._tick_normal)
    continue
```

- silent 分支（:106-107）改为：

```python
if intent.action == "silent":
    engine.record_silent()  # 经 conversation_engine 转发到 ProactivityManager
    self._next_decision_after = time.time() + engine.silent_cooldown_seconds()
    logger.debug(f"[runtime] inner drive chose silent: {intent.reasoning[:80]}")
```

- `if response:` 分支（:110-114）内加 `engine.reset_silents(); self._next_decision_after = 0.0`。
- 用户消息路径不需要改 driver——`handle_message` 会更新 last_activity，idle 归零后 `idle < IDLE_FLOOR_SECONDS` 自然跳过决策；但为保险，在 `record_silent` 的冷却判断处同时要求 `idle >= 60` 才生效（可选，不做也行）。

**第 3 步：`core/conversation_engine.py` 加转发方法**

仿照现有 `record_topic` 转发（:138-141 附近），加 `record_silent()`、`reset_silents()`、`silent_cooldown_seconds()` 三个薄转发到 `agent._proactive`（经 agent 的公开方法，若 `core/agent.py` 没有对应转发就照 `record_topic` 的链路补齐）。

### 测试

- `tests/test_proactivity.py` 新增：连续 silent 1/2/3/10 次时冷却秒数为 60/120/240/1800（封顶）；`reset_silents` 后归零。
- `tests/test_runtime_driver.py`（没有就新建，风格参考现有测试）：silent 决策后 `cooldown` 生效期间 tick 不再调 `decide_proactive_action`；用户消息/发出 proactive 后冷却解除。

### 验收

- 模拟用户沉默 30 分钟，LLM 决策调用次数 ≤ 6 次（修复前约 60-120 次）。
- 全量测试不降级。

---

## F2（P0）：沉思循环成本收敛

### 根因

`core/inner_drive.py:430-462`：每次触发最多 `self._think_max_rounds`（默认 3，`config.py` 的 `proactive_think_max_rounds`）轮，每轮一次 `provider.generate`。日志显示沉默期绝大多数首轮即 `silent`（round=1/3 一次调用就返回）——3 轮上限不是问题主体，但默认值可以收紧。

### 修法

1. `config.py` 与 `config.example.json`：`proactive_think_max_rounds` 默认值 3 → **2**（沉默期想清楚"说不说"不需要第 3 轮）。
2. `prompts/system.py` 的 `build_inner_drive_proactive_prompt` 沉思循环协议块中，在输出格式说明后加一句硬约束（中文，风格跟随周边）：

   > 如果没有真正值得开口的事，第一轮就直接给 silent 决定，不要用 recall 凑轮次。

3. `doc/config-reference.md` 同步默认值说明。

### 测试

- 现有 `TestProactiveThinkLoop`（tests/test_inner_drive.py）中依赖 3 轮上限的用例同步调整为 2 轮语义；断言默认值已改。

---

## F3（P1）：空查询不再走 memory_agent

### 根因

`core/inner_drive.py:389`：`cs = self._context_summary_for("")`——proactive 路径没有用户消息，query 为空字符串。`memory_agent.answer("")` 时 `_encode_bytes('')` 返回 None（`memory/memory_agent.py:307` 的 `text.strip()` 判断），`top_sim=n/a`，但仍返回 facts/observations/experiences 池共 10 条 evidence 和 0.74 的 confidence——**空查询的"最近记忆概览"被当成带置信度的"证据"**喂给思考循环，每 15-30 秒一次。

### 修法

改 `_context_summary_for`（`core/inner_drive.py:220-235` 附近）：**query 为空时跳过 memory_agent，直接用 retriever**（概览场景本来就不需要置信度管线）：

```python
def _context_summary_for(self, query: str):
    # F3: 空 query（proactive 等无用户输入路径）不需要 MemoryAgent 的
    # 置信度/证据链管线——空查询会得到"全部最近记忆 + 虚假高置信度"，
    # 直接用 retriever 的概览即可
    if not (query or "").strip():
        return self._format_summary(self._retriever.retrieve_for_query(""))
    # ……原有逻辑不变……
```

注意：先读该函数现状（M-04 修复后的版本），保持返回类型与原有调用方契约一致；`_format_summary` 是示意名，按现有代码里 retriever 结果格式化的实际写法来。

### 测试

- `tests/test_memory_agent_integration.py`：`use_memory_agent=true` 且 query 为空时 `memory_agent.answer` 不被调用、retriever 被调用；非空 query 行为不变。

---

## F4（P1）：梦境不得当真实记忆反刍

### 根因

`core/sleep_manager.py:generate_dream()`（:185-196）把梦境以 `summary="梦境：..."` 存为 experience（`tags=["dream"]`）。之后它进入检索结果（`memory/retrieval.py` 的 hot memory 最近 experiences、memory_agent 的 experiences 池），出现在 proactive 思考与 Agent 3 的上下文里，**LLM 把虚构梦境当共同回忆反复解读**（日志中的"切种进梦里长根认错"被几十次引用）。

### 修法（两步都做）

1. **标注**：在把 experiences 格式化进 prompt 的位置，给 dream 条目前加明确标记。先 grep 找全位置：

   ```
   grep -rn "梦境\|tags.*dream\|emotional_tone.*summary" memory/ prompts/ --include=*.py
   ```

   主要位置预期在 `memory/retrieval.py`（hot memory 格式化）与 `memory/memory_agent.py:392-399`（experiences → evidence 的 content）。统一在格式化时对 `tags` 含 `"dream"` 的条目把内容前缀改为 `【梦境，非真实事件】`（memory_agent 处在 `content=f"[{e.emotional_tone}] {e.summary}"` 处判断 `e.tags`）。

2. **prompt 约束**：`prompts/system.py` 的 `build_inner_drive_proactive_prompt` 指令块加一句：

   > 标记【梦境】的内容是梦，不是真实发生的事，不要当作共同回忆展开或引用。

注意：`storage/repository.py` 的 `_row_to_experience` 若没读出 `tags`，需先确认 `Experience.tags` 在检索路径可用；不可用则在 SQL/行映射补上（读代码确认，别凭空假设）。

### 测试

- 构造一条 `tags=["dream"]` 的 experience 和一条普通 experience，断言进入检索/evidence 输出时前者带【梦境】前缀、后者没有。
- 全量测试不降级。

---

## F5（P2）：沉默期触发频率加疲劳因子

### 根因

`core/proactivity.py:104`：`emotion_mod = e.arousal * 0.2`——情绪只在用户消息时更新（H-05 修复后 proactive 不再偏移情绪），**用户沉默 70 分钟 arousal 仍冻结在高值**，`base` 又随 idle 单调增长，双重叠加导致高频触发。日志中 `v=+1.00` 的 hard clamp 只是 `models/personality.py:209-211` 的 info 提示，不是 bug 本体，不用改。

### 修法

在 `calculate_proactivity` 的 score 合成行（:119）后加沉默疲劳修正：

```python
# F5: 长时间沉默疲劳——用户半小时以上没说话，逐步压低触发概率
fatigue = min(0.3, max(0.0, (idle_duration - 1800.0) / 1800.0) * 0.1)
score = max(0.0, min(0.8, score - fatigue))
```

（F1 的退避已解决空转主问题，本项是让概率模型本身也对长期沉默脱敏。数值可按实测微调，但必须：沉默 30 分钟内无影响，2 小时沉默时 score 显著低于修复前。）

### 测试

- `tests/test_proactivity.py`：同情绪同 idle=3600 时 score 低于 idle=900 的情形；idle=1800 以内无 fatigue 修正。

---

## F6（P2）：API 断连重试增强

### 根因

`core/provider.py` 的重试链是 3 次、间隔约 1s/2s/4s（日志 `retry_in=1s` 可见），7 秒内放弃；`RemoteDisconnected` 这类服务端故障恢复以分钟计，期间每个调用方（assess / think loop / dream / consolidation）各自烧 3 次重试。

### 修法

1. 重试间隔改指数：`retry_in` 序列由约 1/2/4 秒改为 2/5/15 秒（找到 provider.py 中计算 retry_in 的位置，改为 `min(2 ** attempt * 2, 15)` 或等价写法，保持 3 次上限不变）。
2. 加简易熔断：`DeepSeekProvider` 增加类级/实例级计数——连续 3 次请求彻底失败（重试耗尽）后，60 秒内新请求直接抛出最后一次的异常（不发起 HTTP、不重试），60 秒后自动恢复半开。加注释 `# F6: circuit breaker`。
3. 不改动 `agent1 assess failed, degrading to direct reply` 的降级语义——熔断只是让失败更快、更省。

### 测试

- `tests/test_provider.py`：mock session 连续失败，验证第 4 次调用在熔断窗口内不发 HTTP 直接抛错；窗口过后恢复尝试。
- 重试间隔序列断言。

---

## 执行要求（交给执行模型）

1. **顺序**：F1 → F2 → F3 → F4 → F5 → F6。F1/F2 是核心，必须最先完成并先行验证。
2. **每完成一项**跑相关测试文件；**全部完成后**跑 `python -m pytest tests --ignore=tests/real_api -q`，基线 642 passed + 2 skipped 不得降级（新增测试会使总数上升）。
3. 注释风格跟随周边代码：中文注释 + 本方案编号（如 `# F1: ...`）。
4. 完成后在 `changes/` 写变更记录（命名 `changes/2026-07-20-主动思考空转修复.md`），逐项列改动。
5. **不要做的事**：
   - 不要改 `models/personality.py` 的 hard clamp 日志与钳制逻辑（不是 bug）。
   - 不要动 H-05 的 `skip_post_process` 语义（proactive 不分析旧消息情绪是有意设计）。
   - 不要重构 RuntimeDriver 主循环结构、不要改 sleep/wake 窗口。
   - 不要给 proactive 路径重新引入"对旧用户消息做情感分析"的逻辑。
