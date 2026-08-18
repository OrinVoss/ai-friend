# AI Friend 完整开发日志

> **项目周期**：2026-05-28 → 2026-07-26（59 天）
> **提交总数**：405 次
> **测试增长**：0 → 869 passed
> **数据库 Schema**：v1 → v6
> **架构演进**：单体 Agent → 两阶段 → 三层 Agent → 六层架构
> **文档体系**：从零 → 15+ 份技术文档
>
> 本文结合全部 405 次提交记录与 changes/ 目录下所有修改记录文件写成，
> 覆盖每一次架构决策、每一轮 Bug 歼灭、每一个功能落地的完整背景与实施细节。

---

## 第一卷：创世纪（Day 1，2026-05-28）

### 子时·诞生

2026 年 5 月 28 日凌晨 0:59，项目诞生了。

**`b289667` — Initial commit: AI Friend - 具有人格和长短期记忆的 AI 朋友**

这不是一个空壳初始化。第一次提交就包含了 CLI 交互模式、基础人格引擎、短时记忆和长时记忆的完整雏形。解决的问题从一开始就很明确：打造一个有温度、有记忆、有人格的 AI 伴侣，而非一个冷冰冰的问答机器。

紧接着的一个小时内，README（`af37b70`）和 comprehensive technical documentation（`2ce8b2e`）就位——文档先行的传统从第 0 分钟就确立了。

### 晨时·框架搭建

上午到中午，基础设施密集落地：

| 时间 | 提交 | 内容 |
|------|------|------|
| 11:15 | `10ae951` | 修改追踪系统（changes/ 目录建立） |
| 11:16 | `3d53606` | 项目级 CLAUDE.md，包含修改记录规则 |
| 11:18 | `7e6a802` | 数据库迁移到 data/ 目录 |
| 11:20 | `f339c0d` | 人格风格切换为 playful teasing（嘴贫损友） |
| 11:27 | `1d831d4` | Web 端数据持久化：每轮保存 personality |
| 11:33 | `d2b8716` | 根据情绪动态调整回复长度（max_tokens 绑定 emotion） |

变更记录（`changes/`）对这些改动的描述更具体：
- 数据库迁移出于"项目根目录不能有杂乱文件"的整洁考虑
- playful teasing 风格的改动包含完整的 prompt 改写：反讽、自嘲、歪楼——从第一版人格就奠定了"不是客服机器人"的调性
- Web 端数据持久化的背后是"刷新页面 personality 丢失，AI 变了一个人"的严重 Bug

当天还确定了版本化里程碑体系（`c812550`——v0.1-v0.4），以及全面的 ASCII 图表文档风格（`6e7c33c`、`9c64e47`）。

### 午时·消息系统奠基

下午的核心工作围绕"AI 怎么说话"展开——消息分段系统。

**`272a8fd` — Fix: split segments for responses without punctuation**

AI 的回复没有标点符号就不分段，所有文字挤在一个气泡里。修复是最小干预：检测句号、问号、感叹号、换行符做切分。

**`ea92f74` — Fix: comprehensive message segmentation + separate bubbles + API proxy bypass**

半小时后的第二次修复才真正解决了问题——这是一次 comprehensive 重写，加入了多级切分策略：
1. 段落级（`\n\n`）→ 长停顿
2. 句子级（句号/问号/感叹号）→ 中等停顿
3. 逗号/分号 → 短停顿
4. API proxy 旁路：不走系统代理直连（`trust_env=False` 的原型）

延时调整（`498d387`）在此基础上为每种切分级别分配了不同的打字机延时——段落间 1.2s、句子间 0.6s、逗号 0.3s，模拟真人说话的节奏。

### 暮时·破防机制诞生（项目第一个标志性功能）

**`8f57949` — 实现破防机制**

变更记录详细描述了设计的来龙去脉：用户骂 AI 时 AI 毫无反应——没有累积伤害效果。需要实现真正的「破防」——持续攻击后会委屈、崩溃。

实现是三级阈值，在 `prompts/system.py` 中以行为指令形式嵌入：

| 连续攻击次数 | 状态 | 行为 |
|:---:|:---:|:---:|
| 1-2 次 | 被怼了一下 | 轻回怼，不在意 |
| 3-4 次 | 有点受伤 | 委屈，底气不足 |
| 5+ 次 | 破防 | 哭腔、反问、撒娇式回击 |

配套的代码改动（`core/agent.py`）：
1. 新增 `_consecutive_negative` 计数器追踪连续攻击
2. 修复情绪分析 Bug——此前分析的是 AI 自身的回复而不是用户输入
3. 累积伤害放大：`sentiment *= 1.0 + consecutive * 0.4`
4. 正面互动降计数器：`sentiment > 0.1` 时 `consecutive -= 1`

同一晚确立了"修 Bug 先创 Issue"的工程纪律（`585fa95`——"先创建问题单，再修复代码"）。

### 夜时·情绪系统一期

**`2b86efc` — Fix: dominant_emotion bias for negative valence states**

发现情绪系统的一个基础 Bug：当 valence（效价）为负时，dominant_emotion 的选择存在偏差，不能正确反映真实的主导情绪。

**`c011270` — Add cross-dimension emotional modulation**

变更记录给出了详细的交叉调制系数表——Plutchik 8 个情绪维度独立演化会导致矛盾状态共存（`joy=0.97 + anger=0.70 + sadness=0.73`），AI 的 dominant_emotion 显示 sad 但回复依然活泼开心。

修复引入 10 组压制规则：

| 压制方 | 目标 | 强度 | 逻辑 |
|:---:|:---:|:---:|:---|
| anger | joy | 0.6 | 愤怒时不可能开心 |
| anger | trust | 0.4 | 愤怒削弱信任 |
| sadness | joy | 0.5 | 悲伤压抑快乐 |
| sadness | anticipation | 0.4 | 悲伤降低期待 |
| joy | anger | 0.4 | 开心化解怒气 |
| joy | sadness | 0.3 | 开心冲淡悲伤 |
| trust | fear | 0.5 | 信任减少恐惧 |
| fear | trust | 0.3 | 恐惧侵蚀信任 |
| disgust | joy | 0.4 | 厌恶排斥快乐 |
| disgust | trust | 0.3 | 厌恶降低信任 |

测试效果：`joy 0.975 → 0.331`，`anger 0.698 → 0.426`，dominant 从 "sad" 校正为 "anxious"。

**`adcb60c` — Emotion system upgrade: resentment + per-emotion decay + emotion events**

凌晨的情感系统全面升级（`changes/2026-05-29-情感系统全面升级.md`）引入了项目的四层情绪引擎：怨恨机制 + 分速衰减 + 情绪事件记忆。

**分速衰减**——每个 Plutchik 情绪有独立的半衰期（对话轮次）：
| 情绪 | 半衰期 | 说明 |
|:---:|:---:|:---|
| surprise | 3 | 最快，转瞬即逝 |
| fear | 6 | 快 |
| anticipation | 8 | 中等 |
| disgust | 10 | 中慢 |
| joy | 12 | 中等 |
| anger | 15 | 慢，愤怒残留 |
| sadness | 20 | 慢，悲伤持久 |
| trust | 25 | 最慢，信任不易失去 |

**怨恨残留**：`anger > 0.6` 时累积 `resentment += anger * 0.15`，上限 1.0；衰减 3%/turn。怨恨高时 joy 上限被压制（`joy_ceiling = 1.0 - resentment * 0.5`）。

**情绪事件记忆**：强情绪触发时自动记录（触发文、主要情绪、强度、上下文），prompt 注入最近 3 条未解决事件，最多保留 20 条。

行为变化（对比表格）：「骂完再哄」立刻原谅 → resentment 残留，嘴上原谅心里还硌着。

---

## 第二卷：工具系统与自主行为（Day 2，2026-05-29）

### 工具从无到有

第二天的工作重心转移到工具系统——让 AI 真正能"做事"。

**`49fcc26` — Fix notify tool: remove message→content alias**

变更记录显示：notify 工具的 `message` 参数名在一次重构中被改成 `content`，但调用方仍在传 `message`——工具静默失败。修复删除了有问题的别名映射，改用非阻塞 PowerShell toast。

