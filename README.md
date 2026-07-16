# AI Friend

具有人格、情绪和长短期记忆的 AI 朋友。基于 OpenAI 兼容 API（默认 DeepSeek / DeepSeekProvider），采用三层 Agent 架构，支持 CLI 和 Web 双端。

核心引擎采用三层 Agent 架构：Agent 1 InnerDrive 自主推理 → Agent 2 ToolAgent 外部工具执行 → Agent 3 Roleplay 人格驱动回复，从根本上解决模型虚构工具调用内容的问题。闲聊场景中 Agent 1 检测无需外部工具，直接跳过 Agent 2，仅需 1 次 LLM 调用。

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

角色文件位于 `personalities/{role_id}.json`：
- 每个角色有独立的 `personality`（名字、性格特质、说话风格、背景故事、兴趣领域）
- 每个角色有独立的 `emotional_state`（情绪状态），由系统自动维护
- `config.json` 中的 `personality_file` 作为新建角色的模板
- 系统默认提供 `personalities/default.json`（Luna），原 `personality.json` 保留为备份

### 记忆系统

```
短期记忆（ConversationBuffer）
    │ deque, 线程安全, 重启从 DB 恢复最近 30 轮
    ▼
长期记忆（SQLite 9 表）
    ├── user_facts          用户事实（评分 + 置信度 + 重要性）
    ├── experiences         共享体验（情感色调 + 重要性，软删除）
    ├── reflections         反思洞察（类型 + 重要性，软删除）
    ├── conversation_turns  完整对话历史
    ├── relationship_metrics 关系指标（按 session_id 隔离）
    ├── relationship_snapshots 关系指标历史快照（按 session_id 隔离）
    ├── session_roles       session_id → role_id 映射
    ├── observations        原始观察（记忆生命周期 Layer 1，双写中）
    └── facts_v2            经验证的事实（confidence/stability/freshness/importance）
```

记忆生命周期（一期，双写阶段）：对话 → **Observation**（原始观察，低置信度）→ 验证/用户确认 → **Fact**（带四维评分的事实）→ Insight（二期规划）。由 `MemoryLifecycleManager` 提供 observe / promote / verify / contradict / decay / gc，配置开关 `use_observation_fact`（默认 false）控制双写。

三层检索：Hot Memory → Query-Guided（语义 0.6 + 关键词 0.4 混合评分 → LLM重排）→ On-Demand（recall 工具）

语义搜索基于本地 Qwen3.5-0.8B-Q6_K.gguf（640MB, GPU CUDA, 1024维向量），通过 llama.cpp server 提供 /v1/embeddings API。嵌入服务器不可用时自动降级为纯关键词检索（日志可见），不影响正常使用。

### 工具系统（9 个，三层分工）

**Agent 1 — InnerDriveAgent（内部工具）**：recall / remember

Perceive → 检索记忆 → 识别知识缺口 → 决策。若无需外部工具，直接跳过 Agent 2（闲聊优化：仅 1 次 LLM 调用）。若需要外部工具，输出自然语言请求给 Agent 2。

**Agent 2 — ToolAgent（7 个外部工具）**：web_fetch / web_search / read_file / glob / grep / music_play / notify

接收 Agent 1 的自然语言请求，通过 JSON mode（response_format）结构化输出工具调用，三层解析（JSON 数组 / XML 正则 / 裸 JSON）。ToolAttemptTracker（每轮 3 次重试，最多 3 轮），失败后回报 Agent 1 重新决策。独立精简 prompt，temperature=0.3，无人格/情绪/记忆。

**Agent 3 — Roleplay Agent（内部工具）**：recall / remember

接收 inner_drive_summary + tool_results，仅内部工具可用。完整人格 + 情绪 + 记忆，temperature=0.8。

