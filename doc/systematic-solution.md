# AI Friend 统一系统解决方案（v0.6/v1.0 架构蓝图）

> 目标：把 `doc/known-issues.md` 中分散的 20+ 个问题收敛到一个统一的、分层的架构改造方案中，而不是继续逐个打补丁。
> 
> 本文件由早期概要草案与详细六层架构蓝图两份草稿合并而成。

---

## 1. 根因分析：为什么问题会反复出现

通读 `known-issues.md` 后，所有问题可以归入 6 个根因：

| 根因 | 典型表现 | 涉及 Issue |
|------|----------|------------|
| **数据边界模糊** | Role/Session/Personality 多对多，睡眠状态、记忆、关系指标隔离键不一致 | #210, sleep 相关 |
| **记忆无生命周期** | Observation 直接当 Fact，Reflection 当成永久结论，没有衰减/合并/删除 | 3.1~3.4, 3.8~3.10, 3.15~3.16 |
| **Prompt 无预算与版本** | 每轮塞入全部内容，静态块重复发送，不同 Agent 共享同一份上下文 | #160, #294 P1/P2/P3, #295 |
| **运行时不是真状态机** | BOOT/IDLE/THINK/ACT 定义了但无效，同步/异步混用，超时和错误恢复不足 | #162, #293, #263, MessageHandler review |
| **工具层职责混乱** | 全局参数别名、Session 不复用、跨层重试叠加、工具实例引用外部状态 | #156, dispatcher 别名, tool registry isolation |
| **缺少可观测性** | source 字段为空、metrics 缺失、CSP/前端 bug 难定位 | monitor 优化, #244, #233 等 |

只要这 6 个根因不解决，修单个 symptom 会不断产生新 bug。本方案一次性重构这 6 个根因对应的层。

---

## 2. 统一架构：六层运行时

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 6: Observability (metrics / tracing / structured log) │
├─────────────────────────────────────────────────────────────┤
│ Layer 5: Provider Abstraction (async multi-provider router) │
├─────────────────────────────────────────────────────────────┤
│ Layer 4: Tool Runtime (isolated registries + retry policy)  │
├─────────────────────────────────────────────────────────────┤
│ Layer 3: Async Agent Runtime (state machine + DI + timeout) │
├─────────────────────────────────────────────────────────────┤
│ Layer 2: Context & Prompt Budget (static/dynamic allocator) │
├─────────────────────────────────────────────────────────────┤
│ Layer 1: Memory Lifecycle (Observation → Fact → Insight)    │
├─────────────────────────────────────────────────────────────┤
│ Layer 0: Identity & State (one role = one session)          │
└─────────────────────────────────────────────────────────────┘
```

核心数据流：

```
Layer 0: RoleSession
    ↓
Layer 1: Memory Lifecycle 输出 Fact/Insight/Relationship
    ↓
Layer 2: Context & Prompt Budget 按需分配 Token
    ↓
Layer 3: Async Agent Runtime 状态机驱动 Agent 1/2/3
    ↓
Layer 4: Tool Runtime 执行/重试/摘要
    ↓
Layer 5: Provider Abstraction 真异步调用 LLM
    ↓