**`d8f3fba` — Add web_search and web_fetch tools using AnySearch API**

AnySearch API 的接入让 AI Friend 第一次具备了联网能力。变更记录记载了后续的解析修复（`3cc5fe9`）：AnySearch 返回的是 Markdown 格式文本，直接用就是乱码，需要特定的解析逻辑来提取内容。

**`d4eb2d0` — Add music_list and music_play tools for D:\音乐**

音乐工具的落地让 AI 能扫描和播放 D 盘的音乐文件。变更记录提到：`music_list` 的目录遍历考虑到了 Unicode 编码和中日韩文件名。

**`ad0a60b` — Add tool call history + usage hints + fix music player**

工具调用历史记录——系统追踪 AI 最近使用了哪些工具，以及使用频率/成功率，在提示词中注入 "你可以试试……" 的引导。

### 工具链扩张（关键演进）

当天的工具相关提交密度极高——从下午 5 点到夜间 11 点，几乎全是工具系统的迭代。

**`be5ac21`** 引入了四个关键工具：`glob`、`grep`，同时增强 `read_file` 支持行号显示和偏移读取。
**`76b52c1`** 删除了 `music_list`（功能合并到 `read_file`），扩大了 `D:\音乐`、`D:\桌面` 等读写范围。
**`3e85fc8`** 引入了白名单机制——`read_file` 只能访问允许的目录，同时为 `read_file` 增加了目录列举能力和反幻觉规则（当 AI 声称看到的文件实际不存在时，返回特定格式的错误）。

变更记录的细节显示了一个关键设计决策：**工具的权限控制应该集中在一处**，而不是散落在各工具代码中。`0261c48` 将 `allowed_read_paths` 统一迁移到 `config.py`——这是项目后来「配置中心化」趋势的第一次实践。

### 主动行为与作息系统

**`ca417ad` — Add sleep/wake schedule, rate limits, dream sharing on wake**

变更记录（`2026-05-29-作息系统和频率限制.md`）给出了完整的作息时间表：

| 事件 | 时间窗口 | 触发条件 |
|:---|:---:|:---|
| 午睡 | 12:00-13:00 | 情绪驱动（sad +30%，excited -20%，resentment +20%） |
| 午睡醒 | 13:10-16:00 | 随机唤醒，arousal 高醒得早，resentment 高醒得晚 |
| 夜睡 | 23:30-次日 0:30 | 情绪驱动 + baseline 30% |
| 晨醒 | 7:00-10:00 | 随机，情绪影响 |

频率限制：探索 1 次/小时，主动聊天 2 次/小时，梦境每次睡眠 1 次。

梦境生成的原理是 LLM 基于最近事实 + 经历 + 情绪生成碎片化梦境（1-2 句，第一人称），存储为情绪事件，醒来时注入 prompt。

**`332556a` — Tie proactive idle threshold to emotion state**

主动行为的触发阈值与情绪挂钩——情绪低落时 AI 更不容易主动发起对话，与此前 "不管情绪一律 40% 概率主动" 的机械行为形成对比。

**`36a440c` — Anchor proactive/explore topics to user interests instead of random**

之前主动对话的话题是随机挑选的。这次改为从记忆系统（`long_term.get_active_facts`）中检索用户兴趣，选择最相关的话题。

### 睡眠自动回复

**`95998ff` — Sleep auto-reply: zzz variants**

用户在 AI 睡眠期间发消息时，AI 的回复是各种 "zzz" 变体。但变更记录揭示了设计细节：睡眠回复不是简单重复 "zzz"——它会根据用户消息的情绪选择不同变体，且在后续版本中加入了"说梦话"机制。

### v0.1 首次批量歼灭

当天晚上 22 点开始了一场集中歼灭战：

**`3a1bcb9` — Fix #13 #16 #17 #35 #36 #37 #38**（一次 7 个 issue）
**`7262823` — Fix #18 #34**（bare except + config.json sync）
**`ac41bff` — Fix #33**（context compression）
**`0d630e0` — Fix #3 #9**（token estimation + missing json import）

变更记录总结：v0.1 共关闭 14 个 issue——相当于项目第一个里程碑在一天内走完了大部分路程。

### 睡眠窗口调整

**`22d1650` — Fix repeated sleep message: 10min cooldown**

夜间用户反复触发睡眠消息——AI 每次都说"夜深了"。修复引入 10 分钟冷却期。变更记录显示睡眠窗口从 `23:30-0:30` 调整为 `23:00-01:00`（覆盖更合理的入睡时间），并移除了人工 guard 改用 `.sleep_state` 文件持久化。

---

## 第三卷：Agent 架构革命（Day 3-4，2026-05-30 — 05-31）

### 首次 Agent 拆分——God Class 解体

**`a07a22f` — Fix #30: split Agent into 3 modules by functional cohesion**

变更记录（`2026-05-30-拆分Agent-issue30.md`）给出了当时 `core/agent.py` 的精确数据：**784 行，10+ 职责**——典型的 God Class。

拆分方案：

```
agent.py (784行) — God Class
  │
  ├── agent.py (223行)           — 核心引擎（__init__ + _react_loop + 转发）
  ├── core/context_manager.py    — 上下文窗口管理（token估算 + 压缩 + 摘要存储）
  ├── core/sleep_manager.py      — 睡眠/唤醒系统（窗口判断 + 梦境生成 + 持久化）
  ├── core/proactivity.py        — 主动行为引擎（评分 + 话题选择 + 频率控制）
  ├── core/cli_controller.py     — CLI 状态机（run() + 7个 _on_*）
  └── core/message_handler.py    — 消息入口（Web + CLI 共享）
```

这次拆分顺带修复了 4 个 Bug：重复导入、`_ > 0` 变量名遗漏引用、死代码 `_proactive_flag`、sleep 文件路径未做 `os.path.abspath`。

新模块附带 33 个单元测试覆盖——项目测试从 0 起步，首次拥有结构化测试套件。

### 工具调用信任危机

这是项目遇到的第一个深层次 LLM 行为问题。

**`b659a38` — Fix: detect and retry when LLM fakes tool calls**

变更记录（`2026-05-30-修复假工具调用.md`）记载了完整的三个修复阶段：

**第一轮**：DeepSeek 模型在回复中使用叙事性文字描述工具调用（"（调用web_fetch读取你给的链接…）"），但实际并未输出 `<tool_call>` XML 标签——工具从未被执行，模型凭空编造返回内容。用户连续 12 次发现编造，每次模型都"承认"撒谎然后继续编造。

修复三重：
1. `contains_fake_action()` 从 7 个关键词扩展到 15+ 叙事模式匹配
2. `_react_loop` 增加假调用重试（最多 3 次）
3. 系统提示新增「严禁行为」部分 + 4 条负面示例 + ❌/✅ 图标

**第二轮**：工具已被实际调用（日志确认 web_fetch 执行成功），但模型仍编造返回内容——报道了 2025 年的旧热搜。根因是模型收到真实 tool_result 后不忠实汇报，而是用训练数据"润色"。

修复：在每个 `<tool_result>` 末尾强制注入「以上是工具返回的真实内容。你必须逐字如实汇报……」指令。

**第三轮**：日志显示模型在单轮对话中重复调用同一个 URL 3 次——假调用检测产生了误判。模型第一次迭代假调用（被纠正），第二次真实执行，第三次汇报结果——`contains_fake_action()` 把"工具返回了……"又误判为假调用。

修复：`_react_loop` 新增 `tools_were_called` 标志——只要有工具真实执行过，"工具返回"等短语不再触发假调用检测。

### 两阶段架构诞生

工具调用的信任危机暴露了根本矛盾：**角色扮演人格与工具调用指令混在同一 Agent 中，模型在人格驱动下倾向叙事描述而非输出 `<tool_call>` XML**。

**`067e628` — Refactor: two-phase Agent architecture**

变更记录（`2026-05-30-两阶段Agent架构-职能分离.md`）给出了完整方案。核心思想是职能分离：

