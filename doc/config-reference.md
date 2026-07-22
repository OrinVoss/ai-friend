# 配置参考

> 项目所有配置项的完整说明，包括 `config.json` 和 `personalities/{role_id}.json`。

---

## config.json

配置文件位于项目根目录，支持 JSON 格式。所有字段均有默认值，可选配置。

### LLM API

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `api_endpoint` | string | `"https://api.deepseek.com"` | LLM API 基础地址 |
| `api_key` | string | `""` | API Key，建议用环境变量 `DEEPSEEK_API_KEY` |
| `api_model` | string | `"deepseek-v4-flash"` | 模型名称 |
| `api_timeout` | int | `180` | API 请求超时（秒） |
| `max_tokens` | int | `512` | 每次回复最大 token 数基准值（按主导情绪动态调整，默认 128~512） |
| `temperature` | float | `0.8` | 回复随机性（Agent 3 Roleplay 使用） |
| `thinking` | string | `"disabled"` | 是否启用思维链，"enabled"/"disabled" |
| `reasoning_effort` | string | `""` | 推理努力程度（值取决于模型支持） |

### Web 服务

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `web_host` | string | `"0.0.0.0"` | 监听地址 |
| `web_port` | int | `8000` | 监听端口 |
| `web_access_token` | string | `""` | Web 访问 token：空=不启用；启用后 `/api/*` 需 `Authorization: Bearer <token>` 或 `?token=`，WS init 需带 token。非 loopback 绑定且未设置时启动打印醒目告警 |
| `allowed_origins` | array | `[]` | 额外允许的 CORS 来源（默认已包含 localhost） |

### 记忆系统

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `short_term_capacity` | int | `500` | 短期记忆最大轮数 |
| `consolidation_interval` | int | `5` | 每 N 轮触发记忆合并 |
| `consolidation_unified_call` | bool | `true` | #164 记忆固化统一调用：常规 L1 批次把事实提取+体验总结+L1 insight 合并为 1 次 LLM 调用；`false` 回退旧三次调用路径 |
| `max_facts` | int | `200` | 最大活跃用户事实数，超量修剪 |
| `max_experiences` | int | `100` | 最大共享体验数，超量修剪 |
| `max_reflections` | int | `50` | 最大反思数，超量修剪 |
| `db_path` | string | `"data/ai_friend.db"` | SQLite 数据库路径 |
| `use_memory_agent` | bool | `false` | Memory Agent 灰度开关：开启后 Agent 1 用 `memory_agent.answer()` 替代旧检索（带置信度/证据链的记忆摘要），失败自动回退旧路径 |
| `memory_agent_relevance_floor` | float | `0.35` | Memory Agent 相关性下限：可测量证据 cosine 相似度低于此值时丢弃；recall/summarize 意图豁免 |
| `memory_agent_relevance_full` | float | `0.75` | Memory Agent 置信度满分红线：最终置信度乘以 `min(top_sim/此值, 1.0)` |
| `memory_agent_coreference_threshold` | float | `0.78` | 指代改写触发阈值：query 与指代锚点的最大余弦达到此值才调用 LLM 改写（R2，原 0.65 太松导致空转） |
| `proactive_think_loop` | bool | `true` | 主动沉思循环开关：开启后主动路径走「想起 → 查证 → 决定」有界循环（默认 2 轮）；关闭退回单次决策 |
| `proactive_think_max_rounds` | int | `2` | 沉思循环轮数硬上限 |
| `inner_drive_care_list_size` | int | `20` | 挂念清单容量，超量按「先非活跃、再低 priority、最后旧活跃」淘汰 |
| `inner_drive_surface_top_k` | int | `8` | 内驱状态二期：独处时每轮沉思浮现的挂念条数 |
| `inner_drive_surface_response_k` | int | `3` | 内驱状态二期：对话时按语义相关浮现的挂念条数 |
| `inner_drive_decay_rate` | float | `0.9` | 内驱状态二期：浮现未行动的 priority 衰减率，低于 0.2 自动归档 |
| `inner_drive_care_similarity_threshold` | float | `0.7` | 内驱状态二期：语义浮现与对照解决的相似度阈值 |
| `db_backup_enabled` | bool | `true` | 数据库自动备份：检测到 schema 迁移将执行时，先 `VACUUM INTO` 快照到 `data/backups/` |
| `db_backup_keep` | int | `5` | 备份滚动保留份数，超出时按最旧优先删除 |

### 主动行为

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `proactive_min_idle` | float | `180.0` | 主动触发最小空闲秒数 |
| `proactive_max_interval` | float | `600.0` | 最大主动间隔秒数 |

### 本地嵌入引擎

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `embedding_endpoint` | string | `"http://localhost:8080/v1/embeddings"` | llama-server API 地址 |
| `embedding_dim` | int | `1024` | 嵌入向量维度 |
| `embedding_cache_size` | int | `1000` | 嵌入 LRU 缓存容量 |

