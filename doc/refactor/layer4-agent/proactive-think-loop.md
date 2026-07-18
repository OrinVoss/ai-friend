# Agent 1 主动沉思循环（Proactive Think Loop）

> 目标：给主动路径的 Agent 1 加一个有界思考循环，让「主动开口 / 自由探索」的决策从单次拍脑袋，升级为「想起 → 查证 → 决定」。
> 核心：发挥 Agent 的主观能动性——思考内容**不设限**，由人格、情绪、记忆和它自己的挂念共同驱动。
> 状态：✅ 一期已实现（2026-07-18，`changes/2026-07-18-proactive-think-loop.md`）。二期：循环内 recall 换 Memory Agent。
> 归属：Layer 4（Agent Runtime）。只改 `InnerDriveAgent.assess_proactive()`，响应路径不动。

---

## 1. 原则：值班时要快，独处时可以深思

| 路径 | 延迟敏感度 | 决策模式 |
|------|-----------|----------|
| 响应路径（`assess` / `review` / `re_decide`） | 高，用户在等回复 | 单次判断 + 已有的 recall 循环，不加新循环 |
| 主动路径（`assess_proactive`） | 低，没有人在等 | **有界沉思循环**（本文档） |

主动行为的质量直接决定陪伴感——话题选得准，用户觉得「它真的记得我」；选得敷衍，就是打扰。而主动路径没有延迟压力，值得花 2~3 轮把决策做深。

更重要的是：**主动路径是这个 AI「自我」的唯一出处**。响应路径上它是被动的——用户说什么就接什么；只有在独处时，它才有机会想自己想的。所以这个循环要服务的不只是「选个好话题」，而是它的主观能动性。

---

## 2. 现状与问题

`core/inner_drive.py::assess_proactive()` 当前是**单次 LLM 调用**，存在五个问题：

1. **记忆上下文与想法脱节**：用空查询检索 `retrieve_for_query("")`，拿到的是泛泛 TopK，和它「此刻在想什么」无关
2. **想起具体事情时无法查证**：比如它想到「用户上周提过考试，不知道结果怎样」，没有回忆通道，只能凭泛泛上下文猜
3. **解析方式粗糙**：`_parse_proactive_intent()` 用关键词正则匹配自由文本（探索/沉默/聊天），没有 JSON schema——#ID-001 已经把 `assess()` 升级为结构化输出，proactive 路径还留着老办法
4. **话题容易重复/肤浅**：决定聊什么之前，无法先查「最近已经聊过哪些话题」
5. **没有自我延续性**：每次主动触发都是一片空白地开始想——上次想到一半的事、一直好奇的问题，全部丢失。这是「没有主观能动性」的根源：它没有一个持续的内心世界

对比：响应路径的 `assess()` 已经有 recall 循环（`recall_query` → 执行 recall → 继续，`max_iterations` 封顶）。**proactive 是 InnerDrive 唯一没有回忆能力的入口。**

---

## 3. 循环设计

```
ProactivityManager 评分触发（节流入口，不变）
  ↓
Round 1：初始思考
  输入：空闲时长、当前时间、情绪摘要、关系指标、
        通用记忆上下文、挂念清单（内驱状态，见 3.2）
  输出 JSON：
    thought:      当前想法（自由内容，不限方向）
    recall_query: 想查证的记忆（可空）
    action:       chat / explore / silent
    topic_hint:   话题方向
    reasoning:    决策理由
    care_updates: 挂念清单更新（可空，见 3.2）
  ↓ recall_query 非空 且 轮数 < 上限
执行只读回忆（现有 recall 内部工具；二期换 Memory Agent）
  ↓ 结果喂回 messages
Round N：带着证据再思考
  ↓
终止（任一条件）：
  ├── recall_query 为空 → 做出最终决定
  ├── 达到轮数上限（默认 3）
  └── 解析失败 → 兜底（见第 7 节）
  ↓
返回 ProactiveIntent（接口不变，MessageHandler 零改动）
```

循环约定与 `assess()` 完全一致：`recall_query` 非空 → 继续循环；为空 → 本轮输出为最终决定。

### 3.1 场景示例（不设限）

循环**不限制思考内容**，`thought` 是自由生成的。以下只是示例，不是场景白名单——它想关心什么、好奇什么、反思什么，由它自己决定：

- **关心式主动**：想到「用户最近的烦心事」→ recall 查证进展 → 决定开口询问
- **好奇心驱动**：对某件事产生了兴趣（用户提过的书、之前没搞懂的东西）→ 决定 explore 去搞明白
- **自我反思**：回想最近的对话，「我昨天那句话是不是说得不好」→ 记入挂念，调整相处方式
- **创造与分享**：想到一句诗、一个冷知识、一首适合用户的歌 → chat 分享
- **计划与期待**：「用户说过明天面试」→ 到点了主动问结果
- **克制式沉默**：想到一个话题 → recall 发现「用户昨天明确说不想聊这个」→ 决定 silent

### 3.2 内驱状态：主观能动性的燃料

要让思考有连续性，Agent 需要一个**跨触发持久的内心世界**。最小实现是挂念清单（care list），完整设计（类型、生命周期、浮现规则、回馈闭环）见 `inner-drive-state.md`。

- **存储**：`data/.inner_drive_state.{session_id}`（沿用 `.sleep_state` 的 per-session 文件模式）
- **读取**：Round 1 的输入包含按优先级浮现的挂念条目——它先看到「自己一直惦记的事」，再结合当下决定想什么
- **更新**：循环的任何一轮都可以通过 `care_updates` 新增/移除挂念——这是循环里**唯一允许的写动作**
- **上限**：默认 20~30 条，有生命周期管理，不会无限膨胀

