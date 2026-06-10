# 配置参考

> 项目所有配置项的完整说明，包括 `config.json` 和 `personality.json`。

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
| `max_tokens` | int | `512` | 每次回复最大 token 数（按情绪动态调整 256~768） |
| `temperature` | float | `0.8` | 回复随机性（Agent 3 Roleplay 使用） |
| `thinking` | string | `"disabled"` | 是否启用思维链，"enabled"/"disabled" |
| `reasoning_effort` | string | `""` | 推理努力程度（值取决于模型支持） |

### Web 服务

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `web_host` | string | `"0.0.0.0"` | 监听地址 |
| `web_port` | int | `8000` | 监听端口 |

### 记忆系统

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `short_term_capacity` | int | `500` | 短期记忆最大轮数 |
| `consolidation_interval` | int | `5` | 每 N 轮触发记忆合并 |
| `max_facts` | int | `200` | 最大活跃用户事实数，超量修剪 |
| `max_experiences` | int | `100` | 最大共享体验数，超量修剪 |
| `max_reflections` | int | `50` | 最大反思数，超量修剪 |
| `db_path` | string | `"data/ai_friend.db"` | SQLite 数据库路径 |

### 主动行为

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `proactive_min_idle` | float | `180.0` | 主动触发最小空闲秒数 |
| `proactive_max_interval` | float | `600.0` | 最大主动间隔秒数 |

### 本地嵌入引擎

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `embedding_endpoint` | string | `"http://localhost:8080/v1/embeddings"` | llama-server API 地址 |
| `embedding_dim` | int | `512` | 嵌入向量维度 |
| `embedding_cache_size` | int | `1000` | 嵌入 LRU 缓存容量 |

### 杂项

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `personality_file` | string | `"personality.json"` | 人格定义文件路径 |
| `typing_speed` | float | `0.005` | CLI 打字机效果速度（秒/字符） |
| `log_level` | string | `"INFO"` | 日志级别：DEBUG/INFO/WARNING/ERROR |
| `allowed_read_paths` | array | `[".", "D:\\音乐", ...]` | 文件读取工具白名单目录 |

### 环境变量覆盖

以下环境变量可覆盖 config.json 对应字段：

| 环境变量 | 覆盖字段 | 示例 |
|----------|----------|------|
| `DEEPSEEK_API_KEY` | `api_key` | `set DEEPSEEK_API_KEY=sk-xxx` |
| `DEEPSEEK_API_ENDPOINT` | `api_endpoint` | `set DEEPSEEK_API_ENDPOINT=https://api.deepseek.com` |
| `DEEPSEEK_API_MODEL` | `api_model` | `set DEEPSEEK_API_MODEL=deepseek-v4-flash` |
| `AI_FRIEND_DB_PATH` | `db_path` | `set AI_FRIEND_DB_PATH=D:\data\my_friend.db` |
| `AI_FRIEND_LOG_LEVEL` | `log_level` | `set AI_FRIEND_LOG_LEVEL=DEBUG` |

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
  "max_facts": 200,
  "max_experiences": 100,
  "max_reflections": 50,
  "db_path": "data/ai_friend.db",
  "embedding_endpoint": "http://localhost:8080/v1/embeddings",
  "embedding_dim": 512,
  "embedding_cache_size": 1000,
  "log_level": "INFO"
}
```

---

## personality.json

人格定义和情绪状态持久化文件，同时包含**静态人格定义**（可编辑）和**运行时状态**（自动更新，建议不手动改）。

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