Layer 6: Observability 记录 source/metrics/log
```

---

## 3. 每层设计

### 当前进度总览

| Layer | 主题 | 状态 | 详细文档 |
|-------|------|------|----------|
| Layer 0 | Identity & State | 未开始 | `doc/refactor/layer6-personality/` |
| Layer 1 | Memory Lifecycle | 一期已完成（Observation + Fact 双写） | `doc/refactor/layer1-memory/` |
| Layer 2 | Context & Prompt Budget | 大部分已完成 | `doc/refactor/layer2-prompt/` |
| Layer 3 | Async Agent Runtime | 部分已完成 | `doc/refactor/layer4-agent/` |
| Layer 4 | Tool Runtime | 部分已完成（Prompt 已精简） | `doc/refactor/layer5-tool/` |
| Layer 5 | Provider Abstraction | 未开始 | `doc/refactor/systems/provider.md` |
| Layer 6 | Observability | 部分已完成（监控面板） | `doc/refactor/systems/logging.md` |

### Layer 0: Identity & State —— 一个角色一份完整状态

**核心原则**：`role_id == session_id == memory_namespace == emotion_namespace == sleep_namespace`

```python
@dataclass(frozen=True)
class RoleSession:
    role_id: str
    personality: PersonalityConfig       # 从 personalities/{role_id}.json 加载
    emotional_state: EmotionalState      # 同一文件内的 emotional_state
    memory_namespace: str                # = role_id
    sleep_state: SleepState              # .sleep_state.{role_id}
```

- `SessionManager` 不再允许 `一个角色多个 session`。
- 所有 SQLite 表已经按 `session_id` 隔离，只需保证 `session_id = role_id`。
  - 已知例外（2026-07-16 发现，待修）：`user_facts` 唯一约束 `UNIQUE(category, fact_key)` 不含 `session_id`，跨 session 同 key 会互相覆盖；`update_fact_confidence` / `update_fact_score` / `increment_fact_recall` 仍无 session 校验；`experiences.embedding` 写入后从未读回（经历的语义检索是死路径）。
- `personality.json` 旧文件废弃；`personalities/{role_id}.json` 成为唯一人格+情绪数据源。
- 解决：角色切换混乱、睡眠状态错配、关系指标历史空白、多 session 竞态。

**状态**：未开始。计划与 Layer 6（Personality/Session/记忆绑定）合并实施。

### Layer 1: Memory Lifecycle —— 记忆有出生、验证、衰减、死亡

```
Observation（单次观察）
   ↓ 多次验证 / 矛盾检测
Fact（带 confidence/freshness/stability/importance）
   ↓ 跨事实推理，带证据链
Insight / Reflection（带 hypothesis + confidence + needs_more_evidence）
   ↓ 过期 / 证据失效
Garbage Collection（merge / decay / contradict / obsolete）
```

#### 数据模型改造

```python
@dataclass
class Observation:
    """原始观察，置信度低，可随时写入。"""
    id: str
    content: str
    source_turn: int
    created_at: datetime
    embedding: bytes | None

@dataclass
class Fact:
    """经多次验证或用户确认的事实。"""
    id: str
    category: str
    key: str
    value: str
    confidence: float          # 可信度
    stability: float           # 稳定性
    freshness: float           # 新鲜度
    importance: float          # 重要性
    source_observation_ids: list[str]
    verification_count: int
    last_verified_at: datetime
    status: Literal["active", "decayed", "merged", "obsolete"]

@dataclass
class Insight:
    """基于多个 Fact 的假设，带证据和待验证标记。"""
    id: str
    hypothesis: str
    evidence_fact_ids: list[str]
    confidence: float
    needs_more_evidence: bool
    insight_type: Literal["pattern", "contradiction", "connection", "emotion", "decision"]
    expires_at: datetime | None
```

#### 生命周期操作

由 `MemoryLifecycleManager` 统一负责，避免各模块直接写表：

```python
class MemoryLifecycleManager:
    async def observe(event: str, turn_id: int) -> Observation
    async def promote(observation_ids: list[str]) -> Fact
    async def verify(fact_id: str, evidence_turn_id: int)
    async def contradict(fact_id: str, reason: str)
    async def decay(self)                       # 按半衰期降低 confidence/freshness
    async def merge_duplicates()
    async def obsolete(self, fact_id: str)
    async def garbage_collect()                 # 合并、衰减、删除噪声、重建 Insight
