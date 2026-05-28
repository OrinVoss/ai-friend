# 技术文档

## 目录

1. [整体架构](#1-整体架构)
2. [Agent 循环](#2-agent-循环)
3. [情感系统](#3-情感系统)
4. [记忆系统](#4-记忆系统)
5. [工具系统](#5-工具系统)
6. [提示词工程](#6-提示词工程)
7. [Web 界面](#7-web-界面)
8. [数据模型](#8-数据模型)
9. [存储层](#9-存储层)
10. [配置系统](#10-配置系统)
11. [部署说明](#11-部署说明)

---

## 1. 整体架构

### 模块依赖

```
main.py / web_main.py
    ├── config.py         配置加载
    ├── core/             核心引擎
    │   ├── agent.py      状态机 + ReAct 循环
    │   ├── personality.py 人格 + 情绪动力学
    │   ├── provider.py   LLM API 客户端
    │   └── dispatcher.py tool_call 解析执行
    ├── memory/           记忆系统
    │   ├── short_term.py 对话缓冲
    │   ├── long_term.py  SQLite 封装
    │   ├── retrieval.py  三层检索
    │   └── consolidation.py 记忆合并
    ├── tools/            工具系统
    ├── storage/          SQLite 存储
    ├── prompts/          提示词模板
    ├── models/           数据模型
    ├── ui/               CLI 界面
    └── web/              Web 界面
```

### 双端设计

| | CLI | Web |
|------|-----|-----|
| 驱动 | 状态机循环 while self._running | 事件驱动 process_message() |
| 输入 | 非阻塞 stdin 线程 | WebSocket 协程 |
| 输出 | 打字机效果逐字 | 分段推送 + 情绪间隔 |
| 主动 | IDLE 内轮询 | asyncio.create_task 协程 |

---

## 2. Agent 循环

### 状态机

7 个状态：BOOT → IDLE → PERCEIVE → THINK → ACT → REFLECT → SHUTDOWN

### process_message（Web 模式）

不经过状态机，直接调用核心逻辑：

```python
def process_message(self, user_input, on_token=None):
    self.short_term.add_turn("user", user_input)
    mem_ctx = self.retriever.retrieve_for_query(user_input)
    sys_prompt = build_system_prompt(...)
    messages = [{"role": "system", "content": sys_prompt}, ...]
    return self._react_loop(messages, on_token)
```

### _react_loop（Web + CLI 共用）

支持多轮 ReAct 迭代（最多 5 轮），动态 max_tokens：

```python
def _react_loop(self, messages, on_token=None):
    max_tok = self._max_tokens_for_emotion()
    for _ in range(self._max_tool_iterations):
        resp = self.provider.generate(messages, max_tokens=max_tok if _ == 0 else 128)
        cleaned, calls = parse_tool_calls(resp)
        if not calls:
            return cleaned
        # 执行工具，结果喂回
    # Reflect: 情感更新、记忆合并
```

### 动态 max_tokens

| 情绪 | tokens |
|------|--------|
| excited / joyful | 768 |
| engaged / content / neutral | 512 (base) |
| anxious / afraid | 300 |
| melancholy / sad | 256 |
| frustrated / angry | 256 |

---

## 3. 情感系统

### VAD 模型 + 8 维 Plutchik

| 维度 | 范围 | 说明 |
|------|------|------|
| valence | -1~1 | 积极/消极 |
| arousal | 0~1 | 兴奋/平静 |
| mood_valence | -1~1 | 背景心境（小时级变化） |
| inertia | 0~1 | 情绪惯性，阻尼突变 |
| joy/trust/fear... | 0~1 | 8 维连续维度 |

### 情绪更新

```
每次交互：
  1. estimate_impact(sentiment, sharing, energy)
     → dv, da, primary_deltas（受特质调制）
  2. shift(dv, da, deltas)
     → 带 inertia 阻尼
  3. decay() → 趋向 baseline（快）→ 趋向 mood（慢）
```

### 特质调制

| 特质 | 效果 |
|------|------|
| empathy > 0.7 | 情感反应 1.5x |
| playfulness > 0.6 | arousal 衰减更慢 |
| warmth > 0.7 | trust 提升更多 |

---

## 4. 记忆系统

### 三层检索

1. **Hot Memory**（常驻 prompt）：Top 5 facts + 最新 experiences + 关系状态
2. **Query-Guided**：评分过滤 → 候选 >15 条时 LLM 重排序
3. **On-Demand**：LLM 主动调 recall 工具回溯

### 记忆合并（Consolidation）

触发条件：每 5 轮 / 情感强度 >0.7 / pending >= 10

```
① LLM 抽取 facts → upsert user_facts
② LLM 总结 experience → insert experiences
③ 生成 reflection → insert reflections
④ 更新关系指标
⑤ 修剪超量记忆（facts≤200, experiences≤100, reflections≤50）
```

### 上下文压缩

模型上下文 180k，80% 阈值（144k）触发。生成摘要注入 system prompt，清空短期 buffer。

---

## 5. 工具系统

```python
class Tool:
    def name(self) -> str
    def description(self) -> str
    def parameters_schema(self) -> dict
    def execute(self, args) -> ToolResult
```

### 内置工具

| 工具 | 功能 |
|------|------|
| recall | 回忆用户信息或共同经历 |
| remember | 记住用户重要信息 |
| read_file | 读取本地文本文件（限 100KB） |
| notify | 发送 Windows 桌面通知 |

### tool_call 协议

```xml
<tool_call>
{"name": "recall", "arguments": {"query": "..."}}
</tool_call>
```

---

## 6. 提示词工程

### System Prompt 结构

7 个区块动态组装：

```
1. 当前时间
2. 身份核心（name / traits / backstory）
3. 情绪状态（dominant_emotion + primary hint）
4. 关系指标（trust / familiarity / intimacy / playfulness）
5. 长期记忆（facts + experiences + reflections）
6. 工具列表 + 调用格式说明
7. 对话示例 + 最近对话 + 指令
```

### 模板

- **事实抽取**：`FACT|category|key|value|confidence|importance`
- **体验总结**：`SUMMARY|TONE|SIGNIFICANCE|IMPORTANCE|TAGS`
- **反思生成**：`TYPE|CONTENT|SIGNIFICANCE|RELATED_EXPERIENCES`

---

## 7. Web 界面

### 技术栈

| 组件 | 技术 |
|------|------|
| 框架 | FastAPI (ASGI) |
| 通信 | WebSocket |
| 前端 | 纯 HTML + CSS + JS |
| 运行 | Uvicorn |

### WebSocket 协议

```
客户端 → 服务端:
  {"type": "init", "session_id": "xxx"}
  {"type": "message", "content": "你好"}
  {"type": "ping"}                              ← 30s 心跳

服务端 → 客户端:
  {"type": "init_ok", "session_id": "xxx", "emotion": "engaged"}
  {"type": "segment", "content": "你好呀！"}    ← 追加到同一气泡
  {"type": "done", "emotion": "engaged", "turn": 5}
  {"type": "error", "content": "..."}
  {"type": "pong"}
```

### 分段推送

```python
def _split_segments(text):
    # 按 。！？ 拆分 → 超过 40 字在 ， 再拆 → 合并碎片

def _calc_delay(emotion, seg_len):
    # base_speed[emotion] × (1 + seg_len/80) × random(0.8, 1.5)
```

| 情绪 | 基础间隔 |
|------|----------|
| excited | 1.8s |
| engaged | 3.0s |
| neutral | 4.0s |
| melancholy | 5.0s |
| sad | 6.0s |

### 主动对话后台

```python
async def _proactive_loop(ws, session_id):
    while True:
        idle = time.time() - agent.last_activity_time
        if idle > proactive_min_idle:
            if random.random() < agent._calculate_proactivity(idle):
                response = agent.process_proactive()
                await send_segments(ws, response)
        await asyncio.sleep(15)
```

WebSocket 断开时自动 cancel。

### 会话管理

```python
class SessionManager:
    _sessions: dict[session_id → WebAgent]
    def get_or_create(session_id) -> WebAgent
```

- 每个 session 独立 Agent 实例
- 共享 SQLite 但无 session_id 隔离（待修复）

---

## 8. 数据模型

### EmotionalState

```python
valence: float       # -1~1
arousal: float       # 0~1
inertia: float       # 0~1 情绪惯性
joy/trust/fear...    # 8 维 0~1
mood_valence/arousal # 背景心境
history: list[str]   # 最近 10 轮
```

### UserFact

```python
category: str        # preference/identity/event/relationship/routine
fact_key: str
fact_value: str
confidence: float    # 0~1
importance: float    # 0~1 长久重要性
composite_score: float
```

---

## 9. 存储层

### SQLite Schema

5 张表：user_facts / experiences / reflections / relationship_metrics / conversation_turns

### 连接管理

```python
class Database:
    def __init__(self, db_path):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        # WAL 模式 + threading.Lock
```

---

## 10. 配置系统

优先级：环境变量（计划中） > config.json > Config dataclass

```json
{
  "api_endpoint": "https://api.deepseek.com",
  "api_model": "deepseek-v4-flash",
  "max_tokens": 512,
  "temperature": 0.8,
  "proactive_min_idle": 180,
  "short_term_capacity": 500,
  "max_facts": 200,
  "max_experiences": 100,
  "max_reflections": 50
}
```

## 11. 部署说明

### 环境

```bash
pip install requests tiktoken plyer fastapi uvicorn
```

### 启动

```bash
# CLI
python main.py

# Web 开发
python web_main.py

# Web 生产
uvicorn web.server:app --host 0.0.0.0 --port 8000 --workers 4
```

### 数据文件

| 文件 | 说明 |
|------|------|
| data/ai_friend.db | SQLite 数据库（gitignore） |
| personality.json | 人格定义 + 情绪持久化 |
| config.json | 用户配置（gitignore） |
