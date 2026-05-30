# AI Friend

具有人格、情绪和长短期记忆的 AI 朋友。基于 DeepSeek API，采用 ReAct Agent 架构，支持 CLI 和 Web 双端。

核心引擎采用两阶段 Agent 架构：Phase 1 ToolAgent 纯工具调用 + Phase 2 Roleplay Agent 人格驱动回复，从根本上解决模型虚构工具调用内容的问题。

---

## 功能

### 情感系统（四层架构）

| 层级 | 名称 | 说明 |
|------|------|------|
| Layer 1 | 多维输入 | content sentiment + 交互模式（反驳数、回复速度、态度一致性） |
| Layer 2 | 交叉调制 + 分速衰减 | 情绪互相制约（anger 压制 joy），8 维度独立半衰期（surprise 3t ~ trust 25t） |
| Layer 3 | 怨恨残留 | anger > 0.6 触发 resentment 累积，压制 joy 上限 + 减慢 trust 恢复（3%/turn 衰减） |
| Layer 4 | 情绪事件记忆 | 强情绪自动记录（为什么生气），注入后续 prompt |

### 破防机制

连续 5 次负面交互触发，累积伤害 1.4×/turn，三级递进：

| 次数 | 状态 | 行为 |
|------|------|------|
| 1-2 次 | 被怼了一下 | 轻回怼，不在意 |
| 3-4 次 | 有点受伤 | 委屈，底气不足 |
| ≥5 次 | 破防 | 哭腔、反问、撒娇式崩溃 |

正面互动降低计数。

### 人格系统

`personality.json` 完全可定制：
- 名字、性格特质（playfulness/warmth/humor/empathy/sass 等，0~1 连续值）
- 说话风格描述、背景故事、兴趣领域
- 情绪基线（valence + arousal）和衰减速率
- 情绪状态由系统自动维护，手动修改可强制干预

### 记忆系统

```
短期记忆（ConversationBuffer）
    │ deque, 线程安全, 重启从 DB 恢复最近 30 轮
    ▼
长期记忆（SQLite 5 表）
    ├── user_facts          用户事实（评分 + 置信度 + 重要性）
    ├── experiences         共享体验（情感色调 + 重要性，软删除）
    ├── reflections         反思洞察（类型 + 重要性，软删除）
    ├── conversation_turns  完整对话历史
    └── relationship_metrics 关系指标
```

三层检索：Hot Memory → Query-Guided（评分 + LLM重排）→ On-Demand（recall 工具）

### 工具系统（9 个，两阶段分工）

**Phase 1 — ToolAgent 纯工具调用（7 个外部工具）**：web_fetch / web_search / read_file / glob / grep / music_play / notify

Phase 1 无人格、无情绪、无记忆，仅负责执行外部工具，将结果注入 Phase 2 上下文。使用独立精简 prompt，temperature=0.3。

**Phase 2 — Roleplay Agent 内部工具（2 个）**：recall / remember

Phase 2 保留 recall 和 remember（均为本地 SQLite 操作），外部工具指令已完全移除。

| 工具 | 功能 | 参数 | 后端 | 阶段 |
|------|------|------|------|------|
| `web_fetch` | 提取网页正文（自动去 HTML） | url | AnySearch API | Phase 1 |
| `web_search` | 网络搜索，支持时效过滤 | query, max_results, freshness | AnySearch API | Phase 1 |
| `read_file` | 读取本地文件（≤500KB，行号+行偏移+多文件） | path, limit, offset | 本地 IO | Phase 1 |
| `glob` | glob 模式搜索文件（`**/*.py` 等） | pattern, path | 本地遍历 | Phase 1 |
| `grep` | 正则搜索文件内容（上下文+过滤） | pattern, path, glob, context | 本地搜索 | Phase 1 |
| `music_play` | 播放音乐（模糊搜索） | song | 默认播放器 | Phase 1 |
| `notify` | Windows toast 桌面通知（不阻塞） | title, message, duration | PowerShell WinRT | Phase 1 |
| `recall` | 回忆用户信息或共同经历 | query | SQLite | Phase 2 |
| `remember` | 记住用户重要信息 | category, key, value, importance | SQLite | Phase 2 |

Phase 1 通过 `<tool_call>` XML 标签自主调用，结果作为 `<tool_result>` 注入 Phase 2 prompt。每次调用自动记录到 `_tool_call_history`（最多 20 条）。

