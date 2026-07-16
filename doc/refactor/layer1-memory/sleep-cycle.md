# 睡眠循环（Sleep Cycle）：系统内部工作的统一窗口

> 目标：把「睡眠」从人格表演功能，升级为所有内部工作的统一调度窗口——实质性核查、记忆整理、GC、内驱维护，都趁睡觉时干。
> 状态：设计文档，待实现。
> 归属：Layer 1（大部分 Stage 是记忆工作）；内驱维护 Stage 依赖 Layer 4 的内驱状态。

---

## 1. 定位：身体在睡，大脑在整理

睡眠分两层：

| 层 | 内容 | 状态 |
|----|------|------|
| **表现层** | 睡眠时间窗、睡觉回复、醒来分享梦境——人格真实性 | ✅ 已有（`core/sleep_manager.py`） |
| **工作层** | 实质性核查、记忆整理、GC、内驱维护、提炼——系统健康 | 📐 本文档 |

人类睡眠时大脑在回放和巩固记忆（HMS 启发，见 `insights-from-hms.md` 1.5）。我们的系统目前只有「睡相」，没有「睡眠的功能」。

---

## 2. 现状盘点

`core/sleep_manager.py` 已有（全部保留，不动）：

- 时间窗：午睡 12:00-13:00、夜睡 23:00-01:00，醒来窗口 + 强制唤醒
- 情绪睡意：低落/低唤醒更容易困，兴奋更精神
- 睡眠中用户消息：记录后回一句睡觉回复（`message_handler.py:185`）
- 梦境：醒来时基于 facts+experiences 生成，存为 experience（tag=dream）
- 状态 per-session 持久化，10 分钟转换冷却

**缺口**：

- 睡眠期间**不做任何实质工作**
- consolidation 按对话轮数触发，和睡眠完全无关
- GC 跟着 consolidation 走（每 5 次顺带一次），没有完整运行时机
- 挂念清单（待实现）无人维护——没有 decay、没有 prune、没有从对话中发现新线索
- 旧 Facts 无人核查——只有写入，没有「回头看」

---

## 3. 睡眠流水线（工作层）

入睡时按序执行，每个 Stage 独立、可中断、可恢复：

```
入睡触发（现有 SleepManager 时间窗，不变）
  ↓
Stage 1 整理 Consolidation
  未处理的 turns → Observations → 候选 Facts → 双写
  （已有能力，改为入睡时强制执行一次）
  ↓
Stage 2 核查 Verification（实质性核查，核心新增）
  - 批量验证旧 Facts（Memory Agent verify_fact，最小睡眠式巩固）
  - 矛盾检测：活跃 Facts 比对（带缓存，避免 O(n²)）
  - 低置信度 → decay / 标记待清理
  ↓
Stage 3 清理 GC
  decay / merge / obsolete / archive；超龄 Observation 归档
  （已有骨架，睡眠时完整运行而非顺带）
  ↓
Stage 4 内驱维护 Drive Maintenance
  - 挂念清单 decay_and_prune
  - 从今天的对话/观察发现未完成线索 → 新挂念（plan/care）
  - 对话中已解决的挂念 → resolved
  ↓
Stage 5 提炼 Insight（二期）
  高重要性 Observations 聚类 → Insight（带证据链的假设）
  ↓
Stage 6 做梦 Dream（已有，移到最后）
  基于整理后的记忆生成梦境 → experience
  升级：梦境素材加入挂念清单——梦见惦记的事
  ↓
醒来（现有窗口）→ 输出睡眠报告（日志 + 一句话自我总结）
```

**为什么做梦在最后**：真人做梦是记忆整理后的「回放」。先整理、核查、维护完，再用更新后的记忆和挂念做梦——梦才有素材，「梦见惦记的事」才成立。

---

## 4. 设计原则

1. **Stage 独立**：每个 Stage 独立 try/except，单个失败不影响后续，失败记入睡眠报告
2. **可中断可恢复**：Stage checkpoint 持久化（`.sleep_work.{session_id}`），进程被杀或时间不够时，下次入睡从断点续跑
3. **幂等**：每个 Stage 可重复执行不出错（重跑不产生重复数据）
4. **预算控制**：整个工作层有 token 预算上限（可配置），用完即止，剩余 Stage 标记 pending
5. **不打扰表现层**：用户深夜发消息仍走现有睡觉回复逻辑；工作层在后台静默运行