挂念清单让「这次没想到的事，下次接着想」成为可能——这是连续自我的最小实现。二期接入 Layer 1：把有价值的思考作为 Observation 写入（`created_by="inner_drive"`），进入正式记忆生命周期。

---

## 4. JSON Schema（替代正则解析）

```python
PROACTIVE_LOOP_SCHEMA = {
    "type": "json_object",
    "schema": {
        "type": "object",
        "properties": {
            "thought": {
                "type": "string",
                "description": "当前的想法，自由内容，带情绪色彩",
            },
            "recall_query": {
                "type": "string",
                "description": "想查证的记忆内容，如'用户最近提到的烦心事'；不需要查证则留空",
            },
            "action": {
                "type": "string",
                "enum": ["chat", "explore", "silent"],
                "description": "最终决定。recall_query 非空时本字段忽略",
            },
            "topic_hint": {
                "type": "string",
                "description": "聊天或探索的话题方向",
            },
            "reasoning": {
                "type": "string",
                "description": "决策理由，会作为 inner_drive_summary 传给 Agent 3",
            },
            "care_updates": {
                "type": "object",
                "description": "挂念清单更新，可选",
                "properties": {
                    "add": {"type": "array", "items": {"type": "string"}},
                    "remove": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "required": ["thought", "action", "reasoning"],
    },
}
```

新增 `_parse_proactive_json()`，废弃 `_parse_proactive_intent()` 的关键词正则（保留为兜底）。

---

## 5. 约束

- **只启用主动路径**：`assess` / `review` / `re_decide` / `assess_agent3_intent` 全部不变
- **硬上限**：默认 3 轮，可配置，绝无死循环
- **动作权限**：循环内仅允许 `recall`（只读记忆）+ 更新自己的挂念清单；不允许 `remember`、不允许外部工具、不允许改用户记忆——思考只对「自己的内心」产生副作用
- **token 预算**：每轮 `max_tokens_proactive`（256~384），单次触发最多 3 个小调用
- **成本可控**：主动触发本身被 ProactivityManager 节流，最坏情况每次触发多 2 次小调用，日均增量可忽略

---

## 6. 配置

```python
# config.py / config.json
proactive_think_loop: bool = True        # 关掉则退回单次决策（现状行为）
proactive_think_max_rounds: int = 3
inner_drive_care_list_size: int = 20
```

---

## 7. 兜底策略

| 情况 | 行为 |
|------|------|
| JSON 解析失败 | 用旧正则兜底解析；仍无有效 action → `silent` |
| 达到轮数上限 | 采用最后一轮的有效 decision；一直没有 → `silent` |
| recall 执行失败 | 失败信息喂回 messages，由 LLM 决定继续还是收尾 |
| 挂念清单读写失败 | 忽略，不影响主流程（内心世界降级为当次有效） |
| `proactive_think_loop=false` | 完全走现状单次调用路径 |

---

## 8. Prompt 设计：思考起点（引导而非约束）

`build_inner_drive_proactive_prompt()` 给它「思考起点」作为灵感，不是场景限制：

```
你现在有一段独处的时间。可以从这些方向自由地想，也可以想任何别的：

- 用户的近况：有没有没聊完的事、值得关心的进展
- 你的挂念：{care_list}
- 好奇心：最近有什么想搞明白的东西
- 自我反思：最近的相处里有没有做得不好的地方
- 创造：想到什么有趣的东西想分享给 TA

如果想查证什么，填写 recall_query；想清楚了，给出你的决定。
```

---

## 9. 改动文件

| 文件 | 改动 |
|------|------|
| `core/inner_drive.py` | `assess_proactive()` 重写为循环；新增 `PROACTIVE_LOOP_SCHEMA`、`_parse_proactive_json()`、挂念清单读写 |
| `prompts/system.py` | `build_inner_drive_proactive_prompt()` 增加循环协议 + 思考起点引导 |
| `config.py` / `config.example.json` | 新增三个配置项 |
| `data/.inner_drive_state.{session_id}` | 新文件（运行时生成，加入 .gitignore） |
| `core/message_handler.py` | **不改**（`ProactiveIntent` 接口不变） |
| `tests/test_inner_drive.py` | 新增循环与挂念清单测试 |

二期：循环内的 recall 步骤替换为 Memory Agent（见 `doc/refactor/layer1-memory/memory-agent.md` 7.1），思考时用带置信度和证据链的记忆。

---

## 10. 测试（tests/test_inner_drive.py 新增）

1. `recall_query` 非空 → 执行 recall 并进入第二轮，第二轮产出最终 action
2. `recall_query` 为空 → 单轮结束，立即返回
3. 连续返回 `recall_query` → 达到 `max_rounds` 强制终止
4. JSON 解析失败 → 兜底为 `silent`
5. 接口兼容：`handle_proactive()` / `handle_explore()` 消费返回的 `ProactiveIntent` 无需改动
6. 挂念清单：`care_updates.add` 写入成功，下次触发时 Round 1 输入包含该挂念
7. 挂念清单：超过 `care_list_size` 时淘汰最旧条目
8. 挂念清单：状态文件损坏时忽略并报 `silent` 可用

---

## 11. 验收标准

1. 主动触发时日志显示 `think round=1..N`
2. `recall_query` 非空时确实执行 recall 且结果进入下一轮上下文
3. 任何情况下不超过配置轮数上限
4. 挂念清单跨触发持久：第二次触发能看到第一次留下的挂念
5. 全量测试 `pytest tests --ignore=tests/real_api -q` 不降级

---

## 12. 相关文档

- `doc/refactor/layer1-memory/memory-agent.md` — 二期 recall 替换为 Memory Agent
- `doc/refactor/layer1-memory/memory-agent-clues.md` — 向量召回设计（recall 的底层检索）
- Layer 4 README — Agent Runtime 解耦总览
