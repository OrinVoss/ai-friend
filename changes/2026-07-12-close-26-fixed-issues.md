# 关闭 26 个已修未关 issue

经逐一代码验证，以下 26 个 issue 在当前版本中已修复，关闭：

## Bug 修复
- #214 — repository session_id 过滤（全部 10 个查询/写入方法已加）
- #182 — ReAct 循环修复（add_to_history、max_tokens、空回复兜底）
- #180 — 梦境生成 async（SL-010）
- #170 — CJK token 估算系数修正 + O(k²) 消除
- #169 — 情绪驱动睡眠检测
- #111 — 情感分析单次调用
- #120 — CLI _reset_react
- #150 — NotifyTool 注入防护（Batch 9）
- #165 — 工具降级断路器
- #163 — 主动评分情绪感知

## 功能实现
- #66 — 分层反思（L1/L2/L3）
- #64 — 主动内在驱动力（InnerDriveAgent.assess_proactive）
- #63 — 人格特质全链路渗透
- #7 — 情绪对话节奏（半衰期+衰减率）
- #67 — 虚假记忆矛盾检测（FactChecker）
- #52 — ARIA/键盘导航（Batch 10）
- #8 — 人格特质注入 prompt

## 质量改进
- #249 — short_term 死代码清理
- #250 — long_term 重复定义清理
- #259 — cli_controller 多轮 tool execution
- #266 — personality save 原子写入 + .bak

## 安全/架构
- #155 — API 密钥泄露防护（.gitignore）
- #154 — DB schema 会话隔离（session_id 列）
- #46 — 线程池单例（max_workers=4）

## 其他
- #50 — 文档完善（doc/ 15+ 文件）
- #25 — 测试体系（298 测试用例）

## 关闭 Issue
#214 #182 #180 #170 #169 #111 #120 #150 #66 #52 #67 #64 #63 #7 #50 #46 #165 #163 #155 #154 #8 #25 #249 #250 #259 #266
