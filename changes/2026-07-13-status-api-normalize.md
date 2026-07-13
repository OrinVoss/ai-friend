# 2026-07-13 修复 /api/status 数据格式

## 变更摘要
修复 Web 控制台「关系指标」和「历史变化」面板无数据的问题。

## 问题原因
- `/api/status` 直接透传 `LongTermMemory.get_relationship()` 和 `get_relationship_history()` 的原始结果。
- 数据库中关系维度使用 `playfulness`，而 UI 期望 `fun`。
- `relationship_history` 返回的是扁平列表（每条记录一个 dimension），UI 需要按时间戳聚合的记录。
- 新 session 的关系表为空时，前端显示 `--`。

## 修复内容
- `web/server.py` 的 `status_api`：
  - 对 `relationship` 做归一化，缺失维度默认 `0.3`，并将 `playfulness` 映射为 `fun`。
  - 对 `relationship_history` 按 `created_at` 聚合，每个时间点生成一条包含 `trust/familiarity/intimacy/fun` 的记录。

## 验证
- `python -m py_compile web/server.py` 通过。
- `python -m pytest tests/test_web_agent.py tests/test_message_handler.py -q`：23 passed。
- 启动服务后 `curl /api/status?session_id=default` 返回正确的关系指标和历史变化 JSON。

## 相关文件
- `web/server.py`
