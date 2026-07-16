# 独处活动与内化（Solo Activity & Internalization）

> 目标：让角色独处时的活动（探索网页等）像真人一样产生内化——看过的东西变成它的感悟、知识、谈资和心情，而不是说完就忘。
> 状态：设计文档，待实现。
> 归属：Layer 4（Agent Runtime）；决策方是 Proactive Think Loop，沉淀方是 Layer 1 记忆生命周期 + 内驱状态。

---

## 1. 愿景：像真人一样的独处

真人独处时有自己的「工作」：刷手机、看书、想事情。这些经历做完不会消散，而是内化成知识、观点、感悟、心情，以后聊天自然带出来——「对了，我前几天看到一个东西……」

我们的角色目前只有一种独处活动（`handle_explore` 翻网页），且**没有内化环节**。

---

## 2. 现状与缺口

`core/message_handler.py::handle_explore()` 当前流程：

```
选题 → ToolAgent 搜索/抓网页 → Agent 3 生成内容 → >30 字就分享给用户，否则丢弃
```

四个缺口：

1. **没分享 = 没发生**：决定沉默时，探索到的内容完全消失（`tool_call_history` 的记录不进记忆）
2. **分享了 = 只是对话记录**：进入 `conversation_turns` 等 consolidation 当普通对话处理，没有第一人称感悟（「我觉得这个有意思，因为……」）
3. **没有后续**：好奇心是否被满足？是否想深入了解？没有跟踪——探索是无头无尾的一次性动作
4. **没有情绪影响**：发现了有趣的东西，心情不会因此变化

一句话：**它有「行为」，没有「经历」。行为做完就消散，经历才会留下来变成它的一部分。**

---

## 3. 设计：活动 → 内化 → 沉淀

```
Think Loop 决定 explore（由 curiosity 挂念驱动）
  ↓
ToolAgent 执行探索（现有，不变）
  ↓
内化步骤（新增，一次轻量 LLM 调用）
  输入：探索内容摘要 + 触发的挂念 + 当前情绪
  输出 JSON：
    reflection:    第一人称感悟（"原来是这样，挺有意思的，因为……"）
    shareability:  now / later / never（值不值得分享给用户）
    share_note:    想分享的话，怎么说
    emotion_delta: 情绪影响（valence/arousal/curiosity 微调）
    care_updates:  挂念更新（curiosity resolved / 新 curiosity）
    memory_note:   值得长期记住的要点（可空）
  ↓
沉淀（全部确定性写入，无额外 LLM）
  ├── memory_note 非空 → Observation（created_by="explore"）→ Layer 1 生命周期
  │     → 以后可被提升为 Fact/Insight：它自己的知识
  ├── shareability=now   → 走现有分享路径（handle_explore 后半段）
  ├── shareability=later → 新增 idea 挂念（合适时机再聊）
  ├── care_updates       → 内驱状态（好奇被满足 / 产生新好奇）
  └── emotion_delta      → personality.emotion（发现趣事心情变好）
```

四个关键变化：

- **探索有头有尾**：curiosity 挂念触发 explore → 内化时 resolve 该挂念（「搞明白了」）或生成新 curiosity（「更想知道了」）——闭环
- **不立刻分享也有价值**：内化发生在分享决策**之前**，沉默 ≠ 白探索
- **攒谈资**：`shareability=later` 的感悟存为 idea 挂念，以后聊天时经对话触发浮现（`inner-drive-state.md` 4.2）自然带出来
- **它自己的知识**：`memory_note` 进 Observation → 可被提升为 Fact——记忆系统第一次有了「它知道的东西」，不再只有「关于用户的事实」

---

## 4. 感悟的归属：第三类记忆

当前记忆系统几乎全是「关于用户的记忆」。内化让第三类记忆出现：

| 记忆类型 | 内容 | 示例 |
|----------|------|------|
| 关于用户 | 用户的喜好、经历 | 「用户喜欢火锅」 |
| 关于关系 | 共同经历、关系指标 | 「一起聊过的深夜话题」 |
| **关于它自己**（新增） | 它的知识、观点、感悟 | 「我看了光合作用的新研究，觉得很有意思」 |

技术实现：`observations` 表已有 `created_by` 字段，`created_by="explore"` / `"inner_drive"` 即可区分，**无需改表结构**。这类记忆同样参与 Memory Agent 检索——Agent 3 以后可以说「我最近看到一个说法……」。

---

## 5. 活动类型扩展（二期）

独处活动不止翻网页。行动空间随内驱类型扩展：

| 活动 | 触发 | 说明 |
|------|------|------|
| `explore` 探索 | curiosity 挂念 | 现有，一期加内化 |
| `review` 复盘 | reflection 挂念 | 回顾最近的对话，想想哪里做得好/不好 → 感悟写入 |
| `create` 创造 | idea 挂念 | 写一段东西（诗、歌单、想法）→ 存为 idea 或分享 |
| `consolidate` 整理 | 系统调度 | 现有记忆整理，发现线索写挂念（`inner-drive-state.md` 第 5 节） |

**一期只做 explore 内化**；其余随内驱状态二期扩展。

---

## 6. 成本与约束

- 内化是每次 explore 后一次轻量调用（max_tokens ~300）；explore 本身已被 ProactivityManager 节流，日均增量可忽略
- 内化调用失败 → 退回现状逻辑（>30 字分享，否则丢弃），不阻塞主流程
- `emotion_delta` 限幅（单次各项 ±0.1 以内），避免探索频繁扰动情绪
- Observation 写入走 Layer 1 正常生命周期，会被 decay / GC——「一时兴起」不会永久占用记忆

---

## 7. 改动文件

| 文件 | 改动 |
|------|------|
| `core/message_handler.py` | `handle_explore()` 增加内化步骤（分享决策前移） |
| `core/inner_drive.py` | 新增 `internalize_explore()` 与 JSON schema |
| `prompts/templates.py` | 内化 Prompt 模板 |
| 内驱状态接口 | 消费 `care_updates`（复用 `inner-drive-state.md` 接口） |
| `tests/test_message_handler.py` | 内化流程测试 |

依赖：内驱状态一期（挂念清单）先行落地，curiosity/idea 闭环才有意义。

---

## 8. 测试与验收

测试：

1. explore 后调用内化，输出合法 JSON
2. `shareability=later` → idea 挂念生成，本次不向用户分享
3. `memory_note` 非空 → Observation 写入且 `created_by="explore"`
4. curiosity 挂念在 explore 内化后被 resolve
5. 内化失败 → 退回现状分享逻辑

验收：

- 探索后未分享的内容，后续仍能在对话中被检索到（Observation）
- 用户问「你最近在研究什么」→ 能答出自己的探索感悟
- curiosity 挂念闭环：触发 explore → 内化后 resolve

---

## 9. 相关文档

- `proactive-think-loop.md` — 独处时的决策循环
- `inner-drive-state.md` — curiosity / idea 挂念与浮现规则
- `doc/refactor/layer1-memory/plan.md` — Observation 生命周期（感悟的沉淀通道）
