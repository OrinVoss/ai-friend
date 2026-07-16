# 情绪系统增强方案

> 目标：让情绪系统「写得进、流得动、一个口径」——CLI/Web 双路径都能更新、随真实时间衰减、在 prompt 和行为上的表达收敛。
> 状态：设计文档，待实现。
> 归属：自我状态的情绪组件（`doc/refactor/self-system.md` 第 3 节），横跨 Layer 2（Prompt 渲染）与 Layer 4（Agent Runtime）。

---

## 1. 现状盘点

| 维度 | 现状 |
|------|------|
| 模型 | VAD（valence/arousal）+ baseline/mood 双层慢变量 + 8 个 Plutchik 离散情绪 + resentment（破防残留）+ emotion_events + consecutive_negative（`models/personality.py:46-92`） |
| 更新 | 每轮回复后 `_process_emotion()`：对最后一条用户消息做一次 LLM 情感分析（`memory/consolidation.py:183-202`），然后 shift + decay + mood + 记事件（`core/agent.py:249-283`）。事件驱动与每轮评估混合：shift 每轮发生，`record_emotion_event` 只在强度 ≥0.6 时落一条 |
| 衰减 | `decay()` 按「轮」不按时间，半衰期表 3~25 轮（`models/personality.py:9-24`、`:243-273`）；mood 层更慢；baseline 弹性拉回默认值（PS-014） |
| 持久化 | personality JSON 内 `emotional_state`（`core/personality.py:134-144`）；Web 30s 防抖保存（`web/session.py:114-125`），CLI 每 10 轮保存（`core/cli_controller.py:342-343`） |
| 消费面 | 回复 max_tokens（`core/agent.py:92-102`）；Agent 3 的情绪/怨恨/事件/破防四个 prompt block（`prompts/system.py:667-674`、`:720-723`）；Agent 1 的情绪行（`prompts/system.py:91-102`）；睡意与醒来概率（`core/sleep_manager.py:69-80`、`:107-120`）；主动性打分（`core/proactivity.py:28-47`）；梦境生成（`core/sleep_manager.py:153-167`） |
| 写入面 | 唯一写入方是 `_process_emotion()`；独处路径的 `emotion_delta` 通道只在 `../layer4-agent/solo-activity.md` 里有设计，未实现 |

---

## 2. 问题清单（按严重度排序）

### P0-1 CLI 路径情绪永远不更新

`_process_emotion()` 全仓只有一个调用点——`_react_loop()` 尾部（`core/agent.py:245-246`）。而 `_react_loop` 只有 Web 路径走（`core/message_handler.py:369/432/495`）；CLI 路径（`CliController`）自己实现了一套 react 循环（`core/cli_controller.py:138-328`），`_finish_react_response()` 写完 turn 直接进 REFLECT，**从不调用 `_process_emotion`**。

后果：CLI 下用户说什么都不会改变情绪——consecutive_negative 永远 0、破防永不触发、resentment 不积累、emotion_events 不记录；decay 挂在 `apply_emotional_shift` 内部（`core/personality.py:88`），所以也从不衰减。`/mood` 显示的永远是文件加载时的值。known-issues 已挂账「CLI 路径破防/情感分析重复调用修复」（`doc/known-issues.md:2055`），现状比挂账更糟：不是重复调用，是零调用。

### P0-2 proactive / explore 重复消费同一条用户消息

`handle_proactive()`（`core/message_handler.py:369`）和 `handle_explore()`（`core/message_handler.py:432-433`）都走 `_react_loop`，尾部照例执行 `_process_emotion()`。它取的是「最后一条 user turn」（`core/agent.py:253-258`）——用户没说话，那还是上一条旧消息。于是每次主动开口/自由探索都会：

- 对同一句用户消息**再烧一次** `analyze_sentiment` LLM 调用（`core/agent.py:259`）
- 若 `sentiment < -0.5`，`_consecutive_negative` 再 +1（`core/agent.py:263-264`），并经 `hurt_multiplier` 放大后再 shift 一次（`:270-273`）