### 杂项

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `personality_file` | string | `"personalities/default.json"` | 默认人格模板路径；新建角色时会复制此文件 |
| `typing_speed` | float | `0.005` | CLI 打字机效果速度（秒/字符） |
| `log_level` | string | `"INFO"` | 日志级别：DEBUG/INFO/WARNING/ERROR |
| `max_tool_iterations` | int | `5` | ReAct 循环最大工具调用轮次 |
| `agent2_total_timeout_seconds` | int | `120` | Agent 2 工具循环全局超时（秒），超期后降级为 Agent 3 直接回复（L4-2） |
| `monitor_enabled` | bool | `true` | LLM 调用监控开关（Web `/monitor` 页），生产环境建议关闭以避免记录 prompt |
| `allowed_read_paths` | array | `[".", "~/Documents", "~/Downloads"]` | 文件读取工具白名单目录 |
| `conversation_examples` | array | 5 组默认示例 | 系统提示词中的对话风格示例 |
| `prompt_cache_ttl_seconds` | int | `60` | 慢变提示词块（关系、长期记忆）缓存 TTL（秒），`0` 表示立即过期 |
| `conversation_examples_max_turns` | int | `3` | 系统提示中对话示例仅在会话前 N 轮注入，`0` 表示始终不注入 |
| `degrade_threshold` | int | `3` | 连续工具失败 N 次后降级（#255） |
| `max_fake_actions` | int | `3` | 虚假动作纠正上限（#255） |

`conversation_examples` 每项格式：

```json
{
  "user": "用户说的话",
  "replies": [
    "AI 的第一种回复",
    "AI 的第二种回复（用'或者：'前缀渲染）"
  ]
}
```

### 环境变量覆盖

以下环境变量可覆盖 config.json 对应字段：

| 环境变量 | 覆盖字段 | 示例 |
|----------|----------|------|
| `DEEPSEEK_API_KEY` | `api_key` | `set DEEPSEEK_API_KEY=sk-xxx` |
| `DEEPSEEK_API_ENDPOINT` | `api_endpoint` | `set DEEPSEEK_API_ENDPOINT=https://api.deepseek.com` |
| `DEEPSEEK_API_MODEL` | `api_model` | `set DEEPSEEK_API_MODEL=deepseek-v4-flash` |
| `AI_FRIEND_TIMEOUT` | `api_timeout` | `set AI_FRIEND_TIMEOUT=180` |
| `AI_FRIEND_MAX_TOKENS` | `max_tokens` | `set AI_FRIEND_MAX_TOKENS=512` |
| `AI_FRIEND_TEMPERATURE` | `temperature` | `set AI_FRIEND_TEMPERATURE=0.8` |
| `AI_FRIEND_DB_PATH` | `db_path` | `set AI_FRIEND_DB_PATH=D:\data\my_friend.db` |
| `AI_FRIEND_LOG_LEVEL` | `log_level` | `set AI_FRIEND_LOG_LEVEL=DEBUG` |
| `AI_FRIEND_WEB_HOST` | `web_host` | `set AI_FRIEND_WEB_HOST=0.0.0.0` |
| `AI_FRIEND_WEB_ACCESS_TOKEN` | `web_access_token` | `set AI_FRIEND_WEB_ACCESS_TOKEN=your-token` |
| `AI_FRIEND_WEB_PORT` | `web_port` | `set AI_FRIEND_WEB_PORT=8000` |
| `AI_FRIEND_TYPING_SPEED` | `typing_speed` | `set AI_FRIEND_TYPING_SPEED=0.005` |
| `AI_FRIEND_MAX_TOOL_ITERATIONS` | `max_tool_iterations` | `set AI_FRIEND_MAX_TOOL_ITERATIONS=5` |
| `AI_FRIEND_DEGRADE_THRESHOLD` | `degrade_threshold` | `set AI_FRIEND_DEGRADE_THRESHOLD=3` |
| `AI_FRIEND_MAX_FAKE_ACTIONS` | `max_fake_actions` | `set AI_FRIEND_MAX_FAKE_ACTIONS=3` |
| `AI_FRIEND_EMBEDDING_ENDPOINT` | `embedding_endpoint` | `set AI_FRIEND_EMBEDDING_ENDPOINT=http://localhost:8080/v1/embeddings` |
| `AI_FRIEND_EMBEDDING_DIM` | `embedding_dim` | `set AI_FRIEND_EMBEDDING_DIM=1024` |
| `AI_FRIEND_SHORT_TERM_CAPACITY` | `short_term_capacity` | `set AI_FRIEND_SHORT_TERM_CAPACITY=500` |
| `AI_FRIEND_PROMPT_CACHE_TTL` | `prompt_cache_ttl_seconds` | `set AI_FRIEND_PROMPT_CACHE_TTL=60` |
| `AI_FRIEND_CONVERSATION_EXAMPLES_MAX_TURNS` | `conversation_examples_max_turns` | `set AI_FRIEND_CONVERSATION_EXAMPLES_MAX_TURNS=3` |
| `AI_FRIEND_PERSONALITY_FILE` | `personality_file` | `set AI_FRIEND_PERSONALITY_FILE=personalities/default.json` |

