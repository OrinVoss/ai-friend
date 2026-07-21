# 内驱状态（Inner Drive State）设计

> 目标：给 Agent 一个跨触发持久的「内心世界」——它惦记什么、好奇什么、反思什么、计划什么，不会每次独处都从零开始。
> 状态：一期 + 二期 ✅ 已实现（2026-07-18）；三期 ✅ 回馈闭环 + memory_agent 来源已实现（2026-07-21，`changes/2026-07-21-layer4-tail.md`），dreams 明确不做。
> 归属：Layer 4（Agent Runtime）；与 Layer 1（Memory）、Layer 6（Session 绑定）有接口。

---

## 1. 定位：记忆回答「发生了什么」，内驱回答「我在意什么」

| | 记忆系统（Layer 1） | 内驱状态（本文档） |
|---|---|---|
| 内容 | 关于用户和世界的事实 | Agent 自己的注意力和意图 |
| 积累方式 | 被动：对话中沉淀 | 主动：思考中维护 |
| 工作方式 | **拉（pull）**：被问才答 | **推（push）**：自己浮上来 |
| 消费方 | 所有 Agent | Agent 1 沉思循环 + 响应路径（4.2） |

记忆是图书馆，内驱状态是贴在桌上的便利贴。挂念条目的**内容**来自记忆，但它额外存了记忆没有的运营数据——优先级、时效、浮现次数、解决状态。可以把它理解为记忆之上的**「未闭合的环」索引**。

两者互相喂养：**记忆里未完成的线索变成挂念；挂念被解决后，结果作为新内容回流记忆。**

---

## 2. 条目模型

```json
{
  "id": "c_20260716_001",
  "type": "care",
  "content": "用户妹妹的高考成绩还没问",
  "priority": 0.8,
  "source": "think_loop",
  "created_at": "2026-07-14T22:30:00",
  "last_surfaced_at": "2026-07-16T09:00:00",
  "surface_count": 2,
  "expires_at": null,
  "status": "active",
  "resolution": ""
}
```

五种类型，各驱动不同行为：

| 类型 | 说明 | 驱动的行为 | 示例 |
|------|------|-----------|------|
| `care`（挂念） | 对用户的关心、follow-up | chat | 「用户最近失眠，问问好点没」 |
| `curiosity`（好奇） | 它自己想搞明白的事 | explore | 「用户推荐的那本书讲了什么」 |
| `reflection`（反思） | 对自己行为的改进点 | 影响 chat 方式 | 「上次讲笑话冷场了，换种方式」 |
| `plan`（计划） | 带时间点的承诺/期待 | 到点 chat | 「用户明天面试，晚上问结果」 |
| `idea`（灵感） | 想分享的创造 | chat | 「想到一个适合用户的歌单」 |

关键字段：

- `priority`（0.0~1.0）：浮现权重，动态调整（见第 3、6 节）
- `expires_at`：时效。`plan` 类通常有明确时效（面试当天）；其他类型可空
- `surface_count` / `last_surfaced_at`：被「想到」的次数和时间，用于衰减和淘汰
- `resolution`：解决时的记录（「已询问，用户说考得不错」）——这是它「完成了心事」的证据，并作为新内容回流记忆

---

## 3. 生命周期（与 Layer 1 同构）

内驱条目和记忆一样有生老病死，不能只增不减：

```
active（活跃）
  ├── resolved（已解决）：行动完成——问了、探索了、分享了
  │     resolution 记录结果，保留一段时间后清理
  ├── expired（已过期）：超过 expires_at（计划已过点）
  └── decayed（已衰减）：长期浮现但从未行动，priority 持续下降
        → 低于阈值（如 0.2）自动归档
```

**衰减规则**：每次浮现（进入思考上下文）但未行动，`priority *= 0.9`——「老想到但一直不做的，多半是空谈」，让它自然沉底。

**淘汰规则**：不是 FIFO。容量满时，按 `status > priority > expires_at` 综合淘汰：先清 resolved/expired，再清低 priority，最后才动旧的活跃条目。

---

## 4. 浮现规则：什么进入思考

```
浮现分 = priority × 类型权重 × 时效加成
```

- **情绪联动**：低落时 `reflection` / `care` 类型权重上调；兴奋/好奇时 `idea` / `curiosity` 上调——心情影响它想什么
- **时间敏感**：`plan` 类接近 `expires_at`（如剩余 < 6 小时）时强制置顶——约定不能错过
- **新鲜度**：`created_at` 距今越近，微弱加成

### 4.1 主动触发浮现（独处时）

沉思循环 Round 1 的输入不是全量倾倒，而是按浮现分选出 Top K（默认 8 条）。

### 4.2 对话触发浮现（响应路径）

挂念不只属于独处时。日常对话里，用户聊到的事和某条挂念相关时，它应该自然浮上来——这是「关心」最自然的表达方式：

- 写入时给每条挂念算 embedding（本地向量模型，成本可忽略）
- 用户消息进来时，用消息向量与活跃挂念比对，相关度超过阈值（如 0.7）的 Top 3 注入 Agent 1 的上下文
- 经 #160 的 `context_summary` 链路，同一份结果自然流到 Agent 3，调用侧零改动
- Prompt 引导：「以下是你在意的事，与当前对话相关的可以自然提及，不要硬塞」

**成本**：一次本地向量比对 + 约 100~200 token 上下文，零额外 LLM 调用——响应路径用得起。

**反向闭环**：对话中挂念也可能被**解决**（用户自己提起「我妹妹成绩出来了」）或**产生**（用户说「我后天面试」）。检测放在 consolidation：它整理记忆时对照活跃挂念，命中的标记 resolved，新线索生成新条目——见第 5 节。