| 工具 | 功能 | 参数 | 后端 | Agent |
|------|------|------|------|------|
| `web_fetch` | 提取网页正文（自动去 HTML） | url | AnySearch API | Agent 2 |
| `web_search` | 网络搜索，支持时效过滤 | query, max_results, freshness | AnySearch API | Agent 2 |
| `read_file` | 读取本地文件（≤500KB，行号+行偏移+多文件） | path, limit, offset | 本地 IO | Agent 2 |
| `glob` | glob 模式搜索文件（`**/*.py` 等） | pattern, path | 本地遍历 | Agent 2 |
| `grep` | 正则搜索文件内容（上下文+过滤） | pattern, path, glob, context | 本地搜索 | Agent 2 |
| `music_play` | 播放音乐（模糊搜索） | song | 默认播放器 | Agent 2 |
| `notify` | Windows toast 桌面通知（不阻塞） | title, message, duration | PowerShell WinRT | Agent 2 |
| `recall` | 回忆用户信息或共同经历 | query | SQLite | Agent 1, 3 |
| `remember` | 记住用户重要信息 | category, key, value, importance | SQLite | Agent 1, 3 |

Agent 2 通过 JSON mode 结构化输出（或 XML `<tool_call>` 标签回退）自主调用，结果作为 `<tool_result>` 注入 Agent 3 prompt。每次调用自动记录到 `_tool_call_history`（最多 20 条）。

### 三层响应流程

```
用户输入
    │
    ▼
Agent 1: InnerDriveAgent (core/inner_drive.py)
    │  Perceive → 检索记忆 → 识别缺口 → 决策
    │  内部工具: recall / remember（SQLite）
    │  若闲聊无需工具 → 直接跳过 Agent 2
    │  若需外部工具 → 输出自然语言请求给 Agent 2
    ▼
Agent 2: ToolAgent ──── (闲聊跳过) ────┐
    │  core/tool_agent.py              │
    │  接收自然语言请求                   │
    │  执行外部工具: web_fetch/web_search │
    │  read_file/glob/grep/music/notify   │
    │  ToolAttemptTracker: 3retry×3round  │
    │  失败→回报 Agent 1 重新决策         │
    ▼                                   │
Agent 3: Roleplay Agent (core/agent.py)◄┘
    │  temp=0.8, 完整人格 + 情绪 + 记忆
    │  personalities/{role_id}.json → PersonalityConfig + EmotionalState
    │  analyze_sentiment(user_input) → sentiment 值
    │  estimate_emotional_impact(sentiment) → trait 调制 → shift()
    │  _cross_modulate() → 情绪互相制约
    │  decay() → 分速衰减
    │  build_system_prompt(inner_drive_summary, tool_results) → LLM
    │  可用工具: recall / remember（内部 SQLite 操作）
    ▼
AI 回复 = 人格底色 × 当前情绪 × Agent 1 决策 × Agent 2 工具结果 × 对话上下文
    │
    ▼
Emotion → Memory consolidation → Reflection（后处理，不变）
```

### 人格实现

四层实现：
1. `personalities/{role_id}.json` — 名字、特质、说话风格、背景故事、兴趣
2. `EmotionalState` — VAD + 8 Plutchik + resentment + emotion_events（运行时动态，每个角色/会话独立）
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
| 主题 | - | 浅色主题，响应式 |

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

空闲时 ProactivityManager 评分触发后，由 InnerDrive (Agent 1) LLM 推理决定主动聊天、自由探索还是保持安静——不再是随机分流。探索模式：AI 自主使用工具（上网/听歌/翻文件），发现有趣的才分享给用户，没什么就安静结束。

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
- **会话管理** — 角色与 session 严格一一对应：`session_id = role_id`。一个角色只有一份记忆、一种情绪、一组关系指标、一个睡眠状态，实现角色级持久化。每个 session 只有一个 active proactive 任务，新标签页连接自动取消旧任务并接管，消除多标签页并发竞争
- **环境变量安全** — API Key 支持 `DEEPSEEK_API_KEY` 环境变量，优先级高于 config.json
- **Provider 抽象层** — `LLMProvider(ABC)` 抽象基类，`DeepSeekProvider` 为默认实现，便于切换多模型
- **REST API 类型安全** — 使用 Pydantic 模型校验请求/响应，自动返回 422 错误
- **Web 安全加固** — CORS 来源可配置、基于滑动窗口的速率限制、CSP/X-Frame-Options 安全头
- **对话示例可配置** — `config.json` 的 `conversation_examples` 可自定义系统提示词中的对话风格示例
- **共享 embedding 启动** — CLI/Web 双端统一调用 `core/embedding_server.py`，消除启动代码重复
- **Prompt 分层缓存** — system prompt 拆为静态/慢变/动态块，静态块跨调用复用，减少重复 token 消耗（#160）
- **记忆生命周期（双写中）** — Observation → Fact 显式生命周期，事实带置信度/稳定性/新鲜度/重要性四维评分（`use_observation_fact` 开关）
- **语义检索维度自适应** — 向量按 BLOB 实际维度解码，维度不匹配时日志告警而非静默降级
- **数据库自动备份** — 检测到 schema 迁移将执行时自动 `VACUUM INTO` 快照到 `data/backups/`，滚动保留最近 5 份（`db_backup_enabled` / `db_backup_keep`）

