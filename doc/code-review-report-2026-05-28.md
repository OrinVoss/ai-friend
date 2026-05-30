# AI Friend 项目 — 全量代码审查报告

---
**2026-05-30 更新**: 
- #30 拆分 Agent God Class 已完成：784→223行，拆为 6 功能类聚模块 + 33 单元测试
- sleep 文件持久化已实现
- 日志系统 (#102) 已完成：logs/YYYY-MM-DD.log
- 文件工具已增强：目录列举、白名单统一、glob/grep 工具
---

**审查日期**：2026-05-28
**项目路径**：D:\桌面\编程作品\AI朋友
**审查范围**：28 个源文件，约 2000+ 行 Python/JS/HTML/CSS 代码
**Git 分支**：main（最新 commit: c1786d1）
**总体评分**：35/100（等级：D）

---

## 1. 执行摘要

### 项目概览

AI Friend 是一个基于 DeepSeek API 的 AI 伴侣应用，具有人格系统、情感模型、三层记忆系统和 CLI/Web 双端界面。核心架构采用 ReAct Agent 模式（tool_call 机制），支持主动发起对话、上下文压缩、记忆合并等能力。

### 总体评分：35/100（D）

项目在架构设计上有清晰意图（三层记忆检索、VAD 情感模型、ToolRegistry），但在工程实践层面存在多个严重影响生产可用性的问题：API Key 明文硬编码、会话隔离完全缺失、代码重复率高、测试覆盖率为零、情感值饱和丧失有效性。

### 最关键发现 Top 5

1. **API Key 明文硬编码（严重安全风险）**：`config.json:3` 包含真实有效的 DeepSeek API Key `sk-28f0fc689ae6453180bdd564dbdd962a`，若代码库泄露将直接产生经济损失。当前该文件尚未被 git 追踪，但风险极高。

2. **会话隔离完全缺失（架构缺陷）**：`conversation_turns` 表无 `session_id` 列（`storage/database.py:86-93`），所有 Web 用户共享同一份对话历史。`SessionManager` 创建的所有 `WebAgent` 操作同一个 `Repository` 实例。

3. **main.py 与 web/session.py 初始化逻辑 80% 重复**：两个文件独立完成 10+ 组件的完整组装链（Database → Repository → LongTermMemory → KimiProvider → MemoryRetriever → ...），没有任何共用工厂函数。

4. **情感值饱和（功能失效）**：`personality.json` 中 `valence: 0.98`、`arousal: 0.98`、`joy/trust/anticipation: 0.975` 全部接近上限，情感系统已丧失区分度，`dominant_emotion` 被锁定在 `"joyful"`。

5. **测试覆盖率为零（工程风险）**：全项目无一个单元测试。`test_manual.py` 和 `test_simulate.py` 依赖真实 DeepSeek API 调用，无法在 CI 中运行。

### 各维度评分表

| 维度 | 评分 | 等级 | 说明 |
|------|------|------|------|
| 代码质量 | 40/100 | C | God Class、双代码路径、重复初始化、多处逻辑缺陷 |
| 安全 | 30/100 | D | API Key 明文、无 session 隔离、无 CORS/CSP、无输入验证 |
| 架构 | 35/100 | D | 缺抽象层、会话串扰、Web 绕过状态机、无工厂模式 |
| UI/UX | 40/100 | C | Segment 独立气泡、硬编码角色名、CJK 换行问题、无障碍缺失 |
| 测试 | 5/100 | F | 零单元测试、零断言、两个测试文件都依赖真实 API |
| 文档 | 50/100 | C | 架构文档较完整但有小过期、缺少 Web 端文档 |
| 性能 | 45/100 | C | 每消息 3-6 次 LLM 调用、O(n²)插入、SQLite 单连接瓶颈 |
| **总体健康** | **35/100** | **D** | 可作为 MVP 原型，但需 P0 级安全和会话修复才能投入使用 |

---

## 2. 安全审计

### 2.1 API Key 硬编码（严重）

| 发现 | 位置 | 风险 |
|------|------|------|
| DeepSeek API Key 明文 | `config.json:3` `sk-28f0fc689ae6453180bdd564dbdd962a` | 若提交 git 即永久泄露 \\
| 无环境变量支持 | `config.py:33-44` `load_config()` 仅从 JSON 读取 | 无法安全部署到 CI/CD/容器 \\
| config.json git 历史 | git log 无 config.json 提交记录 | 当前安全，但仍有泄漏风险 |

**根因**：`config.py:33-43` 的 `load_config()` 只从 JSON 文件读取，未检查环境变量。`config.example.json` 提供了占位模板，但实际使用的 `config.json` 为真实密钥。

### 2.2 SQL 注入防护（良好）

`storage/repository.py` 中全部 15+ 个查询方法均使用参数化查询（`?` 占位符），无 SQL 拼接风险。

### 2.3 路径穿越风险（中危）

**文件**：`tools/file_tools.py:55`

```python
resolved = os.path.abspath(filepath)
```

`ReadFileTool.execute()` 未限制文件路径在项目目录内，LLM（或通过 prompt 注入的攻击者）可读取任意系统文件。

### 2.4 Prompt 注入风险（中危）

**文件**：`core/agent.py:114`

```python
user_msg = f"用户输入：{user_input}"
```

用户输入直接拼接到 messages 中，仅通过角色区分。无输入过滤、逃逸或边界检测。攻击者可构造覆盖系统指令的输入。

### 2.5 Web 安全缺失

| 问题 | 位置 | 风险 |
|------|------|------|
| 无 CORS 中间件 | `web/server.py` | 跨域请求无控制 |
| 无速率限制 | `web/server.py:39` `/api/chat` | 可被滥用于 API 代理 |
| WebSocket 无身份认证 | `web/server.py:119` | 任意客户端可连接 |
| 无 CSP 头 | `web/static/index.html` | XSS 防护缺失 |

### 2.6 依赖安全

项目无 `requirements.txt` 或 `pyproject.toml`，依赖通过 `README.md` 的手动 `pip install` 管理，无版本锁定，无法做安全扫描。

---

## 3. 架构分析

### 3.1 God Class 问题—Agent（480 行）

**文件**：`core/agent.py:56-482`

Agent 类在同一模块内承担 10+ 职责：

| 职责 | 方法 | 行数 |
|------|------|------|
| 状态机编排 | `run()`, `_on_*()` | ~120 |
| 对话处理 | `process_message()`, `process_proactive()` | ~40 |
| ReAct 循环 | `_react_loop()` | ~40 |
| 情绪计算 | `_max_tokens_for_emotion()` | ~12 |
| 主动发起计算 | `_calculate_proactivity()`, `_pick_proactive_topic()` | ~50 |
| 命令处理 | `_handle_command()` | ~30 |
| 上下文压缩 | `_compress_context()` | ~25 |
| Token 估算 | `estimate_tokens()`（模块级函数） | ~20 |
| 生命周期 | `_on_shutdown()` | ~10 |

**问题**：`_on_think()`（80 行）和 `_on_act()`（20 行）包含多级嵌套的 UI 渲染逻辑，违反单一职责原则。

### 3.2 双代码路径（严重）

系统有两套并行的对话处理逻辑：

| 路径 | 入口 | 回复生成 | 情感分析 | 上下文压缩 | 合并 |
|------|------|----------|----------|-----------|------|
| **CLI 路径** | `_on_perceive` → `_on_think` → `_on_act` → `_on_reflect` | `_on_think` 内联 | `_on_reflect` 分析用户输入 | 有 `_compress_context` 调用 | `_on_reflect` 每轮加 2 条 |
| **API/Web 路径** | `process_message` → `_react_loop` | `_react_loop` | `_react_loop` 分析 AI 自己回复 | 阈值检查永不触发 | `_react_loop` 每 3 轮加 1 条 |

**关键 Bug**：
- `agent.py:163`：API 路径 `analyze_sentiment(final_text)` 分析的是 AI 自己的回复而非用户输入，**情感系统在 Web 模式基本失效**
- `agent.py:167-172`：API 模式每 3 轮 consolidation 只处理 1 条 turn，**约 67% 对话不进入长期记忆**
- `agent.py:111`：阈值检查 `messages[-5:]` 只取最后 5 条，**`COMPRESS_THRESHOLD` 永远不会被触发**

### 3.3 代码重复—main.py 与 web/session.py 初始化

`web/session.py:24-60`（WebAgent.__init__）与 `main.py:38-97` 几乎完全重复（约 18 处对应点）：

| 组件 | main.py | web/session.py | 差异 |
|------|---------|----------------|------|
| Database | 创建 | 创建（共享） | Web 端单例 |
| MemoryRetriever | 传 `llm_rerank_fn` | **不传** | Web 端缺 LLM 重排序 |
| llm_rerank | 有 closure | 无 | Web 端降级 |
| ConsoleInterface | 创建 | 不创建 | 合理 |

任何新依赖（如 Embedding 模型、异步数据库驱动）需同时在两处修改。

### 3.4 会话隔离缺失

**文件**：`web/session.py:89-114`

```python
class SessionManager:
    def __init__(self, config: Config):
        self.db = Database(config.db_path)      # 所有 session 共享
        self.repo = Repository(self.db)          # 所有 session 共享
```

`SessionManager` 为所有 session 共享同一个 `Database` + `Repository` 实例。`conversation_turns` 表无 `session_id` 列，无法区分不同用户的对话。

### 3.5 缺少抽象层

- **Provider 无 ABC**（`core/provider.py:11`）：`KimiProvider` 是具体实现，无 `BaseProvider` 接口，无法替换模型或 mock 测试。
- **无工厂模式**：Agent 的依赖组装链无处工厂化，导致 main.py 和 web/session.py 各写一遍。
- **无 DI 容器**：组件间依赖通过构造函数手动注入，耦合度高。

### 3.6 设计模式使用良好之处

- **ToolRegistry**（`tools/traits.py:50-74`）：干净的注册-查找模式，便于扩展新工具。
- **三层记忆检索**（`memory/retrieval.py`）：Hot Memory → Query-guided（评分 + LLM rerank）→ On-Demand，层次清晰。
- **VAD 情感模型**（`models/personality.py:12-142`）：Valence/Arousal 二维空间 + Plutchik 基本情绪 + 分层衰减（Turn-level decay → Hours-level mood shift），设计合理。

---

## 4. 代码质量问题

### 4.1 Agent 双代码路径

已在 3.2 节详细分析。`process_message()` + `_react_loop()` 与 `_on_think()` + `_on_act()` + `_on_reflect()` 两条路径高度相似但代码独立维护。

### 4.2 情感分析每轮调用 2 次

**第一次**：`agent.py:162-165`（`_react_loop` 中）
```python
sentiment, sharing, energy = self.consolidator.analyze_sentiment(final_text or "")
self.personality.apply_emotional_shift(sentiment, sharing, energy)
```

**第二次**：`agent.py:363-368`（`_on_reflect` 中）
```python
sentiment, sharing, energy = self.consolidator.analyze_sentiment(last.content)
self.personality.apply_emotional_shift(sentiment, sharing, energy)
```

每次 `analyze_sentiment()` 触发一次 LLM 调用（`consolidation.py:74-87`），相当于每个用户消息多浪费 1 次 LLM 调用。

### 4.3 Token 估算使用 cl100k_base（GPT-4 Tokenizer）用于 DeepSeek

**文件**：`core/agent.py:25-33`

```python
_TOKENIZER = tiktoken.get_encoding("cl100k_base")  # GPT-4 tokenizer
```

DeepSeek 使用不同的 tokenizer，`cl100k_base` 与实际计数存在偏差，可能导致提前或延迟触发上下文压缩。

### 4.4 上下文压缩仅在部分路径生效

- `process_message()` → `_react_loop()` 路径：`COMPRESS_THRESHOLD` 检查仅阻止追加消息（`agent.py:111`），但从不调用 `_compress_context()`。
- `_on_think()` 路径：调用 `_compress_context()`（`agent.py:275`）。
- 结果：REST API（`/api/chat`）用户走 `process_message()` 路径，不会触发上下文压缩。

### 4.5 情感值饱和

**文件**：`personality.json:28-44`

```
valence: 0.983, arousal: 0.976
joy: 0.975, trust: 0.975, anticipation: 0.975
dominant_emotion: "joyful"
```

所有核心情感指标接近最大值 1.0，情感系统已丧失动态范围：
- `dominant_emotion` 被锁定在 `"joyful"`（joy=0.975 远超阈值 0.7）
- `_max_tokens_for_emotion()` 始终返回 768（excited/joyful 映射的最高值）
- 情感对回复风格的影响完全失效

**根因**：`decay_rate: 0.05` 过低，长期积累正向 sentiment 无法衰减回 baseline。

### 4.6 特质（Trait）忽略

**文件**：`personality.json:5-9`

```json
"traits": { "playfulness": 0.95, "warmth": 0.85, "humor": 0.9, "empathy": 0.8, "sass": 0.75 }
```

代码中实际使用的特质仅有 `playfulness`、`warmth`、`empathy`、`thoughtfulness`（`personality.py:46-57`）。`humor`（幽默 0.9）和 `sass`（嘴贫 0.75）在 `personality.py` 和 `agent.py` 中无任何对应逻辑——它们只在 system prompt 中 `format_traits()` 显示，不对情感或行为产生任何影响。

### 4.7 配置键不匹配

| 配置项 | config.py 默认值 | config.json 实际值 | 问题 |
|--------|-------------------|---------------------|------|
| `db_path` | `"data/ai_friend.db"` | `"ai_friend.db"` | 不一致，Web 进程可能在不同目录下找不到 DB |
| `max_facts` | 200 | 不存在 | 默认值生效，无显式配置 |
| `max_experiences` | 100 | 不存在 | 同上 |
| `max_reflections` | 50 | 不存在 | 同上 |

---

## 5. 数据层

### 5.1 所有 session 共享 DB，无 session_id 隔离

**文件**：`storage/database.py:86-93`

```sql
CREATE TABLE IF NOT EXISTS conversation_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    turn_number INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    emotional_state TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

无 `session_id` 列。`Repository.insert_turn()`（`repository.py:165-172`）写入时不区分 session。

### 5.2 conversation_turns 表无 session_id 列

同上。所有 Web 用户 + CLI 的对话历史写入同一张表，无法实现用户级数据隔离。

### 5.3 ALTER TABLE 迁移每次启动都执行

**文件**：`storage/database.py:102-108`

```python
for stmt in [...]:
    try:
        c.execute(stmt)
    except Exception:        # bare except 静默吞异常
        self.conn.rollback()
```

- 使用 `bare except` 静默忽略错误
- 每次启动都执行，浪费启动时间
- 无版本化 schema 迁移机制

### 5.4 Reflections 被 DELETE 而非 Archive（数据丢失风险）

**文件**：`storage/repository.py:218-225`

```python
c.execute("""
    DELETE FROM reflections WHERE id IN (
        SELECT id FROM reflections
        ORDER BY significance ASC, created_at ASC
        LIMIT ?
    )
""", (excess,))
```

与 `prune_facts()`（UPDATE `is_active = 0`）和 `prune_experiences()`（UPDATE `is_archived = 1`）不同，`prune_reflections()` 直接执行 `DELETE`——一旦裁剪，数据永久丢失。

### 5.5 Prune 排序方向与预期一致（正确）

`prune_facts`（`repository.py:188`）：`ORDER BY composite_score ASC, recall_count ASC`——删除最低分的，正确。

### 5.6 SQLite 单连接 + threading.Lock 成为并发瓶颈

**文件**：`storage/database.py:9-12`

- `check_same_thread=False` 允许跨线程访问，但 `threading.Lock` 串行化所有操作
- 在 FastAPI 异步环境下阻塞事件循环线程
- 所有 WebAgent 共享同一个锁，无法并发处理用户请求

---

## 6. 内存系统

### 6.1 短期记忆（ConversationBuffer）

**文件**：`memory/short_term.py:10-62`

- **无线程锁**：`add_turn()`、`clear()`、`get_all()` 等方法未加锁。多线程 Web 环境下并发访问 `deque` 可能导致数据竞争。
- **`format_for_prompt` 方向问题**（line 37-48）：从最早对话开始遍历，`max_chars` 截断后丢失**最新**对话，而非最早对话。
- `_next_id` 自增非原子操作。

### 6.2 长期记忆（LongTermMemory）

**文件**：`memory/long_term.py:8-66`

- `build_context()` 直接读 Repository，所有 session 共享数据。
- `get_all_active_facts()` / `search_facts()` 等无 session 过滤。

### 6.3 记忆检索（MemoryRetriever）

**文件**：`memory/retrieval.py`

- **`_score_facts()` 修改 `composite_score` 原地**（line 135）：
  ```python
  f.composite_score = max(0, score)
  ```
  每次检索覆写内存中 UserFact 对象的字段，多线程并发可能相互覆盖，且不写回数据库。

- **LLM rerank**（line 141-162）：候选 >15 条时触发一次 LLM 调用，合理但 overhead 存在。

### 6.4 记忆合并（MemoryConsolidator）

**文件**：`memory/consolidation.py`

- **`_pending_buffer` 可能导致重复处理**：
  `add_pending()` 在 `_react_loop()`（agent.py:168）和 `_on_reflect()`（agent.py:376-377）中都调用，同一 turn 可能被两次加入。

- **情感分析在多个位置被重复调用**：
  - `_react_loop()`（agent.py:162-165）：分析 assistant response
  - `_on_reflect()`（agent.py:363-368）：分析 user turn
  - `_update_relationship()`（consolidation.py:225-227）：分析 user turn
  每次调 `analyze_sentiment()` 触发一次 LLM API 调用。

---

## 7. LLM 集成

### 7.1 Provider 无抽象接口

**文件**：`core/provider.py:11-109`

- `KimiProvider` 直接实现所有逻辑，无 `BaseProvider` ABC
- 无法替换为其他模型 API
- 无法在测试中 mock

### 7.2 重试逻辑（3 次指数退避），但 180s 硬编码超时

**文件**：`core/provider.py:49-80`

```python
for attempt in range(3):
    # 指数退避 2s/4s/8s
    return self._do_request(...)
```
```python
timeout=180  # 无配置化入口
```

- 指数退避合理
- 180 秒超时硬编码，网络差时用户等待过长
- 无断路器模式

### 7.3 每用户消息产生 3-6 次 LLM 调用

典型消息处理链路：

| 序号 | 调用位置 | 用途 | 触发 |
|------|----------|------|------|
| 1 | `_react_loop` 第 1 轮 | 主回复生成（streaming） | 总是 |
| 2-N | `_react_loop` 第 2-N 轮 | 工具调用续生成 | 有 tool_call 时 |
| N+1 | `consolidator.analyze_sentiment` | 情感分析（_react_loop 尾部） | 总是 |
| N+2 | `consolidator.analyze_sentiment` | 情感分析（_on_reflect 中） | 总是 |
| N+3 | `consolidator._extract_facts` | 事实抽取 | 触发合并时 |
| N+4 | `consolidator._summarize_experience` | 体验总结 | 触发合并时 |
| N+5 | `consolidator._generate_reflection` | 反思生成 | 触发合并时 |

### 7.4 系统提示词含大量示例对话（~600 tokens）

**文件**：`prompts/system.py:49-70`

8 组对话示例（约 600 tokens）浪费上下文窗口，且在人格改变后需手动更新。示例的幽默损友风格已硬编码在 prompt 中，无法通过 `personality.json` 配置。

### 7.5 Prompt 注入保护仅靠"用户输入："前缀

**文件**：`agent.py:114`

```python
user_msg = f"用户输入：{user_input}"
```

无转义、过滤或边界检测，攻击者可构造覆盖系统指令的输入。

---

## 8. Web 层

### 8.1 WebAgent 与 main.py 初始化严重重复

已在 3.3 节详细分析。

### 8.2 每个消息写 personality.json 到磁盘

**文件**：`web/session.py:69-70`

```python
def process_message(self, user_input: str) -> str:
    result = self.agent.process_message(...)
    self.personality.save(self.config.personality_file)  # 每次消息都写磁盘
    return result
```

每次用户消息触发一次 JSON 序列化 + 文件写入，高并发下磁盘 I/O 成为瓶颈。

### 8.3 Session 内存泄漏（严重）

**文件**：`web/session.py:93`

```python
self._sessions: dict[str, WebAgent] = {}
```

- `_sessions` 字典永不清理（除 `cleanup_old()` 手动调用外）
- WebSocket 断开时调用 `remove()`（server.py:168），但 REST API 创建的 session 永不释放
- 每个 WebAgent 持有完整 ConversationBuffer（500 条），长期运行占用大量内存

### 8.4 多个 WebSocket 连接产生多个 proactive_loop

**文件**：`web/server.py:136-138`

```python
if proactive_task:
    proactive_task.cancel()
proactive_task = asyncio.create_task(_proactive_loop(websocket, session_id))
```

同浏览器打开多个标签页会创建多个独立的 WebSocket 连接和 `proactive_loop`，都通过 `get_or_create(session_id)` 获取同一个 `WebAgent` 实例，导致：
- 多个 loop 同时调用 `agent.process_proactive()`
- 多个 stream 向不同 WebSocket 发送同一回复
- 条件竞争修改 `agent.last_activity_time`

### 8.5 私有方法从 Web 层访问

**文件**：`web/server.py:105`

```python
score = agent.agent._calculate_proactivity(idle)  # 访问私有方法
```

破坏封装。

### 8.6 生命周期 shutdown 不清理资源

**文件**：`web/server.py:22-25`

```python
async def lifespan(app: FastAPI):
    yield
    logger.info("Server shutting down...")  # 仅打日志
```

shutdown 时不关闭数据库连接、不保存状态、不取消活跃的 WebSocket 连接和 proactive_loop。

### 8.7 REST API 缺输入验证

**文件**：`web/server.py:39-51`

- 无 Pydantic 模型验证
- 无长度限制、无字符过滤
- `body` 类型标注为 `dict`，FastAPI 不会自动解析

---

## 9. 前端

### 9.1 WebSocket Segments 每个创建新消息气泡（非追加）

**文件**：`web/static/app.js:34-36`

```javascript
case 'segment':
    createMessage('assistant', data.content);  // 每个 segment 创建独立气泡
```

一句回复被切分成多个独立气泡，视觉上像多条消息。应追加到最后一个气泡。

### 9.2 角色名在 HTML/JS 中硬编码

**文件**：
- `web/static/app.js:131`：`avatar.textContent = role === 'user' ? '我' : '星';`
- `web/static/index.html:6`：`<title>小星 - AI 朋友</title>`
- `web/static/index.html:13`：`<h1>小星</h1>`

修改 `personality.json` 中 `name` 后 UI 不自动同步。

### 9.3 无 WebSocket 心跳

**文件**：`web/static/app.js:14-69`

虽然有 `ping`/`pong` 消息类型支持（server.py:156-157），但前端未实现周期性发送 `ping` 的逻辑。

### 9.4 JSON.parse 无 try/catch

**文件**：`web/static/app.js:24`

```javascript
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);  // 无 try/catch
```

服务器发送非 JSON 数据时整个处理中断。

### 9.5 无无障碍支持

- 无 ARIA 标签
- 无角色属性
- 无键盘导航支持（除输入框外）

### 9.6 无 CSP 头

前端未通过 `Content-Security-Policy` 头限制脚本来源。

### 9.7 CJK 终端换行使用 len()（视觉宽度错误）

**文件**：`ui/display.py:54-63`

```python
while len(paragraph) > width:  # len() 按字符数计算
```

中文字符在终端中通常占 2 个英文字符宽度，`len("你好")` 返回 2 但视觉宽度为 4，导致 CJK 文本换行偏早。

### 9.8 CLI 打字速度忽略配置

**文件**：`ui/display.py:7-8`、`ui/cli.py:45`

```python
class DisplayEngine:
    def __init__(self, typing_speed: float = 0.02):