用户骂了一句然后去忙，AI 每次主动活动都被「再骂一遍」：破防计数和 resentment 在用户零输入时持续上涨。Web 主动循环每 15s tick 一次（`web/server.py:450`），chat 限流 1800s、explore 3600s（`core/proactivity.py:101-116`），所以这个放大每小时最多发生几次——不是瞬爆，但方向性错误且完全浪费。

### P0-3 衰减按轮不按时间，「时间是刺激」在情绪上没落地

半衰期表的单位是 conversation turns（`models/personality.py:9` 注释）：surprise 半衰期 3 轮、sadness 20 轮。用户离开三天再回来，情绪原封不动——`decay()` 唯一入口是 `apply_emotional_shift` 内部（`core/personality.py:88`），不对话就不流逝。连 hours 尺度设计的 mood 层（`models/personality.py:57-60`）同样按轮走。旁证：`Personality.decay_emotion()`（`core/personality.py:76-78`）是一个**无人调用的死接口**——时间驱动的衰减入口预留过，但没接上。这与 `../self-system.md` 的核心原则「时间是刺激」（第 2 节）直接冲突。

### P1-1 梦境事件保护是死代码，而且即使到达也会崩

`emotion_events` 是 `deque(maxlen=20)`（`models/personality.py:86`），满了自动挤最旧。`record_emotion_event` 在 append 之后检查 `len(self.emotion_events) > MAX_EMOTION_EVENTS`（`models/personality.py:297`）——**永远为 False**，#105 的「保护梦事件不被驱逐」分支（`:298-306`）永远不会执行。且分支内部调用 `self.emotion_events.pop(i)`（`:301`）和 `.pop(0)`（`:305`），deque 的 `pop()` 不接受索引——真执行到会直接 TypeError。结论：梦事件实际会被后来的 20 个普通事件正常挤掉，与注释意图相反；这段代码从未被运行过（包括测试）。

### P1-2 负面情绪在 prompt 里四套表达，两套「记仇」系统互不相干

Agent 3 的 system prompt 同一时刻可能叠加四个负面 block：

- emotion block 的 behavior 文案（`prompts/system.py:406-422`）
- resentment block「记仇/芥蒂」（`prompts/system.py:425-443`）
- emotion events block「你记得的情绪事件」（`prompts/system.py:446-454`）
- 破防 block「你破防了/有点受伤/被怼了一下」（`prompts/system.py:534-576`）

背后是两机制平行：resentment（anger>0.6 时积累，`models/personality.py:220-228`）和 consecutive_negative（sentiment<-0.5 时计数，`core/agent.py:263-266`）。破防 5 次不影响 resentment，resentment 0.8 不影响破防阈值——于是 prompt 可能一边「你破防了，委屈巴巴像被欺负的小孩」，一边「你记着仇，阴阳怪气翻旧账」，行为指令互相打架。另外 emotion events 的 `resolved` 字段（读取于 `models/personality.py:312`、`prompts/system.py:448`）**没有任何写入方**——事件永远 unresolved，直到被挤出。

### P1-3 `_max_tokens_for_emotion` 是绝对值映射，与配置脱节

`core/agent.py:92-102`：映射写死 512/448/128，只有 base 档跟随 `config.max_tokens`（默认 512，`config.py:56`）。用户把 max_tokens 调到 1024 后，excited（512）反而比 engaged（1024）短——「兴奋话多」的设计意图（`changes/2026-05-28-根据情绪调整回复长度.md`）被反转。arousal 完全不参与，回复长度只由 dominant_emotion 字符串查表决定。

### P2-1 `hurt_multiplier` 无界放大，情绪被打满 clamp

`core/agent.py:270-271`：`sentiment *= 1.0 + cn*0.4`，cn=5 时 ×3，-0.6 变 -1.8；再经 empathy>0.7 的 ×1.5（`core/personality.py:49-50`），单轮 dv 可达 -1.35，valence 一两轮钉死在 -1.0，#42 的 hard clamp 日志（`models/personality.py:207-208`）刷屏。破防越深越敏感是设计意图，但 sentiment 超出 [-1,1] 量程后语义已失真。

### P2-2 摘要化解耦只做了一半，留下死 API