---

## 快速开始

```bash
pip install -r requirements.txt
cp config.example.json config.json
# 编辑 config.json 填入 API Key
# 或用环境变量: export DEEPSEEK_API_KEY=sk-...
# 搜索工具: export ANYSEARCH_API_KEY=as_sk-...
# 语义搜索（可选）: start_embedding_server.bat（需下载 Qwen3.5-0.8B-Q6_K.gguf 约 640MB + llama.cpp）
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
| `embedding_endpoint` | — | `http://localhost:8080/v1/embeddings` | llama.cpp 嵌入服务地址 |
| `embedding_dim` | — | `1024` | 嵌入向量维度（Qwen3.5-0.8B 输出） |
| `embedding_cache_size` | — | `1000` | 嵌入缓存条目数（LRU） |
| `conversation_examples` | — | 5 组默认示例 | 系统提示词中的对话风格示例（可配置） |
| `allowed_origins` | — | `[]` | 除 localhost 外额外允许的 CORS 来源 |

---

## 人格定制

角色文件位于 `personalities/{role_id}.json`。例如 `personalities/小星.json`：

```json
{
  "id": "小星",
  "personality": {
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
}
```

- 新增角色：在 `personalities/` 下新建 `{role_id}.json`（可从 `default.json` 复制修改）。
- 切换角色：Web 端顶部「切换」按钮选择角色；每个角色只有一个 session，直接进入对应记忆。

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
- 文档用 ASCII 图表达架构/流程/状态机；README 与 `doc/architecture.md`、`doc/api.md`、`CLAUDE.md` 同步更新
- 提交前 `python -m py_compile` 检查语法
- API 调用使用 `trust_env=False`
- Provider 必须继承 `LLMProvider(ABC)`，禁止直接依赖具体实现
- Web 层通过 `WebAgent` 公共接口与 Agent 交互，禁止直接访问 `agent._xxx`
- REST API 入参/返回使用 `web/schemas.py` Pydantic 模型
- CSS 颜色统一使用 `web/static/style.css` CSS 变量，禁止硬编码色值

---

## 项目结构