优先级：**环境变量 > config.json > 代码默认值**

### 示例文件

```json
{
  "api_endpoint": "https://api.deepseek.com",
  "api_key": "",
  "api_model": "deepseek-v4-flash",
  "api_timeout": 180,
  "max_tokens": 512,
  "temperature": 0.8,
  "web_host": "0.0.0.0",
  "web_port": 8000,
  "short_term_capacity": 500,
  "consolidation_interval": 5,
  "consolidation_unified_call": true,
  "proactive_think_loop": true,
  "max_facts": 200,
  "max_experiences": 100,
  "max_reflections": 50,
  "db_path": "data/ai_friend.db",
  "embedding_endpoint": "http://localhost:8080/v1/embeddings",
  "embedding_dim": 1024,
  "embedding_cache_size": 1000,
  "log_level": "INFO",
  "allowed_origins": [],
  "conversation_examples": [
    { "user": "今天去外滩拍照了", "replies": ["蛙趣！发出来看看", "听起来就很绝"] }
  ],
  "monitor_enabled": true,
  "prompt_cache_ttl_seconds": 60,
  "conversation_examples_max_turns": 3
}
```

---

## personalities/{role_id}.json

人格定义和情绪状态持久化文件，每个角色一份。同时包含**静态人格定义**（可编辑）和**运行时状态**（自动更新，建议不手动改）。

- `personalities/default.json` 是 `config.json` 中 `personality_file` 指向的默认模板。
- 新增角色时，系统会复制该模板到 `personalities/{role_id}.json`。
- 根目录 `personality.json` 已废弃并从 git 移除；正常运行不再读取（数据库一次性迁移仍会读取遗留文件以推断旧角色名）。

### 静态部分 — 人格定义（可编辑）

| 字段 | 类型 | 说明 |
|------|------|------|
| `personality.name` | string | AI 的名字 |
| `personality.traits` | object | 性格特质字典，key=特质名，value=强度 0~1 |
| `personality.speaking_style` | string | 说话风格描述 |
| `personality.backstory` | string | 背景故事 |
| `personality.interests` | array | 兴趣领域列表 |
| `personality.emotional_baseline` | object | 情绪基线 `{valence, arousal}` |
| `personality.emotional_decay_rate` | float | 情绪衰减速度 |
| `personality.first_run_greeting` | string | 首次启动欢迎语 |

### 运行时状态 — 情绪（自动更新，不建议手动编辑）

| 字段 | 说明 |
|------|------|
| `emotional_state.valence` | 效价 -1.0~1.0，积极/消极 |
| `emotional_state.arousal` | 唤醒度 0.0~1.0，兴奋/平静 |
| `emotional_state.baseline_*` | 情绪基线（慢速变化） |
| `emotional_state.mood_*` | 背景心境（小时级变化） |
| `emotional_state.inertia` | 情绪惯性 0~1 |
| `emotional_state.joy/trust/fear/...` | 8 维 Plutchik 基础情绪 0~1 |
| `emotional_state.resentment` | 怨恨值 0~1 |
| `emotional_state.emotion_events` | 最近的强情绪事件记录 |
| `emotional_state.history` | 最近 10 轮情绪标签 |
| `emotional_state.dominant_emotion` | 当前主导情绪标签 |

### 内置特质参考

| 特质 | 效果 |
|------|------|
| `playfulness` | 提高调皮程度，减缓 arousal 衰减 |
| `warmth` | 提高亲和力，增强 trust 增长 |
| `humor` | 减轻 sadness，增加正面倾向 |
| `empathy` | 放大情绪输入（dv × 1.5） |
| `sass` | 减少 anger，轻度负面激发 joy |
| `thoughtfulness` | 增加反思深度 |
| `curiosity` | 增强探索欲 |

### 示例

```json
{
  "personality": {
    "name": "小星",
    "traits": {
      "playfulness": 0.95,
      "warmth": 0.85,
      "humor": 0.9,
      "empathy": 0.8,
      "sass": 0.75
    },
    "speaking_style": "幽默、嘴贫、爱开玩笑，说话带点损但其实是关心。",
    "backstory": "一个嘴欠但心暖的损友。",
    "interests": ["聊天互怼", "吃瓜", "打游戏", "摄影", "音乐"],
    "emotional_baseline": { "valence": 0.4, "arousal": 0.3 },
    "emotional_decay_rate": 0.05,
    "first_run_greeting": "哈哈哈哈终于来了！等你半天了[旺柴]"
  }
}
```
