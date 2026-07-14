# AI Friend 统一系统解决方案（v0.6/v1.0 架构蓝图）

> 目标：把 `doc/known-issues.md` 中分散的 20+ 个问题收敛到一个统一的、分层的架构改造方案中，而不是继续逐个打补丁。
> 
> 本文件合并了 `doc/systematic-solution.md`（早期概要草案）与 `doc/martian-manhunter-icon-valkyrie.md`（详细六层架构蓝图）。

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
- `personality.json` 旧文件废弃；`personalities/{role_id}.json` 成为唯一人格+情绪数据源。
- 解决：角色切换混乱、睡眠状态错配、关系指标历史空白、多 session 竞态。

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

### Layer 6: Observability —— 每个请求可追溯

- 所有 LLM 调用记录 `source`（assess / review / tool_agent / react / proactive / dream）。
- 结构化日志统一 JSON 输出，解决 Windows 中文乱码。
- Metrics：`agent_time`, `tool_calls`, `token_in/out`, `memory_hits`, `error_rate`。
- 监控面板保持现有功能，但改为可配置开关，生产环境可关闭完整 prompt 保存。

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

### Phase 1 — Layer 0 + Layer 3 骨架（2~3 周）

- 强制 `session_id = role_id`，删除旧 `personality.json` 依赖。
- 把 `Agent` 拆出 `AgentRuntime` + `ConversationRuntime` + `ReactExecutor`。
- 核心方法改为 `async def`，用 `asyncio` 替代 `_run_sync`。
- 引入真实状态机，CLI 和 Web 共享同一状态机。
- 验收：CLI/Web 都能正常对话，单元测试不降级。

### Phase 2 — Layer 1 记忆生命周期（2~3 周）

- 新增 `Observation` / `Fact` / `Insight` 数据模型和表。
- 改写 `consolidation`：只生成 Observation。
- 新增 `FactExtractor`：把 Observation 升级为 Fact。
- 新增 `InsightGenerator`：把 Fact 升级为带证据的 Insight。
- React 默认不读取 Insight。
- 验收：记忆表有 type/source/evidence，Reflection 输出带 hypothesis。

### Phase 3 — Layer 2 Prompt Budget（1~2 周）

- 实现 `ContextBudget` 和 `ContextAllocator`。
- 每个 Agent 配 `ContextProfile`。
- 引入 Jinja2 模板和 prompt 版本管理。
- 验收：API token 消耗下降 30%+，不同 Agent 上下文不同。

### Phase 4 — Layer 4 + Layer 5（2 周）

- 取消 dispatcher 全局别名。
- 统一 HTTP Session 和重试策略。
- `BaseLLMProvider` + `httpx.AsyncClient`。
- 验收：工具调用稳定，Provider 可切换。

### Phase 5 — Layer 6 + Web 生产化（1~2 周）

- 结构化日志、metrics、source 字段。
- 监控面板可配置开关。
- 修复 #244/#233/#210 等 Web 层问题。
- 验收：监控面板可用，CORS/Origin/Cookie 正确。

---

## 6. 验收标准

1. **单元测试**：`pytest tests --ignore=tests/real_api -q` 保持 390+ passed。
2. **Token 效率**：同样 10 轮闲聊，API token 输入下降 ≥ 30%。
3. **记忆质量**：连续对话 50 轮后，Fact confidence 衰减机制生效，无自相矛盾 Fact。
4. **稳定性**：Web 端 30 分钟无人访问自动释放资源，shutdown 不丢数据。
5. **可观测性**：每次 LLM 调用都有非空 `source`，监控面板能按 source 过滤。

---

## 7. 两种推进方式

| 方式 | 描述 | 风险 | 适用场景 |
|------|------|------|----------|
| **A. 按 Phase 逐层重构（推荐）** | 从 Layer 0 → Layer 6 依次替换 | 单次改动面大，但回归可控 | 准备做 v0.6/v1.0 |
| **B. 只抽取公共层，保留现有代码** | 新增 `runtime/`, `memory_lifecycle/` 等包，老代码逐步迁移 | 并行代码多，过渡期长 | 想先验证某一层 |

---

## 8. 下一步

如果批准方案 A，从 **Phase 1** 开始：先强制 `session_id = role_id` 并拆分 `Agent` 运行时。

如果批准方案 B，从 **Phase 2 中的 `memory_lifecycle/` 模块**开始，与现有 `consolidation` 并行运行，验证 Observation/Fact/Insight 流程后再替换。
