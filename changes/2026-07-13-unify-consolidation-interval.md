# 统一 Web 与 CLI 模式的 consolidation 触发间隔

## 问题
Web 模式和 CLI 模式的 consolidation 触发间隔不一致：

| 模式 | 触发条件 |
|---|---|
| Web 模式 | `core/agent.py` 里硬编码了 `if self.turn_count % 3 == 0`，所以是 **3 轮** |
| CLI 模式 | 使用 `should_consolidate()`，读取 `config.consolidation_interval = 5`，所以是 **5 轮** |

这导致 Web 下 consolidation 和关系指标更新比 CLI 更频繁，行为不一致。

## 改动
- `core/agent.py`
  - 将硬编码的 `turn_count % 3 == 0` 改为读取 `self.config.consolidation_interval`。
  - 增加 `interval > 0` 保护，避免配置为 0 时无限触发。

## 效果
Web 和 CLI 模式现在统一使用 `config.consolidation_interval`（当前为 5 轮）触发 consolidation，行为一致。

## 验证
- `python -m py_compile core/agent.py` 通过。
