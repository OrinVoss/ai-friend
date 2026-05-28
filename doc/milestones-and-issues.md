# 里程碑与 Issue 规划

## Milestone 1: 架构与工程化 — 从"能跑"到"健壮"

### Issue 1.1: 异步数据库驱动
- **描述**：当前 `Database` 类使用 `threading.Lock` + `sqlite3`，在 FastAPI 异步环境下会阻塞事件循环。
- **方案**：替换为 `aiosqlite`，实现真正的异步数据库操作。
- **涉及文件**：`storage/database.py`, `storage/repository.py`, `web/session.py`

### Issue 1.2: 工具调用解析优化
- **描述**：`dispatcher.py` 用正则在自由文本中提取 `<tool_call>`，LLM 输出格式不稳定时易失败。
- **方案**：改用 JSON Schema 约束 + 结构化输出（如 OpenAI Function Calling），让模型直接输出结构化 JSON。
- **涉及文件**：`core/dispatcher.py`, `core/provider.py`

### Issue 1.3: 配置管理增强
- **描述**：配置全部挤在 `config.json`，不支持环境变量覆盖，敏感信息（API_KEY）在容器化部署时不便。
- **方案**：支持 `os.environ` 环境变量覆盖配置项（如 `DEEPSEEK_API_KEY`），优先级：环境变量 > config.json > 默认值。
- **涉及文件**：`config.py`

---

## Milestone 2: 记忆与认知 — 从"存储"到"理解"

### Issue 2.1: 向量检索
- **描述**：当前检索基于关键词命中 + 重要性评分，对"我上次说的那个有点辣的菜"这类模糊查询完全失效。
- **方案**：引入 Embedding 模型，对 facts/experiences 生成向量，语义检索。
- **涉及文件**：`memory/retrieval.py`, `memory/long_term.py`, `storage/repository.py`

### Issue 2.2: 分层次反思机制
- **描述**：每轮合并都生成反思，产生大量浅层、重复的感悟。
- **方案**：低层反思总结事实，高层反思在积累足够经验后触发，形成更深度的认知。
- **涉及文件**：`memory/consolidation.py`, `prompts/templates.py`

### Issue 2.3: 虚假记忆修正机制
- **描述**：用户说"不对，我不喜欢吃鱼"时，系统只新增事实，不降低矛盾事实的置信度。
- **方案**：事实合并时检测矛盾，降低旧置信度或标记为已修正。
- **涉及文件**：`memory/consolidation.py`, `storage/repository.py`

---

## Milestone 3: 情感与人格 — 从"模拟"到"涌现"

### Issue 3.1: 情绪模型增强
- **描述**：情绪更新过度依赖最后一条输入的 sentiment，真实情感是对话动态博弈的结果。持续反驳应升高 arousal 而非单纯由内容正负决定。
- **方案**：引入对话节奏检测（反驳/附和/转换话题），多轮累积情感影响。
- **涉及文件**：`core/personality.py`, `models/personality.py`

### Issue 3.2: 人格特质深度化
- **描述**：当前特质只是参数调整（playfulness > 0.6 让 arousal 衰减更慢），未真正影响认知环节。
- **方案**：特质影响记忆编码（开放性→新奇话题权重高）、检索（神经质→易想起负面体验）、回应规划（宜人性→多一层委婉思考）。
- **涉及文件**：`core/personality.py`, `memory/retrieval.py`, `memory/consolidation.py`

---

## Milestone 4: 主动性与规划 — 从"被动反应"到"具有内部驱动力"

### Issue 4.1: 主动性机制升级
- **描述**：`_calculate_proactivity()` 基于空闲时间 + 随机命中，缺乏内在驱动力。
- **方案**：主动性基于三个维度：
  - 未完成话题（上次聊到一半）
  - 长期目标（用户设定的提醒或AI生成的健康目标）
  - 情感联结需求（intimacy 高但久未联系时主动问候）
- **涉及文件**：`core/agent.py`, `memory/long_term.py`