```

`DisplayEngine` 默认 `typing_speed=0.02`，但配置为 `0.005`。`main.py` 初始化 `ConsoleInterface()` 时不传入配置值。

---

## 10. 性能分析

### 10.1 每用户消息 3-6 次 LLM 调用

已在 7.3 节详述。主要浪费在情感分析被调用两次。

### 10.2 线程池耗尽风险

**文件**：`web/server.py:108, 153`

```python
loop = asyncio.get_event_loop()
response = await loop.run_in_executor(None, agent.process_proactive)
```

使用默认线程池（通常 max_workers=min(32, os.cpu_count()+4)）。大量并发 WebSocket 连接时可能耗尽线程池。

### 10.3 SQLite 单连接瓶颈

所有 session 共享一个 SQLite 连接 + `threading.Lock`。在 FastAPI 异步架构下，多个请求串行等待锁。

### 10.4 情感分析每轮跑 2 次（浪费）

每用户消息两次 `analyze_sentiment()` LLM 调用，浪费 300-500 tokens/次。每日 1000 条消息额外消耗 600K-1M tokens。

### 10.5 系统提示词含大量示例（~600 tokens）

prompts/system.py:49-70 的对话示例每次请求多消耗约 600 tokens。

---

## 11. 测试与文档

### 11.1 无单元测试

全项目无一个 `unittest`、`pytest` 或任何形式的单元测试。关键模块（`core/agent.py` 状态机、`core/personality.py` 情感计算、`memory/retrieval.py` 评分公式、`core/dispatcher.py` tool_call 解析、`storage/repository.py` SQL 查询）均无可自动化执行的测试。

### 11.2 test_manual.py 和 test_simulate.py 依赖真实 API 调用

- 依赖真实 DeepSeek API 调用，无网络则无法运行
- `test_manual.py` 需要人工交互式对话
- `test_simulate.py` 无断言检查（零 assert）
- 不可在 CI 环境中运行

### 11.3 文档可能过期

- `doc/architecture.md:120`：描述"空闲超过 60 秒后发起对话"，但 `config.json` 中 `proactive_min_idle` 为 `180.0` 秒
- 文档未覆盖 Web 端架构（WebSocket、SessionManager 等）

### 11.4 测试覆盖率接近于 0

| 模块 | 行数 | 测试行数 | 覆盖率 |
|------|------|----------|--------|
| core/ | 750+ | 0 | 0% |
| memory/ | 430+ | 0 | 0% |
| storage/ | 270+ | 0 | 0% |
| web/ | 285+ | 0 | 0% |
| tools/ | 200+ | 0 | 0% |
| **总计** | **~2000+** | **~0** | **~0%** |

---

## 12. 错误处理

### 12.1 bare except 多处

| 位置 | 代码 | 问题 |
|------|------|------|
| `database.py:108` | `except Exception: self.conn.rollback()` | ALTER TABLE 失败静默吞异常 |
| `consolidation.py:85` | `except Exception:` | sentimental 分析失败静默 |
| `consolidation.py:115` | `except Exception:` | fact 抽取失败静默 |
| `consolidation.py:157` | `except Exception:` | 体验总结失败静默 |
| `consolidation.py:213` | `except Exception:` | 反思生成失败静默 |
| `config.py:42` | `except (json.JSONDecodeError, OSError): pass` | 配置损坏无警告 |
| `personality.py:90` | `except (json.JSONDecodeError, OSError):` | 人格加载失败静默重置 |

### 12.2 WebSocket 错误处理静默吞异常

**文件**：`web/server.py:160-166`

```python
except Exception as e:
    logger.error(f"WebSocket error: {e}")
    try:
        await websocket.send_text(...)
    except Exception:  # 发送失败时静默
        pass