```

#### 运行规则

- `consolidation` 只生成 Observation，不直接生成 Fact。
- Fact 需要至少 2 条相关 Observation，或 1 条高重要性 Observation + LLM/用户验证。
- Reflection 改为 `Insight`：输出固定 JSON schema：
  ```json
  {
    "hypothesis": "用户可能偏好互损式交流",
    "evidence": ["fact_12", "fact_18", "fact_25"],
    "confidence": 0.47,
    "needs_more_evidence": true,
    "type": "pattern"
  }
  ```
- React（Agent 3）默认不读取 Insight；只有 InnerDrive/Planner 在需要时检索。
- 每日 GC：合并重复、衰减 confidence、删除 noise、压缩 episode、重建过期 insight。

**状态**：一期已正式上线（2026-07-18）。新增 `observations` / `facts_v2` 表、`MemoryLifecycleManager`；跳过灰度直接完整上线：user_facts 数据迁入 facts_v2（schema v4）、读路径经 repository 适配器切到 facts_v2、单写 promote、旧表归档为 `user_facts_archive`、开关 `use_observation_fact` 已删除。二期将实现 Insight 替换 Reflection。

### Layer 2: Context & Prompt Budget —— Token 是有限资源

**核心抽象**：`ContextBudget` 把 prompt 看成预算分配问题。

```python
@dataclass
class ContextBudget:
    total: int
    identity: int        # 静态，只加载一次
    emotion: int         # 动态，小摘要
    relationship: int    # 慢变
    memory: int          # 分层：hot > recent > semantic > insight
    tools: int           # 工具说明 + 历史
    conversation: int    # 最近对话，超预算触发 ContextManager 压缩
    examples: int        # 前 N 轮才有
```

#### Runtime State 摘要

Runtime 在调用 prompt builder 前自己生成轻量摘要：

```python
@dataclass
class CognitiveState:
    identity_summary: str      # 人格一句话 + 当前 dominant emotion
    emotion_summary: dict      # valence/arousal + 行为指导
    relationship_summary: str  # 关系指标一句话
    hot_facts: list[str]       # Top5 facts
    recent_episodes: list[str] # 最近 3 个 episode
    pending_task: str | None   # 当前任务/意图
    tool_history: list[str]    # 最近工具调用摘要
```

`build_system_prompt()` 只接收 `CognitiveState`，不再访问 `Agent` 内部状态。

#### Prompt Template Engine

不引入 Jinja2 等外部依赖（保持零新增依赖原则）。基于现有 `prompts/templates.py` 扩展轻量模板：

```python
class PromptTemplate:
    def __init__(self, blocks: list[PromptBlock])
    def render(self, state: CognitiveState, budget: ContextBudget) -> str
