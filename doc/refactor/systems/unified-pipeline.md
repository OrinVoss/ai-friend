# 统一管线：CLI 与 Web 共用一条对话引擎

> 目标：CLI 和 Web 不再是两份对话管线实现，而是同一个会话引擎的两个「前端」——新功能只写一次，两端同时获得。
> 状态：P0（装配统一）、P1（管线统一）已完成（2026-07-16）；P1 默认 `cli_shared_pipeline=false` 灰度中；P2-P3 待实施。
> 归属：systems/（接口层）；收口 `cli.md` 的「双轨管线」根因和 `emotion.md` 的 CLI 情绪缺失。

---

## 1. 问题：双轨管线

当前一条对话从输入到回复，存在**两份独立实现**：

| | CLI | Web |
|---|-----|-----|
| 装配 | `main.py` 手工接线全部组件 | `web/session.py` SessionManager 手工接线 |
| 管线 | `CliController` 内联 perceive→think→act→reflect（`core/cli_controller.py:138-345`） | `MessageHandler` 三层 Agent 编排 |
| 主动/睡眠 | **没有** | `web/server.py` 后台循环驱动 |
| 情绪更新 | **没有**（从不调用 `_process_emotion`） | 有 |

后果（都已在 `cli.md` / `emotion.md` 立案）：

- CLI 情绪永远不变、没有睡眠循环、没有主动消息
- 两份装配手工对齐，已经漂移（embedding endpoint 两处不一致，见 `provider.md`）
- **每个新功能都要选边**：Think Loop、Memory Agent 接入、挂念浮现——照现在的结构，做完 Web 还得在 CLI 再写一遍，而历史证明没人会写第二遍

根因：CLI 和 Web 是「两个应用」，而不是「一个应用的两个界面」。

---

## 2. 目标架构

```
┌────────────┐        ┌────────────┐
│  CLI 前端   │        │  Web 前端   │
│ ui/cli.py  │        │ web/server │
└─────┬──────┘        └─────┬──────┘
      │  实现同一个 Frontend 接口 │
      ↓                     ↓
┌──────────────────────────────────────┐
│     会话引擎（唯一管线）               │
│     ConversationEngine               │
│                                      │
│  handle_message(input)               │
│  handle_proactive(intent)            │
│  sleep / wake / dream                │
│  事件回调：on_token / on_segment /    │
│  on_status / on_proactive / on_error │
├──────────────────────────────────────┤
│  Agent 1/2/3 · 情绪 · 记忆 · 工具     │
└──────────────────────────────────────┘
      ↑ 同一个工厂构造
┌──────────────────────────────────────┐
│  SessionFactory（共享装配）            │
│  config → db → personality → memory  │
│  → provider → tools → engine         │
└──────────────────────────────────────┘
```

三条边界：

1. **引擎只有一份**：`MessageHandler` 是功能超集，以它为管线核心，包成 `ConversationEngine`；`CliController` 的内联 ReAct 删除
2. **前端只剩「输入 + 渲染」**：CLI 的终端交互、Web 的 WS/REST，通过同一个 `Frontend` 回调接口接收引擎事件
3. **装配只有一处**：`SessionFactory` 统一接线，CLI 和 Web 都调它——配置漂移从结构上消失

---

## 3. 核心接口

### 3.1 Frontend 接口（前端实现）

```python
class Frontend(Protocol):
    def on_token(self, token: str) -> None          # 流式 token
    def on_message_done(self, text: str) -> None    # 一条完整回复
    def on_proactive(self, text: str) -> None       # 主动消息
    def on_sleep_reply(self, text: str) -> None     # 睡眠中的回复
    def on_status(self, status: str) -> None        # 「正在搜索…」等状态
    def on_error(self, error: str) -> None
```

- `ConsoleInterface` 实现它：print / 打字机效果（顺带解决 `<tool_call>` 原始标记喷给用户的问题——引擎只发清理后的事件）
- Web 的 WS handler 实现它：包成 JSON 帧发给浏览器

### 3.2 ConversationEngine（引擎对外）

```python
class ConversationEngine:
    async def handle_message(self, user_input: str, fe: Frontend) -> str
    async def handle_proactive(self, fe: Frontend) -> str | None
    async def handle_explore(self, fe: Frontend) -> str | None
    async def get_sleep_state(self) -> tuple[bool, str | None]
    # 状态查询（供命令层）
    def get_emotion_summary(self) -> dict
    def get_relationship(self) -> dict
```

### 3.3 SessionFactory（共享装配）

```python
class SessionFactory:
    def __init__(self, config): ...
    async def create_session(self, session_id: str, role_id: str) -> ConversationEngine
```

- 抽出 `main.py:38-116` 和 `web/session.py` 的重复接线
- **每个 session 独立的 `Repository` 实例**（顺带消除 `web.md` 立案的 `session_id` 共享竞态）
- provider / embed_engine / db 按进程共享（现在是、以后也是），其余 per-session

### 3.4 共享 Runtime（主动/睡眠驱动）

把 `web/server.py:394-415` 的后台循环抽成 `RuntimeDriver`：

