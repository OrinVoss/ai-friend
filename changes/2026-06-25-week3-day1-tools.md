# 2026-06-25 Week 3 Day 1-2 — 工具层 15 项修复

## 修改原因

按 Week 3 计划从低风险工具层开始，修复 file_tools / search_tools / music_tool /
web_tools 共 15 项代码质量与安全性问题。

## 修改文件与摘要

- `tools/file_tools.py` — FL-001 NameError（`logger.debug` 引用未定义 `path`→`filepath`）；
  FL-002 `_get_allowed_roots` 缓存 60s；FL-005 目录列表过滤隐藏文件；FL-007 `readlines()`
  全量加载改为 `itertools.islice(f, limit)` 流式读取，大文件不再 OOM。
- `tools/search_tools.py` — SR-003 `os.walk` 加 10_000 文件上限；SR-004 删除死代码 `pass`
  及重复条件；SR-007 `any(skip in dirpath)` 子串误杀改为 `os.sep` 分割后精确匹配目录组件；
  SR-008 打开文本前先 `_is_binary()` 跳过二进制文件；SR-009 魔法数字替换为命名常量。
- `tools/music_tool.py` — MU-002 `os.walk` 遍历加 10_000 文件上限；MU-004 `_play()` 先
  `os.path.realpath` 再校验音频扩展名后调用 `os.startfile`，防止执行非音频文件。
- `tools/web_tools.py` — WT-001 模块级单例 `_session()` 复用 TCP+TLS 连接；WT-002 JSON-RPC
  `id` 改为 `uuid.uuid4().hex`；WT-003 API 调用加指数退避重试（1/2/4s，最多 3 次重试）；
  WT-004 `freshness` 参数通过 `_VALID_FRESHNESS` set 校验后再传入 API。
- `doc/v05-plan/week-3-completion.md` — 15 项全部标记 ✅

## 验证

- `python -m py_compile tools/file_tools.py tools/search_tools.py tools/music_tool.py tools/web_tools.py` ✅
