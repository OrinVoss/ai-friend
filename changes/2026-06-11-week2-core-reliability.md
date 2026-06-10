# Week 2 稳固：核心可靠性修复

## 修改文件

### core/agent.py
- **AG-002**: `_react_loop` 循环耗尽后空回复降级（兜底文本）
- **AG-005**: 3 次假工具调用修正后硬兜底
- **AG-012**: `_react_loop` 异常隔离 + `_reset_react` 统一在循环后调用
- **AG-014**: `_consecutive_negative` 通过 `personality.emotion.consecutive_negative` 持久化

### models/personality.py
- **AG-014(辅助)**: `EmotionalState` 新增 `consecutive_negative` 字段
- **PS-012**: 怨恨死亡螺旋修复——10 轮无 anger 触发宽恕机制（怨恨折半）
- **PS-014**: 基线漂移修复——`default_baseline` 弹性牵引
- **PS-009**: `joy_ceiling` 负值防护 `max(0.0, ...)`

### core/message_handler.py
- **MH-003**: Agent 2 多轮执行包裹 try/except，异常降级到 Agent 3

### core/tool_agent.py
- **TA-005**: retry 时追加失败历史而非重建 messages
- **TA-007**: 区分"解析失败"和"执行失败"类型

### core/provider.py
- **PR-002**: 连接池限制 `HTTPAdapter(pool_connections=5, pool_maxsize=10)`
- **PR-004**: 429 限流解析 `Retry-After` 头
- **PR-008**: 流式响应超时保护

### core/context_manager.py
- **CM-001**: `_MODEL_CONTEXT` 180000 → 131072（128K，与实际模型窗口一致）

### core/async_utils.py
- **AU-001**: 模块级单例 `ThreadPoolExecutor(max_workers=4)`
- **AU-002**: 超时时 `future.cancel()` 清理

### core/personality.py
- **PE-004**: 加载前备份 `.bak`，JSON 损坏时提示
- **PE-005**: `EmotionalState.from_dict()` 包裹 try/except

### storage/repository.py
- **R-005**: `search_facts` else 分支补全 `AND fact_type='user_fact' AND session_id=?`
- **R-017**: `upsert_relationship` 包裹 `BEGIN...COMMIT` 保持原子性

### storage/database.py
- **S-005**: `get_connection()` 添加 `@deprecated` 警告

### memory/retrieval.py
- **RT-003**: `health_check` 结果缓存变量（避免同次查询调用两次）
- **RT-010**: `_merge_unique_experiences` 添加 `e.id is not None` 防护

### memory/embeddings.py
- **EM-001**: `EmbeddingCache` 添加 `threading.Lock` 线程安全

### memory/short_term.py
- **ST-004**: 移除无调用者死代码 `last_n_turns_content`

### doc/v05-plan/week-1-hemostasis.md
- 清理重复的 "Day 3-4：安全关键 P1（9 个）" 段落

## 测试
- 全量测试 290 用例通过
- pytest tests/ -v