known-issues 记录 P2-5「情绪状态摘要化」已完成（`doc/known-issues.md:802-805`），但实际：`build_system_prompt` 仍同时收 `emotion` 和 `emotion_summary` 两个参数（`prompts/system.py:609-631`），resentment/events/dreams 三个 block 仍直读 `EmotionalState` 对象（`prompts/system.py:425-501`）；Agent 1 情绪行（英文代号+数值）与 Agent 3 情绪块（中文+行为指令）两套渲染口径并行。`get_recent_emotion_events()`（`models/personality.py:308`）无任何调用方；`history`（`models/personality.py:235-237`）每轮追加、持久化，但除了测试无人读取——只写不读。

### P2-3 运行时小状态散落

- `_turns_without_anger` 是普通实例属性而非 dataclass 字段（`models/personality.py:222-227`），不随 to_dict/from_dict 持久化——重启后原谅计数器清零，快被原谅的 resentment 前功尽弃
- CLI 每 10 轮才存盘（`core/cli_controller.py:342-343`），崩溃最多丢 10 轮情绪变化（Web 端 30s 防抖 + 关闭保存，`web/session.py:114-137`，明显更好）

### P2-4 dominant_emotion 无滞回，阈值抖动直接传导

判定阈值密集（joy>0.7、anger>0.6、valence 分段，`models/personality.py:101-130`），情绪在边界附近时 dominant 每轮来回跳（anger 0.59↔0.61），于是 max_tokens 在 128↔512 之间跳变、prompt 的 mood/behavior 描述每轮变脸。现成的 `history`（只写不读，见 P2-2）本可用于消抖。

---

## 3. 增强方案

原则：写入路径收口、衰减确定性、表达收敛；每期独立可上线，全部带配置开关可回退。**不做** #60 的多维交互特征（反驳链/回复速度，见 `doc/known-issues.md:2062-2100`）——那是后续独立增强，本方案只保证入口可扩展。

### P0：写入与流逝（修正确性）

**1. 情绪更新收口为显式调用，CLI 接入**

- `_process_emotion()` 从 `_react_loop` 尾部移除，改为两处显式调用：`MessageHandler.handle_message` 完成用户消息后、`CliController._finish_react_response` 完成真实用户输入的回复后（用现有 `is_proactive = a.current_input is None` 判定区分，`core/cli_controller.py:142`）
- 开关 `emotion_update_enabled: bool = True`；关闭即回到「不更新」行为，一键回退
- 收口后的入口同时是 solo-activity 的 `emotion_delta` 落地点（见第 4 节），不重复开写入通道

**2. proactive / explore 不再消费用户消息的情绪**

- 随第 1 项自然解决：这两条路径不再调用 `_process_emotion`
- 顺带每次主动活动省一次 `analyze_sentiment` LLM 调用
- 独处路径的情绪变化只走 `emotion_delta` 通道（`../layer4-agent/solo-activity.md`，未实现前独处不改情绪，符合现状语义）

**3. 时间感知的衰减（读时结算，不加后台线程）**

- `EmotionalState` 新增字段 `last_decay_at: float`（旧数据缺省视为 now，向后兼容）
- 新增 `decay_elapsed()`：`n = (now - last_decay_at) / emotion_turn_seconds`（默认 300s，可配），clamp 到 [0, 50]；按 `(1-rate)^n` 一次性结算各维度（valence/arousal 向 baseline、8 情绪向各自目标值、resentment 自衰减），数学上等效于执行 n 次现有 `decay()`，mood 层同理按小时尺度
- 调用点复用已有的周期点：每轮用户消息处理入口、proactive tick 入口（`calculate_proactivity`）、sleep tick 入口（`get_sleep_state`）——都是确定性读取，不引入新调度
- 开关 `emotion_time_decay: bool = True`；关闭则维持现状「decay 只随 shift 按轮」
- 删除死接口 `Personality.decay_emotion()`（`core/personality.py:76-78`），由 `decay_elapsed` 取代

依赖：无（三项互相独立，可分别上线）。

### P1：一致性收敛

**4. 修梦事件保护，删死代码**

