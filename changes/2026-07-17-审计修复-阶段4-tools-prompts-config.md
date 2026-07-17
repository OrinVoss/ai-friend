# 审计修复·阶段 4：tools / prompts / config 清理

日期：2026-07-17

来源：`doc/refactor/audit-report-2026-07-17.md`（#273/#281/#282/#270/#271/#181 + L-02/L-03/L-05/L-07/L-09）。

## 修改的文件

- `tools/traits.py`（#273）：`ToolRegistry.to_json_schema()` 的 `calls.items`
  改为 per-tool `oneOf` 变体——每个工具一项，`name` 用单值 enum、`arguments`
  注入该工具自己的 `parameters_schema()`；顶层加 `"required": ["calls"]`；
  删掉空工具时硬编码 `["web_fetch"]` 的死回退（无工具回退为泛 `{"type": "object"}`）；
  docstring 改为如实描述。调用方 `core/tool_agent.py:101,160` 无需改动。
- `prompts/system.py`（#281）：`_build_internal_tools_block` 不再硬编码
  `names=["recall", "remember"]` 与 recall 示例，工具清单与 `<tool_call>` 示例
  都从传入 registry 派生（新增 `_build_tool_call_example`，按 schema 的
  required/default/类型生成占位参数）；文件顶部加 `import json`。
- `prompts/templates.py`（#282）：
  - `FACT_EXTRACTION_PROMPT` 的 fact_type 文案同步为
    `user_fact / agent_fact / system_fact`（对齐 `tools/memory_tools.py` 三枚举）。
  - `REFLECTION_PROMPT` 的 `{relationship[trust]:.2f}` dict 下标格式串改为
    `{rel_trust:.2f}` 等简单占位符——下标缺键会让 `safe_format` 整体失败、
    LLM 看到未格式化模板原文。
  - `safe_format` 函数体内的 `import logging` 挪到模块顶部。
- `memory/consolidation.py`（#282 配套）：`_generate_reflection` 调用方先用
  `relationship.get(..., 0.3)` 取出数值，再以 `rel_trust/rel_familiarity/rel_intimacy`
  传入。
- `tools/search_tools.py`（#270）：删 `import signal`、`GREP_TIMEOUT`、
  `GREP_RESULTS_LIMIT`、`MAX_RESULTS_DISPLAY/MAX_HEADER_LINES/SORTED_DIRS_MAX/SORTED_FILES_MAX`
  （均定义未用）；去掉 grep 截断提示 f-string 的多余 f 前缀。
- `tools/music_tool.py`（#271）：
  - 删未用导入 `subprocess`、`pathlib.Path`。
  - 新增 `MUSIC_SCAN_LIMIT = 10_000` 常量；`_collect_songs`/`_find_matches` 的
    `files_scanned` 只对音频文件计数（非音频不再消耗扫描额度导致漏歌）。
  - 安全修复：`MusicListTool.execute` 的路径白名单改为 `realpath` +
    `os.sep` 边界检查（仿 `file_tools._path_in_allowed`），`D:\音乐2` 这类
    同前缀兄弟目录不再能绕过 `D:\音乐`。
- `tools/file_tools.py`（#181）：删 `_build_tree` 死变量 `prefix_stack`；
  去掉"二进制文件"报错 f-string 的多余 f 前缀。
- `config.py`：env_map 新增 `"AI_FRIEND_PERSONALITY_FILE": "personality_file"`（L-05）；
  删重复的 `"AI_FRIEND_LOG_LEVEL": "log_level"`（L-09）。
- `core/prompt_cache.py`（L-02）：`_store` 改为 `OrderedDict`，容量上限
  `MAX_ENTRIES = 200`，写入超限即 FIFO 淘汰最旧 key（人格文件每次保存产生新
  personality_version key，旧 key 不再无限堆积）。
- `core/agent.py`（L-03）：删只写不读的 `_react_messages`（`__init__` 初始化
  与 `_reset_react` 重置行）；删 `_react_loop` 内与模块级重复的
  `from core.dispatcher import ...`。
- `models/personality.py`（L-07）：`_turns_without_anger` 由 getattr 惰性属性
  改为 dataclass 字段 `turns_without_anger: int = 0`，随 `to_dict/from_dict`
  持久化（旧文件缺字段取默认值 0），`shift()` 三处赋值点改名。

## 测试

- `tests/test_dispatcher.py` `TestJSONSchema`：per-tool schema 注入、
  `required: ["calls"]`、names 过滤、空工具无 web_fetch 死回退（#273）。
- `tests/test_prompt_instructions.py` `TestInternalToolsBlock`：block 内容随
  registry 变化、示例从首个工具 schema 派生、空 registry 返回空串（#281）。
- `tests/test_music_tool.py`：扫描限额只数音频（patch `MUSIC_SCAN_LIMIT`）、
  同前缀兄弟目录绕过被拒、子目录放行（#271）。
- `tests/test_prompt_cache.py`：第 201 条写入淘汰最早 key、命中不刷新 FIFO 顺位（L-02）。
- `tests/test_emotional_state.py`：`turns_without_anger` 序列化往返、旧文件默认值、
  `shift()` 累加计数（L-07）。
- `tests/test_config.py`：`AI_FRIEND_PERSONALITY_FILE` env 覆盖生效、缺省用默认（L-05）。
- `tests/test_cli_controller.py`：同步删除 `_react_messages` 相关断言（L-03）。

## 验证

- `python -m pytest tests --ignore=tests/real_api -q` → 573 passed, 2 skipped（全绿；
  基线 557 + 新增 16 个测试）。
