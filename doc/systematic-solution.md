# AI Friend 系统性解决方案

> 目标：把 `doc/known-issues.md` 中分散的技术债务，归纳为一套统一、可落地的架构改造方案。

---

## 1. 核心诊断：当前系统的本质问题

### 1.1 问题分层

| 层级 | 当前症状 | 根因 |
|------|---------|------|
| **记忆层** | Fact 一步推理、Reflection 下结论、无来源、无衰减、无 GC | Memory 只有"存储/检索"，没有"生命周期管理" |
| **Prompt 层** | 各 Agent 重复构建完整上下文、示例过长、指令分散 | Prompt builder 直接依赖完整模型对象，没有"状态摘要"边界 |
| **Agent 运行时** | 同步/异步混用、状态机未驱动流程、MessageHandler 依赖 Agent 内部状态 | Runtime 仍是"过程式脚本"而非"状态机 + 依赖注入" |
| **工具层** | dispatcher 全局别名冲突、ToolAgent 重复重试 | 工具解析与工具实现耦合，重试策略缺少统一预算 |
| **Web/会话层** | session 与 role 关系历史包袱、睡眠消息持久化补丁式修复 | 会话模型未彻底与角色模型绑定 |

### 1.2 统一解决思路

把系统拆成三条清晰的主线，每条主线有明确的边界和接口：

```
Memory Layer（记忆生命周期）
    ↓ 输出：UserFacts, Episodes, Insights, RelationshipSnapshot
    
Cognitive Runtime（认知运行时）
    ↓ 输入：摘要化的 Memory State + Emotional State + Task
    ↓ 输出：ToolPlan → ToolResult → Response
    
Interaction Layer（交互层）
    ↓ CLI / Web / Proactive 只负责 IO 和会话生命周期
```

---

## 2. 记忆系统重构：从"存储"到"生命周期"

### 2.1 三层 Memory 模型

当前 `UserFact / Experience / Reflection` 承担了三层语义，但代码没有区分。统一改为：

```python
class Observation:
    """原始观察，置信度低，可随时写入。"""
    id: int
    content: str
    source_turn: int
    created_at: datetime
    embedding: bytes | None

class Fact:
    """经多次验证或用户确认的事实，有置信度和来源。"""
    id: int
    category: str
    key: str
    value: str
    confidence: float
    stability: float
    freshness: float
    importance: float
    source_observation_ids: list[int]
    verification_count: int
    last_verified_at: datetime
    status: Literal["active", "decayed", "merged", "obsolete"]

class Insight:
    """基于多个 Fact 的假设，带证据和待验证标记。"""
    id: int
    hypothesis: str
    evidence_fact_ids: list[int]
    confidence: float
    needs_more_evidence: bool
    insight_type: InsightType
    expires_at: datetime | None
```

### 2.2 生命周期操作

由 `MemoryLifecycleManager` 统一负责，避免各模块直接写表：

```python
class MemoryLifecycleManager:
    async def observe(event: str, turn_id: int) -> Observation
    async def promote(observation_ids: list[int]) -> Fact
    async def verify(fact_id: int, evidence_turn_id: int)
    async def contradict(fact_id: int, reason: str)
    async def decay(self)  # 按半衰期降低 confidence/freshness
    async def merge_duplicates()
    async def obsolete(self, fact_id: int)
    async def garbage_collect()  # 合并、衰减、删除噪声、重建 Insight
```

### 2.3 Reflection 改为假设驱动

当前 `consolidation.py` 的 `_generate_reflection` 直接让 LLM 写结论。改为：

1. 只把 **Observation + Fact** 喂给 Reflection LLM；
2. 输出固定 JSON schema：`{hypothesis, evidence, confidence, needs_more_evidence, type}`；
3. `Insight` 默认带 `expires_at`，GC 时根据新证据重验证或删除。

### 2.4 来源追踪（Source）

所有 Memory 写入必须携带：

- `source_turn` / `source_episode_ids`
- `created_by`：哪个 Agent / 哪个阶段
- `created_at`
- `verification_count`
- `last_verified_at`

这样未来可以：按可信度排序、追踪污染、删除被污染记忆。

### 2.5 Memory GC

新增 `memory/gc.py`，按调度运行：

```python
async def run_memory_gc(session_id: str):
    await merge_duplicate_facts()
    await decay_confidences()
    await archive_low_importance_episodes()
    await rebuild_insights()
    await delete_obsolete()
```

触发时机：每天首次启动、每 N 轮对话后、或 Web 端提供手动触发接口。

---

## 3. Prompt 与 Agent 认知架构：从"大 Prompt"到"状态摘要"

### 3.1 Runtime State 摘要

当前 `build_system_prompt()` 仍接收 `EmotionalState` 和 `MemoryContext` 完整对象。统一改为：Runtime 在调用前自己生成轻量摘要字典：

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

### 3.2 Prompt Template Engine

