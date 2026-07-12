# 修改记录：Web 安全性审查（第3轮）

## 修改文件

- `doc/round03-web-security.md`（新增）

## 修改原因

执行项目计划中的第3轮安全性审查，聚焦 Web 安全十大维度：XSS、CSRF、会话固定、点击劫持、CSP、CORS、敏感信息暴露、WebSocket 安全、速率限制、输入验证。

## 修改内容摘要

- 对 `web/server.py`、`web/session.py`、`web/static/index.html`、`web/static/app.js` 及相关后端组件进行全面安全审查
- 共发现 23 项安全问题：严重 2 项、高危 5 项、中危 10 项、低危 6 项
- 输出约 6000 字审查报告，包含文件路径、行号、风险评级、攻击场景和修复建议
- 关键发现：
  - REST API 和 WebSocket 均缺失 CSRF 防护
  - Session ID 完全由客户端控制，无过期机制
  - 完全缺失 CSP、X-Frame-Options、速率限制
  - WebSocket 无 Origin 校验、无消息大小限制
  - LLM 响应存在存储型 XSS 攻击链风险
  - 错误消息直接反射可能泄露系统路径和数据库结构