```

每个 Block 声明：
- `name`
- `priority`（预算耗尽时先丢弃低优先级）
- `render_fn`（纯函数，只读 state）
- `max_tokens`（可选）

#### 各 Agent 使用不同 Retrieval

| Agent | 可读取的记忆 |
|-------|-------------|
| React / Agent 3 | hot_facts, recent_episodes, relationship_summary |
| Planner / Agent 1 | 以上 + insights（按需） |
| Fact Extractor | raw episodes |
| Tool Agent | 不读 Memory，只读 task + schema + retry history |

#### 新增问题：Agent 1 短输入过滤过于粗糙

> **已解决（2026-07-16）**：不是按下面的语义相似度方案改，而是**整体移除**了 `_should_skip_llm`——用户决策：LLM API 成本很低，为省一次调用承担双向误判不值得。所有输入一律走完整 Agent 1 推理，`TOOL_KEYWORDS` 与 `agent1_short_input_threshold` 配置同步删除。见 `changes/2026-07-16-remove-short-input-skip.md`。以下为历史分析存档。

`core/inner_drive.py::_should_skip_llm()` 目前使用硬编码中文关键词列表判断短输入是否需要工具：

```python
TOOL_KEYWORDS = [
    "http", "https", "www.", ".com", ".cn", ".net", ".org",
    "搜索", "查", "找", "搜", "查一下", "查查", "google", "百度",
    "放歌", "听歌", "音乐", "歌曲", "播放",
    "通知", "提醒", "闹钟",
    "文件", "路径", "读取", "读", "打开", "看", "目录", "文件夹",
    "新闻", "天气", "时间", "日期",
]
```

缺陷：
- **误判**："我不查了"、"别放歌" 命中关键词，本可跳过却调 LLM
- **漏判**：用户说 "Teeth"（歌名）时没有任何关键词命中，被误判为闲聊
- **不可维护**：新增工具或场景需要不断扩展关键词表

**推荐改进**：结构化 JSON 规则 + Embedding 语义相似度。

```json
{
  "inner_drive_skip_filter": {
    "short_input_threshold": 20,
    "url_patterns": ["http://", "https://", "www.", "\\.com", "\\.cn"],
    "file_path_patterns": ["[A-Za-z]:\\\\", "/home/", "/Users/", "\\.txt", "\\.md"],
    "explicit_tool_verbs": ["搜索", "查", "找", "播放", "通知", "提醒", "读取", "打开"],
    "skip_examples": ["你好", "嗯", "好的", "哈哈", "行", "可以", "拜拜", "晚安", "ok"],
    "tool_examples": ["Teeth", "放首歌", "查下天气", "提醒我", "读这个文件"],
    "similarity_threshold": 0.72
  }
}
```

判断流程：
1. 长度、URL、文件路径、最近工具成功等硬规则保留
2. 用 embedding 比较用户输入与 `skip_examples` / `tool_examples` 的相似度
3. 最近的是 tool example 且相似度 > threshold → 不跳过
4. 最近的是 skip example 且相似度 > threshold → 跳过
5. 都不高 → 回退到规则判断

这样 "Teeth" 会跟 "放首歌" 等 tool examples 语义接近，被正确判定为需要工具；同时避免否定句误判。

**状态**：大部分已完成。
- [x] 分层 Prompt Cache
- [x] 静态/慢变/动态 block 分离
- [x] Agent 1 短输入跳过（当前为关键词版）（已于 2026-07-16 整体移除，见上）
- [x] Agent 1 向 Agent 3 传递 context_summary
- [x] 静态对话示例仅前 N 轮注入
- [x] 指令集中化
- [x] 工具规则从 ToolRegistry 动态生成
- [x] 情绪摘要化
- [x] Tool Agent Prompt 精简
- [x] ~~短输入过滤升级为语义相似度~~（改为整体移除，2026-07-16）
- [ ] 监控 Prompt Cache 实际命中率
- [ ] `ContextBudget` / `ContextAllocator` 完整实现

### Layer 3: Async Agent Runtime —— 用状态机驱动真实流程

**状态机**（统一 CLI/Web）：

```
BOOT → IDLE → PERCEIVE → PLAN → EXECUTE_TOOLS → GENERATE → EMIT → REFLECT → IDLE
         ↑                          │                │
         └──── 用户输入 / proactive ──┘                └──── 错误 / 超时时走 FALLBACK
```

#### 运行时职责拆分

当前 `Agent` 类 300+ 行，持有全部模块。拆成：

```python
class AgentRuntime:
    """只负责会话生命周期和模块装配。"""
    role_session: RoleSession
    provider: LLMProvider
    memory_service: MemoryService
    tool_runtime: ToolRuntime
    state_machine: CognitiveStateMachine

class ConversationRuntime:
    """负责 turn 管理、上下文、压缩。"""
    turn_count: int
    short_term: ConversationBuffer
    context_manager: ContextManager

class ReactExecutor:
    """负责调用 InnerDrive / ToolAgent / Roleplay。"""
    async def execute_turn(user_input: str) -> TurnResult

class CognitiveStateMachine:
    """驱动 PERCEIVE → PLAN → EXECUTE → GENERATE → REFLECT 的状态流转。"""
    async def run_turn(user_input: str) -> TurnResult
