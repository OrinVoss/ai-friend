# Web会话状态数据流审查报告

**日期**: 2026-05-31
**审查文件**:
- `web/session.py`
- `web/server.py`
- `core/agent.py`
- `core/message_handler.py`
- `core/inner_drive.py`
- `core/personality.py`
- `models/personality.py`
- `memory/short_term.py`
- `memory/long_term.py`
- `memory/retrieval.py`
- `memory/consolidation.py`
- `storage/repository.py`
- `storage/database.py`
- `core/proactivity.py`
- `core/sleep_manager.py`
- `core/context_manager.py`
- `core/tool_agent.py`
- `config.py`
- `web_main.py`

**输出报告**: `doc/round02-web-session-flow.md`

## 修改原因

对 Web 端会话状态的数据流进行深度审查，跟踪从会话创建、消息处理、状态更新到保存的完整流程，识别状态泄漏、竞态条件和资源泄漏。

## 关键发现

### 高风险问题（7个）
1. **HR1**: 全局情绪状态共享 —— 所有会话共用同一个 `personality.json`
2. **HR2**: 睡眠状态全局共享 —— 所有会话共用同一个 `.sleep_state` 文件
3. **HR3**: Proactive Task 的 WebSocket 竞争和消息错发
4. **HR4**: `cleanup_old` 不完整 —— 只清理 `_sessions`，不清理 `_proactive_tasks` 和 `_active_ws`
5. **HR5**: HTTP API 与 WebSocket 共用会话但无并发控制
6. **HR6**: 长期记忆数据库无会话隔离 —— 所有会话共享同一张表
7. **HR7**: 情绪事件记录未按会话隔离

### 中风险问题（5个）
1. **MR1**: WebSocket 断开时 proactive task 的取消不是立即生效的
2. **MR2**: HTTP API 的 `session_id` 默认为 `"default"` 导致冲突
3. **MR3**: `ConversationBuffer` 恢复历史时不区分会话
4. **MR4**: `Agent._tool_call_history` 可能包含敏感信息
5. **MR5**: `ProactivityManager` 的速率限制层级不明确

### 低风险问题（4个）
1. **LR1**: `SessionManager._lock` 是 `threading.Lock` 而非 `asyncio.Lock`
2. **LR2**: `WebAgent` 的 provider 是 `KimiProvider` 但配置默认是 DeepSeek
3. **LR3**: `_proactive_loop` 中的 `sleep_cooldown` 是整数递减而非时间戳比较
4. **LR4**: WebSocket 异常处理过于宽泛

## 修复优先级

- **P0（立即修复）**: HR1, HR2, HR6
- **P1（本周修复）**: HR3, HR4, HR5, HR7
- **P2（下周修复）**: MR1-MR5
- **P3（可选优化）**: LR1-LR4
