# Layer 6: Personality / Session / 记忆绑定

## 目标

一个角色 = 一个完整实例。角色个性、情绪状态、Session、记忆、关系指标、睡眠状态全部绑定到同一个 `role_id`。

## 当前状态

**未开始**。

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

`personalities/{role_id}.json`：

```json
{
  "id": "小星",
  "config": {
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

```python
class PersonalityManager:
    def load_role(self, role_id: str) -> RoleSession:
        """加载角色的完整状态（人格 + 情绪）。"""
        
    def save_role(self, role_session: RoleSession) -> None:
        """保存角色的完整状态。"""
        
    def list_roles(self) -> list[str]:
        """列出所有可用角色。"""
        
    def create_role(self, role_id: str, config: PersonalityConfig) -> RoleSession:
        """创建新角色。"""
```

### 2. Session Manager

```python
class SessionManager:
    def get_or_create_session(self, role_id: str) -> Session:
        """一个角色只对应一个 session。"""
        
    def validate_session_role(self, session_id: str, role_id: str) -> bool:
        """验证 session 和 role 匹配。"""
```

### 3. 数据库约束

所有表已经有 `session_id`，需要强制：

```sql
-- 插入时检查 session_id == role_id
-- 或者通过 Repository 层强制
```

### 4. 睡眠状态

```python
# 从 .sleep_state.小星 改为 .sleep_state.小星
# 如果 role_id 就是 小星，则不需要改文件名，但需要确保通过 role_id 查找
```

## 实施步骤

### Step 1：强制 session_id = role_id

- `Repository.session_id` 必须从 `RoleSession.role_id` 读取
- `SessionManager` 不再允许创建非 role_id 的 session
- 数据库迁移：把现有 session 数据合并到 role_id

### Step 2：统一 Personality 管理

- 废弃根目录 `personality.json`
- `personalities/{role_id}.json` 成为唯一数据源
- `PersonalityManager` 统一加载/保存

### Step 3：情绪状态绑定

- `EmotionalState` 持久化到 `personalities/{role_id}.json`
- 运行时从 RoleSession 读取，修改后写回

### Step 4：睡眠状态绑定

- `.sleep_state.{role_id}` 按 role_id 命名
- 睡眠状态属于 RoleSession 的一部分

### Step 5：多角色验证

- 创建测试角色，验证数据隔离
- 切换角色时确认不串数据

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