```python
class RuntimeDriver:
    """按节奏驱动 engine 的 proactivity / sleep tick，前端只负责展示。"""
    async def start(self, engine: ConversationEngine, fe: Frontend) -> None
    async def stop(self) -> None
```

CLI 启动时同样跑一个——睡眠、做梦、主动搭话在 CLI 自然出现。这是 self-system「时间是刺激」在接口层的落地：**时间驱动属于引擎，不属于某个前端**。

---

## 4. 合法保留的差异

统一管线不等于两端一模一样，以下差异是正当的：

- **渲染**：终端纯文本 vs 浏览器 markdown/气泡
- **输入**：终端单行/快捷键 vs 浏览器输入框
- **Web 独有的调试界面**：monitor、导出、日志查看——开发工具，不属于对话管线
- **命令层**：CLI 的 `/mood` 等命令（P2 评估哪些提升为引擎级状态查询，两端都能用）

---

## 5. 分期实施

| 期 | 内容 | 依赖 |
|----|------|------|
| **P0 装配统一** ✅ | 新建 `SessionFactory`，`main.py` 和 `web/session.py` 都改调它；行为不变，先消灭配置漂移（2026-07-16 完成） | 无 |
| **P1 管线统一** ✅ | `MessageHandler` 包出 `ConversationEngine` 事件接口；CLI 切换（`cli_shared_pipeline` 开关，灰度后默认开）；删除 CliController 内联 ReAct（引擎与开关 2026-07-16 完成，见 `changes/2026-07-16-unified-pipeline-p1-conversation-engine.md`；旧状态机保留至 P3 灰度验证后删除） | P0 |
| **P2 Runtime 下沉** | 主动/睡眠循环抽成 `RuntimeDriver`；CLI 启动同款；睡眠/主动消息进 CLI | P1 |
| **P3 收尾** | 删除死代码（旧 CLI 循环、Web 端 `_split_segments` 等）；命令层评估统一；文档对齐 | P2 |

每期独立可上线，`cli_shared_pipeline` 默认先 false 灰度，验证后翻 true。

---

## 6. 顺带解决的问题

| 已立案问题 | 解决方式 |
|-----------|---------|
| CLI 情绪永不更新（`emotion.md` P0） | 管线只有一条，情绪更新自然覆盖 CLI（P1 已实现，`cli_shared_pipeline=true` 后生效；灰度验证中） |
| CLI 无睡眠循环（`cli.md` P0） | RuntimeDriver 共享（P2） |
| `<tool_call>` 原始标记喷给用户（`cli.md` P0） | 引擎只发清理后的事件，前端不再接触原始流（P1 已实现，开关开启后生效） |
| 装配配置漂移（`provider.md`） | SessionFactory 单一接线（P0）✅ 2026-07-16 |
| Web `session_id` 共享竞态（`web.md` P0） | Factory 为每 session 建独立 Repository（P0）✅ 2026-07-16 |
| 新功能选边问题（Think Loop / Memory Agent / 挂念浮现） | 引擎一处接入，两端同时获得 |

---

## 7. 改动文件

| 文件 | 改动 | 期 |
|------|------|----|
| `core/session_factory.py`（新建） | 共享装配 | P0 |
| `main.py` / `web/session.py` | 改调 SessionFactory | P0 |
| `core/message_handler.py` | 包出 ConversationEngine 事件接口 | P1 |
| `core/cli_controller.py` | 删除内联 ReAct，改为输入循环 + Frontend 实现 | P1 |
| `core/runtime_driver.py`（新建） | 主动/睡眠驱动下沉 | P2 |
| `web/server.py` | 后台循环改调 RuntimeDriver | P2 |
| `config.py` | `cli_shared_pipeline` 开关 | P1 |
| `tests/test_unified_pipeline.py`（新建） | 见下 | 各期 |

---

## 8. 测试与验收

测试：

1. **等价性**：同一输入经引擎产生的事件序列，CLI mock 前端与 Web mock 前端收到的一致 ✅（`tests/test_unified_pipeline.py`，2026-07-16）
2. SessionFactory：两个 session 的 Repository 互不共享 `session_id` ✅（`tests/test_session_factory.py`，2026-07-16）
3. 开关回退：`cli_shared_pipeline=false` 时 CLI 走旧路径行为不变（P1 灰度期间）✅（`tests/test_unified_pipeline.py::TestCliSharedPipelineSwitch`，2026-07-16）
4. RuntimeDriver：tick 触发 proactive 时，前端收到 `on_proactive` 事件

验收：

- CLI 中 `/mood` 随对话变化（情绪链路打通）
- CLI 到点会困、会醒、会做梦、会主动搭话
- 两端对同一问题给出同等质量的回答（同一管线，不存在「Web 更聪明」）
- 全量测试不降级

---

## 9. 相关文档

- `cli.md` — 双轨管线问题清单（本方案收口其 P1）
- `emotion.md` — CLI 情绪缺失（本方案顺带解决）
- `web.md` — session 隔离与竞态（SessionFactory 解决）
- `provider.md` — 装配漂移实证
- `../self-system.md` — 「时间是刺激」的架构原则
