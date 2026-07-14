# 修复早上概率唤醒可能睡过头

## 问题

`sleep_manager` 的早上唤醒窗口是 7:00–10:00，但唤醒是概率性的（`random.random() < wake_chance`）。如果随机数一直没命中，10:00 之后窗口关闭，AI 就会一直睡下去，需要手动改 `.sleep_state` 文件才能叫醒。

## 修复

`core/sleep_manager.py` 的 `get_sleep_state()`：
- 在早上唤醒窗口末尾（9:30–10:00）把 `wake_chance` 强制设为 1.0，确保必然醒来
- 新增 10:00–11:00 的强制唤醒兜底窗口，如果 AI 还在睡，无条件叫醒

## 验证

```bash
python -m pytest tests/test_sleep_manager.py -v
# 6 passed
```