```

#### 关键改造

- 核心方法全部 `async def`，消除 `_run_sync` 和 `run_in_executor`。
- 依赖注入：`AgentRuntime` 接收 `inner_drive`, `tool_agent`, `roleplay_agent`, `context_manager`。
- 全局超时：每阶段可配置超时，整体请求也有硬上限。
- 错误恢复：阶段失败进入 `FALLBACK`，向用户说明降级原因，不再静默吞异常。

**状态**：部分已完成。
- [x] `MessageHandlerState` 状态机
- [x] `ToolExecutionResult` dataclass
- [x] 魔法数字提取为类常量
- [x] Agent 1/2 工具注册表隔离
- [ ] `Agent` 公开方法封装
- [ ] 全局超时
- [ ] 依赖注入
- [ ] 错误处理向用户反馈
- [ ] 完整的 `CognitiveStateMachine`

### Layer 4: Tool Runtime —— 工具是独立运行时单元

```python
class ToolRuntime:
    def __init__(self, external_registry: ToolRegistry, http_session: requests.Session):
        ...

    async def execute(self, request: ToolRequest) -> ToolExecutionResult:
        ...
```

#### 规则

- 取消 dispatcher 全局别名，每个工具内部处理自己的参数别名：
  ```python
  class WebSearchTool(Tool):
      def normalize_args(self, args: dict) -> dict:
          return {
              "query": args.get("query") or args.get("search") or args.get("keyword"),
              "freshness": args.get("freshness", "week"),
          }
  ```
- 外部工具与内部工具（recall/remember）完全隔离，实例不复用。
- HTTP Session 单例化（已部分实现），Provider 层负责网络重试，ToolAgent 负责 LLM 输出质量重试，`MessageHandler` 不再做 in-round retry。
- 单次用户消息设置全局 API 调用预算，超过直接 fallback：
  ```python
  @dataclass
  class RetryBudget:
      max_total_calls: int = 9      # 单次用户消息最多 API 调用次数
      max_llm_attempts: int = 3     # ToolAgent 内部重试
      max_network_retries: int = 3  # Provider 网络重试
  ```
- 工具结果在 dispatcher 层摘要/截断，默认 1000 tokens。

**状态**：部分已完成。
- [x] Agent 1/2 注册表隔离
- [x] Tool Agent Prompt 精简
- [ ] dispatcher 全局别名取消
- [ ] 统一 HTTP Session 和重试策略
- [ ] `ToolRuntime` 抽象
- [ ] `RetryBudget`

### Layer 5: Provider Abstraction —— 多模型、真异步

```python
class BaseLLMProvider(ABC):
    async def generate(self, messages, budget, source) -> LLMResponse: ...
    async def stream_generate(self, messages, budget, source) -> AsyncIterator[str]: ...
    def context_window(self) -> int: ...
    def supports_thinking(self) -> bool: ...