```
ai-friend/
├── main.py                    CLI 入口
├── web_main.py                Web 入口
├── config.py / config.json    配置系统（dataclass + JSON + 环境变量）
├── requirements.txt           依赖锁定（含 aiosqlite 等）
├── personalities/             角色定义目录（每个角色独立 JSON）
│   ├── default.json             默认角色模板（Luna）
│   └── 小星.json                 示例角色
├── personality.json           旧版人格文件（保留为备份）
├── CLAUDE.md                  AI 协作规则
├── data/                      SQLite 数据库（WAL 模式）
├── logs/                      运行日志（YYYY-MM-DD.log，含 API/情绪/睡眠/工具追踪）
├── changes/                   修改记录（按日期，200+ 条）
├── doc/                       文档
│   ├── architecture.md        架构总览 + 使用指南
│   ├── technical.md           技术细节（全模块）
│   ├── message-flow.md        消息流转流程
│   ├── startup-flow.md        启动流程（从 web_main 到聊天就绪）
│   ├── api.md                 WebSocket/REST API 文档
│   ├── config-reference.md    配置参考
│   ├── personality-guide.md   人格定制指南
│   ├── tool-development.md    工具开发指南
│   ├── prompt-reference.md    Prompt 工程参考
│   ├── testing-guide.md       测试指南
│   ├── deployment.md          部署手册
│   ├── known-issues.md        已知问题清单（按优先级）
│   ├── systematic-solution.md 六层系统性解决方案
│   └── refactor/              重构设计与进度（self-system 总装图 + 六层方案 + systems 增强 + progress）
│
├── tests/                     单元测试（422 用例，33 个测试文件）
│   ├── mocks.py                Mock 工厂
│   ├── test_emotional_state.py EmotionalState 测试（41 用例）
│   ├── test_dispatcher.py      工具调度测试（37 用例）
│   ├── test_inner_drive.py     InnerDrive 测试（32 用例）
│   ├── test_fact_checker.py    矛盾检测测试（26 用例）
│   ├── test_retrieval.py       检索评分 + 语义维度回归（22 用例）
│   ├── test_message_handler.py 消息处理测试（21 用例）
│   ├── test_repository.py      Repository 数据访问 + session 隔离（19 用例）
│   ├── test_segmentation.py    分段推送测试（18 用例）
│   ├── test_embeddings.py      嵌入引擎测试（16 用例）
│   ├── test_web_agent.py       WebAgent 主动行为测试（15 用例）
│   ├── test_tool_agent.py      ToolAgent 测试（14 用例）
│   ├── test_v02_issues.py      v0.2 综合测试（14 用例）
│   ├── test_prompt_instructions.py Prompt 指令测试（12 用例）
│   ├── test_personality_core.py 人格核心测试（12 用例）
│   ├── test_context_manager.py 上下文管理测试（12 用例）
│   ├── test_consolidation.py   记忆合并 FactChecker 集成测试（12 用例）
│   ├── test_provider.py        Provider 测试（10 用例）
│   ├── test_notify_tool.py     通知工具测试（9 用例）
│   ├── test_cli_controller.py  CLI 状态机测试（8 用例）
│   ├── test_agent_proactive.py Agent 主动行为测试（8 用例）
│   ├── test_rate_limit.py      限流测试（7 用例）
│   ├── test_memory_lifecycle.py 记忆生命周期（Observation→Fact）测试（7 用例）
│   ├── test_database_backup.py 数据库自动备份测试（6 用例）
│   ├── test_user_facts_unique_migration.py 唯一约束迁移测试（3 用例）
│   ├── test_session_factory.py 统一装配测试（5 用例）
│   ├── test_sleep_manager.py   睡眠系统测试（6 用例）
│   ├── test_session_manager.py 会话管理测试（6 用例）
│   ├── test_memory_tools.py    记忆工具测试（6 用例）
│   ├── test_prompt_cache.py    Prompt 缓存测试（5 用例）
│   ├── test_file_tools.py      文件工具测试（5 用例）
│   ├── test_provider_abc.py    Provider 抽象测试（4 用例）
│   ├── test_music_tool.py      音乐工具测试（4 用例）
│   └── test_conversation_examples.py 对话示例测试（2 用例）
│
├── core/                      核心引擎（17 模块，三层架构）
│   ├── inner_drive.py          Agent 1 InnerDriveAgent：自主推理 + 记忆检索 + 缺口决策
│   ├── tool_agent.py           Agent 2 ToolAgent：外部工具执行 + ToolAttemptTracker
│   ├── agent.py                核心引擎：Agent 3 Roleplay + ReAct 循环
│   ├── message_handler.py     消息入口（process_message/proactive/explore + 公共构建）
│   ├── session_factory.py     CLI/Web 共享会话装配（统一管线 P0，per-session Repository）
│   ├── context_manager.py     上下文窗口管理：token 估算 + 压缩 + 摘要
│   ├── prompt_cache.py        Prompt 分层缓存（静态/慢变/动态块复用，#160）
│   ├── personality.py          情绪引擎（四层：输入→调制→怨恨→记忆）
│   ├── sleep_manager.py       睡眠系统：窗口判断 + 梦境生成 + 状态持久化
│   ├── proactivity.py         主动行为：评分 + 话题选择 + 频率限制
│   ├── cli_controller.py      CLI 状态机（run + 7 个 _on_* + _handle_command）
│   ├── provider.py             LLMProvider(ABC) 抽象基类 + DeepSeekProvider 实现（OpenAI 兼容，trust_env=False）
│   ├── monitor.py             LLM API 调用监控（环形缓冲，开发调试用）
│   ├── embedding_server.py    共享 embedding server 启动（CLI/Web 共用）
│   ├── logging_setup.py       日志配置（logs/YYYY-MM-DD.log + stderr）
│   ├── async_utils.py         异步→同步桥接 run_async()（线程池安全）
│   └── dispatcher.py           tool_call 三层解析（JSON calls 数组 + XML 正则 + 裸 JSON）+ 执行 + 别名归一化
│
├── memory/                    记忆系统
│   ├── short_term.py           ConversationBuffer（deque, 线程安全, get_all_reversed）
│   ├── long_term.py            LongTermMemory（aiosqlite 异步 CRUD + 同步兼容包装）
│   ├── embeddings.py           本地嵌入语义搜索（Qwen3.5-0.8B, llama.cpp, 1024维, LRU cache + 线程锁）
│   ├── lifecycle.py            MemoryLifecycleManager（Observation→Fact 生命周期：observe/promote/verify/contradict/decay/gc）
│   ├── fact_checker.py         矛盾检测 + 置信度衰减 + 用户纠正（语义相似度→衰减→软删除）
│   ├── retrieval.py            三层检索 + 混合评分（语义 0.6 + 关键词 0.4 + 置信度权重 0.15）
│   └── consolidation.py        记忆合并（事实/体验/反思/分层反思L1/L2/L3）+ FactChecker 集成 + 自动嵌入编码 + 双写 Observation/FactV2
│
├── tools/                     工具系统（Agent 1,3: 2 内部 / Agent 2: 7 外部）
│   ├── traits.py               Tool 基类 + to_json_schema() + ToolResult + ToolRegistry
│   ├── memory_tools.py         recall + remember
│   ├── file_tools.py           read_file（路径限制 + 大小限制 + 目录列举）
│   ├── search_tools.py         glob（模式匹配）+ grep（正则内容搜索）
│   ├── notify_tool.py          notify（PowerShell toast + 独立线程）
│   ├── web_tools.py            web_search + web_fetch（AnySearch API）
│   └── music_tool.py           music_play（模糊搜索 + 默认播放器）
│
├── storage/                    SQLite（aiosqlite 异步 + WAL + 版本化 Schema 迁移 + 软删除）
├── prompts/                    提示词模板（inner_drive / 破防/怨恨/梦境/工具记录注入）
├── models/                     数据模型（EmotionalState / EmotionEvent / Turn）
├── ui/                         CLI 界面（ConsoleInterface + 打字机效果）
└── web/                        Web 界面
    ├── server.py               FastAPI + WebSocket + Pydantic 校验 + CORS/速率限制/CSP
    ├── session.py              SessionManager + WebAgent（会话隔离 + Agent 私有接口封装）
    ├── schemas.py              Pydantic 请求/响应模型（ChatRequest / ChatResponse / ...）
    ├── rate_limit.py           内存滑动窗口限流中间件
    └── static/                 前端（HTML + CSS + JS，浅色响应式主题，CSS 变量统一颜色）
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
    ├─ ProactivityManager 评分命中? (Stage 1 轻量预筛选)
    │   └─ InnerDrive Agent 1 决策 (Stage 2 LLM推理)
    │       ├─ 聊天 (max 2/hr) → 主动搭话
    │       ├─ 探索 (max 1/hr) → 自由工具 → 有趣才分享
    │       └─ 沉默 → 不操作（不消耗频率限制）
    └─ 未命中 → 等 15s
```

## 相关链接

- [架构文档](doc/architecture.md) — 快速开始与架构总览
- [启动流程](doc/startup-flow.md) — web_main → 聊天就绪，逐步骤详解
- [API 文档](doc/api.md) — WebSocket + REST API
- [技术文档](doc/technical.md) — 完整技术细节
- [消息流转](doc/message-flow.md) — CLI/Web/自主行为三路径详解
- [配置参考](doc/config-reference.md) — 全部配置项说明
- [人格定制指南](doc/personality-guide.md) — 自定义 AI 人格
- [工具开发指南](doc/tool-development.md) — 添加新工具
- [Prompt 工程参考](doc/prompt-reference.md) — 提示词模板
- [测试指南](doc/testing-guide.md) — 运行和编写测试
- [部署手册](doc/deployment.md) — 生产环境部署
- [已知问题](doc/known-issues.md) — 按优先级排列的问题清单
- [系统性解决方案](doc/systematic-solution.md) — 六层统一解决方案
- [重构设计与进度](doc/refactor/README.md) — self-system 总装图 + 各层方案 + 进度追踪

## License

MIT
