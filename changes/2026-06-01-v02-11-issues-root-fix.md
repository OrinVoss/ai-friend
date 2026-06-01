# 2026-06-01 — v0.2 11 issue 根本修复

## 修改文件

- **tools/notify_tool.py** — #150 PowerShell injection escape ($ ` " ')
- **tools/search_tools.py** — #150 Grep ReDoS: nested quantifier detection + 500 char limit
- **tools/web_tools.py** — #155 SSRF: _is_safe_url() blocks private/loopback IPs + localhost
- **web/server.py** — #158 WebSocket Origin validation; #176 100KB message size limit
- **web/session.py** — #148 Session TTL 24h auto-GC
- **core/personality.py** — #153 atomic save (.tmp → os.replace)
- **storage/database.py** — #157 WAL checkpoint on close + integrity_check on open; #154 busy_timeout=5000
- **core/agent.py** — #165 degradation: 3 consecutive tool failures → skip tools

## 解决的 issue

| # | 标题 | 修复 |
|---|------|------|
| #148 | 数据丢失 + Session TTL | 24h TTL 自动清理 |
| #150 | 命令注入 + ReDoS | PowerShell escape + 正则嵌套检测 |
| #153 | personality 写入不原子 | .tmp→os.replace |
| #154 | 数据库连接池 | PRAGMA busy_timeout=5000 |
| #155 | API Key 泄露 + SSRF | URL 内网 IP 检测 |
| #157 | 数据库可靠性 | WAL checkpoint + integrity_check |
| #158 | WebSocket Origin | Origin 头白名单 |
| #159 | 情绪事件不持久 | to_dict/from_dict 已包含 emotion_events |
| #162 | 异步桥接 | core/async_utils 已统一 |
| #165 | 降级模式 | 3 次失败→跳过工具 |
| #176 | 消息大小限制 | 100KB limit + proactive task cleanup |

## 测试
272 passed
