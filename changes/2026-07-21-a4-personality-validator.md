# A4：人格校验器 + .bak 时机修复

日期：2026-07-21

## 背景

`systems/personality.md`：人格文件零校验——拼错的字段名/特质名被 `from_dict` 静默丢弃；`.bak` 时机错误（读前复制，把损坏文件覆盖到备份上）；损坏文件静默退默认人格（整个角色人设无声丢失）。

## 改动

- **`core/personality_validator.py`（新建）**：`validate_personality_data` / `validate_personality_file` 返回问题列表（warning 级不抛异常）。检查：未知顶层字段、未知 personality 字段（疑似拼写错误）、name 缺失、trait 越界/不可解析、emotional_baseline 结构、decay_rate 越界、emotional_state 类型。
- **`core/personality_manager.py::load_role`**：加载前校验，每个问题一条 `[personality.validate]` warning——手改 JSON 的错误从此可见。
- **`core/personality.py::load`**（PE-004 时机修复）：
  - `.bak` 从「读前复制」改为「**解析成功后刷新**」——`.bak` 始终是 last-known-good，不会再把损坏文件复制到备份上
  - 主文件损坏时**先从 `.bak` 恢复**（之前直接退默认）；`.bak` 也没有或同样损坏才退默认人格

## 测试（`tests/test_personality_validator.py`，+10）

- 校验器：合法通过、未知顶层字段、拼写错误、name 缺失、trait 越界/不可解析、baseline 结构、文件不可解析
- `.bak`：损坏主文件→备份不被覆盖且成功恢复、无备份→退默认

## 验证

- 全量 `pytest tests --ignore=tests/real_api -q`：**784 passed + 2 skipped**（774 → 784）

## 备注

- 「模板文件含情绪事件检查」「version 字段按版本解析」属 systems/personality.md 后续项（依赖格式定稿），未做。