典型场景：用户说「我妹妹成绩出来了」，那条「还没问成绩」的挂念正好在上下文里，AI 自然接「太好了，考得怎么样？」——而不是等独处时才想起来。

---

## 5. 写入来源（不只是思考循环）

| 来源 | 说明 | 阶段 |
|------|------|------|
| `think_loop` | 沉思循环中 `care_updates` 新增/移除 | 一期 |
| `consolidation` | 记忆整理时发现「未完成的线索」自动写入（如「用户说过两天要面试」→ 生成 plan）；同时对照活跃挂念，把对话中已解决的标记 resolved | 二期 |
| `memory_agent` | 交叉验证发现矛盾/缺口时生成 curiosity（「用户说的和之前矛盾，找机会确认」） | 二期 |
| `user` | 用户直接交代（「到时候提醒我」→ plan） | 二期 |

多来源写入让内驱状态成为**全系统的注意力列表**，不只是 Agent 1 的私人笔记本。consolidation 写入尤其关键：它睡觉整理记忆时发现线索，醒来惦记——这是「睡眠式巩固」和内驱的合流。

---

## 6. 回馈闭环：主动性会学习

每次由内驱驱动的主动行为，记录结果：

```
主动开口（由某条 care 驱动）
  ↓
用户回应积极 → 该条目 resolved，同类型条目 priority 微弱上调
用户回应冷淡/无回应 → 该条目 resolved，同类型条目 priority 微弱下调
```

长期效果：它逐渐学会「什么样的主动是受欢迎的」——不是固定策略，而是从相处中长出来的分寸感。这和 Layer 1 的 verification_count 是同一个哲学：置信度来自证据，不来自规则。

---

## 7. 存储与配置

- **存储**：`data/.inner_drive_state.{session_id}`（JSON 文件，沿用 `.sleep_state` 的 per-session 模式；Layer 6 落地后随角色绑定）
- **损坏兜底**：文件损坏/读取失败 → 当次触发以空白内驱状态运行，不影响主流程

```python
# config.py / config.json
inner_drive_state_max_entries: int = 30    # 条目容量
inner_drive_surface_top_k: int = 8         # 独处时每轮思考浮现条数
inner_drive_surface_response_k: int = 3    # 对话时相关浮现条数
inner_drive_decay_rate: float = 0.9        # 浮现未行动的衰减率
```

---

## 8. 接口（供 Think Loop / Consolidation / 响应路径调用）

```python
class InnerDriveState:
    async def load(self, session_id: str) -> None
    async def surface(self, emotion: EmotionalState, top_k: int = 8) -> list[DriveEntry]
    async def surface_for_query(self, query_embedding: bytes, top_k: int = 3) -> list[DriveEntry]
    async def add(self, entry: DriveEntry) -> None
    async def remove(self, entry_id: str) -> None
    async def resolve(self, entry_id: str, resolution: str) -> None
    async def record_outcome(self, entry_id: str, positive: bool) -> None
    async def decay_and_prune(self) -> None
    async def save(self) -> None
```

- `surface()`：独处时按浮现分选 Top K（4.1）
- `surface_for_query()`：对话时按向量相关性选 Top K（4.2），由 Agent 1 `assess()` 调用

---

## 9. 分期实施

| 期 | 内容 | 依赖 |
|----|------|------|
| 一期 ✅（2026-07-18，`changes/2026-07-18-proactive-think-loop.md`） | 最小挂念清单：扁平列表、20 条、FIFO，随 Proactive Think Loop 落地 | Think Loop |
| 二期 ✅（2026-07-18，`changes/2026-07-18-inner-drive-state-p2.md`） | 类型化条目 + 生命周期（resolved/expired/decayed）+ 浮现规则 + consolidation 写入与对照解决 + **响应路径注入（surface_for_query）** | Layer 1 双写稳定 |
| 三期 | 回馈闭环 ✅ + `memory_agent` 来源 ✅（2026-07-21）；长期梦想 dreams 明确不做（数周尺度，当前无数据支撑） | Memory Agent P0 |

**dreams（三期）**是真正的长期内驱：比挂念大一个时间尺度，不因单次行动 resolved，而是持续影响思考方向。一期二期先不做，但条目模型预留了扩展空间（`type: "dream"`）。

---

## 10. 测试与验收

测试（`tests/test_inner_drive_state.py`）：

1. add / remove / resolve 基本读写
2. 浮现排序：plan 临期置顶、情绪联动加权正确
3. 衰减：连续浮现未行动 priority 下降，低于阈值归档
4. 淘汰：容量满时先清 resolved，不动高 priority 活跃条目
5. record_outcome：正面/负面反馈对同类型条目的加权
6. 文件损坏兜底：返回空状态不报错
7. surface_for_query：相关用户消息命中对应挂念，无关消息不命中
8. consolidation 对照：对话中提及挂念内容后，该条目标记 resolved

验收：

- 连续两次主动触发，第二次能看到第一次留下的挂念
- 一条 plan 到点后被强制浮现并驱动主动开口
- 用户冷淡回应后，同类主动行为频率可观察地下降
- 用户主动提起挂念的事后，该挂念被 resolved，不再浮现

---

## 11. 相关文档

- `proactive-think-loop.md` — 沉思循环（内驱状态的主要消费方）
- `doc/refactor/layer1-memory/plan.md` — 记忆生命周期（生命周期设计的同构参考）
- `doc/refactor/layer1-memory/memory-agent.md` — 二期 curiosity 来源