```

### 12.3 状态机错误时回退到 IDLE 但可能状态不一致

**文件**：`core/agent.py:198-203`

在 `_on_think()` 执行到一半出错时，不清理 `_react_messages`、`_react_iteration` 等状态，可能导致下条消息处理时状态污染。

### 12.4 Config 加载解析错误静默忽略

`config.py:42-43` 捕获 `json.JSONDecodeError` 和 `OSError` 后静默返回全默认配置，用户无任何警告。若 API Key 为空，直到首次 API 调用才崩溃。

---

## 13. 优先级行动方案

### P0（今天必须修）

| # | 问题 | 修复方案 | 涉及文件 | 估时 |
|---|------|----------|----------|------|
| 1 | **API Key 硬编码** | 改用环境变量 `DEEPSEEK_API_KEY`，config.json 清空 key 字段 | `config.json`、`config.py` | 30min |
| 2 | **Session 无隔离** | `conversation_turns` 表加 `session_id` 列，Repository 按 session_id 过滤 | `database.py`、`repository.py`、`session.py` | 2h |
| 3 | **Session 内存泄漏** | WS 断开时调 `remove()`，REST session 加 LRU 驱逐或 TTL | `server.py`、`session.py` | 1h |
| 4 | **多 proactive_loop** | SessionManager 维护每个 session 的 proactive 引用，新连接复用 | `server.py`、`session.py` | 1h |
| 5 | **统一 db_path** | config.json 改 `"data/ai_friend.db"`，与 config.py 默认值一致 | `config.json` | 5min |

### P1（本周）

| # | 问题 | 修复方案 | 估时 |
|---|------|----------|------|
| 6 | **抽取依赖工厂** | `core/factory.py` 消除 main.py/web/session.py 的 80% 重复 | 1h |
| 7 | **统一情感更新路径** | 移除 `_react_loop()` 中的 `analyze_sentiment()`，仅保留 `_on_reflect()` 中的 | 30min |
| 8 | **前端 WebSocket 心跳** | app.js 加 30s 定时间隔发送 `ping` | 15min |
| 9 | **前端 JSON.parse try/catch** | app.js onmessage 增加异常处理 | 15min |
| 10 | **Web 端添加 CORS 中间件** | FastAPI 添加 `CORSMiddleware` | 15min |

### P2（下月）

| # | 问题 | 修复方案 | 估时 |
|---|------|----------|------|
| 11 | **拆分 Agent God Class** | 抽 MessagePipeline / ProactivityEngine / ContextManager | 4h |
| 12 | **添加 Provider ABC** | 定义 `BaseProvider` 抽象基类 | 1h |
| 13 | **添加单元测试** | pytest + mock，覆盖 dispatcher/personality/retrieval/repository | 8h |
| 14 | **CSS 自定义属性** | 颜色值集中为 CSS 变量 | 1h |
| 15 | **CJK 终端宽度修复** | 使用 `wcwidth` 库或自定义宽度计算函数 | 30min |

---

## 14. 评分总结

| 维度 | 评分 | 等级 | 主要扣分项 |
|------|------|------|-----------|
| 代码质量 | 40/100 | C | God Class、双代码路径、多处重复、逻辑缺陷 |
| 安全 | 30/100 | D | API Key 明文、无 session 隔离、无 CORS/CSP |
| 架构 | 35/100 | D | 缺抽象层、会话串扰、Web 绕过状态机、无工厂 |
| UI/UX | 40/100 | C | Segment 独立气泡、硬编码角色名、CJK 换行问题 |
| 测试 | 5/100 | F | 零单元测试、零断言、依赖真实 API |
| 文档 | 50/100 | C | 较详细但有小过期、缺 Web 端文档 |
| 性能 | 45/100 | C | O(n²)插入、LLM 调用未合并、SQLite 单连接 |
| **总体健康** | **35/100** | **D** | — |

---

## 附录：全部源代码文件审查清单

共计审查 28 个源文件：

- `main.py`（108 行）、`web_main.py`（42 行）、`config.py`（49 行）、`config.json`、`personality.json`
- `core/agent.py`（482 行）、`core/personality.py`（109 行）、`core/provider.py`（110 行）、`core/dispatcher.py`（155 行）
- `models/personality.py`（179 行）、`models/conversation.py`（25 行）、`models/memory.py`（45 行）
- `memory/short_term.py`（63 行）、`memory/long_term.py`（67 行）、`memory/retrieval.py`（174 行）、`memory/consolidation.py`（252 行）
- `storage/database.py`（113 行）、`storage/repository.py`（258 行）
- `tools/traits.py`（75 行）、`tools/memory_tools.py`（121 行）、`tools/file_tools.py`（88 行）、`tools/notify_tool.py`（69 行）
- `prompts/system.py`（190 行）、`prompts/templates.py`（99 行）
- `ui/cli.py`（72 行）、`ui/display.py`（64 行）
- `web/server.py`（170 行）、`web/session.py`（115 行）
- `web/static/index.html`（37 行）、`web/static/app.js`（212 行）、`web/static/style.css`（221 行）
- `test_manual.py`（176 行）、`test_simulate.py`（203 行）

---

*本报告由 5 轮全量代码审查结果综合编译而成。审查基于 2026-05-28 的代码库状态。*