```
Phase 1: Tool Agent（纯工具层）
  - 无角色、无情绪、无记忆
  - temperature=0.3
  - 提示词仅含 7 个外部工具定义 + 调用规则
  - 输出完整工具调用记录传给 Phase 2

Phase 2: Roleplay Agent（角色层）
  - 完整人格、情绪、记忆
  - temperature=0.8
  - 提示词含 Phase 1 工具调用记录
  - 内部工具保留：recall, remember
  - 外部工具指令完全移除
```

新建文件 `core/tool_agent.py`（120 行），新增 `ToolCallRecord` / `ToolAgentResult` 数据类，`format_for_phase2()` 格式化工具记录。

配套修复：ToolAgent 懒初始化（`agent._tool_registry` 在 Agent 构造后才填充，首次 `handle_message` 时创建），Phase 2 使用过滤后的注册表（仅 recall + remember）。

### 三层 Agent 架构：最终形态

**`dfd963a` — Arch: three-layer Agent -- InnerDrive + ToolAgent + Roleplay (#107)**

变更记录（`2026-05-31-三层Agent架构-内驱域.md`）给出了完整的架构图：

```
用户 → Agent 1 (内驱域) → Agent 2 (工具调用) → Agent 3 (情感表达) → 回复
         │                      │                     │
         自知+知彼+决策         纯工具+重试            角色+人格+工具结果
         recall/remember        7 external tools       recall/remember only
```

三层各自在 one-shot 热聊和工具场景下的 Token 成本：
- **旧架构（两阶段）**：每条消息 2 次 LLM 调用（ToolAgent + Roleplay）
- **新架构（三层）**：闲聊只需 1 次（Agent 1 → 直接 Agent 3），工具场景 3 次

新建 `core/inner_drive.py`（200 行）——`InnerDriveAgent` + `InnerDriveResult` / `ToolRequest` 数据类 + `assess()` / `re_decide()` 方法。

日志标签体系随之建立（`[inner_drive] start / iter / decision`），测试增加到 62 用例全部通过。

### 文档体系启动

同一天，由代码审查报告（`d788cd8` ）驱动的文档体系开始成形。但项目真正成体系的文档工作要等到 v0.5 阶段。里程碑文件（`c1dbea4`）在这一天被重写为详细版本——包含进度条、验收标准和路线图。

---

## 第四卷：v0.1 收尾与 v0.2 起航（Day 4-7，2026-05-31 — 06-01）

### 106 个单元测试

**`1d1c08d` — Add 106 unit tests: EmotionalState, Provider, Dispatcher, Personality, Segmentation (#83)**

这是项目第一次大规模测试基建。覆盖 EmotionalState 的状态转换、Provider 的 API 调用模式、Dispatcher 的工具分发逻辑、Personality 的文件读写、Segmentation 的切分规则——测试总数从 0 飙升到 171。

### 本地向量语义搜索

**`863045b` — Feat: local vector semantic search with Qwen3.5-0.8B GPU (#77)**

Qwen3.5-0.8B 模型在 GPU 上运行，提供本地化向量嵌入服务。记忆检索从纯关键词匹配升级到语义相似度搜索——这是项目记忆系统的一个质变。

变更记录提到：嵌入服务器以子进程模式启动（`embedding_server.py`），通过 HTTP API 与主进程通信。这个架构后来成为稳定性问题的源头（M-18 看门狗正是为了解决它）。

### 异步数据库 + 结构化工具（#1 #2）

**`9a0062b` — Fix #1: aiosqlite async database + Fix #2: structured JSON tool calling**

两个重大基础设施变更一次落地：
1. 数据库从同步 sqlite3 迁移到 aiosqlite——为后续 WebSocket 并发访问奠定基础
2. 工具调用从纯文本解析（正则提取 `<tool_call>`）升级为 JSON 结构化——可通过 `response_format` 约束 LLM 输出为合法 JSON

### 代码审查与新 Issue

**`4e31a09` — Create 6 new issues from code review report (#110-#115)**

代码审查产生的 Issue 快速膨胀：`80de921` 补充到 8 新 + 14 现有 + 9 已修复，`83770a7` 又添加 3 个，`08073c2` 再加 4 个。

**`fa3526b` — Add complete open issues document: 70 issues across 7 milestones**

70 个已知问题分布在 7 个里程碑——这是项目第一次把所有已知债务摊在桌面上，为后续 v0.5 的大规模修复提供了完整的作战地图。

### 主动行为升级：两级门控

**`9376fbd` — Integrate #125: Inner Drive + Proactive Behavior — two-stage gatekeeper**

变更记录（`2026-05-31-inner-drive-proactive-integration.md`）显示了架构变化：之前主动行为引擎完全绕过 Agent 1（InnerDrive），使用硬编码评分和随机话题选择。现在 InnerDrive 成为主动行为的决策大脑。

两级门控：ProactivityManager 评分（轻量预筛选）→ InnerDrive 决策（LLM 推理）→ 执行。引入 `ProactiveIntent` dataclass（chat / explore / silent 三种决策），测试从 171→202。

### 虚假记忆修正（#6）

**`77f2f85` — Fix #6: False memory correction**

变更记录（`2026-06-01-false-memory-correction-6.md`）展示了三层机制：

1. **矛盾检测**：同 `(category, key)` 不同 value → 直接矛盾；embedding 余弦相似度 > 0.65 且 value 不同 → 语义矛盾
2. **置信度衰减**：被矛盾的事实 `confidence × 0.4`，低于 0.2 软删除（`is_active=0`）
3. **用户纠正**：`RememberTool(correct=true)` → 旧事实软删除，新事实 confidence=1.0（确保不会被后续 upsert 覆盖）

这是项目记忆系统第一次具备"自我修正"能力。新建 6 个测试文件，测试从 222→250。

### v0.2 完成

**`5403dc5` — Complete v0.2: all 5 remaining issues resolved**

变更记录（`2026-06-01-v02-issues-complete.md`）列出了 v0.2 关闭的 5 个核心 issue：
- #5 分层反思：L1 事实（每次）→ L2 模式（每 3 次）→ L3 深度洞察（每 10 次）
- #20 humor/sass 无实际效果 → 情绪调制公式修正
- #21 `_score_facts` 原地覆写 → 改元组排序
- #22 pending 重复 → `add_pending` 按 `(turn_id, role)` 去重
- #40 无 session 隔离 → 5 表加 session_id 列 + Repository 过滤

---

## 第五卷：v0.5 修复大行动（6月1日—7月12日）

### 178 个问题的作战计划

**`af610ad` — Add detailed 4-week v0.5 remediation plan (178 issues)**

6月1日下午，项目制定了一份雄心勃勃的 4 周修复计划。178 个问题意味着这不是"修 Bug"——这是一场系统级的质量战争。

优先级分层：P0 系统崩溃（5 个）、P1 核心功能（若干）、P2/P3 代码质量和优化。

P0 在计划发布后几小时内就被歼灭（`c4cc233`）。这种"先灭火、再装修"的思路贯穿了项目始终。

### 存储层审计（#186-#200）

**`31b663d` — Add #186-#200: memory system audit issues**
**`e7a3c0b` — Fix #186-#200: memory system audit — 15 issues root-caused**

变更记录（`2026-06-01-fix-186-200-memory-audit.md`）记载：核心修复包括 `store_fact` 重复定义（`#193`）、EmbeddingCache 未集成（`#196`，encode() 先查缓存再调 API）、API 异常无缓存回退（`#197`）。

linter 审计附加了 2 个 P0 修复：embedding 维度变化时新旧向量混合导致 `np.stack` 崩溃，以及零向量污染相似度计算导致相关事实被错误降级。

### 根本修复 #127-#142

**`fe1ae18` — Root fix #127-#142: business logic completion**

变更记录（`2026-06-01-root-fix-127-142.md`）揭示了一个深层问题：LLM 提取"事实"时不能区分用户信息（"我喜欢吃披萨"）和 AI 自身行为（"我搜索了披萨的做法"）——导致数据库里混杂了大量系统垃圾信息。

修复引入 `fact_type` 字段（`user_fact / agent_fact / system_fact`），只存储 `user_fact`。统一的 `run_async()` 桥接（`core/async_utils.py`）替换了三处重复的 `_run_sync` 实现。

### v0.2 11 个安全修复

**`571d864` — Fix v0.2: 11 issues — security, reliability, architecture, performance**

变更记录（`2026-06-01-v02-11-issues-root-fix.md`）覆盖安全多个维度：

| # | 问题 | 修复 |
|:---:|:---|:---|
| #148 | 数据丢失 + 无 Session TTL | 24h 自动清理 |
| #150 | PowerShell 注入 + ReDoS | `$ ' "` 转义 + 正则嵌套检测 |
| #153 | personality 写入不原子 | `.tmp → os.replace` |
| #154 | 无连接池 | `PRAGMA busy_timeout=5000` |
| #155 | SSRF | `_is_safe_url()` 拦截内网 IP |
| #157 | 数据库可靠性 | WAL checkpoint + integrity_check |
| #158 | WebSocket Origin 无校验 | Origin 头白名单 |
| #165 | 无降级模式 | 3 次工具失败 → 跳过工具 |

追加修复了 3 个交叉调用链 Bug（`5753936`）：
- `asyncio.run()` 在事件循环中崩溃
- Agent 2 工具结果未写入 `_tool_call_history`
- `handle_explore` 同理

变更记录特别指出根因："AI 逐文件修改时，调用链上其他文件仍用旧代码，数据流断裂。"

### 日志系统全面升级（#102）

**`5a272b7` — Fix #102: comprehensive logging across all 21 files**

变更记录（`2026-05-30-全面日志系统升级.md`）给出了分层日志方案——21 个文件分 6 个 Phase：

1. 基础设施层：config、database、repository、models
2. 核心运行时：provider（`[api]` model/stream/duration）、dispatcher（`[tool]` N calls, X ok, Y failed）、agent（`[msg]` `[emotion]` `[sleep]` `[dream]` `[proactive]`）
3. 记忆系统：short_term、long_term、retrieval、consolidation
4. 工具层：file_tools、search_tools、music_tool、memory_tools、web_tools
5. Web 层：server（`[ws]` `[rest]`）、session（`[session]`）
6. 入口点：main.py、web_main.py（启动信息）

统一的日志规范：`[tag] description key=value`，用户消息截断到 60 字符，API Key 用 `***` 遮盖。

### v0.5 简单修复批量

**`c032226` — Fix v0.5 simple issues**

变更记录（`2026-06-01-v05-simple-fixes.md`）显示了 4 个简单但重要的修复：
- #201 — P0：repository 9 个写方法全部缺少 `commit()`——在 `update_fact_score`、`deactivate_fact` 等方法执行后数据从未落盘
- #193 — 删除重复 `store_fact` 前向引用
- #245 — `turn_id` 竞态：Turn 构造要移入锁内
- #240 — PowerShell 转义修正为双单引号

### 停工期与重启

提交历史中有一个明显间隙：6月1日到6月9日之间几乎没有提交。6月9日晚项目重启——`9a9b40e` 修复 #209 #212 #241，Week 1 计划完成。

随后的开发（6月9日-7月12日）呈现"增量修复 + 质量基建并行"的节奏。嵌入服务器的稳定性问题反复出现（路径编码、超时配置、集成缓存），直到 M-18 看门狗才根治——这中间隔了整整 41 天。

### 前端密集改造（7月12日—13日）

7月12日迎来了前端的爆发式更新：

**`913be49` — Fix #297: WebSocket 气泡分裂**
**`a11bfd3` — Linter 优化 + 前端 segment markdown 渲染**

变更记录（`2026-07-12-fix-websocket-segment-bubble.md`）描述了问题：WebSocket 分片到达时可能把一条完整消息切成两个气泡——因为前端是在 `onmessage` 回调中直接渲染，没有聚合缓冲。

修复引入消息聚合器：对 500ms 内到达的碎片做缓冲合并，按 segment_index 排序后统一渲染。

同一天的前端调整还包括：动态 avatar 名称（硬编码"星"→ `init_ok.name`）、REST 超时兜底（AbortController 15s）、JSON.parse 静默失败修复、SVG 图标替换 emoji、面板展开/折叠动画、移动端适配等近 30 次提交。

### #299 连环修复

**`908e771` — Fix #299: 修复 Web 端 WebSocket 连接失败**

变更记录显示这个 issue 牵出了一条"问题链"：

1. **表层**：WebSocket 连接建立失败 → 添加 CORS/Origin 白名单
2. **第二层**：glob 工具无法访问 D:\音乐 → 白名单路径权限放行
3. **第三层**：AI 错误记忆固化 → InnerDrive 改用 JSON Schema 替代脆弱的关键词/正则解析
4. **第四层**：嵌入 API 400 → 更新嵌入服务接口路径
5. **第五层**：主动消息不持久化 → 修复 `add_to_history` 路径

每次修复都暴露更深层的问题，直到触及基础设施缺陷。这是项目 "根因追击" 风格的最佳例证。

### 角色-Session-记忆绑定（7月13日）

**`4ee7507` — feat: bind role/session/memory and fix relationship session isolation**

变更记录（`2026-07-13-role-session-binding.md`）描述了设计决策：**一个 Session = 一个角色实例**。

此前 `personality.json` 是全局共享文件，所有 session 共用同一个角色情绪状态——多角色互相覆盖。`relationship_metrics` 主键只有 `dimension`，没有 `session_id`——新 session 写入时覆盖旧数据。

修复方案：
1. 每个角色有独立的 personality 文件：`personalities/{role_id}.json`
2. 新增 `session_roles` 表记录 `session_id → role_id` 映射
3. `relationship_metrics` 主键改为 `(session_id, dimension)`
4. `relationship_snapshots` 增加 `session_id` 列
5. 新增 REST API：`GET /api/roles`、`GET /api/sessions?role_id=xxx`

### 浅色响应式 Web 控制台

**`87b4c59` — feat: light responsive web console with status/history/logs**

变更记录（`2026-07-13-light-responsive-web-console.md`）：将深色聊天首页重写为浅色三栏布局——左侧状态面板、中间聊天区、右侧日志面板。移动端底部 Tab 切换「聊天 / 状态 / 日志」。

新增 `GET /api/logs` SSE 接口实时推送日志——`StreamingResponse` 持续 tail 最新 100 行。

旧页面备份到 `web/backups/`（`index.html.v1.bak`、`style.css.v1.bak`、`app.js.v1.bak`），有清晰的回滚路径。

---

## 第六卷：监控与 Prompt 重构（7月13日—14日）

### 监控面板诞生

**`b9ab556` — 新增 LLM API 调用监控面板**

纯内嵌 HTML 单页应用，不依赖任何前端框架。能够实时显示 LLM API 调用的状态、延迟、Token 消耗和错误率。

后续迭代（MN-002 至 MN-005）：
- **MN-002**（`25f39ff`）：布局优化、自动刷新、卡片式信息展示
- **MN-003**（`b80388a`）：CSP 安全策略修复 + favicon 路由兼容 + 刷新保持展开状态
- **MN-004**（`9508d86`）：浅色主题，更适合运维场景
- **MN-005**（`6601c76`）：JSON / Markdown 导出

### Prompt 系统集中化（#294）

**`255b259` — refactor(prompts): centralize instructions, derive tool rules from registry (#294)**

Prompt 的痛点此前分散在各个模块中——工具规则既写在代码里又写在提示词里，两者不同步就会导致诡异行为。

重构结果：所有提示词指令集中到 `prompts/instructions.py`，工具规则从 `tool_registry` 动态推导，运行时情感摘要从 Runtime 传递到提示词层（`ea4c617`）。

### MessageHandler 状态机化

**`7126df9` — refactor(message_handler): state machine, ToolExecutionResult, tool registry isolation**

MessageHandler 从过程式重构为状态机模式。每个状态（INITIAL、TOOL_EXECUTING、ROLEPLAY、COMPLETED、ERROR）之间的转换被显式建模，不再通过 if-else 拼凑。

### 新工具批

**`496b0d2`** — 音乐随机播放 + 测试
**`075f7e2`** — `file_tree` 工具（目录树探索）
**`827ef8d`** — Agent 1 获取最近工具调用历史，用于解释简短输入
**`78f0f20`** — InnerDrive prompt 强化 + 扩展文件读取权限

### 休眠唤醒保底

**`7282f7e` — fix(sleep): guarantee morning wake-up with fail-safe window**

修复了一个长期存在的休眠问题：如果 AI 在入睡后系统重启或时钟跳变，可能会永远醒不来。修复引入兜底窗口——在 7:00-10:00 范围内，无论什么状态都强制唤醒。

---

## 第七卷：系统性重构与六层架构（7月14日—21日）

### 从战术修复到战略设计

**`90b7a11` — docs: add systematic solution plan for known-issues**

项目修了 200+ 个问题之后，开发者做了一个关键认知升级——有些问题不是修得完的，它们来自架构层面的设计缺陷。

**`d1e22a0` — docs: merge systematic solution drafts into unified v0.6/v1.0 blueprint**

变更记录（`2026-07-14-systematic-solution-plan.md`）把 `doc/known-issues.md` 中分散的 20+ 个问题收敛到一份统一的六层架构蓝图中。

覆盖的七层运行时（后来精简为六层）：
1. **Layer 0: Identity & State** —— `role_id == session_id == memory_namespace`
2. **Layer 1: Memory Lifecycle** —— Observation → Fact → Insight → GC
3. **Layer 2: Context & Prompt Budget** —— Token 预算分配
4. **Layer 3: Async Agent Runtime** —— 状态机 + 依赖注入 + 全局超时
5. **Layer 4: Tool Runtime** —— 别名下沉 + Registry 隔离 + 统一重试
6. **Layer 5: Provider Abstraction** —— 真异步多 Provider 路由
7. **Layer 6: Observability** —— 结构化日志 + 监控

蓝图中附带了根因分析表、与 `known-issues.md` 的完整映射表、五阶段实施路线图和 A/B 两种推进方式。

### Layer 1：Memory 生命周期

**`be1f187` — ML-001: Layer 1 Memory lifecycle (Observation → Fact), phase 1**

变更记录（`2026-07-14-memory-layer1-observation-fact.md`）详细描述了分两期实施的设计：

一期（双写灰度）：
1. 新增 `observations` 表：保存每次 consolidation 的原始观察
2. 新增 `facts_v2` 表：保存带 `confidence / stability / freshness / importance` 的事实
3. `MemoryLifecycleManager` 提供核心生命周期方法
4. `MemoryConsolidator` 在原有流程基础上双写 Observation + FactV2
5. GC 机制：freshness/confidence 随时间衰减，旧 Observation 归档

二期（Insight 替换 Reflection + 检索切换 facts_v2）。

### 统一管线（Unified Pipeline）

**`12b8d08`** — P0: SessionFactory（会话组件装配统一）
**`73b159a`** — P1: ConversationEngine + CLI 灰度切换
**`3d92d8a`** — P2: RuntimeDriver（休眠/主动行为节拍器）
**`6aec6d6`** — P3: 删除遗留 CLI 循环和死代码

变更记录（`2026-07-16-unified-pipeline-p0-session-factory.md`）揭示了管线统一的背景：CLI 和 Web 此前各自手工装配同一套组件栈（repo → ltm → retriever → consolidator → tools → agent），两份代码已经漂移——CLI 注册 `file_tree`、传 LLM rerank fn，Web 都不做；且 Web 端所有 session 共享同一个 `Repository` 实例，多角色同时活跃时互相踩。

修复方案是 `SessionFactory`：进程共享组件单一构造点 + 每 session 独立 Repository 实例。

### MemoryAgent：确定性记忆推理

**`293fa58` — feat: Memory Agent P0+P1 — deterministic memory reasoning pipeline**

变更记录（`2026-07-16-memory-agent-p0-p1.md`）——MemoryAgent 定位为确定性推理组件，不调用 LLM。

管道流程：
```
answer(query)
  ├── _extract_clues()      整句向量 + 时间规则→绝对日期 + 意图锚点 (>0.65)
  ├── _retrieve_parallel()  facts_v2 / observations / experiences / relationship
  ├── _cross_verify()       同 key 矛盾检测 + 批量编码余弦均值
  └── _reconstruct()        MemoryAnswer：答案 + 置信度 + 证据链 + 矛盾 + 建议
```

置信度公式六维加权：consistency .30 / verification .20 / source_quality .20 / freshness .15 / timeline .10 / contradiction .05。

新建 21 用例，测试从 417→459。

### Layer 1 完整上线

**`29df5c8` — feat: Memory Layer 1 full launch — migrate user_facts to facts_v2**

变更记录（`2026-07-18-memory-layer1-full-launch.md`）：跳过双写灰度，直接切换。读路径切到 facts_v2、写入单写 facts_v2、旧表数据迁移后归档（schema v4）、开关删除。

迁移映射——`UserFact` 字段到 `facts_v2` 列的完整对应表：
| UserFact | facts_v2 源 |
|:---|:---|
| `composite_score` | `ROUND(0.5*confidence + 0.3*importance + 0.2*freshness, 4)` |
| `recall_count` | `verification_count` |
| `is_active` | `status == 'active'` |
| `fact_type` | 固定 `'user_fact'` |

`upsert_fact_v2` 的 ON CONFLICT 补充了 `status = 'active'`——被软删的同名事实在用户重述时恢复可见（"复活语义"）。

### Insight 替换 Reflection（schema v5）

**`91374cf` — feat: structured Insight replaces Reflection (Layer 1 P2, schema v5)**

变更记录（`2026-07-20-insight-replaces-reflection.md`）：旧 Reflection 是开放式结论文本（`content + significance`），没有假设/证据/置信度结构。Insight 的结构化为：

`hypothesis + evidence_fact_ids + confidence + needs_more_evidence + expires_at + status`

迁移有损：旧 Reflection 无证据链，迁入的 `evidence_fact_ids` 一律 `'[]'`，`needs_more_evidence=1`。保留旧方法名与 `Reflection` 返回形状，适配器模式（`get_recent_reflections` 内部 SQL 改打 `insights_v2`，外部调用方零改动）。

### 挂念清单二期（Inner Drive State P2）

**`31ce91a` — feat: inner drive state P2 — typed entries, lifecycle, emotion-linked surfacing**

变更记录（`2026-07-18-inner-drive-state-p2.md`）——一期的挂念清单是扁平字符串列表 + FIFO：没有类型、没有生命周期、只增不减会沉底。

升级为类型化系统：
- **`DriveEntry` 五类**：`care / curiosity / reflection / plan / idea`
- **生命周期**：`active → resolved / expired / decayed`
- **浮现规则**：`浮现分 = priority × 情绪类型权重 × 新鲜度加成`——低落时 care/reflection ×1.3，兴奋时 idea/curiosity ×1.3，plan 临期 6 小时强制置顶
- **响应路径注入**：用户消息命中挂念时，相关条目注入 `context_summary`——零额外 LLM 调用

测试从 613→635。

### 主动思考节流（F1-F6）

**`0888e4a` — fix: proactive token drain — silent backoff, think-loop cap, API circuit breaker**

6 个维度的主动行为 Token 消耗修复：
- F1：静默回退——AI 决定"保持安静"时不再消耗 LLM 调用
- F2：沉思循环上限——最多 N 轮沉思
- F3：空查询守卫——无检索结果的空查询不再触发补充 LLM 调用
- F4：梦境守卫——睡眠期间不做主动推理
- F5：API 断路器——连续 API 失败时自动降低主动频率
- F6：review 和 re_decide 中的相应保护

### CognitiveState 世界状态（Phases 1+2）

**`b11419b` — feat: CognitiveState world-state (Phase 1+2) + prompt history pollution fixes**

变更记录（`2026-07-22-cognitive-state.md`）描述了核心哲学：把"四个 Agent 各自重新理解世界"改为"每轮用户消息构建一次统一状态，所有模块消费同一份"——即 Blackboard 模式 / Think Once, Use Everywhere。

Phase 1（行为不变纯重构）：
- 定义 `CognitiveState` dataclass
- 在 Agent 1 `assess()` 完成后装配
- 状态信息注入 Agent 3 的 prompt 构建

Phase 2（真正 Think Once）：
- 记忆检索前移到 Agent 1 `assess()` **之前**——每条消息只检索一次记忆
- `CognitiveState` 注入 `InnerDriveAgent.assess()`
- 情绪在轮次开始一次性快照
- 验证测试：`handle_message` 中 `retriever.retrieve_for_query` 只被调用一次

Prompt 等价验证：构造同样的记忆摘要与 drive_summary，分别走 state 路径和旧路径，比较 `build_system_prompt` 的关键字段完全一致。

---

## 第八卷：Layers 2-6 执行与 A 批次（7月21日—22日）

### L3：共享检索管线

**`7dab49a` — feat(L3): shared retrieval pipeline + ContextBuilder profiles**

变更记录（`2026-07-21-layer3-retrieval-pipeline.md`）——Layer 3 设计的五个组件约 70% 内嵌在 `MemoryAgent` 中。本次将共享检索/验证逻辑抽取为独立管线 `memory/retrieval_pipeline.py`。

核心创新是 `ContextBuilder`：按 Agent Profile 渲染同一份记忆——Agent 1 看到完整置信度标注版，Agent 3 看到轻量摘要版。

设计偏离：设计文档中 `ParallelRetriever` 使用 `asyncio.TaskGroup` 并行，但实现必须串行 await——因为 SQLite `cursor()` 持有进程级 `threading.Lock`，同一事件循环内并发 acquire 会冻死事件循环（2026-07-20 生产死锁，见 `memory-agent-gather-deadlock.md`）。

**Agent 3 轻量格式示例**：
```
=== 相关记忆 ===
- preference|最爱食物: 披萨
- [开心] 一起聊歌单
关系：trust=1.00，familiarity=0.80
```
过滤规则：剔除矛盾条目、剔除 insight/observation 类型、fact 最多 3 条、无置信度标注。

### L5：ToolResult v2

**`f6dc565` — feat(L5): ToolResult v2 error taxonomy, smart retry with backoff, per-tool timeout, parallel dispatch, tool metrics**

工具系统的全面升级：
- 错误分类：`NetworkError / AuthError / TimeoutError / PermissionError / NotFoundError / RateLimitError / InternalError`
- 智能重试：按错误类型决定是否重试（NetworkError 重试，AuthError 不重试），带退避策略
- 每工具独立超时
- 并行执行：工具执行不阻塞主流程
- 工具 Metrics：调用次数、成功率、平均延迟

### L6：PersonalityManager + 角色绑定

**`65827de` — feat(L6): PersonalityManager + enforce session_id==role_id + isolation tests**

角色绑定的最终实现：
- `PersonalityManager` 类管理多角色人格文件
- 强制 `session_id == role_id`——一个角色一个 namespace
- 删除根目录的 `personality.json`（全局文件）
- 隔离验证测试

### A 批次（A1-A8）

7月21日集中推送了 8 个独立功能：

**A1 — Web Token 鉴权**（`f14293e`）：
- Bearer/query-token 中间件
- WS init 校验 + 4001 close
- 前端 `authFetch()` + `localStorage` 持久化
- 启动时非 loopback 绑定 + 无 token 打印醒目告警（不阻断）

**A2 — 截断语义**（`cc76933`）：
- 4 种截断模式精确检测（长度截断 / JSON 截断 / 对话截断 / 异常截断）
- `TruncatedResponseError` 用于 JSON 模式的检测
- monitor 字段记录截断类型

**A3 — Request ID**（`ce253ab`）：
- `ContextVar` + logging filter
- 跨 `run_async` 桥接传播
- monitor 日志关联 request_id

**A4 — 人格校验器**（`7a05049`）：
- 加载时检验 personality.json 完整性
- `.bak` 备份 + 最大保留 N 份 + 时序回退
- 发现损坏自动恢复上一次正常版本

**A5 — 语义去重**（`1d51e78`）：
- Union-Find 聚类
- Keeper selection + 验证合并
- GC 时清理语义近似重复条目

**A6 — 时间情感衰减**（`f6daa07`）：
- 读取时通过 `decay_elapsed` 结算衰减
- 不依赖后台线程（零资源消耗）
- 衰减量与真实经过时间成正比

**A8 — Schema v6 迁移**（`db455f0`）：
- 删除 archive 表（`user_facts_archive`、`reflections_archive`）
- A7 closure 文档

### M-18：Embedding 看门狗 + KI-1：别名下沉

**`39a5e59` — feat: embedding crash watchdog (M-18) + per-tool arg aliases replacing dispatcher global map**

变更记录（`2026-07-21-看门狗与别名下沉.md`）：

**M-18 看门狗**：`auto_start_embedding()` 的原 watcher 线程在服务就绪后即退出，llama-server 之后崩溃无人处理。修复引入 `_watchdog_loop()`：
- 每 30s 探活（`WATCHDOG_INTERVAL`）
- 连续 3 次无响应 → `kill_existing_llama()` + 重启
- 连续 3 次重启失败 → 放弃并保持关键词检索降级

**KI-1 别名下沉**：此前 `dispatcher._normalize_args()` 对所有工具做统一别名映射——曾把 notify 的 `title` 当成 music 的 `song` 吃掉。修复下沉到各工具：`Tool` 基类新增 `ALIASES` 类属性，各工具声明自己的别名映射。

---

## 第九卷：推理优化与收官（7月22日）

### R1-R5：推理约束与 Prompt 瘦身

**`2ce8023` — feat: reasoning & prompt fixes R1-R5**

变更记录（`2026-07-22-推理与prompt修复.md`）给出了具体的修改指标：

**R1 — Agent 1 推理约束**：`INNER_DRIVE_INTRO` 中"深层需求是什么？"改为"用户的意图是什么——他想让我做什么或回答什么？"并追加硬约束：禁止推断用户人格、心理动机或"潜台词"。

**R2 — Agent 3 心理分析限制**：Agent 1 的判断块截断到 300 字符，标题改为"=== 你刚才的分析（仅供参考，不要在回复里复述或展开）==="。`AGENT3_BASE_INSTRUCTIONS` 追加两条：禁止"我猜你…/你真正想…/其实你…"；拿不准直接问。

**R3 — 推断不进事实**：`FACT_EXTRACTION_PROMPT` 追加：性格/心理/动机画像不要提取——那是推断，不是事实。只能提取用户亲口陈述或可严格验证的事实。

**R4 — 情绪边界收益递减**：引入 `_soft_apply`——当当前值距离目标边界不足 0.4 时，同向 delta 按剩余空间比例衰减（最小保留 5%）。

**R5 — Agent 3 Prompt 瘦身**：reflection 条数 3→2，截断到 120 字符；tool history 条数 5→3，output 摘要由 100→60 字符。

### 时间查询短路

**`4cb2446` — fix: Agent 1 time-query shortcut**

监控 Review 发现：用户问"现在几点"时，系统走了「Agent 1 决策 → Agent 2 工具（返回空）→ Agent 3 回复」的远路。实际上 `build_inner_drive_prompt` 首行就动态注入了 `当前时间：...`。

根因：`INNER_DRIVE_CHECKLIST` 首条把"时间"列为潜在工具触发项——而工具层根本没有"获取时间"工具。修复将首条拆为两条：外部事实类保留（新闻/天气），时间/日期类明示"当前时间就写在上文，直接回答"。

### ContextManager 去重（T1-T6）

**`305fd7d` — fix: ContextManager compression strategy + inner-drive decision loop dedup**

这次提交（第 386 次）：

| 项 | 内容 |
|:---:|:---|
| T1 | `should_compress()` 作为阈值判断统一入口，消除内联散落的阈值比较 |
| T2 | `estimate_tokens` 加 `@lru_cache(maxsize=2048)` + 超长文本 >4000 chars 直走避免缓存污染 |
| T3 | 压缩输入不再均匀截断：最近 6 条完整保留，更早的每条短截断到 120 字符，总预算 12000 |
| T4 | 压缩摘要增量合并：有旧摘要时构造"已有历史摘要 + 新增对话"的合并输入 |
| T5 | InnerDrive 推理循环抽取 `_decision_loop`：`assess()`/`review()`/`re_decide()` 变为薄壳 |
| T6 | 循环导入确认——所有 lazy import 均必要，无需修改 |

测试：840 passed + 2 skipped。

---

## 第十卷：重构收尾与前端双主题（7月22日—26日）

### Token 预算三刀（T1-T3）

**`9f7daf8` — feat: token budget T1-T3 — Agent1 instruction slimming, history char budget, history_search tool**

变更记录（`2026-07-22-token-budget.md`，依据 `doc/fix-plan-2026-07-22-token-budget.md` 执行）：

- **T1 — Agent 1 指令瘦身**：`prompts/instructions.py` 五段指令（~1429 chars，占 Agent 1 prompt 的 66%）压缩合并为 `INNER_DRIVE_COMPRESSED`（684 chars，-52%），硬规则一字保留；旧五段常量保留为遗留别名。
- **T2 — Agent 3 历史字符预算**：`config.py` 新增 `react_history_budget_chars: int = 16000`，`_build_messages` 在 token 预算外按字符从最旧开始丢弃，不触发 compress_context。
- **T3 — `history_search` 内部工具**：历史被预算裁剪后可按需回查原始对话——`HistorySearchTool`（keyword / semantic / batch 三模式）+ Repository 新增 `search_turns` / `get_turns_range`。

复审追加修正：history_search 的 JSON Schema 会吃回 Agent 1 的瘦身成果，改为 `_make_internal_registry(include_history_search=False)`——Agent 1 注册表只含 recall/remember，Agent 3 三处调用点传 True。

### MessageHandler God Object 拆分

**`0277301` — refactor: split MessageHandler god object (990→838) into agent_wiring/message_builder/proactive_outcome**

变更记录（`2026-07-22-message-handler-split.md`）：`core/message_handler.py` 长到 990 行、25+ 方法。纯机械搬移 + 薄委托，行为零变化：

| 新模块 | 内容 |
|:---|:---|
| `core/agent_wiring.py` | `AgentWiring`：懒加载装配（InnerDrive/ToolAgent/MemoryAgent/两种 registry 及其缓存） |
| `core/message_builder.py` | `build_messages()`：prompt 消息数组构建（过滤 + 字符与 token 双预算） |
| `core/proactive_outcome.py` | `match_active_care()` / `evaluate_proactive_outcome()`（L4-6a 主动行为回馈归因） |
| `core/message_handler.py` | 只剩编排（838 行）：三层流水线 + 状态机 + ToolExecutionResult + 输入清洗 |

既有调用方与测试零改动——原私有方法全部保留为薄委托，`handler._inner_drive` 等改为读写 property 转发到 wiring。

### InnerDrive 清理与 core 同域归并

**`b9b6bb5` — refactor: InnerDrive cleanup — intent mapping single source + MemoryContextProvider extraction**

变更记录（`2026-07-22-inner-drive-cleanup.md`）：
1. intent→tool 魔法字符串归一：`inner_drive.py` 硬编码映射改由 `prompts/tools_description.py` 的 `_TOOL_INTENT_ALIASES` 派生反向映射 `INTENT_TO_TOOL`，正反向映射永不漂移
2. 记忆检索+格式化逻辑（~50 行）抽离为 `MemoryContextProvider`，含同消息 R1 memo 缓存；`InnerDriveAgent` 保留薄委托（929 → 898 行）

**`077593b` — refactor: move INTENT_TO_TOOL import to module level**

`INTENT_TO_TOOL` 改为模块级导入（`core/inner_drive.py:16`）。

**`23bba77` — refactor: merge same-domain core modules (proactive_outcome→proactivity, memory_context_provider→cognitive_state)**

变更记录（`2026-07-22-core-module-merge.md`）：上一周拆分产生的两个同域小模块归并回所属域——`proactive_outcome.py`（50 行）并入 `proactivity.py`（同属"主动行为"域），`memory_context_provider.py`（68 行）并入 `cognitive_state.py`（同属"轮次状态"域）。core/ 模块数 26 → 24。

### Agent 2 错误元数据化 + 可配置常量

**`0b6e989` — refactor: agent2_error as system metadata + configurable dispatcher_output_cap/stream_max_bytes**

变更记录（`2026-07-22-error-metadata-and-config-constants.md`）：

1. **agent2_error 元数据化**：此前 Agent 2 超时/异常时错误文本被 prepend 到 `records_text`，以 `role="user"` 进入 prompt，模型可能把系统错误当成用户输入。修复后 `agent2_error` 作为独立参数传给 `_run_agent3`，以 `[系统状态] ...` 形式附加到 **system prompt** 末尾（`core/message_handler.py:665-666`）。
2. **硬编码常量入 Config**：`config.py` 新增 `dispatcher_output_cap: int = 2000`（原 dispatcher `_OUTPUT_CAP`）与 `stream_max_bytes: int = 1_048_576`（原 provider `STREAM_MAX_BYTES`），ToolAgent / ReAct 循环 / DeepSeekProvider 均改读实例配置。

### 前端界面升级：双主题 + 流式渲染 + 智能滚动

**`cea8d4f` — feat(web): dual-theme UI upgrade with streaming markdown & smart scroll**

变更记录（`2026-07-26-前端界面升级双主题.md`）——纯前端升级，零后端改动，仅复用现有 WS 与 REST API：

- **双主题**：新增 `web/static/theme.css` 共享设计令牌（语义色板 + 监控页专用 `--monitor-*` 变量）；`<html data-theme>` 手动指定，未指定时经 `prefers-color-scheme` 跟随系统；手动选择存 `localStorage.ai_friend_theme`，主界面与监控页共用。`style.css` 全部颜色改为 `var(--*)`，无硬编码色值。
- **流式渲染**：WS `segment` 到达即增量 `marked.parse` 渲染（失败回退纯文本），流式气泡带闪烁光标，`done` 终渲染。
- **智能滚动**：贴底才自动跟随；用户上翻时显示"回到底部"悬浮按钮并累计未读角标。
- **消息操作条**：悬停显示复制按钮；实时消息显示 `HH:MM` 时间戳（历史接口无时间字段，历史消息不显示）。
- 其余：空态引导、历史加载骨架屏、WS 断线/重连横幅、header 主题切换按钮、静态资源版本 `?v=14` → `?v=15`。
- **监控页统一**：`monitor.html` 引入 theme.css；因 CSP `script-src 'self'` 禁内联脚本，主题初始化放在 `monitor.js` 头部。

### Embedding 端口冲突修复

**`3ccb7d7` — docs(changes): record embedding port conflict fix (8080 occupied by Steam)**

变更记录（`2026-07-26-修复embedding端口冲突.md`）：运行日志报 `llama-server exited early` 且 `/v1/embeddings` 404——`netstat` 确认 8080 被 `steamwebhelper.exe`（Steam）占用，语义检索退化为关键词模式。

修复只动 `config.json`（不入库）：`embedding_endpoint` 改为 `http://localhost:18080/v1/embeddings`。依据 H-04 设计（`core/embedding_server.py`），llama-server 启动端口由 `_port_from_endpoint()` 从该 endpoint 派生，改一个键即同时生效；也可用环境变量 `AI_FRIEND_EMBEDDING_ENDPOINT` 覆盖（默认值 `http://localhost:8080/v1/embeddings`，见 `config.py:86`）。

全量测试：841 passed + 2 skipped。

### 7月26日下午：一致性与体验收尾

同一天的最后一波提交，主题是"对齐"——prompt 声明与执行对齐、状态语义对齐、终端体验对齐。

**`148e9aa` — Fix #301: align Agent 3 prompt tool declaration with execution registry**

变更记录（`2026-07-26-修复issue301-agent3工具声明与执行一致.md`）：Agent 3 prompt 的「可用工具」块此前与 ReAct 循环实际执行的 registry 不一致。修复后 `build_system_prompt` 增加 `rule_tools` 参数：工具块只渲染内部 registry（recall / remember / history_search，与执行严格一致），输出规则块的 intent 选项改由 `rule_tools`（全量 registry）派生。

**四问题修复（`f5a2c10` / `7718717` / `233f412` / `3565c63`）**

按 `doc/fix-plan-2026-07-26-四问题修复.md`（`34babc4` 立项）逐项落地：

1. **inner_drive_state 淘汰策略补测试**（`f5a2c10`，`2026-07-26-内驱状态淘汰策略补充测试.md`）：核实实现已是"非活跃优先 + priority + created_at"淘汰（非 FIFO），不改代码，只补三个行为用例。
2. **MH-002 多请求工具结果归因**（`7718717`，`2026-07-26-多请求工具结果归因.md`）：`ToolCallRecord` 增加 `request` 字段（自然语言请求归属，截断 80 字符）；`format_for_phase2` 在多请求时按请求分组渲染（小标题【请求：…】，铁律段仅末尾一次），单请求格式不变；`format_tool_results` 增加 `append_iron_rule` 参数。解决"请求 2 成功、请求 1 失败时说不清哪件事没办成"。
3. **WS-27/28 CognitiveState 一致性**（`233f412`，`2026-07-26-CognitiveState一致性修复.md`）：删除 message_handler 对 `state.memory_summary` / `memory_confidence` 的改写，确立"装配后不再修改"约定；新增 `render_memory_light()` helper 统一 Agent 3 轻量渲染（inner_drive 与 message_handler 原各写一遍）；`_run_agent3` 有摘要时不再冗余 `retrieve_for_query`。
4. **AU-004 run_async 重入防护**（`3565c63`，`2026-07-26-run_async重入防护.md`）：thread-local 标记，worker 线程内嵌套调用立即抛 `RuntimeError("nested run_async call")`，把潜在的 4 线程池饿死（60 秒级卡顿）变成立刻可定位的报错。

**`70e953d` — Fix code review issues: retrieval serialization, embed context, health probe, dead code, buffer cleanup, encode guard**

变更记录（`2026-07-26-代码审查修复-死锁与健壮性.md`）：当天代码审查发现的 6 项逐项修复——`MemoryRetriever` 加 `threading.RLock` 串行化检索（禁 `asyncio.gather` 并发调用，防 SQLite 交错冻死事件循环）；`memory_agent._cross_verify` 显式传 embed；`health_check` 回退探测改 "health-check-ping" + `X-Probe-Type` 头、状态码放宽 2xx；`long_term` 删除引用未定义变量的死代码；consolidation 事实提取成功即清空缓冲区（后续步骤失败也清）；`_embed_new_items` 防御 encode 返回 None/数量不匹配。

**`7643131` — refactor: unify InnerDriveState construction into create_inner_drive_state**

变更记录（`2026-07-26-innerdrivestate单一创建点.md`）：`core/inner_drive_state.py` 新增 `create_inner_drive_state()` 工厂函数，消除 session_factory 与 agent_wiring 两处重复的 7 项参数映射（"初始化链断裂"），创建职责收敛为单一点。

**`d006086` — feat(cli): prompt_toolkit UI upgrade — history/completion/status bar, phase hints, panels**

变更记录（`2026-07-26-CLI界面升级.md`）：CLI 输入层重写为 prompt_toolkit `PromptSession`（FileHistory 历史、斜杠命令补全、AutoSuggestFromHistory、bottom_toolbar 状态栏、patch_stdout），删除 NonBlockingInputReader 轮询线程；`ui/display.py` 新增面板/关系进度条/分隔线/新 banner/emoji mood；管线透传 `on_status` 阶段提示（她在想…/翻工具箱…/写回复…）；非控制台回退 `input()`，非 tty 强制 UTF-8。新增 `prompt_toolkit==3.0.51` 依赖。

另有 `707830f` sleep 锁护栏测试（SL-002：梦境生成绝不在锁内 await，纯测试无行为变化）。

全量测试：**869 passed + 2 skipped**（871 collected）。

---

## 最终章：项目总结

### 代码库全景

**提交分布**：405 次提交，约 7 次/活跃日。单分支（main），从头到尾一条线。

**版本里程碑**：

| 版本 | 核心内容 | 状态 |
|:---|:---|:---:|
| v0.1 | 基础交互、情绪引擎、消息分段、破防 | ✅ |
| v0.2 | 异步数据库、结构化工具、三层架构、语义搜索 | ✅ |
| v0.3 | 自主行为、作息调度、梦境系统、工具集 | ✅ |
| v0.4 | 角色绑定、session 隔离 | ⚡ 部分 |
| v0.5 | 178 个问题系统修复、质量基建、安全加固 | ✅ |
| v0.6 | 六层架构、MemoryAgent、CognitiveState、A 批次 | ✅ |
| v1.0 | （蓝图：统一自我系统、多角色进化） | 📋 |

**测试规模增长**：
- 第 1 天：0
- 第 4 天：106 → 171
- 第 7 天：250
- 第 14 天：290
- 第 48 天：401
- 第 50 天：466
- 第 54 天：635
- 第 56 天：842
- 第 59 天：869（+2 skipped；上午归并后 841，下午 #301 / MH-002 / 审查修复 / CLI 升级等新增用例）

**数据库 Schema 演进**：v1（原始 SQLite）→ v2（observations/facts_v2）→ v3（UK-001）→ v4（facts_v2 上线）→ v5（insights_v2）→ v6（archive 清理）

### 关键决策回顾

1. **Day 1 确立文档先行**——13 份技术文档，同步规则在 CLAUDE.md 中硬编码
2. **Day 2 破防机制**——AI 的情绪不只是数据，它能"受伤"
3. **Day 3-4 架构革命**——单体 → 两阶段 → 三层 Agent，每次架构升级都对应一个深层次 LLM 行为问题
4. **Day 7 虚假记忆修正**——事实管理从"存进去就不改"升级为带矛盾检测的"活"系统
5. **Day 14 178 问题作战计划**——系统级质量问题管理
6. **Day 48 六层架构蓝图**——从战术修复转向战略设计
7. **Day 50 MemoryAgent**——确定性记忆推理替代纯 LLM 记忆
8. **Day 55 CognitiveState**——Think Once, Use Everywhere

### 经验与教训

**做得好的**：
1. **文档纪律**——405 次提交几乎每次都同步更新文档和 changes/ 记录。13+ 份文档分布在所有维度
2. **问题清单驱动**——178 个问题按优先级歼灭，不做随机修 Bug
3. **从战术到战略的跃迁**——第 48 天从"修 Bug"切换到"系统性设计"，3 天设计 5 天落地
4. **根因追击**——#299 从 WebSocket 连接失败一路深挖到 CORS、权限、记忆固化、API 兼容
5. **测试随行**——每次 Bug 修复都附带回归测试，测试规模从 0 增长到 869

**可以更好的**：
1. **单分支风险**——405 次提交全在 main 上，无功能分支隔离
2. **嵌入服务器稳定性**——问题从 Day 14 出现，Day 55 看门狗才根治，41 天的间歇性故障
3. **v0.5 计划规模失当**——"4 周完成"过于乐观，实际约 6 周才接近完成
4. **前端系统性不足**——大部分时间前端远落后于后端，UI 开发碎片化
5. **架构决策滞后**——如果 Day 1 就确立三层 Agent 架构，可以节省大量返工（工具伪造修复的 3 轮补丁、Agent 拆分的 3 次迭代）

---

### 尾声

405 次提交，59 天，从命令行下一段"你好"到拥有完整人格、情绪、记忆、工具、Web 界面、监控面板、Token 鉴权的 AI 系统。

项目从零开始，最终成长为：
- **3 层 Agent 架构**（InnerDrive → ToolAgent → Roleplay）
- **4 层情绪引擎**（输入调制 + 分速衰减 + 怨恨累积 + 事件记忆）
- **2 级记忆体系**（短期 LRU + 长期 SQLite + 语义检索 + FactChecker）
- **6 层架构设计**（Memory → Prompt → Retrieval → Runtime → Tools → Identity）
- **15+ 工具**（搜索、文件、音乐、通知、记忆、目录浏览）
- **双模式运行**（CLI + WebSocket/REST Web）
- **可观测性**（监控面板、结构化日志、request_id 追踪）

所有这一切，始于 2026 年 5 月 28 日凌晨 0:59 的一次 `git init`。

---

*开发日志完 · 全文约 18,000 字*

*项目路径：D:\桌面\编程作品\AI朋友*
*提交范围：b289667 → d006086（共 405 次）*
*数据来源：全部 git log + changes/ 目录下所有修改记录文件*
