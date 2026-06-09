# 2026-06-01 — Week 1 remaining fixes: #209 #212 #241

## 修改文件

- **tools/file_tools.py** — #209: `_path_in_allowed` 改用 `os.path.realpath` + `os.sep` 边界检查
- **tools/search_tools.py** — #209: `_resolve_search_path` 同上
- **tools/web_tools.py** — #241: `urlparse` 检查 scheme，拒绝非 http/https，修复 `//example.com`
- **web/server.py** — #212: lifespan shutdown 调用 `session_manager.shutdown()`
- **web/session.py** — #212: 新增 `shutdown()` — 保存所有 personality、cancel proactive tasks、清空 sessions

## 修复的 issue

| # | 问题 | 修复 |
|---|------|------|
| #209 | 符号链接白名单绕过 | 3 文件 abspath→realpath |
| #212 | lifespan shutdown 空操作 | 保存 session + clean up |
| #241 | web_tools URL 协议漏洞 | urlparse 校验 |