不引入 Jinja2 等外部依赖（保持零新增依赖原则）。基于现有 `prompts/templates.py` 扩展一个轻量模板：

```python
class PromptTemplate:
    def __init__(self, blocks: list[PromptBlock])
    def render(self, state: CognitiveState, budget: TokenBudget) -> str
```

每个 Block 声明：
- `name`
- `priority`（预算耗尽时先丢弃低优先级）
- `render_fn`（纯函数，只读 state）
- `max_tokens`（可选）

### 3.3 Token Budget

新增 `prompts/budget.py`：

```python
@dataclass
class TokenBudget:
    total: int
    identity: int
    emotion: int
    memory: int
    conversation: int
    tools: int
    instruction: int
```

`PromptTemplate.render()` 按优先级分配预算，超出时截断低优先级 Block。

### 3.4 各 Agent 使用不同 Retrieval

当前所有 Agent 共享 `MemoryContext`。统一改为：

| Agent | 可读取的记忆 |
|-------|-------------|
| React / Agent 3 | hot_facts, recent_episodes, relationship_summary |
| Planner / Agent 1 | 以上 + insights（按需） |
| Fact Extractor | raw episodes |
| Tool Agent | 不读 Memory，只读 task + schema + retry history |

### 3.5 不同 Agent 不同 Prompt

- Agent 1（Planner）：只给 identity + emotion + task + available intents + memory summary
- Agent 2（Tool）：只给 task + tool schemas + retry history
- Agent 3（React）：只给 identity + emotion + memory summary + tool_results

---

## 4. Agent 运行时重构：状态机 + 依赖注入 + 异步化

### 4.1 运行时职责拆分

当前 `Agent` 类 300+ 行，持有全部模块。拆成：

```python
class AgentRuntime:
    """只负责会话生命周期和模块装配。"""
    personality: Personality
    memory: MemoryService
    emotion: EmotionalState
    provider: LLMProvider
    tool_registry: ToolRegistry
    state_machine: CognitiveStateMachine

class CognitiveStateMachine:
    """驱动 Agent 1 → Agent 2 → Agent 3 的状态流转。"""
    async def run_turn(user_input: str) -> TurnResult

class MessageHandler:
    """只负责编排三层 Agent，不直接操作 Agent 内部状态。"""
    def __init__(self, runtime: AgentRuntime, ...)
```

### 4.2 状态机真正驱动流程

当前 `AgentState` 已定义但只在 CLI 使用。统一用状态机驱动所有路径：

```
IDLE → PERCEIVE → PLAN → EXECUTE → EXPRESS → CONSOLIDATE → IDLE
            ↓         ↓        ↓         ↓
         检索记忆   Agent 1   Agent 2   Agent 3
```

每个状态只负责一件事，状态转换由 `CognitiveStateMachine` 统一处理。

### 4.3 依赖注入

所有 Handler/Agent 通过构造函数接收依赖：

```python
class InnerDriveAgent:
    def __init__(self, provider, retriever, memory_service, config)

class ToolAgent:
    def __init__(self, provider, external_registry, config)

class RoleplayAgent:
    def __init__(self, provider, prompt_template, cognitive_state)
```

不再从 `Agent` 对象内部取属性。

### 4.4 渐进式异步化

当前核心层大量 `run_async()` 包装。改造路线：

1. **短期**：把 `_run_sync()` 中的 `ThreadPoolExecutor` 改为模块级单例，避免每次创建线程池。
2. **中期**：`Repository`、`LongTermMemory`、`MessageHandler` 改为 `async`；CLI 用 `asyncio.run()`，Web 直接 await。
3. **长期**：核心 Agent 流程全面 `async`，消除 `run_async` 包装层。

---

## 5. 工具层统一改造

### 5.1 取消 dispatcher 全局别名

把参数别名处理下沉到每个 Tool 内部：

```python
class WebSearchTool(Tool):
    def normalize_args(self, args: dict) -> dict:
        return {
            "query": args.get("query") or args.get("search") or args.get("keyword"),
            "freshness": args.get("freshness", "week"),
        }
```

`dispatcher` 只负责解析 `<tool_call>` XML、校验 schema、分发执行。

### 5.2 统一重试预算

当前 Provider、ToolAgent、MessageHandler 都有重试。统一为：

```python
@dataclass
class RetryBudget:
    max_total_calls: int = 9   # 单次用户消息最多 API 调用次数
    max_llm_attempts: int = 3  # ToolAgent 内部重试
    max_network_retries: int = 3  # Provider 网络重试
```

由 `CognitiveStateMachine` 持有预算，每步递减，耗尽时直接走降级。

### 5.3 工具结果摘要

当前 `WebFetchTool` / `ReadFileTool` 结果可能几千 tokens。在 `dispatcher` 层增加摘要/截断：

```python
def summarize_tool_output(output: str, budget: int = 1000) -> str
```

