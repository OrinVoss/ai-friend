# Layer 6: Personality / Session / 记忆绑定

## 目标

一个角色 = 一个完整实例。角色个性、情绪状态、Session、记忆、关系指标、睡眠状态全部绑定到同一个 `role_id`。

## 当前状态

**已实现（2026-07-21）**。本次为收口：session_roles 表、按 session_id 隔离的各记忆表、以及 personalities/{role_id}.json 中的情绪持久化此前已部分落地，本次通过 `PersonalityManager` 与 `session_id == role_id` 硬校验完成最终绑定。

## 核心原则

```
role_id == session_id == memory_namespace == emotion_namespace == sleep_namespace
```

## 当前问题

| 问题 | 表现 |
|------|------|
| `personality.json` 管理混乱 | 旧文件和新 `personalities/` 目录并存 |
| Session 与 Role 绑定不严格 | 一个角色可能有多个 session |
| 数据隔离未完全验证 | 多角色切换时是否串数据？ |
| 情绪状态位置不明确 | 情绪到底属于 personality 还是 session？ |
| 睡眠状态分散 | `.sleep_state.{name}` 文件按名字而不是 role_id |

## 数据模型

### RoleSession（冻结的数据类）

```python
@dataclass(frozen=True)
class RoleSession:
    role_id: str
    personality: PersonalityConfig
    emotional_state: EmotionalState
    memory_namespace: str
    sleep_state: SleepState
```

### Personality 文件结构

`personalities/{role_id}.json`（实际键名为 `personality`，保持代码现状）：

```json
{
  "personality": {
    "name": "小星",
    "traits": {"humor": 0.8, "warmth": 0.7, "sass": 0.6},
    "speaking_style": "朋友式互损，但心里暖",
    "backstory": "...",
    "interests": ["音乐", "编程", "电影"],
    "first_run_greeting": "..."
  },
  "emotional_state": {
    "valence": 0.5,
    "arousal": 0.5,
    "joy": 0.3,
    "trust": 0.3,
    "resentment": 0.0
  }
}
```

## 绑定关系

```
Role (role_id)
  │
  ├── personalities/{role_id}.json
  │      ├── 个性定义 (config)
  │      └── 情绪状态 (emotional_state)
  │
  ├── Session (session_id = role_id)
  │      ├── conversation_turns (session_id)
  │      ├── observations (session_id)
  │      ├── facts_v2 (session_id)
  │      ├── experiences (session_id)
  │      ├── insights_v2 (session_id)
  │      ├── relationship_metrics (session_id)
  │      └── relationship_snapshots (session_id)
  │
  ├── SleepState (.sleep_state.{role_id})
  │      └── 睡眠/梦境状态
  │
  └── Embedding / Vector Store
         └── 按 memory_namespace 隔离
```

## 需要修改的组件

### 1. Personality Manager

实现位置：`core/personality_manager.py`

```python
class PersonalityManager:
    def personality_path(self, role_id: str) -> str:
        """返回 personalities/{role_id}.json 路径。"""

    def list_roles(self) -> list[str]:
        """列出所有可用角色（排除 .bak）。"""

    def role_exists(self, role_id: str) -> bool:
        """角色文件是否存在。"""

    def load_role(self, role_id: str) -> Personality:
        """加载角色的完整状态（人格 + 情绪）。"""

    def save_role(self, role_id: str, personality: Personality) -> None:
        """保存角色的完整状态。"""

    def create_role(self, role_id: str, base: Personality | None = None) -> Personality:
        """以 default 为模板创建新角色。"""
```

### 2. Session 绑定

- `core/session_factory.py::assemble_session(session_id, role_id=None)`：
  - `role_id` 缺省时默认等于 `session_id`；
  - 两者不一致时抛 `ValueError`；
  - 内部 `Repository.session_id`、Agent、SleepManager、InnerDriveState 一律使用 `role_id`。
- `web/session.py::SessionManager.get_or_create(session_id, role_id)`：
  - 同时传入且不一致时抛 `ValueError`；
  - 只传 `session_id` 时，若数据库中存有不一致的旧映射也抛 `ValueError`。

### 3. 数据库约束

所有长期记忆表（`facts_v2`、`experiences`、`observations`、`insights_v2`、`conversation_turns`、`relationship_metrics`、`relationship_snapshots`）已按 `session_id` 隔离。Layer 6 下 `session_id == role_id`，因此这些表也按角色隔离。

`Repository` 层所有读写均带 `session_id` 过滤；新代码路径不再写入 `session_id != role_id` 的行。

### 4. 睡眠状态

睡眠状态文件 `.sleep_state.{role_id}` 按 role_id 命名。`assemble_session` 与 `Agent` 构造时传入 `session_id=role_id`，因此睡眠状态天然随角色隔离。

## 实施步骤

### Step 1：强制 session_id = role_id ✅

- `Repository.session_id` 必须从 `RoleSession.role_id` 读取
- `SessionManager` 不再允许创建非 role_id 的 session
- 数据库迁移：把现有 session 数据合并到 role_id

> 注：`session_roles` 表与 #SR-002 迁移此前已落地，本次新增硬校验防止回归。

### Step 2：统一 Personality 管理 ✅

- 废弃根目录 `personality.json`
- `personalities/{role_id}.json` 成为唯一数据源
- `PersonalityManager` 统一加载/保存

### Step 3：情绪状态绑定 ✅

- `EmotionalState` 持久化到 `personalities/{role_id}.json`
- 运行时从 RoleSession 读取，修改后写回

> 注：情绪状态已随 personalities/{role_id}.json 持久化，本次未改文件结构，只通过 `PersonalityManager` 统一入口。

### Step 4：睡眠状态绑定 ✅

- `.sleep_state.{role_id}` 按 role_id 命名
- 睡眠状态属于 RoleSession 的一部分

### Step 5：多角色验证 ✅

- 创建测试角色，验证数据隔离
- 切换角色时确认不串数据

验证文件：`tests/test_role_isolation.py`（facts / relationship / turns / insights / sleep state 全隔离）。

## 配置

```json
{
  "default_role": "default",
  "personality_dir": "personalities/",
  "enforce_role_session_binding": true
}
```

## 验收标准

1. 一个角色只有一个 session，session_id == role_id
2. 切换角色后，memory / relationship / sleep state 完全隔离
3. `personality.json` 不再被代码引用
4. 情绪状态正确保存到 `personalities/{role_id}.json`
5. 全量测试不降级

## 依赖

- Layer 1 Memory 生命周期：记忆是角色绑定的核心数据
- Layer 3 Retrieval：不同角色的记忆需要正确隔离检索
