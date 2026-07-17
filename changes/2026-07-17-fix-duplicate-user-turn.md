# 修复用户消息重复入库（刷新后气泡成双）

现场报告（2026-07-17）：Web 端发一条消息，刷新后变成两条一模一样的消息。

## 根因

用户消息被**重复插入两次**：

1. `MessageHandler.handle_message()` 入口处 `a.add_turn("user", user_input)`（message_handler.py:203）
2. `_run_agent3()` 里再次 `a.add_turn("user", user_input)`（原 message_handler.py:477）

两次插入同 turn_number、同内容 → 数据库出现两条一模一样的用户行，前端刷新从 DB 加载历史时显示为重复气泡。短记忆 buffer 同样被污染（LLM 上下文里用户消息也出现两遍）。

`_run_agent3` 的所有调用方（`handle_message` 直调、`_handle_agent3_intent` 回路）都已经在入口持久化过用户消息，该行的 `add_turn` 纯属重复。

## 修复

- `core/message_handler.py`：删除 `_run_agent3` 中的 `a.add_turn("user", user_input)`，加注释说明唯一持久化点在 `handle_message`
- `tests/test_message_handler.py`：新增 `test_handle_message_persists_user_turn_once`——断言一次对话用户消息只 `add_turn` 一次

## 历史数据清理（可选）

已入库的重复行可用（**先停应用、先复制 db 文件备份**）：

```sql
DELETE FROM conversation_turns
WHERE id NOT IN (
    SELECT MIN(id) FROM conversation_turns
    GROUP BY session_id, turn_number, role, content
);
```

该 bug 的签名是「同 session + 同 turn_number + 同 role + 同内容」，正常对话不会撞这个组合（user/assistant 同 turn_number 但 role 不同）。

## 测试

- 新增 1 用例通过
- 全量：`python -m pytest tests --ignore=tests/real_api -q` → **467 passed**（基线 466）
