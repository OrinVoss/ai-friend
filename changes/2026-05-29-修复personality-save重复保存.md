# 修复 personality.save 重复保存

**时间**：2026-05-29

## 修改文件

- `core/agent.py` — 移除 `_react_loop` 中的 `personality.save()`

## 修改原因

Fix #73：CLI 路径中 `_react_loop` 和 `_on_reflect` 各自在 `turn_count % 10 == 0` 时调用 `personality.save`，同一轮保存两次。

Web 路径 `WebAgent.process_message` 也有 save（每消息一次，#44 待修）。

## 修改内容

- `_react_loop` 不再调用 `personality.save`（由上层调用者负责）
- CLI 路径：`_on_reflect` 每 10 轮保存
- Web 路径：`WebAgent.process_message` 每次保存
- 注释标注各路径的保存责任