### 两阶段响应流程

```
用户输入
    │
    ▼
Phase 1: ToolAgent (core/tool_agent.py)
    │  temp=0.3, 无人格/情绪/记忆
    │  纯工具调用: web_fetch/web_search/read_file/glob/grep/music_play/notify
    │  结果作为 <tool_result> 注入 Phase 2 上下文
    ▼
Phase 2: Roleplay Agent (core/agent.py)
    │  temp=0.8, 完整人格 + 情绪 + 记忆
    │  personality.json → PersonalityConfig + EmotionalState
    │  analyze_sentiment(user_input) → sentiment 值
    │  estimate_emotional_impact(sentiment) → trait 调制 → shift()
    │  _cross_modulate() → 情绪互相制约
    │  decay() → 分速衰减
    │  build_system_prompt() → LLM 看到人格 + 情绪 + 怨恨
    │  可用工具: recall / remember（内部 SQLite 操作）
    ▼
AI 回复 = 人格底色 × 当前情绪 × Phase 1 工具结果 × 对话上下文
    │
    ▼
Emotion → Memory consolidation → Reflection（后处理，不变）
```

### 人格实现

四层实现：
1. `personality.json` — 名字、特质、说话风格、背景故事、兴趣
2. `EmotionalState` — VAD + 8 Plutchik + resentment + emotion_events（运行时动态）
3. `Personality.estimate_emotional_impact()` — 特质调制情绪变化幅度（高 empathy → 响应 ×1.5）
4. `prompts/system.py` — 人格翻译为自然语言 + 对话示例 + 破防/怨恨/梦境注入

人格是底色，情绪是滤镜——小星永远嘴贫，但开心时贫得更欢，愤怒时贫中带刺，破防时贫不起来了。

### 双端界面

| | CLI | Web |
|------|-----|-----|
| 启动 | `python main.py` | `python web_main.py` |
| 驱动 | 状态机循环 | 事件驱动 |
| 输入 | stdin 线程 | WebSocket |
| 输出 | 打字机效果 | 分段独立气泡 + 情绪调速（6 级 fallback 分段） |
| 主题 | - | 暗色主题，响应式 |

### 自主行为系统

#### 作息

| 事件 | 时间窗口 | 触发条件 |
|------|---------|---------|
| 午睡 | 12:00-13:00 | 情绪驱动（sad +40%，excited -20%，resentment +20%） |
| 午醒 | 13:10-16:00 | 随机（arousal 高→早醒，resentment 高→晚醒），分享梦境 |
| 夜睡 | 23:00-次日 01:00 | 情绪驱动（baseline 30% + sleepiness） |
| 晨醒 | 7:00-10:00 | 随机（情绪影响），分享梦境 |

睡前发一条消息（"困了去睡了…" / "晚安"），醒来分享 LLM 生成的碎片化梦境。

#### 自主探索

空闲时 40% 概率进入探索模式：AI 自主使用工具（上网/听歌/翻文件），发现有趣的才分享给用户，没什么就安静结束。

#### 频率限制

| 行为 | 上限 |
|------|------|
| 探索 | 1 次/小时 |
| 聊天 | 2 次/小时 |
| 梦境 | 每次睡眠 1 次 |

#### 情绪驱动的空闲阈值

| 情绪 | 主动触发最小空闲 |
|------|----------------|
| excited | 60s |
| joyful | 90s |
| engaged | 180s（3min） |
| neutral | 360s（6min） |
| sad | 900s（15min） |
| angry | 480s（8min） |
| +resentment | 额外 +0~300s |

### 其他特性

- **上下文压缩** — 180K 上下文 80% 阈值自动压缩，有递归保护
- **token 动态调整** — max_tokens 随情绪变化（excited 768, neutral 512, sad 256）
- **会话管理** — session_id cookie 持久化，多标签页独立会话，短期记忆重启恢复
- **环境变量安全** — API Key 支持 `DEEPSEEK_API_KEY` 环境变量，优先级高于 config.json

---

## 快速开始

```bash
pip install -r requirements.txt
cp config.example.json config.json
# 编辑 config.json 填入 API Key
# 或用环境变量: export DEEPSEEK_API_KEY=sk-...
# 搜索工具: export ANYSEARCH_API_KEY=as_sk-...
```

