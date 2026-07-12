# 修改记录：资源泄漏与可靠性审查报告

## 修改文件
- `doc/round04-resource-leaks.md`（新建）

## 修改原因
执行第4轮代码审查：错误处理与可靠性审查，聚焦资源泄漏问题。

## 修改内容摘要
对 AI Friend 项目进行全面的资源泄漏与可靠性审查，覆盖数据库连接、requests.Session、ThreadPoolExecutor、asyncio.Task、文件句柄、内存、WebSocket、日志Handler等8大类别。

共识别 27 项问题，按风险等级分布：
- 严重 (Critical)：4 项
- 高 (High)：7 项
- 中 (Medium)：12 项
- 低 (Low)：4 项

关键发现包括：
1. Web端 Database 连接永不关闭（严重）
2. KimiProvider 流式响应连接可能泄漏（严重）
3. 默认 ThreadPoolExecutor 无上限（严重）
4. Proactive task 取消不彻底（严重）
5. setup_logging 重复添加 handler（高）
6. WebAgent 资源无显式释放（高）
7. tools/web_tools.py 每次调用新建 Session（高）

报告包含详细的文件路径、行号、风险分析和修复建议，并按 P0/P1/P2 优先级给出修复路线图。