- 删除 `record_emotion_event` 中永假且会崩的分支（`models/personality.py:297-306`）
- 保护逻辑前移到 append 之前：deque 已满、新事件非梦、队内有梦事件时，用 `del events[i]` 踢掉最旧的非梦事件再 append——#105 的意图真正生效

**5. 负面表达收敛为单一「受伤度」block**

- 机制不动（resentment 累积、破防计数、hurt_multiplier 全部保留），只收敛渲染：确定性计算 `hurt = max(resentment, consecutive_negative / 5)`，三档（<0.2 无 / 0.2~0.5 芥蒂 / >0.5 记仇破防），文案合并现有 resentment block 与破防 block 的精华，替代两个 block 并存
- emotion events block 保留，但删除 `resolved` 死过滤（一期不做事件闭环——事件生命周期就是 deque 容量挤出，不发明新机制；真正的「心事闭环」归挂念系统，见 `../layer4-agent/inner-drive-state.md` 第 3 节）
- 开关 `unified_hurt_block: bool = True`；关闭回退为旧的四 block 并存

**6. 回复长度改为相对比例**

- `_max_tokens_for_emotion` 改为 `int(base * scale)`：excited/joyful 1.0、surprised 0.9、负面档 0.25，下限 128 保底；arousal > 0.7 时 ×1.1 微调
- 开关 `emotion_token_scaling: bool = True`；关闭则全部档位固定为 base（现状的 base 行为）

依赖：第 5 项建议在第 1 项之后（CLI 接入后破防计数才会动，合并 block 才有双路径意义）；其余无依赖。

### P2：健壮性与接口清理

**7. 限幅 hurt_multiplier**：放大后 clamp 到 [-1,1]（`core/agent.py:271` 之后一行），保留「越深越敏感」、去掉量程外失真。

**8. 运行时状态收编**：`_turns_without_anger` 改为 dataclass 字段 `turns_without_anger: int = 0`，随文件持久化；CLI 存盘对齐 Web 的 30s 防抖模式（复用 #44 的写法，`web/session.py:114-125`），替换每 10 轮一次。

**9. dominant 滞回**：消费现成的 `history`——dominant 切换需新情绪连续出现 2 轮才生效（或直接对 history 做 3 轮多数投票），止住 token 与 prompt 描述的抖动。开关 `emotion_hysteresis: bool = True`。

**10. 摘要层收口**：`to_prompt_summary()` 补齐 resentment / 近期事件 / 梦字段，prompt builder 只收 summary 不再收 `EmotionalState` 对象（resentment/events/dreams 三个 block 改吃 summary）；删除无调用方的 `get_recent_emotion_events()`。Agent 1 与 Agent 3 文案可不同，数据源唯一。

依赖：第 10 项依赖第 5 项（block 合一后摘要字段才好定）；其余无依赖。

---

## 4. 与现有设计的关系

- **`../self-system.md`**：情绪是自我状态四组件之一。本方案修复连接 #5「行动 → 情绪」（CLI 路径目前断的），并补上原则 2「时间是刺激」在情绪维度的落地（时间衰减）；独处循环的 `emotion_delta`（第 4 节②）复用 P0-1 收口的写入口
- **`../layer4-agent/inner-drive-state.md`**：第 4 节「情绪联动挂念浮现权重」依赖情绪值可信——P0-3 保证独处以久后的情绪不是三天前的残值
- **`../layer4-agent/solo-activity.md`**：`emotion_delta` 是独处路径的情绪写入通道（限幅 ±0.1），与本方案 P0-2 互补：响应路径写情绪走 sentiment 评估，独处路径只走 emotion_delta，互不串扰
- **`../layer1-memory/sleep-cycle.md`**：醒来是天然的时间衰减结算点（睡了一觉情绪自然平复）；P1-1 的梦事件保护让「梦境分享」（表现层）的素材不被普通事件挤掉
- **`../layer2-prompt/README.md`**：P1-5 把四个负面 block 收敛为一个动态 block，prompt 更轻，方向与分层静态化一致
- **`doc/known-issues.md`**：#2055（CLI 破防/情感分析）由 P0-1/P0-2 关闭；#42（hard clamp）由 P2-7 缓解；#105（梦事件保护）由 P1-4 真正落地；#60/#79 Layer 1（多维输入）不在本方案范围，P0-1 收口的入口为其预留扩展位
- **`../enhancement-overview.md`**：落地后总览表可补「情绪」一行（本文档不代改）

