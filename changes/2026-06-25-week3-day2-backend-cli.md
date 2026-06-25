# 2026-06-25 Week 3 Day 3-4 — 后端/CLI/配置 10 项修复

## 修改原因

继续 Week 3 低风险项：display.py CJK 正确性、cli.py 配置穿透、config.py 验证
与环境变量补全、main.py/web_main.py 异常处理与 MA-005。

## 修改文件与摘要

- `ui/display.py` — DP-002 CJK 字宽估算（`_is_cjk` + `_cjk_aware_width`）；
  DP-004 CJK 感知换行（`_cjk_break`）；DP-010 `\n` 从 sentence-ending 集合移除，
  避免双重延迟。《word_wrap》新增 CJK fast-path/slow-path 分支。
- `ui/cli.py` — CL-001 `ConsoleInterface.__init__` 接收 `typing_speed` 参数并传入
  `DisplayEngine`，使用 config 中的实际速度值。
- `config.py` — CF-002 `_validate()` 检查 temperature/timeout/max_tokens/embedding_dim
  范围并告警；CF-009 补全 ALL 12 环境变量映射（含类型转换）；CF-006 默认值移除
  `D:\音乐`/`D:\桌面` 硬编码 Windows 路径。
- `main.py` — MA-005 `await db.close()`；MA-001 `main()` 外层 try/except 友好错误。
- `web_main.py` — MA-001 try/except + 友好错误。
- `doc/v05-plan/week-3-completion.md` — 新加 10 项标记 ✅

## 验证

- `python -m py_compile ui/display.py config.py main.py ui/cli.py web_main.py` ✅
- `python -m py_compile *.py core/*.py memory/*.py storage/*.py tools/*.py web/*.py models/*.py prompts/*.py ui/*.py` ✅
