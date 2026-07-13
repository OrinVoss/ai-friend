# 修复睡眠回复（梦话）未持久化

## 问题

AI 处于睡眠状态时，用户发消息会收到随机梦话回复（如 "zzz...ZZZ...💤"）。这些回复只在内存中临时返回，没有写入 `short_term` 对话缓冲和长期记忆数据库，导致刷新页面后梦话消失。

## 修复

`core/message_handler.py` 的 `handle_message` 睡眠分支：
- 在返回睡眠回复前，先把回复内容写入 `short_term.add_turn("assistant", sleep_reply, metadata={"sleep": True})`
- 同步写入数据库 `ltm.repo.insert_turn_sync(..., "assistant", sleep_reply, ...)`
- `turn_count` 正确递增

## 测试

`tests/test_message_handler.py`：`test_handle_message_sleeping` 新增断言，验证 assistant 睡眠回复也被持久化。
