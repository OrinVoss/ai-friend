# 修复 issue #366：inner_drive 四处重复 prompt 装配收敛

## 修改的文件
- `core/inner_drive.py`

## 修改原因
assess / review / re_decide / assess_agent3_intent 四处各有约 13 行逐字重复的 `build_inner_drive_prompt(...)` 装配，差别仅在 messages。

## 修改内容
- 新增 `_build_sys_prompt()` 私有方法，统一装配 + prompt_cache 统计日志（cache_tag 区分来源）。
- 四处调用点收敛；清理各处不再使用的局部 import 与多余 conv_hist。
- 验证：`pytest -k "inner_drive or inner or drive"` 90 passed, 2 skipped。