---

## 5. Stage 2 细则：实质性核查

用户点名的核心能力——对整体记忆做「回头看」：

**核查对象**（按优先级）：

1. `freshness` 低于阈值的 Facts
2. `last_verified_at` 超过 N 天（如 7 天）的 Facts
3. `verification_count = 0` 的新 Facts（刚提升还没被验证过）

**核查方式**：

- 逐条调用 Memory Agent `verify_fact()`：检索近期 Observations，判断是否仍被支持
- 结果分流：仍成立 → `verification_count + 1`，freshness 回升；存疑 → confidence 下调；被推翻 → contradicted
- 矛盾检测复用 `FactChecker`，结果缓存，避免 O(n²) 重复计算

**为什么放在睡眠**：核查是 Memory Agent 的批量模式（`memory-agent.md` P1「最小睡眠式巩固」），它需要逐条检索 + 打分，是重操作——睡眠是唯一没有用户在等的窗口。

---

## 6. 调度

| 场景 | 行为 |
|------|------|
| 午睡（短） | 只跑 Stage 1 + 4（轻量，无核查） |
| 夜睡（长） | 全量流水线 |
| 手动触发 | Web/CLI 提供「立即睡眠整理」入口（调试用），跑全量 |
| 时间不够/中断 | checkpoint 记录已完成 Stage，下次入睡续跑 |
| 连续失败 | 单 Stage 连续失败 3 次 → 跳过并告警（日志），不阻塞其他 Stage |

---

## 7. 改动文件

| 文件 | 改动 |
|------|------|
| `core/sleep_manager.py` | 入睡时启动工作层（调用 SleepWorker），现有表现层逻辑不变 |
| `core/sleep_worker.py`（新建） | 流水线编排、checkpoint、预算控制、睡眠报告 |
| `memory/consolidation.py` | 暴露「强制执行一次」接口（不走轮数计数） |
| `memory/lifecycle.py` | 配合批量验证的查询接口（低 freshness / 逾期未验证列表） |
| 内驱状态接口 | `decay_and_prune()`；线索发现写挂念（二期） |
| `config.py` / `config.example.json` | `sleep_work_enabled` / `sleep_work_max_tokens` / `sleep_work_stages` |
| `tests/test_sleep_worker.py`（新建） | 流水线测试 |

---

## 8. 分期

| 期 | 内容 | 依赖 |
|----|------|------|
| 一期 | Stage 1 + 3（整理 + 清理）——全部复用已有能力，**零新增 LLM 调用** | 无 |
| 二期 | Stage 4（内驱维护） | 内驱状态一期（挂念清单） |
| 三期 | Stage 2（实质性核查） | Memory Agent P0/P1 |
| 四期 | Stage 5（提炼）+ 梦境素材升级（挂念入梦） | insights_v2 |

每期独立可上线：一期先让睡眠「开始干活」，核查随 Memory Agent 落地后再接入。

---

## 9. 测试与验收

测试（`tests/test_sleep_worker.py`）：

1. 各 Stage 独立失败不影响其他 Stage
2. checkpoint 中断恢复：模拟进程被杀，下次入睡从断点续跑
3. token 预算超限 → 停止后续 Stage 并记录 pending
4. 午睡只跑轻量 Stage，夜睡跑全量
5. Stage 1 幂等：重复执行不产生重复 Observation

验收：

- 夜睡一次后，`facts_v2` 中逾期未验证条目减少或 `verification_count` 增长（三期起）
- 挂念清单被 decay_and_prune（二期起）
- 日志输出睡眠报告：各 Stage 耗时、处理条数、失败项
- 全量测试不降级

---

## 10. 相关文档

- `doc/refactor/self-system.md` — 睡眠循环在自我系统中的位置（③）
- `plan.md` — Layer 1 记忆生命周期（Stage 1/3/5 的基础）
- `memory-agent.md` — 实质性核查的能力来源（P1 批量验证）
- `../layer4-agent/inner-drive-state.md` — Stage 4 的挂念维护
