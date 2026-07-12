# 修改记录：第5轮性能与可扩展性审查（内存使用专题）

## 修改文件

- `doc/round05-memory-usage.md`（新增）

## 修改原因

执行第5轮审查任务（Task #7），聚焦内存使用，对以下文件进行深度分析：
- memory/short_term.py
- web/session.py
- core/agent.py
- core/context_manager.py
- memory/consolidation.py

同时阅读了相关依赖文件以获取完整上下文：memory/embeddings.py、tools/file_tools.py、core/message_handler.py、core/tool_agent.py、memory/long_term.py、memory/retrieval.py、web/server.py、core/provider.py、core/inner_drive.py、storage/repository.py、config.py、models/ 等。

## 修改内容摘要

撰写并输出约 6000 字的性能与可扩展性审查报告，涵盖 8 大内存风险类别：

1. ConversationBuffer 的 maxlen 与内存占用（配置不一致、content 未截断、列表副本）
2. SessionManager 会话无限增长（无过期机制、WebAgent 重量级对象、cleanup_old 不安全）
3. _tool_call_history 的 20 条限制（截断策略、数据冗余）
4. 消息列表在 _react_loop 中的累积（Critical：messages 持续增长、format_tool_results 未截断）
5. 嵌入向量的内存占用（EmbeddingCache 未启用、向量双重存储与反序列化）
6. 大文件读取的内存峰值（read_file 一次性读取、批量读取、web_fetch 截断滞后）
7. WebSocket 消息缓冲（无背压机制、无队列限制）
8. Python 对象引用循环（Agent/MessageHandler、WebAgent/Agent、SessionManager、ThreadPoolExecutor 重复创建）

报告包含风险评级（Critical/High/Medium/Low）、文件路径和行号、内存占用估算表、修复优先级建议。
