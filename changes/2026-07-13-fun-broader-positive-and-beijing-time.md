# fun 指标对更多正向情绪敏感 + 历史时间显示北京时间

## 问题
1. `fun`（`playfulness`）关系指标仍然没有变化。
   - 之前只让 `joyful`/`excited`/`surprised` 增加 fun，但常见主导情绪是 `trusting`/`engaged`/`content`，导致 fun 长期不动。
2. 历史变化面板显示的时间是 UTC，例如 `07/13 07:42`，而不是北京时间 `07/13 15:42`。

## 改动
- `memory/consolidation.py`
  - 扩大增加 `playfulness` 的情绪集合：
    - `{joyful, excited, surprised, content, engaged, anticipating, trusting}`
  - 负面情绪仍会降低 fun。
- `web/server.py`
  - `/api/status` 返回 `relationship_history` 前，把 SQLite 中的 UTC 时间戳转换为北京时间（UTC+8）。

## 效果
- `trusting` / `engaged` / `content` 等常见正向情绪也会推动 `fun` 增长。
- 历史变化面板显示 `07/13 15:42` 这样的北京时间。

## 验证
- `python -m py_compile memory/consolidation.py web/server.py` 通过。
- 重启服务后对话，触发 consolidation 时 `playfulness` 出现非默认值。
- `/api/status` 返回的时间戳为北京时间。
