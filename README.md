# AI Friend

具有人格、情绪和长短期记忆的 AI 朋友。基于 DeepSeek API，采用 ReAct Agent 架构，支持 CLI 和 Web 双端。

## 功能

- **四层情感系统** — VAD + 8 Plutchik 维度，交叉调制、分速衰减、怨恨残留、情绪事件记忆
- **破防机制** — 连续负面交互触发三级递进式情感崩溃（轻怼 → 受伤 → 破防）
- **人格系统** — 自定义名字、性格特质、说话风格、背景故事
- **短期记忆** — 最近对话缓冲，动态塞入上下文
- **长期记忆** — LLM 自动抽取事实、总结体验、生成反思，存入 SQLite
- **三层检索** — 评分过滤 → LLM 重排序 → 按需回溯
- **上下文压缩** — 达到 80% 阈值时自动压缩旧对话
- **工具系统** — recall / remember / read_file / notify，LLM 自主调用
- **双端界面** — CLI 控制台 + Web（暗色主题，分段独立气泡 + 情绪调速）
- **主动对话** — 空闲时根据情绪、时间、关系动态计算，探索×1/时、聊天×2/时
- **作息系统** — 午睡(12-13点)/夜睡(23:30-0:30)，醒来分享梦境
- **自主探索** — 空闲时自由上网/听歌/翻文件，有趣的才分享
- **会话管理** — 多标签页独立会话，后台 proactive 协程

## 快速开始

```bash
pip install -r requirements.txt
cp config.example.json config.json
# 编辑 config.json 填入 API Key（或用环境变量 DEEPSEEK_API_KEY）
```

```bash
# CLI 模式
python main.py

# Web 模式
python web_main.py
# → http://localhost:8000
```

## 配置

支持 config.json + 环境变量覆盖（优先级：环境变量 > config.json > 默认值）：

| 字段 | 环境变量 | 默认值 | 说明 |
|------|---------|--------|------|
| `api_key` | `DEEPSEEK_API_KEY` | - | **必填** |
| `api_endpoint` | `DEEPSEEK_API_ENDPOINT` | `https://api.deepseek.com` | |
| `api_model` | `DEEPSEEK_API_MODEL` | `deepseek-v4-flash` | |
| `api_timeout` | - | `180` | API 超时（秒） |
| `max_tokens` | - | `512` | 回复长度上限 |
| `temperature` | - | `0.8` | |
| `proactive_min_idle` | - | `180` | 主动对话最小空闲（秒） |
| `db_path` | `AI_FRIEND_DB_PATH` | `data/ai_friend.db` | |
| `log_level` | `AI_FRIEND_LOG_LEVEL` | `INFO` | |

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
  "speaking_style": "幽默、嘴贫、爱开玩笑…",
  "backstory": "一个嘴欠但心暖的损友…",
  "emotional_baseline": {
    "valence": 0.4,
    "arousal": 0.3
  }
}
```

`emotional_state` 由系统自动维护（情绪、怨恨值、情绪事件记忆），手动修改可强制干预。

## 项目结构

```
├── main.py                  CLI 入口
├── web_main.py              Web 入口
├── start.py                 [计划中] 统一入口
├── config.py / config.json  配置系统
├── requirements.txt         依赖锁定
├── personality.json         人格定义（含情绪状态）
├── data/                    数据库目录
├── changes/                 修改记录（按日期）
├── doc/                     文档
│   ├── architecture.md      架构与使用
│   ├── technical.md         技术细节
│   ├── message-flow.md      消息流转
│   └── milestones-and-issues.md  里程碑与 84 issue
│
├── core/                    核心引擎
│   ├── agent.py             ReAct Agent（状态机 + process_message）
│   ├── personality.py       情绪引擎（四层架构）
│   ├── provider.py          LLM API 客户端
│   └── dispatcher.py        tool_call 解析执行
├── memory/                  记忆系统
│   ├── short_term.py        ConversationBuffer（线程安全）
│   ├── long_term.py         SQLite CRUD
│   ├── retrieval.py         三层检索
│   └── consolidation.py     记忆合并 + 情感分析
├── tools/                   工具系统
├── storage/                 SQLite（WAL 模式 + 版本化 Schema 迁移）
├── prompts/                 提示词（破防/怨恨/情绪事件注入）
├── models/                  数据模型（EmotionalState / EmotionEvent）
├── ui/                      CLI 界面
└── web/                     Web 界面
    ├── server.py            FastAPI + WebSocket
    ├── session.py           SessionManager + WebAgent
    └── static/              前端（HTML + CSS + JS）
```

## 内置命令（CLI）

| 命令 | 功能 |
|------|------|
| `/exit` | 保存并退出 |
| `/save` | 强制记忆合并 |
| `/mood` | 查看当前心情（含怨恨值） |
| `/status` | 查看关系状态和统计 |
| `/forget` | 清除短期记忆 |

## 情感系统架构

```
Layer 4: 情绪事件记忆  — 记得"为什么生气"
Layer 3: 怨恨残留      — anger 触发后 lingering bitterness
Layer 2: 交叉调制+分速衰减 — 情绪互相制约，surprise 3t / trust 25t
Layer 1: 多维输入      — sentiment + 反驳链 + 回复速度
    ↓
EmotionalState (VAD + 8 Plutchik → dominant_emotion)
```

详细文档见 [doc/technical.md](doc/technical.md) §3 情感系统。

## 相关链接

- [里程碑与 Issue](doc/milestones-and-issues.md) — 84 issue，6 个里程碑
- [技术文档](doc/technical.md) — 完整技术细节
- [消息流转](doc/message-flow.md) — CLI/Web 双路径详解
- [架构文档](doc/architecture.md) — 快速开始与架构总览

## License

MIT