```bash
# CLI 模式
python main.py

# Web 模式
python web_main.py
# → http://localhost:8000
```

---

## 配置

支持 `config.json` + 环境变量覆盖（优先级：环境变量 > config.json > 默认值）：

| 字段 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `api_key` | `DEEPSEEK_API_KEY` | — | **必填** |
| `api_endpoint` | `DEEPSEEK_API_ENDPOINT` | `https://api.deepseek.com` | |
| `api_model` | `DEEPSEEK_API_MODEL` | `deepseek-v4-flash` | |
| `api_timeout` | — | `180` | API 超时（秒） |
| `max_tokens` | — | `512` | 回复长度上限 |
| `temperature` | — | `0.8` | 生成温度 |
| `db_path` | `AI_FRIEND_DB_PATH` | `data/ai_friend.db` | 数据库路径 |
| `log_level` | `AI_FRIEND_LOG_LEVEL` | `INFO` | 日志级别 |
| `web_host` | — | `0.0.0.0` | Web 绑定地址 |
| `web_port` | — | `8000` | Web 端口 |
| — | `ANYSEARCH_API_KEY` | — | AnySearch API Key（可选，匿名也可用） |

---

## 人格定制

编辑 `personality.json`：

```json
{
  "name": "小星",
  "traits": {
    "playfulness": 0.95,
    "warmth": 0.85,
    "humor": 0.9,
    "empathy": 0.8,
    "sass": 0.75
  },
  "speaking_style": "幽默、嘴贫、爱开玩笑，说话带点损但其实是关心…",
  "backstory": "一个嘴欠但心暖的损友，日常就是和朋友互怼互夸…",
  "interests": ["聊天互怼", "吃瓜", "打游戏", "摄影", "音乐"],
  "emotional_baseline": {
    "valence": 0.4,
    "arousal": 0.3
  },
  "emotional_decay_rate": 0.05,
  "first_run_greeting": "哈哈哈哈终于来了！等你半天了[旺柴]"
}
```

`emotional_state` 由系统自动维护，包含：
- VAD 维度（valence/arousal）+ 8 Plutchik 情绪 + baseline + mood
- `resentment`（怨恨值，0~1）
- `emotion_events`（情绪事件记忆，最多 20 条）
- `history`（最近 10 次情绪标签）
- `dominant_emotion`（自动计算，负面 valence 时负面情绪优先）
- `consecutive_negative`（连续负面计数，驱动破防）

---

## CLAUDE.md 规则

- 发现 bug → 先创建 GitHub issue → 修复 → changes 记录 → 推送
- 修改文件 → `changes/YYYY-MM-DD-简短描述.md`
- 文档用 ASCII 图表达架构/流程/状态机
- 提交前 `python -m py_compile` 检查语法
- API 调用使用 `trust_env=False`

---

## 项目结构