```

- `DeepSeekProvider` / `OpenAIProvider` / `LocalProvider` 三后端。
- 使用 `httpx.AsyncClient` 替代同步 `requests`，彻底消除事件循环阻塞。
- 路由策略：日常聊天 → 本地模型；反思/梦境/复杂推理 → 云端模型。

**状态**：未开始（现有同步 `LLMProvider` 抽象 + `DeepSeekProvider` 单后端，未做异步化与多后端路由）。

### Layer 6: Observability —— 每个请求可追溯

- 所有 LLM 调用记录 `source`（assess / review / tool_agent / react / proactive / dream）。
- 结构化日志统一 JSON 输出，解决 Windows 中文乱码。
- Metrics：`agent_time`, `tool_calls`, `token_in/out`, `memory_hits`, `error_rate`。
- 监控面板保持现有功能，但改为可配置开关，生产环境可关闭完整 prompt 保存。

**状态**：部分已完成。
- [x] 监控面板
- [x] source 字段已填充
- [x] `monitor_enabled` 配置开关
- [ ] 结构化日志 JSON 输出
- [ ] Metrics 收集与暴露

---

## 4. 与 known-issues.md 的映射表

| known-issues 条目 | 根因 | 本方案解决层 |
|-------------------|------|-------------|
| 1. dispatcher 全局别名 | 工具层职责越界 | Layer 4 |
| 2. 日志中文乱码 | 可观测性缺失 | Layer 6 |
| 3.1~3.4 记忆分层 / Reflection 假设化 | 记忆无生命周期 | Layer 1 |
| 3.5~3.7 Prompt 过长 / Personality 放 Prompt / Tool Agent 不需要人格 | Prompt 无预算 | Layer 2 |
| 3.8~3.10 Memory Source / 多维度 / 低频 Reflection | 记忆无生命周期 | Layer 1 |
| 3.11~3.12 Episode 结构化 / Importance | 记忆无生命周期 | Layer 1 |
| 3.13~3.14 多阶段 Retrieval / 不同 Agent 不同上下文 | Prompt 无预算 + 运行时耦合 | Layer 1 + Layer 2 |
| 3.15~3.16 Memory GC / Reflection 过期 | 记忆无生命周期 | Layer 1 |
| 4.295 ContextManager | Prompt 无预算 | Layer 2 |
| 4.294 Prompt 架构 | Prompt 无预算 + 运行时耦合 | Layer 2 + Layer 3 |
| 4.293 三层 Agent 成熟度 | 运行时不是真状态机 | Layer 3 |
| 4.263 async_utils | 同步/异步混用 | Layer 3 + Layer 5 |
| 4.244 / #233 / #210 WebSocket/Cookie/Origin/Session race | 数据边界模糊 + 运行时耦合 | Layer 0 + Layer 3 |
| 4.166 KimiProvider 阻塞 + 工具结果未摘要 | Provider 未异步 + Prompt 无预算 | Layer 2 + Layer 5 |
| 4.164 记忆固化 4 次 LLM + Proactive 持续消耗 | 记忆无生命周期 + 运行时不是真状态机 | Layer 1 + Layer 3 |
| 4.162 异步/同步混用 | 运行时不是真状态机 | Layer 3 + Layer 5 |
| 4.160 Prompt 重复构建 | Prompt 无预算 | Layer 2 |
| 4.156 web_tools Session / 嵌套重试 | 工具层职责混乱 | Layer 4 |
| 5. MessageHandler 封装/错误恢复/超时 | 运行时不是真状态机 | Layer 3 |
| 6. Sleep 持久化 | 数据边界模糊 | Layer 0 |

---

## 5. 实施路线图

> 注：实际实施顺序已调整为从 Layer 1 开始，风险最低且能早期验证。

### Phase 1 — Layer 1 记忆生命周期（已完成一期）

- [x] 新增 `Observation` / `FactV2` 数据模型和表
- [x] 实现 `MemoryLifecycleManager`
- [x] `MemoryConsolidator` 双写 Observation + FactV2
- [x] ~~配置开关 `use_observation_fact`~~（2026-07-18 完整上线后删除）
- [x] 完整上线（2026-07-18）：数据迁移 schema v4 + 读路径切 facts_v2 + 旧表归档 user_facts_archive
- [ ] 二期：新增 `InsightV2` 表，替换 Reflection
- [ ] 二期：Retrieval 切换到新表
- [ ] 二期：完整 GC（merge / decay / obsolete）

验收：
- `pytest tests/test_memory_lifecycle.py tests/test_consolidation.py -v` 通过
- 全量测试不降级
- 同一喜好重复 3 次后 `verification_count >= 3`

### Phase 2 — Layer 2 Prompt Budget（大部分已完成）

- [x] 分层 Prompt Cache
- [x] Agent 1 短输入跳过
- [x] Agent 1 context_summary 复用
- [x] 指令集中化
- [x] 工具规则动态生成
- [x] 情绪摘要化
- [ ] 短输入过滤升级为语义相似度
- [ ] `ContextBudget` / `ContextAllocator` 完整实现
- [ ] 各 Agent ContextProfile

验收：
- API token 输入下降 ≥ 20%
- "Teeth" 这类歌名能被正确判定为需要工具

### Phase 3 — Layer 3 Async Agent Runtime（部分已完成）

- [x] `MessageHandlerState` 状态机
- [x] `ToolExecutionResult`
- [ ] 完整 `CognitiveStateMachine`
- [ ] 核心方法全部 `async def`
- [ ] 依赖注入
- [ ] 全局超时
- [ ] 错误恢复向用户反馈

验收：
- CLI/Web 共享同一运行时
- 阶段失败进入 FALLBACK 并向用户说明

### Phase 4 — Layer 0 Identity & State + Layer 6 Observability

- [ ] 强制 `session_id = role_id`
- [ ] `personalities/{role_id}.json` 成为唯一数据源
- [ ] 结构化日志 JSON 输出
- [ ] Metrics 收集

验收：
- 角色切换数据不串
- 每次 LLM 调用有非空 source

### Phase 5 — Layer 4 Tool Runtime + Layer 5 Provider Abstraction

- [ ] 取消 dispatcher 全局别名
- [ ] 统一 HTTP Session 和重试策略
- [ ] `ToolRuntime` 抽象
- [ ] `BaseLLMProvider` + `httpx.AsyncClient`
- [ ] 多后端路由

验收：
- 工具调用稳定
- Provider 可切换
- 无事件循环阻塞

---

## 6. 验收标准

1. **单元测试**：`pytest tests --ignore=tests/real_api -q` 保持不降级（当前 408 passed + 2 skipped，30 个测试文件）。
2. **Token 效率**：同样 10 轮闲聊，API token 输入下降 ≥ 20%。
3. **记忆质量**：连续对话 50 轮后，Fact confidence 衰减机制生效，无自相矛盾 Fact。
4. **稳定性**：Web 端 30 分钟无人访问自动释放资源，shutdown 不丢数据。
5. **可观测性**：每次 LLM 调用都有非空 `source`，监控面板能按 source 过滤。
6. **短输入过滤**："Teeth"、"放这首" 等语义明确的短输入被正确路由到工具执行。

---

## 7. 两种推进方式

| 方式 | 描述 | 风险 | 适用场景 |
|------|------|------|----------|
| **A. 按 Phase 逐层重构（推荐）** | 从 Layer 1 → Layer 2 → Layer 3 → Layer 0/6 → Layer 4/5 | 单次改动面大，但回归可控 | 当前实际推进方式 |
| **B. 只抽取公共层，保留现有代码** | 新增 `runtime/`, `memory_lifecycle/` 等包，老代码逐步迁移 | 并行代码多，过渡期长 | 想先验证某一层 |

---

## 8. 下一步

当前实际推进顺序：

1. ~~**Layer 1 验证**：开启 `use_observation_fact=true` 运行一段时间，验证 `facts_v2` 数据质量~~（2026-07-18 已直接完整上线，改为线上观察 facts_v2 数据质量）
2. **Layer 2 短输入过滤优化**：实现语义相似度版 `_should_skip_llm`
3. **Layer 1 二期**：Insight 替换 Reflection
4. **Layer 3 完整状态机**：`CognitiveStateMachine` + 依赖注入 + 全局超时
5. **Layer 0**：强制 `session_id = role_id`

---

## 9. 相关文档

- `doc/refactor/`：各 Layer 详细计划与进度（入口 `self-system.md` 为六层方案总装图，`progress.md` 为最新进度）
  - 注意：`doc/refactor/` 的层号是建设顺序，与本方案的运行时层号不同；其中 `layer3-retrieval/`（多阶段 Retrieval）对应本方案 Layer 1 二期之后的检索改造
- `doc/known-issues.md`：原始问题列表
- `changes/`：每次改动的变更记录