默认预算 1000 tokens，超过时提取关键句子或截断。

---

## 6. 会话/角色模型最终统一

当前已朝 "一个角色一个 session" 方向演进，但历史包袱仍在。最终形态：

```python
class Character:
    role_id: str
    personality: Personality          # 个性定义
    emotional_state: EmotionalState   # 情绪状态

class Session:
    session_id: str
    character_id: str                 # 一一对应
    memory: MemoryService             # 隔离
    runtime: AgentRuntime
```

- `personalities/{role_id}.json` 只存 `Character` 定义；
- `session_roles` 表保证一一映射；
- 不允许一个角色多个 session；
- 切换角色 = 切换 `Session` 实例。

---

## 7. 实施路线图

### 阶段一：基础层（2-3 周）

1. **Memory 模型拆分**：新增 `Observation / Fact / Insight` 模型，数据库表迁移。
2. **Memory Lifecycle Manager**：实现 promote/verify/decay/merge/obsolete/gc。
3. **来源追踪**：所有 Memory 写入增加 `source_turn / created_by / verification_count`。
4. **测试**：`tests/test_memory_lifecycle.py`，覆盖提升、验证、衰减、合并。

### 阶段二：Prompt 与 Runtime 解耦（2 周）

1. **CognitiveState**：统一 Runtime 摘要对象。
2. **PromptTemplate + TokenBudget**：实现 Block 优先级和预算分配。
3. **各 Agent 使用不同 Retrieval**：Agent 2 不读 Memory。
4. **测试**：`tests/test_prompt_template.py`、`tests/test_token_budget.py`。

### 阶段三：Agent 运行时重构（2-3 周）

1. **CognitiveStateMachine**：用状态机驱动 CLI 和 Web 的主循环。
2. **AgentRuntime + 依赖注入**：拆分 `Agent` 类。
3. **异步化中期**：核心 Repository/MessageHandler 改为 async。
4. **测试**：重写 `tests/test_message_handler.py`，增加状态机测试。

### 阶段四：工具层与收尾（1-2 周）

1. 取消 dispatcher 全局别名。
2. 统一 RetryBudget。
3. 工具输出摘要。
4. 角色-会话一一对应最终绑定。
5. 更新 `doc/architecture.md`、`doc/known-issues.md`。

---

## 8. 风险与回滚策略

| 风险 | 缓解措施 |
|------|---------|
| 数据库 schema 大改导致旧数据不兼容 | 写迁移脚本；保留旧表一段时间；提供导出/导入 |
| Prompt 模板化后行为变化 | 保留旧 `build_system_prompt()` 作为 fallback；AB test 开关 |
| 异步化引入死锁/竞态 | 小步迁移；每步加测试；关键路径加超时 |
| 改造周期过长 | 分阶段交付；每阶段结束都可独立发布 |

---

## 9. 与 `known-issues.md` 的对应关系

| known-issues 条目 | 本方案覆盖点 |
|-------------------|-------------|
| 3.1 Observation/Fact/Insight | 2.1 三层 Memory 模型 |
| 3.2 Reflection 下结论 | 2.3 Reflection 改为假设驱动 |
| 3.3 React 直接读 Reflection | 3.4 各 Agent 使用不同 Retrieval |
| 3.4 Fact 未降级 | 2.2 Memory Lifecycle Manager |
| 3.5 React Prompt 太长 | 3.2 / 3.4 Prompt Template + selective retrieval |
| 3.6 Personality 放 Prompt | 3.1 CognitiveState 摘要 |
| 3.7 Tool Agent Prompt 过长 | 3.5 Tool Agent 极简 Prompt |
| 3.8 Memory 无 Source | 2.4 来源追踪 |
| 3.9 只有 confidence | 2.1 Fact 四维度 |
| 3.10 Reflection 高频 | 2.3 / 2.5 GC + 条件触发 |
| 3.11 Episode 自然语言 | 2.1 Observation 保留结构化 |
| 3.12 Episode Importance | 2.1 / 2.2 importance 字段 |
| 3.13 / 3.14 Retrieval | 3.4 多阶段/分 Agent Retrieval |
| 3.15 / 3.16 Memory GC | 2.5 Memory GC |
| #293 Agent 架构 | 4.1 / 4.2 / 4.3 运行时重构 |
| #160 Prompt 重复构建 | 3.1 / 3.2 Runtime State + Template |
| #156 web_tools 重试 | 5.2 统一 RetryBudget |
| #1 dispatcher 别名 | 5.1 取消全局别名 |
| MessageHandler 封装 | 4.1 / 4.3 依赖注入 + 状态机 |

---

## 10. 推荐下一步

先执行 **阶段一：Memory 系统重构**。因为它是：
- 最底层，其他改造依赖它；
- 当前 `known-issues.md` 中问题最集中、价值最高的区域；
- 改造后 Prompt 和 Agent 自然变轻。
