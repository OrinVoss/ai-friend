# 2026-07-13 修复午睡消息丢失 + last_activity 脏属性 + proactivity 转发

## 修改原因

1. 午睡/醒来消息通过 WebSocket 主动推送但未存入对话历史，
   刷新页面后消失。同时修复 `agent.last_activity` 脏属性（应是
   `last_activity_time`）导致的空闲时间计算不准。

## 修改文件

- `web/server.py` — 午睡消息推送后调用 `short_term.add_turn` +
  `insert_turn_sync` 持久化；`agent.last_activity` 统一为
  `last_activity_time`
- `core/agent.py` — 添加 `check_rate_limit` / `record_rate_limit`
  公有转发方法