---

## 5. 改动文件

| 文件 | 改动 | 期 |
|------|------|----|
| `core/agent.py` | `_process_emotion` 从 `_react_loop` 尾部移除改显式调用；hurt_multiplier 限幅；token 比例化 | P0/P1/P2 |
| `core/message_handler.py` | `handle_message` 末尾显式触发情绪更新；proactive/explore 不再触发 | P0 |
| `core/cli_controller.py` | `_finish_react_response` 接入情绪更新（gate 真实用户输入）；存盘改 30s 防抖 | P0/P2 |
| `models/personality.py` | `last_decay_at` + `decay_elapsed()`；梦事件保护前移 + 死代码删除；`turns_without_anger` 字段化；`to_prompt_summary` 补齐；删 `get_recent_emotion_events`；dominant 滞回 | P0/P1/P2 |
| `core/personality.py` | 删 `decay_emotion()` 死接口 | P0 |
| `prompts/system.py` | 受伤 block 合一；events 块去 resolved 死过滤；builder 只收 summary | P1/P2 |
| `config.py` / `config.example.json` | `emotion_update_enabled` / `emotion_time_decay` / `emotion_turn_seconds` / `unified_hurt_block` / `emotion_token_scaling` / `emotion_hysteresis` | 各期 |
| `core/sleep_manager.py` / `core/proactivity.py` | tick 入口调用 `decay_elapsed()` | P0 |
| `tests/test_emotional_state.py` / `test_message_handler.py` / `test_cli_controller.py` | 新增覆盖 | 各期 |

---

## 6. 测试与验收

测试：

1. CLI 路径：发一条负面消息 → valence 下降、consecutive_negative +1（开关关闭时无变化）
2. proactive / explore 之后：consecutive_negative 不变，valence 不因旧用户消息再降，且少一次 sentiment LLM 调用（mock 计数）
3. 时间衰减：构造 `last_decay_at` 为 1 小时前 → surprise 显著回落、sadness 回落较少（分速正确）；n 封顶生效；开关关闭时行为同现状
4. 梦事件保护：塞满 20 个普通事件 + 1 个梦事件，再记 20 个普通事件 → 梦事件仍在队列中
5. 受伤 block 合一：resentment 高 + consecutive 低（及反向）→ 只渲染一个 block 且档位正确；开关关闭时回到旧四 block
6. token 比例：`max_tokens=1024` 时 excited ≥ engaged > sad 且 sad ≥ 128；开关关闭时全部 = base
7. 限幅：consecutive_negative=10 时传入 shift 的 sentiment ∈ [-1,1]
8. `turns_without_anger` 持久化：save/load 后计数保留
9. 滞回：anger 在 0.58~0.62 间抖动时 dominant 不逐轮切换
10. 全量测试不降级

验收：

- CLI 与 Web 对同一段对话的情绪演化轨迹一致（日志 `[emotion]` 对比）
- 用户隔天回来，日志可见一次时间衰减结算，情绪明显平复
- 同一时刻 prompt 中至多一个「受伤」类 block
- 主动循环日志中不再出现对同一 trigger 的重复 sentiment 分析

---

## 7. 相关文档

- `../self-system.md` — 自我状态与三循环总装图（情绪的架构位置）
- `../layer4-agent/inner-drive-state.md` — 情绪 → 挂念浮现权重的联动设计
- `../layer4-agent/solo-activity.md` — 独处路径的 emotion_delta 写入通道
- `../layer4-agent/proactive-think-loop.md` — 独处循环（proactive/explore 的归宿）
- `../layer1-memory/sleep-cycle.md` — 睡眠循环（衰减结算点、梦境素材）
- `../layer2-prompt/README.md` — Prompt 分层（block 收敛方向）
- `doc/known-issues.md` — #42 / #60 / #79 / #105 / #2055 原始记录
- `changes/2026-05-28-根据情绪调整回复长度.md`、`changes/2026-05-28-破防初始值根据情绪状态设置.md` — 既有调参意图