```
ai-friend/
├── main.py                    CLI 入口
├── web_main.py                Web 入口
├── config.py / config.json    配置系统（dataclass + JSON + 环境变量）
├── requirements.txt           依赖锁定（5 个包）
├── personality.json           人格定义 + 情绪状态
├── CLAUDE.md                  AI 协作规则
├── data/                      SQLite 数据库（WAL 模式）
├── logs/                      运行日志（YYYY-MM-DD.log，含 API/情绪/睡眠/工具追踪）
├── changes/                   修改记录（按日期，20+ 条）
├── doc/                       文档
│   ├── architecture.md        架构总览 + 使用指南
│   ├── technical.md           技术细节（全模块）
│   ├── message-flow.md        消息流转流程
│   └── milestones-and-issues.md 里程碑 + 90 issue
│
├── tests/                     单元测试（33 用例）
│   ├── mocks.py                Mock 工厂
│   ├── test_context_manager.py 上下文管理测试（12 用例）
│   ├── test_sleep_manager.py   睡眠系统测试（6 用例）
│   ├── test_cli_controller.py  CLI 状态机测试（8 用例）
│   └── test_message_handler.py 消息处理测试（7 用例）
│
├── core/                      核心引擎（7 模块，两阶段架构）
│   ├── tool_agent.py           Phase 1 ToolAgent：纯工具调用（7 外部工具，temp=0.3）
│   ├── agent.py                核心引擎（223 行）：Phase 2 Roleplay Agent + ReAct 循环
│   ├── context_manager.py     上下文窗口管理：token 估算 + 压缩 + 摘要
│   ├── sleep_manager.py       睡眠系统：窗口判断 + 梦境生成 + 状态持久化
│   ├── proactivity.py         主动行为：评分 + 话题选择 + 频率限制
│   ├── cli_controller.py      CLI 状态机（run + 7 个 _on_* + _handle_command）
│   ├── message_handler.py     消息入口（process_message/proactive/explore + 公共构建）
│   ├── personality.py          情绪引擎（四层：输入→调制→怨恨→记忆）
│   ├── provider.py             LLM API 客户端（OpenAI 兼容，trust_env=False）
│   ├── logging_setup.py       日志配置（logs/YYYY-MM-DD.log + stderr）
│   └── dispatcher.py           tool_call XML 解析 + 执行 + 别名归一化
│
├── memory/                    记忆系统
│   ├── short_term.py           ConversationBuffer（deque, 线程安全, get_all_reversed）
│   ├── long_term.py            LongTermMemory（SQLite CRUD 封装）
│   ├── retrieval.py            三层检索（评分 + LLM 重排 + 按需回溯）
│   └── consolidation.py        记忆合并（事实/体验/反思）+ 情感分析
│
├── tools/                     工具系统（Phase 1: 7 外部 / Phase 2: 2 内部）
│   ├── traits.py               Tool 基类 + ToolResult + ToolRegistry
│   ├── memory_tools.py         recall + remember
│   ├── file_tools.py           read_file（路径限制 + 大小限制 + 目录列举）
│   ├── search_tools.py         glob（模式匹配）+ grep（正则内容搜索）
│   ├── notify_tool.py          notify（PowerShell toast + 独立线程）
│   ├── web_tools.py            web_search + web_fetch（AnySearch API）
│   └── music_tool.py           music_play（模糊搜索 + 默认播放器）
│
├── storage/                    SQLite（WAL + 版本化 Schema 迁移 + 软删除）
├── prompts/                    提示词模板（破防/怨恨/梦境/工具记录注入）
├── models/                     数据模型（EmotionalState / EmotionEvent / Turn）
├── ui/                         CLI 界面（ConsoleInterface + 打字机效果）
└── web/                        Web 界面
    ├── server.py               FastAPI + WebSocket + proactive_loop（作息/探索/聊天）
    ├── session.py              SessionManager + WebAgent（会话隔离 + 记忆恢复）
    └── static/                 前端（HTML + CSS + JS，暗色主题）
```

---

## CLI 内置命令

| 命令 | 功能 |
|------|------|
| `/exit` | 保存并退出 |
| `/save` | 强制记忆合并 |
| `/mood` | 查看当前心情（含怨恨值） |
| `/status` | 查看关系状态和统计 |
| `/forget` | 清除短期记忆 |
| `/help` | 帮助 |

---

## 情感系统架构

```
Layer 4: 情绪事件记忆  — 记录"为什么生气"，注入 prompt
Layer 3: 怨恨残留      — anger>0.6 触发，3%/turn 衰减
Layer 2: 交叉调制+分速衰减 — 情绪互相制约，各维度独立衰减率
Layer 1: 多维输入      — sentiment + 反驳链 + 回复速度趋势
    ↓
EmotionalState (VAD + 8 Plutchik + resentment + emotion_events → dominant_emotion)
```

## 自主行为流程

```
_proactive_loop (15s)
    │
    ├─ 睡眠时间? → 入睡/醒来 → 发消息 + 梦境
    ├─ 睡着? → skip
    ├─ idle < 情绪阈值? → skip
    ├─ proactivity score 命中?
    │   ├─ 40% 探索 (max 1/hr) → 自由工具 → 有趣才分享
    │   └─ 60% 聊天 (max 2/hr) → 主动搭话
    └─ 未命中 → 等 15s
```

## 相关链接

- [里程碑与 Issue](doc/milestones-and-issues.md) — 90 issue，7 个里程碑（v0.1~v2.0）
- [技术文档](doc/technical.md) — 完整技术细节
- [消息流转](doc/message-flow.md) — CLI/Web/自主行为三路径详解
- [架构文档](doc/architecture.md) — 快速开始与架构总览

## License

MIT
