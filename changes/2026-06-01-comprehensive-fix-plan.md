# AI Friend 全面修复方案

> 生成日期：2026-06-01 | 来源：23 子代理 × 48 份审查文档 × 全量代码审计
> 总发现问题：**525 项**（去重后）| 预估工时：~175h+

---

## 目录

1. [修复优先级速查](#1-修复优先级速查)
2. [按模块的所有修复项](#2-按模块的所有修复项)
   - [2.1 Storage 存储层](#21-storage-存储层)
   - [2.2 Memory 记忆层](#22-memory-记忆层)
   - [2.3 Agent Core 核心层](#23-agent-core-核心层)
   - [2.4 Infrastructure 基础设施](#24-infrastructure-基础设施)
   - [2.5 Personality/Emotion 人格情绪](#25-personalityemotion-人格情绪)
   - [2.6 Sleep/Proactive 睡眠主动](#26-sleepproactive-睡眠主动)
   - [2.7 Tools 工具层](#27-tools-工具层)
   - [2.8 Web 层](#28-web-层)
   - [2.9 Frontend 前端](#29-frontend-前端)
   - [2.10 Security 安全](#210-security-安全)
   - [2.11 CLI/UI 终端界面](#211-cliui-终端界面)
   - [2.12 Config/Startup 配置启动](#212-configstartup-配置启动)
   - [2.13 Prompts 提示词](#213-prompts-提示词)
   - [2.14 Models 数据模型](#214-models-数据模型)
   - [2.15 Cross-cutting 横切关注点](#215-cross-cutting-横切关注点)
3. [优先级总表](#3-优先级总表)
4. [按文件统计](#4-按文件统计)

---

## 1. 修复优先级速查

| 等级 | 数量 | 判定标准 |
|------|------|---------|
| **P0 🔴** | 18 | 数据丢失、运行时崩溃、可被利用的安全漏洞 |
| **P1 🟡** | 98 | 正确性缺陷、性能明显退步、安全纵深缺失 |
| **P2 🟢** | 210 | 代码质量、可维护性、测试增强 |
| **P3 ⚪** | 199 | 微优化、文档、日志、风格问题 |
| **合计** | **525** | |

---

## 2. 按模块的所有修复项

### 2.1 Storage 存储层

#### `storage/database.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| S-001 | 18 | `os.makedirs` 创建数据库目录用默认权限，Unix 下 0o777 | P1 | 添加 `os.chmod(dir, 0o700)` |
| S-002 | 21 | WAL 模式缺 `wal_autocheckpoint`，WAL 文件持续增长 | P2 | 添加 `PRAGMA wal_autocheckpoint=100` |
| S-003 | 23 | `busy_timeout=5000` 但仓库层无 SQL 级重试逻辑 | P2 | 添加指数退避重试包装器 |
| S-004 | 31-43 | `cursor()` 不自动 commit，与文档声称不符 | P1 | 补全文档或添加自动 commit |
| S-005 | 50-54 | `get_connection()` 暴露裸连接绕过锁 | P1 | 移除或改为 async 上下文管理器 |
| S-006 | 59-62 | `schema_version` 表创建但从不读写 | P1 | 实现版本化迁移 |
| S-007 | 67-93 | `user_facts`/`experiences` 中 `composite_score` 缺 `NOT NULL` | P2 | 添加 `NOT NULL DEFAULT 0.5` |
| S-008 | 70-100 | Schema 缺 CHECK 约束（布尔值、范围） | P2 | 添加 CHECK 约束 |
| S-009 | 120-150 | 初始 `relationship_metrics` 行在 migration 前插入 → 缺 `session_id` | P0 | 交换顺序：先迁移再插入 |
| S-010 | 133 | 动态 SQL 拼接缺白名单验证 | P1 | 添加 `ALLOWED_TABLES` 白名单 |
| S-011 | 159-167 | `close()` 不等活跃操作完成 | P1 | 添加 `_closing` 标志 |
| S-012 | 162 | WAL checkpoint 只发生在 close 时，运行时从不执行 | P1 | 定期执行 `PRAGMA wal_checkpoint(PASSIVE)` |

#### `storage/repository.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| R-001 | 17 | `repo.session_id` 全局单例可变属性 → 竞态数据污染 | P0 | 移除可变字段，方法显式传参 |
| R-002 | 37 | `ON CONFLICT` 用 `MAX` 覆盖矛盾修正的置信度 | P0 | 改用 `excluded.confidence` |
| R-003 | 42 | `recall_count` 在 upsert 时递增而非检索时 | P2 | 从 upsert 中移除，加到 search/get_active_facts |
| R-004 | 73-84 | `search_facts` else 分支 SQL 参数数与占位符不匹配 | P0 | `(session_id, limit)` → `(limit,)` |
| R-005 | 83 | `search_facts` 与 `get_active_facts` 的 session_id 处理不一致 | P1 | 统一 WHERE 条件 |
| R-006 | 101-104 | `update_fact_score` 缺 `commit()` → 重启丢失 | P0 | 添加 `await self.db.commit()` |
| R-007 | 106-109 | `increment_fact_recall` 缺 `commit()` | P0 | 添加 commit |
| R-008 | 111-117 | `deactivate_fact` 缺 `commit()` | P0 | 添加 commit |
| R-009 | 119-125 | `update_fact_confidence` 缺 `commit()` + 0.7 硬编码 | P0 | 添加 commit + 命名常量 |
| R-010 | 141-154 | `insert_experience` 缺 `commit()` + 缺 session_id 列 | P0 | 添加 commit + session_id |
| R-011 | 156-177 | `search_experiences` 两个分支都缺 `WHERE session_id` | P1 | 添加 session_id 过滤 |
| R-012 | 179-187 | `get_recent_experiences` 缺 `WHERE session_id` | P1 | 添加 session_id 过滤 |
| R-013 | 189-192 | `update_experience_score` 缺 `commit()` | P0 | 添加 commit |
| R-014 | 196-206 | `insert_reflection` 缺 `commit()` + 缺 session_id | P0 | 添加 commit + session_id |
| R-015 | 208-215 | `get_recent_reflections` 缺 `WHERE session_id` | P1 | 添加 session_id 过滤 |
| R-016 | 217-225 | `bulk_update_embeddings` f-string 拼接表名缺白名单 | P1 | 添加 `ALLOWED_TABLES` 白名单 |
| R-017 | 229-248 | `upsert_relationship` + 快照插入不是原子操作 | P2 | 用显式 BEGIN/COMMIT 包裹 |
| R-018 | 250-259 | `get_relationship_history` SQL 参数化不够优雅 | P3 | 传原始时间戳替代天数 |
| R-019 | 264-274 | `insert_turn` 无 `turn_number` 唯一性约束 | P2 | 添加 `UNIQUE(session_id, turn_number)` |
| R-020 | 276-285 | `get_recent_turns` 缺 `WHERE session_id` | P1 | 添加 session_id 过滤 |
| R-021 | 289-308 | `prune_facts` 缺 `WHERE session_id` | P1 | 添加 session_id 过滤 |
| R-022 | 310-327 | `prune_experiences` 缺 `commit()` + 缺 session_id 过滤 | P0 | 添加 commit + session_id |
| R-023 | 329-345 | `prune_reflections` 缺 `commit()` + 缺 session_id 过滤 | P0 | 添加 commit + session_id |
| R-024 | 349-361 | `_row_to_fact` 用 `r.keys()` 替代简单的 `in` | P3 | 简化为 `"fact_type" in r` |
| R-025 | 363-381 | `_row_to_experience`/`_row_to_reflection` 缺 `json.loads` 异常保护 | P2 | 添加 `try/except json.JSONDecodeError` |
| R-026 | 70-88 | `search_facts` LIKE 无索引 → 全表扫描 | P1 | 添加 FTS5 或复合索引 |
| R-027 | 298 | `prune_facts` 仅降级 composite_score 不降 confidence | P2 | 同步降低 confidence |
| R-028 | 17-21 | 同步包装器通过 `run_async` 创建新线程，Web 模式下额外开销 | P2 | 所有上层代码统一 async |

---

### 2.2 Memory 记忆层

#### `memory/short_term.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| ST-001 | 27 | `_next_id` 在锁外读取 → 竞态，相同 turn_id | P0 | 将 Turn 构造函数移入 `with self._lock:` 内 |
| ST-002 | 49 | `get_all_reversed` 文档称 "without extra copy" 但实际创建新列表 | P3 | 更新文档或返回只读迭代器 |
| ST-003 | 52 | `format_for_prompt` 参数 `max_chars` 实为 token 预算，内部乘以 0.6 | P2 | 重命名 `max_tokens`，移除魔法数字 |
| ST-004 | 81 | `last_n_turns_content` 属性无调用者 → 死代码 | P3 | 移除或改为 `format_for_prompt` 别名 |
| ST-005 | 24-36 | `Turn` 构造在锁外，非原子操作 | P1 | 移至锁内，保证 ID 生成 + 追加原子性 |

#### `memory/long_term.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| LT-001 | 21,105 | `store_fact` 两个同步包装器定义冲突（前向引用） | P1 | 删除第 21 行的前向声明 |
| LT-002 | 89-101 | `_build_context` 与 `MemoryRetriever` 逻辑重复，无调用者 | P2 | 移除或委托给 MemoryRetriever |
| LT-003 | 90-91 | `_build_context`关键词提取 `re.findall` 不含停用词过滤 | P3 | 与 `MemoryRetriever._extract_keywords` 对齐 |

#### `memory/retrieval.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| RT-001 | 32 | Layer 1 仅查 `is_active=1` 事实，剪枝后永久丢失 | P1 | 语义模式下添加 inactive 事实回退查询 |
| RT-002 | 34 | 反思无语义/关键词检索，仅按时间获取 | P2 | 添加 `_search_reflections_semantic()` |
| RT-003 | 39,58 | `health_check()` 在同一次 `retrieve_for_query` 中调用两次 | P1 | 调用一次，结果存入局部变量 |
| RT-004 | 46-49 | LLM 重排序失败时不截断 → 候选池保持 30 条 | P1 | 失败时截断到 15 条 |
| RT-005 | 102 | `_search_experiences_semantic` 回退返回 `all_exp` → 无关结果 | P1 | 返回 `[]`，由调用者处理 |
| RT-006 | 120,153 | query 被编码两次（一次 hybrid score、一次 experience） | P1 | `retrieve_for_query` 中编码一次复用 |
| RT-007 | 132,163 | `bytes_to_vec` 用默认 dim=512，不传实际 dim | P1 | 传递 `self._embed._dim` |
| RT-008 | 172 | `_keyword_score_single` 读 `f.composite_score` 但可能被另一线程陈旧值污染 | P1 | 仅从 DB 持久化字段算分 |
| RT-009 | 221 | LLM 重排序 `result.split(",")` 不处理中文标点/范围 | P2 | 改用 `re.findall(r'\d+', result)` |
| RT-010 | 229 | `_merge_unique_experiences` 合并时 `id is None` 的体验被视为相同 | P2 | None id 跳过去重或用摘要作键 |
| RT-011 | 71-102 | `retrieve_by_recall_tag` 与 `check_recall_tag` 完全重复 | P2 | 移除冗余方法 |

#### `memory/consolidation.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| CO-001 | 28-30 | `from memory.fact_checker` 导入在 `__init__` 内 | P3 | 移到模块顶部 |
| CO-002 | 65-120 | `consolidate()` 中过多 bare except → 异常信息丢失 | P1 | 用 `logger.exception()` 换掉 bare except |
| CO-003 | 118-123 | 部分失败时清空 pending_buffer → 已成功步骤数据丢失 | P1 | 保留 buffer，仅移除已成功处理的轮次 |
| CO-004 | 131-132 | `logger.info("Consolidation complete.")` 重复两次 | P3 | 删掉一行 |
| CO-005 | 150 | `analyze_sentiment` 注释与实现不完全匹配 | P3 | 更新注释 |
| CO-006 | 189 | FactChecker 循环中 N+1 查询：每个新事实单独调 `get_similar_facts` | P2 | 批量收集后一次调用 |
| CO-007 | 190-191 | `from models.memory import UserFact` 在 for 循环内 | P3 | 移到模块顶层 |
| CO-008 | 231-232 | `turn_range` 用 `min/max(t.turn_id)` 假设连续 ID | P2 | 排序或存实际轮次序列 |
| CO-009 | 377-398 | 关系维度只增不减 → 趋近 1.0，丧失区分度 | P2 | 添加衰减因子 |
| CO-010 | 386-388 | 情感分析仅分析 `pending_buffer[-3:]` 中末条用户消息 | P2 | 平均或取极值，或分析全部 |
| CO-011 | 412-449 | `_embed_new_items` 绕过 `cursor()` 锁管理器 | P1 | 使用 `self.ltm.repo.db.cursor()` |
| CO-012 | 414-449 | `_embed_new_items` 缺 `session_id` 过滤 | P1 | SQL 中添加 `WHERE session_id = ?` |
| CO-013 | 418 | `_embed_new_items` 在 sync 上下文里用 `with` 操作 `aiosqlite.Connection` → 属性错误 | P1 | 改为异步 |
| CO-014 | 422-432 | `_embed_new_items` f-string 拼接 SQL 缺白名单 | P1 | 添加表名白名单 |
| CO-015 | 35-47 | `should_consolidate` 中 `consolidation_interval=1` 可能每轮触发 | P3 | 无操作需求，为设计选择 |
| CO-016 | 55-60 | `add_pending` 在 CLI 端 `_on_reflect` 中重复调用（消重后仍调两次） | P1 | 移除 `cli_controller.py:290` 的重复调用 |

#### `memory/embeddings.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| EM-001 | 23 | `EmbeddingCache` 已集成但无线程锁 → 并发 `OrderedDict` 操作崩溃风险 | P1 | 添加 `threading.Lock` |
| EM-002 | 40-60 | API 返回维度与缓存不一致时筛选掉旧维度向量但下标可能错乱 | P1 | 维度变化时清空缓存 + 丢弃所有旧向量 |
| EM-003 | 74-83 | API 失败时未缓存文本生成零向量而非跳过 | P1 | 已修复 ✓ |
| EM-004 | 95-100 | `bytes_to_vec` 维度不匹配时抛 `ValueError` 中断整个检索 | P2 | 返回零向量 + 日志警告 |
| EM-005 | 111 | `health_check` `rsplit("/",1)[0] + "/health"` 硬编码路径 | P3 | 可配置或文档化 |
| EM-006 | 86-117 | `encode_single` 重复调用时在 encode 内部走缓存，但无命中率监控 | P3 | 添加命中率计数器 |
| EM-007 | 140-152 | `EmbeddingCache.set` 不限制单条向量内存 → 超长文本可能大向量 | P3 | 向量大小无实际风险，接受 |

#### `memory/fact_checker.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| FC-001 | 55-70 | `detect_contradiction` 中每个 existing_fact 单独调用 `self._embed.encode([text])` → N+1 | P1 | 批量编码所有 existing_facts 一次 |
| FC-002 | 88-104 | `resolve` 同步调 async repo 方法，静默无操作 | P0 | 改为 `async def` + `await` |
| FC-003 | 88-104 | `resolve` 总是衰减旧事实置信度，不验证新事实质量 | P2 | 仅 `new_fact.confidence >= old_fact.confidence` 时衰减 |
| FC-004 | 107-113 | `_cosine_sim` 纯 Python 实现而非 numpy，慢 ~10x | P3 | 用 `np.dot` 替换 |
| FC-005 | 39-46 | FactChecker 仅检查同 category+同 key 的显式矛盾 | P2 | 添加第三轮 LLM 矛盾检测 |

---

### 2.3 Agent Core 核心层

#### `core/agent.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| AG-001 | 87-88 | 同时创建 CliController + MessageHandler，违反按需创建 | P2 | 惰性初始化 |
| AG-002 | 119-181 | `_react_loop` 循环 10 次全工具调用失败后返回空字符串 | P1 | 空回复时生成兜底文本 |
| AG-003 | 122-123 | `from core.dispatcher import ...` 模块级已导入 → 死代码 | P3 | 删除 |
| AG-004 | 130-133 | 后续 ReAct 迭代（idx>0）用 `stream=False`，屏幕冻结无输出 | P2 | always stream 或发送心跳 token |
| AG-005 | 157-158 | 3 次假动作修正后仍接受 LLM 未修正文本作为最终回复 | P2 | 超限后使用硬兜底文本 |
| AG-006 | 162-169 | `_tool_call_history` 用 list + `[-20:]` 切片 | P2 | 改用 `deque(maxlen=20)` |
| AG-007 | 183-196 | `add_to_history=False` 时仍写 SQLite 并递增 turn_count → 状态不同步 | P1 | 写入也受 `if add_to_history` 控制 |
| AG-008 | 183-196 | `insert_turn_sync` 和 `turn_count += 1` 在 `if final_text:` 内但不在 if add_to_history 内 | P1 | 同上 |
| AG-009 | 199 | `_process_emotion()` 在 Web `_react_loop` 中调用但 CLI `_on_reflect` 中或缺 | P1 | CLI 路径中添加调用 |
| AG-010 | 214 | `_process_emotion` `KeyError` 可能从空 deque 的 `reversed()` 后的 for 循环中产生 | P3 | 处理空字符串情况 |
| AG-011 | 216-219 | `_consecutive_negative` 增减阈值与 `estimate_emotional_impact` 阈值有盲区 [-0.5,-0.3] | P2 | 对齐阈值 |
| AG-012 | 236-247 | 异常后不调 `_reset_react()` → 状态污染下轮 | P0 | `try/finally` 确保重置 |
| AG-013 | 58,179 | `_tool_call_history` append 无锁 → 多线程丢失 | P2 | 加锁或改用线程安全结构 |
| AG-014 | 73-80 | `_consecutive_negative` 不持久化 → 重启后重新估算 | P1 | 存入 EmotionalState，序列化 |
| AG-015 | 127 | `_max_tool_iterations=10` 过大，简单工具调用仍可 10 次 | P2 | 改为 5 或可配置 |

#### `core/message_handler.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| MH-001 | 100 | 仅 `tool_requests[0].description` 传给 Agent 2 → 丢失后续请求 | P1 | 传全部 ToolRequest |
| MH-002 | 104 | `ToolAttemptTracker` 每轮新建 → round_number 永远 0 | P0 | 创建在 while 循环前 |
| MH-003 | 105 | Agent 2 调用无 try-except → Provider 异常崩溃整个消息处理 | P1 | 添加 try/except |
| MH-004 | 127-130 | Agent 1 review 新记忆对 Agent 3 不可见（两套独立检索） | P2 | 将 review 记忆上下文传给 Agent 3 |
| MH-005 | 144-167 | Agent 2 多轮结果丢弃：只传最后一轮的 `tool_result` 给 Agent 3 | P0 | 传已合并的 `tool_records` |
| MH-006 | 270-272 | Web 路径 Agent 3 `tool_registry` 仅内部工具，CLI 路径可调外部工具 → 行为不一致 | P2 | 统一工具权限 |
| MH-007 | 274-291 | `_build_messages` token 估算只检查 `messages[-5:]` 非累计总量 | P0 | `running_total += estimate_tokens(t.content)` |
| MH-008 | 280 | `_build_messages` 中 `messages.insert(1, ...)` O(k²) 复杂度 | P2 | 用 `reversed(history)` 再 extend |
| MH-009 | 285 | 用户输入直接拼接 `f"用户输入：{user_input}"` 无转义 | P1 | 添加输入验证和过滤 |
| MH-010 | 288-289 | `estimate_tokens` 只取每条消息前 200 字符估算，失真 | P2 | 使用完整内容或增加截断长度 |
| MH-011 | 294-301 | `track_failures` 是模块级函数但只被 MessageHandler 使用 | P3 | 改为 MessageHandler 方法 |
| MH-012 | 302-312 | `overflow` 时插入摘要但已插入的旧消息不移除 | P2 | 重建 messages 列表 |
| MH-013 | 64-75 | 空用户输入通过完整三层 Agent 管道浪费 token | P2 | 提前返回 |

#### `core/inner_drive.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| ID-001 | 17-20 | `EXTERNAL_TOOL_NAMES` 与 `tool_agent.py:15-18` 重复定义 | P2 | 提取到公共模块 |
| ID-002 | 99 | Agent 1 持有 `_full_registry` → 可绕过 Agent 2 执行外部工具 | P0 | 创建隔离的内部 registry |
| ID-003 | 105-111 | `max_iterations` 超限后默认 `needs_external_tools=False` 静默跳过工具调用 | P1 | 默认 True 或返回用户友好提示 |
| ID-004 | 146 | `assess_proactive` 用 max_tokens=256 可能截断 | P3 | 增至 512 |
| ID-005 | 217-264 | `re_decide()` 无 try-except → Provider 异常崩溃 | P1 | 添加 try/except |
| ID-006 | 222 | `re_decide()` 不包含已尝试工具历史 → 可能重复建议失败工具 | P1 | 在 prompt 中包含尝试过的工具名 |
| ID-007 | 266-302 | `_parse_decision` 关键词匹配过于严格 → 假阴性 | P2 | 扩展触发关键词 |
| ID-008 | 309-311 | URL 正则 `[^\s一-鿿]` 不包括 CJK 标点 → URL 尾部带句号 | P3 | `rstrip` 添加 CJK 标点 |
| ID-009 | 353-358 | `_parse_proactive_intent` 关键词过于脆弱 | P3 | 扩展同义词集 |

#### `core/tool_agent.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| TA-001 | 15-18 | `EXTERNAL_TOOL_NAMES` 与 `inner_drive.py` 重复 | P2 | 提取公共常量 |
| TA-002 | 48-67 | `ToolAttemptTracker.round_number` 永不递增 → 无限重试 | P0 | MessageHandler 中设置 `tracker.round_number = round_num` |
| TA-003 | 116-120 | `ToolCallRecord.arguments` 永远空字典 → 无参数审计 | P2 | 从解析结果中提取实参 |
| TA-004 | 142-224 | `run_with_request` 空 calls 时 `last_failure` 不更新 → retry 显示 None | P1 | 设置失败原因 "未能解析出工具调用" |
| TA-005 | 172-179 | 每次 retry 重建 messages 而非追加 → LLM 看不到之前尝试 | P1 | 追加失败结果而非重建 |
| TA-006 | 181-182 | `self._provider.generate()` 无 try-except → 异常崩溃 | P1 | 添加 try/except 返回错误结果 |
| TA-007 | 142-224 | retry 混淆"解析失败"和"执行失败"，last_failure 信息不准 | P2 | 区分两种失败类型 |

#### `core/cli_controller.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| CC-001 | 148-157 | CLI 路径无 Agent 2 多轮循环（无 review/re-decide） | P2 | 提取共享编排函数 |
| CC-002 | 153 | 直接取 `drive_result.tool_requests[0]` 同 MH-001 | P1 | 传全部请求 |
| CC-003 | 199-205 | `_on_think` 异常时不调 `_reset_react()` | P0 | `try/finally` 确保重置 |
| CC-004 | 243 | off-by-one: `_react_iteration > _max_tool_iterations` 应改 `>=` | P1 | `>` -> `>=` |
| CC-005 | 258 | `contains_fake_action` 在 CLI 路径中误报（工具返回关键词匹配） | P2 | 引入 `tools_were_called` 标志 |
| CC-006 | 264-272 | 空 `current_response` 时用户看不到任何输出 | P2 | 添加兜底显示 |
| CC-007 | 289-290 | `_on_reflect` 合并后 `add_pending` → 下次合并重复处理 | P1 | 提前到合并前调用 |
| CC-008 | 296-305 | `_on_shutdown` 中 consolidate/save 无 try-except | P2 | 添加异常保护 |

#### `core/dispatcher.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| DI-001 | 50 | `json.loads(raw_json)` 无线大小限制 → LLM 可生成数 MB JSON | P1 | 超过 10KB 就跳过 |
| DI-002 | 68-75 | Tier 3 bare JSON 缺 `arguments` 类型验证 → `dict(args)` 崩溃 | P1 | 添加类型守卫 |
| DI-003 | 126-130 | `from core.async_utils import run_async` 在 for 循环 try 块内 | P3 | 移到模块顶部 |
| DI-004 | 130 | `execute_tool_calls` 中 `asyncio.run()` 循环调用 → 性能极差 | P0 | 改用共享线程池或 `run_coroutine_threadsafe` |
| DI-005 | 140-146 | `except Exception` 用 `str(e)` 丢失回溯信息 | P2 | 用 `logger.exception()` |
| DI-006 | 153-169 | `format_tool_results` 无输出长度限制 | P2 | 截断到 2000 字符 |
| DI-007 | 172-194 | `contains_fake_action` 关键词列表易绕过 | P2 | 扩展关键词或引入语义检测 |
| DI-008 | 191-194 | "工具返回"关键词匹配合法工具结果报告 → 误报 | P2 | 仅在 `tools_were_called=False` 时检查 |
| DI-009 | 197-212 | `_normalize_args` 缺 "path" 别名（LLM 用 file/target/filepath） | P2 | 添加别名映射 |

---

### 2.4 Infrastructure 基础设施

#### `core/provider.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| PR-001 | 14 | `max_tokens=2048` 构造默认值 vs `config.max_tokens=512` 不一致 | P1 | 显式传递 max_tokens |
| PR-002 | 25-26 | `requests.Session` 连接池无上限，session 永不关闭 | P2 | 配置 `HTTPAdapter(pool_connections=5)` |
| PR-003 | 57-80 | 未捕获 `ReadTimeout` / `ConnectTimeout` | P1 | 添加 `except requests.exceptions.Timeout` |
| PR-004 | 65-67 | 429 未读 `Retry-After` 头 | P1 | 读取 Retry-After 等待该时长 |
| PR-005 | 26 | `session.trust_env = False` 静默忽略 HTTP 代理环境变量 | P2 | 移除或文档化 |
| PR-006 | 37 | API endpoint URL 尾部有 `/v1` 时重复 → `v1/v1/chat` | P2 | 初始化时 strip `/v1` |
| PR-007 | 72-77 | `ChunkedEncodingError` / `StreamConsumedError` 在 `ConnectionError` 之后无法到达 → 死代码 | P2 | 调换 catch 顺序 |
| PR-008 | 82-134 | 流式响应 `resp.iter_lines()` 无超时 → 服务端挂起时永久挂起 | P1 | 每块添加超时 |
| PR-009 | 84,99 | `time.time()` 用做耗时测量 → 受系统时钟跳动影响 | P3 | 用 `time.monotonic()` |
| PR-010 | 86-87 | 流式响应在异常时不关闭 → 连接池泄漏 | P1 | `with self.session.post(...) as resp:` |
| PR-011 | 96 | `resp.json()` 无 try/except → JSONDecodeError 不触发重试 | P1 | 捕获并重试 |
| PR-012 | 107-128 | 流式响应无限累积 → OOM 风险 | P2 | 添加 `MAX_STREAM_SIZE=1MB` |
| PR-013 | 125-126 | 流式模式下 JSON decode 错误静默 continue | P3 | 添加 logger.debug |
| PR-014 | 87-92 | `verify=True` 隐式，无证书钉扎 | P2 | 显式 `verify=True` |

#### `core/context_manager.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| CM-001 | 7-8 | `_MODEL_CONTEXT=180000` 超实际窗口（128K）→ COMPRESS_THRESHOLD 永不触发 | P0 | 设为 131072 |
| CM-002 | 10-11 | `_TOKENIZER` 模块级无锁检查—设 | P3 | 初始化或 lru_cache |
| CM-003 | 27-35 | `estimate_tokens` 回退公式 CJK/1.5 误差大 | P2 | CJK/1.0, ASCII/4, 数字/3, 标点/2 |
| CM-004 | 27-35 | 回退公式 3 次独立遍历字符串 | P3 | 合并为一次遍历 |
| CM-005 | 46,62-70 | `_compressing` 布尔标志无锁 → 双线程同时压缩 | P1 | 用 `threading.Lock` 保护 |
| CM-006 | 62-98 | `compress()` 调用 `_short_term.clear()` 后 messages 列表不同步 | P1 | 压缩后重建 messages 保留最后 2-3 轮 |
| CM-007 | 95 | `compress()` 清空 short_term 后最近上下文丢失 | P1 | 保留最后 2-3 轮替代全清 |
| CM-008 | 86 | `text[-8000:]` 从尾部截断可能在消息中间 | P3 | 找到消息边界再截断 |

#### `core/async_utils.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| AU-001 | 26-27 | `ThreadPoolExecutor` 每次调用新建 → 开销大 | P1 | 用模块级单例 `max_workers=4` |
| AU-002 | 29-31 | Timeout 时 future 不取消 → 僵尸线程 | P1 | 调用 `future.cancel()` |
| AU-003 | 27 | timeout 不向协程内部传播 | P2 | 内部也用 `asyncio.wait_for(coro, timeout)` |
| AU-004 | 27 | 未处理 `RuntimeError` from `asyncio.run()` in executor | P3 | 显式 `asyncio.Runner` |

#### `core/sleep_manager.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| SL-001 | 14-31 | 全局 `.sleep_state` 文件所有 session 共享 | P1 | 按 session_id 命名或移除文件持久化 |
| SL-002 | 19,23,60,68,78,89 | `_sleeping` 无跨协程同步 → 竞态 | P1 | 添加 `asyncio.Lock` |
| SL-003 | 19 | init 时从文件加载后不与当前时间窗口校对 | P3 | 加载后调用 `get_sleep_state()` 校对 |
| SL-004 | 25-38 | `_load_save_sleep_state` bare except 隐藏磁盘错误 | P3 | 区分权限错误 |
| SL-005 | 29,37 | `except Exception as e:` 太宽泛 | P3 | 具体异常类型 |
| SL-006 | 40 | `get_sleep_state()` 同步调用但 `_proactive_loop` 中有 30s 延迟 → 验证间隙 | P2 | await 后重新校验 |
| SL-007 | 45-55 | `sleepiness` 忽略 anxious/angry/afraid 等情绪 | P3 | 扩展 if 链 |
| SL-008 | 58,65,73,84 | 时间窗口硬编码 | P2 | 提取到 Config |
| SL-009 | 73 | `13.16` 应为 `13.1667`（24 秒误差） | P3 | `13 + 10/60` |
| SL-010 | 96-119 | `generate_dream()` 同步阻塞 LLM 调用 | P2 | 改为 async def |
| SL-111 | 111-114 | 梦境不保存为 Experience → AI 不记得梦过 | P2 | 存为 Experience |
| SL-112 | 111-114 | `record_emotion_event` 可能因 intensity<0.6 丢弃梦境 | P1 | 绕过强度检查或强制记录 |
| SL-113 | 117-119 | `generate_dream` 异常在 DEBUG 级别日志 → 不可见 | P2 | 提到 WARNING |
| SL-114 | 59,67,77,88 | `random.random()` 无可控种子 → 不可测 | P3 | 注入 `random.Random` |

#### `core/proactivity.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| PR-001 | 18-19 | `_last_chat_time`/`_last_explore_time` 无锁保护 | P2 | 文档化或加锁 |
| PR-002 | 27-34 | `idle_thresholds` 不漏盖所有情绪 → 未列情绪默认 300s 可能不当 | P2 | 文档化默认值 |
| PR-003 | 35 | 怨恨只增加等待时间不降低主动意愿 | P2 | `score -= r * 0.2` |
| PR-004 | 40 | `base` 增长过慢（15 分钟才到 0.3 cap） | P2 | 分母从 900 改为 600 |
| PR-005 | 42 | `time_mod` 条件重叠（10-21 是 7-22 子集）但逻辑正确 | P3 | 简化表达 |
| PR-006 | 46-56 | `calculate_proactivity` 无 try-except → LTM 异常崩溃 | P2 | 添加 fallback score |
| PR-007 | 51-54 | `sentiment_mod` 关键词匹配脆漏 | P2 | 扩展词集或用分类器 |
| PR-008 | 56 | `goodbye` 不按 `t.role=="user"` 过滤 → 算了自己的消息 | P1 | 添加角色过滤 |
| PR-009 | 56 | `goodbye` 关键词"睡了""晚安"误报 | P2 | 分强/弱 goodbye 不同惩罚 |
| PR-010 | 59 | score cap 0.8 无文档说明 | P3 | 添加注释 |
| PR-011 | 66-92 | `pick_proactive_topic` 无去重无历史 → 话题重复 | P2 | 添加最后 5 个话题排除 |
| PR-012 | 68-69 | LTM 调用无 try-except → 数据库异常崩溃 | P2 | 添加保护 |
| PR-013 | 94-115 | `check_rate_limit("chat")` 在发送前就更新 `_last_chat_time` | P1 | 改为发送成功后更新 |
| PR-014 | 101 | `check_rate_limit("explore")` 同上 | P1 | 同上 |

---

### 2.5 Personality/Emotion 人格情绪

#### `core/personality.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| PE-001 | 30-36 | `estimate_emotional_impact` 阈值 ±0.3 vs 破防 ±0.5/0.1 盲区 | P2 | 对齐阈值 |
| PE-002 | 61-72 | humor/sass 影响 emotion deltas 但不影响 prompt 行为风格 | P2 | 将 trait 值注入 prompt 修饰语 |
| PE-003 | 80-91 | `apply_emotional_shift` → shift → decay 后记录 emotion event → 记录的是残余状态而非波峰 | P1 | decay 前记录或返回波峰快照 |
| PE-004 | 104-109 | JSON 损坏时完全重置为默认 → 情绪历史全部丢失 | P2 | 保留备份文件 `.bak` |
| PE-005 | 114 | `from_dict()` 在 try 块外 → TypeError 崩溃 | P2 | 包裹在 try/except 中 |
| PE-006 | 125-135 | `save()` 无 try/except → OSError 崩溃 | P1 | 添加 `except OSError` |

#### `models/personality.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| PS-001 | 36-70 | `EmotionalState` 默认值与 `PersonalityConfig.emotional_baseline` 隐耦合 | P2 | init 从 baseline 推导 |
| PS-002 | 42,310 | `decay_rate=0.05` 过慢 → VAD 维度粘性饱和 | P0 | 添加饱和反弹机制 |
| PS-003 | 47-55 | `sleepiness` 漏 anxious/angry/afraid 情绪 | P3 | 扩展情绪映射 |
| PS-004 | 67,239-269 | `emotion_events: list[dict]` 最松类型，无结构验证 | P2 | 改为 `list[EmotionEvent]` dataclass |
| PS-005 | 72-130 | `dominant_emotion` VAD 标签 "engaged" 阈值过高（v=0.1） | P3 | 调整 VAD 阈值 |
| PS-006 | 72-130 | `dominant_emotion` 中 "fear" 的情感名 "afraid" 与 prompt 行为块 "fearful" 不匹配 | P1 | 统一为 "afraid" |
| PS-007 | 98,114 | `dominant_emotion` 返回 "afraid"，但 `emotion_behavior` 不包含 "afraid"，行为描述丢失 | P1 | 统一键名 |
| PS-008 | 132-173 | `_cross_modulate` 顺序敏感，魔法数字多无注释 | P2 | 命名常量 + 文档步骤 |
| PS-009 | 170-173 | `joy_ceiling = 1.0 - r * 0.5` 当 `r > 2.0` 时为负数 | P1 | `max(0.0, 1.0 - r * 0.5)` |
| PS-010 | 175-208 | `shift()`、`decay()`、`_cross_modulate` 无锁 → 多线程竞态 | P1 | 添加 `threading.Lock` |
| PS-011 | 186-191 | `shift()` 用 `hasattr(self, key)` 校验 → 可覆盖方法和字段 | P0 | 替换为白名单 |
| PS-012 | 194-195 | 怨恨死亡螺旋（正反馈：愤怒→怨恨积累→减速衰减→愤怒维持） | P1 | 添加"宽恕"机制 |
| PS-013 | 210-237 | `decay()` 中积极/消极情绪硬编码目标值 0.5/0.1，与配置的 baseline 无关 | P2 | 关联 `baseline_valence` |
| PS-014 | 216-218 | 基线向 mood 单向漂移，mood 无锚定 → 基线永久改变（已从 +0.4 漂至 -0.27） | P1 | 添加向 default_baseline 的弹性牵引 |
| PS-015 | 225-226 | `target = 0.5 for joy/trust/anticipation else 0.1` 与 config baseline 无关 | P2 | 关联基线 |
| PS-016 | 228-229 | 怨恨衰减减速（`rate *= (1.0 - r * 0.5)`）加剧正反馈 | P1 | 限制减速上限 |
| PS-017 | 239-262 | `record_emotion_event` intensity<0.6 静默丢弃 → 弱情绪事件不记录 | P2 | 两级记录 |
| PS-018 | 247 | `primary_intensity < 0.6` 阈值过滤可导致梦境事件被丢弃 | P1 | 梦境强制记录 |
| PS-019 | 260-262 | `pop(0)` 替代 `deque` → O(n) 每 20 次 | P3 | 用 `deque(maxlen=20)` |
| PS-020 | 261-262 | FIFO 上限 20 → 梦境事件被用户交互事件挤出 | P1 | 分离 dreams 队列 |
| PS-021 | 271-274 | mood 单向累积无衰减目标 | P1 | 添加向 0.4 的缓慢衰减 |
| PS-022 | 276-286 | `to_dict()` 含 `dominant_emotion`（计算属性），`from_dict()` 过滤它 → 往返不一致 | P3 | 统一 |
| PS-023 | 289-310 | `PersonalityConfig` 所有字段无验证（name 空串、baseline 非法值） | P2 | 添加 `__post_init__` |
| PS-024 | 292-298 | 默认特质不包含 humor/sass → 这些 trait 代码对新安装无效果 | P2 | 添加 `Trait("humor", 0.7)` 和 `Trait("sass", 0.5)` |
| PS-025 | 313-322 | `Trait` 无范围验证 → `Trait("empathy", 999.0)` 可创建 | P2 | 添加 `__post_init__` 范围检查 |

---

### 2.6 Sleep/Proactive 睡眠主动

（见 2.4 Infrastructure 中的 `core/sleep_manager.py` 和 `core/proactivity.py` 条目）

---

### 2.7 Tools 工具层

#### `tools/web_tools.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| WT-001 | 66-68 | 每次调用新建 `requests.Session()` → 无连接复用 | P1 | 模块级单例 Session |
| WT-002 | 63 | JSON-RPC `"id"` 固定 1 → 违反规范 | P3 | `uuid.uuid4().hex` |
| WT-003 | 68 | HTTP 请求无重试 → 网络波动单次失败 | P1 | 添加指数退避重试 |
| WT-004 | 113 | `freshness` 不校验 enum | P3 | 校验后 fallback |
| WT-005 | 127-128 | URL 协议检查仅 `http://`/`https://` → `ftp://` 等绕过 | P1 | 拒绝非白名协议 |
| WT-006 | 165-166 | `"//example.com"` 协议相对 URL 变成 `https:////example.com` | P1 | strip `//` 再补前缀 |
| WT-007 | 175 | 结果解析可能返回 list/dict/string 多种格式，容错不足 | P2 | 处理多种格式 |
| WT-008 | 182 | 8000 字符截断无提示 → Agent 3 基于不完整信息回复 | P3 | 添加截断提示 |

#### `tools/file_tools.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| FL-001 | 27 | `logger.debug` 引用未定义变量 `path`（应为 `filepath`）→ 触发时 NameError | P1 | `path` → `filepath` |
| FL-002 | 31-48 | `_get_allowed_roots` 缺缓存 → 每次路径检查都读文件 | P2 | 缓存 + 时间戳检查 |
| FL-003 | 52-53 | `os.path.abspath()` 不解析符号链接 → junction 点绕过白名单 | P1 | 用 `os.path.realpath()` |
| FL-004 | 56 | `abspath` 前缀匹配缺尾部 `os.sep` → `D:\音乐` 可匹配 `D:\音乐fake` | P1 | 尾部追加 `os.sep` 再比较 |
| FL-005 | 108-132 | 目录列表暴露所有文件（含隐藏/系统文件） | P2 | 过滤隐藏文件 |
| FL-006 | 137-146 | TOCTOU 竞态：`getsize()` 和 `open()` 之间文件可改 | P3 | `read(MAX_FILE_SIZE+1)` 简化 |
| FL-007 | 146 | `f.readlines()` 全量加载 → 即使用户只要 limit 行 | P2 | 用 `itertools.islice` |

#### `tools/search_tools.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| SR-001 | 16 | `_resolve_search_path` 用 `abspath` 非 `realpath` | P1 | 用 `realpath` |
| SR-002 | 68 | `os.walk` 无 `followlinks=False` | P1 | 添加 |
| SR-003 | 72 | GlobTool 在 `os.walk` 中无文件计数上限 | P2 | 超过 10000 文件停止 |
| SR-004 | 76-78 | 第 1 个 `if fnmatch` 块含 `pass` 和重复条件 → 死代码 | P3 | 删除 |
| SR-005 | 164 | ReDoS 检测正则过于局限：漏 `(a|aa)+`、`(a*)*` 等模式 | P1 | 用 `regex` 库 + 2s 超时 |
| SR-006 | 169 | `GREP_TIMEOUT=5` 定义但从不在 `regex.search()` 上执行 | P1 | 在线程中执行并设超时 |
| SR-007 | 180-181 | 跳过目录用子字符串匹配 `"data" in dirpath` → 匹配 `my_data`、`data_modeling` 误杀 | P2 | `os.sep` 分割精确匹配 |
| SR-008 | 200 | GrepTool 用 `errors="ignore"` 打开 → 二进制文件产生误导性匹配 | P2 | 先检查二进制 |
| SR-009 | 214,223,234 | 魔法数字 `MAX_RESULTS * 3` 和 `MAX_RESULTS * 4` 无注释 | P3 | 命名常量 |

#### `tools/music_tool.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| MU-001 | 55 | `target.startswith(abspath(MUSIC_DIR))` 不解析符号链接 | P1 | 用 `realpath` |
| MU-002 | 64-77 | 遍历无文件计数上限 | P2 | 停止超过 N 首 |
| MU-003 | 77 | `break` 停在第 1 次 `os.walk` 迭代，注释说 "Only current dir" | P3 | 明确注释 |
| MU-004 | 152 | `os.startfile()` 执行任意文件类型 → 符号链接 `.mp3` 可指向 `.exe` | P1 | `realpath` 后验证类型 |

#### `tools/notify_tool.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| NT-001 | 48-49 | PowerShell 转义用 `` `' `` 错误，单引号字符串中反引号是字面量 → 注入仍有效 | P0 | `s.replace("'", "''")` |
| NT-002 | 68 | `except Exception: pass` 静默吞掉所有通知错误 | P1 | 添加 `logger.warning(...)` |
| NT-003 | 63 | `subprocess.run(..., timeout=10)` 超时后不 kill 进程 | P2 | 捕获 `TimeoutExpired` 后 kill |
| NT-004 | 33-38 | `duration` 参数定义了从未使用 | P3 | 从 schema 移除 |

#### `tools/traits.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| TR-001 | 39 | `async def execute()` 与所有 8 个同步实现冲突 → LSP 违反 | P1 | 基类改为同步 |
| TR-002 | 56-57 | `register()` 静默覆盖同名工具 | P3 | 覆盖时记录警告 |
| TR-003 | 82-95 | `to_json_schema()` 返回 `{"type": "json_object"}` 无结构约束 | P2 | 生成完整 JSON Schema |
| TR-004 | 7-17 | `ToolResult` 缺执行耗时、异常详情 | P3 | 添加 `elapsed_ms` 和 `exception` 字段 |

#### `tools/memory_tools.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| MT-001 | 44 | `RecallTool` 调 `self.retriever._extract_keywords`（私有方法） | P3 | 添加公共方法 |
| MT-002 | 38-70 | `RecallTool.execute()` 无 try/except | P2 | 添加异常保护 |
| MT-003 | 115 | `float(args.get("importance", 0.6))` → 传入 "high" 时崩溃 | P2 | 添加 `try/except ValueError` |

---

### 2.8 Web 层

#### `web/server.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| WS-001 | 17-18 | `config`/`session_manager` 模块级在导入时创建 | P2 | 移入 `lifespan` |
| WS-002 | 22-27 | `lifespan` shutdown 是空操作 → DB 不关闭、session 不保存 | P0 | 关闭所有 session、DB、WAL checkpoint |
| WS-003 | 29 | 无 CORS 中间件 | P2 | 添加 `CORSMiddleware` |
| WS-004 | 30 | `StaticFiles` 用相对路径 | P2 | `os.path.join(os.path.dirname(__file__), "static")` |
| WS-005 | 30 | `StaticFiles` 可能暴露隐藏/备份文件 | P2 | 过滤隐藏文件 |
| WS-006 | 39-54 | REST API 缺 Pydantic 验证 | P1 | 定义 `ChatRequest` 模型 |
| WS-007 | 41 | `session_id = body.get("session_id", "default")` → 匿名用户互相污染 | P1 | 无 session_id 时生成新 UUID |
| WS-008 | 43-44 | 空消息返回 HTTP 200 带 "error" 字段而非 400 | P3 | `raise HTTPException(400)` |
| WS-009 | 46 | REST API `agent.process_message()` 同步阻塞事件循环 | P1 | 包装 `run_in_executor` |
| WS-010 | 46-47,260 | REST + WebSocket 同时访问同一 WebAgent → 竞态 | P1 | 加 `asyncio.Lock` |
| WS-011 | 57-69 | `/api/status` 无身份验证 → 任何 session_id 可读取 | P1 | 添加速率限制和所有权验证 |
| WS-012 | 82-128 | `_split_segments` 与前端 `splitSegments` 逻辑不同步 | P3 | 同步或统一后端处理 |
| WS-013 | 131-142 | `_send_segments` 无 per-send try/except → 段间丢失 | P1 | 逐段保护 |
| WS-014 | 131-142 | 分段消息发新气泡而非追加到上一条 | P0 | 前端 `append` 标志 |
| WS-015 | 151 | 旧 proactive task 可获取新区 WebSocket → 消息发错客户端 | P1 | 添加生成计数检查 |
| WS-016 | 156-168 | `sleep_cooldown` 整数递减 120 次 ~30 分而非 10 分 | P2 | 改为时间戳 `time.time() + 600` |
| WS-017 | 165 | `ag._generate_dream()` 无 timeout → 挂起线程池 | P1 | 加 timeout |
| WS-018 | 216-222 | Origin 校验 `startswith("http://localhost")` → `localhost.evil.com` 绕过 | P1 | `urlparse(origin).hostname == "localhost"` |
| WS-019 | 217-219 | 允许 `"null"` origin 被沙箱 iframe 伪造 | P1 | 移除 "null" 白名单 |
| WS-020 | 226,255-256 | 未 init 时 `session_id` 为 None，回退 "default" | P1 | 要求先 init，缺省时生成新 ID |
| WS-021 | 230 | `receive_text()` 无 `max_size` → OOM 向量 | P1 | `max_size=102400` |
| WS-022 | 233 | `json.loads(raw)` 无 try/except → 无效 JSON 泄露到外层 | P2 | 添加专有异常处理 |
| WS-023 | 238-248 | 可重复 send init → 每个 init 创建新 proactive task | P1 | 添加状态机只允许一次 init |
| WS-024 | 244-245 | `str(e)` 发给客户端 → 泄露路径、SQL、API key | P1 | error code + logger.exception |
| WS-025 | 269-273 | bare `except Exception` 太宽泛（捕获 `KeyboardInterrupt`） | P1 | 具体异常类型 |
| WS-026 | 274-276 | 断开时销毁 session → 多标签页互相冲突 | P1 | 引用计数 |
| WS-027 | 29 | 无 `X-Frame-Options: DENY` → 点击劫持 | P2 | 添加安全标头 |
| WS-028 | 29 | 无 Content-Security-Policy | P2 | 添加 CSP 中间件 |

#### `web/session.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| SN-001 | 32 | `Personality.load(config.personality_file)` 全局共享文件 | P0 | 按 session 隔离或 deepcopy |
| SN-002 | 34 | `repo.session_id = session_id` 可变属性竞态 | P0 | 移除可变字段 |
| SN-003 | 36-37 | `get_recent_turns_sync(30)` 无 session_id 过滤 → 加载全局历史 | P1 | 加 session_id 过滤 |
| SN-004 | 36-37 | 数据库损坏时阻止所有 session 创建 | P2 | try/except 容错 |
| SN-005 | 43-49 | 每个 WebAgent 创建独立 `DeepSeekProvider`（含 requests Session） | P2 | 移除或共享 |
| SN-006 | 54-62 | 每个 WebAgent 创建独立 `EmbeddingEngine` | P3 | SessionManager 级别共享 |
| SN-007 | 88-104 | `personality.save()` 每次调用后都保存（3 个路径） | P0 | 写入防抖（10 次存一次） |
| SN-008 | 91-99 | `personality.save()` 失败返回 500 但消息已处理完 | P2 | 不传播异常 |
| SN-009 | 129-131 | `threading.Lock` 在 asyncio 上下文 → 阻塞事件循环 | P1 | 改为 `asyncio.Lock` |
| SN-010 | 139-147 | `get_or_create` 不区分"获取"和"创建" | P3 | 返回布尔标志 |
| SN-011 | 141 | Session ID 完全客户端控制 → 固定攻击 | P1 | 服务端生成 |
| SN-012 | 144 | 新 session_id 创建 WebAgent，无速率限制 → DoS | P1 | 硬上限 100 个 |
| SN-013 | 149-156 | `remove()` 不关闭 provider session、不 await task cancel、不保存 personality | P1 | 添加 WebAgent.close() |
| SN-014 | 158-166 | `register_proactive` 取消旧 task 异步 → 新旧同时运行 | P1 | 生成计数 |
| SN-015 | 168-170 | `get_active_ws()` 不加锁读取 `_active_ws` | P2 | 加锁 |
| SN-016 | 172-194 | `cleanup_old()` 是死代码，从不被调用 | P1 | 定期调用或启动时调用 |
| SN-017 | 172-194 | cleanup 时不保存 personality → 丢失情绪状态 | P1 | evict 前 save |

---

### 2.9 Frontend 前端

#### `web/static/app.js`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| FJ-001 | 34-36 | Cookie 缺 HttpOnly/Secure/SameSite | P1 | 添加标志 |
| FJ-002 | 99-123 | `JSON.parse(event.data)` 空 `catch(e) {}` → 所有错误静默丢失 | P1 | 记录错误到 console |
| FJ-003 | 107-109 | `createMessage('assistant', data.content)` 不检查 `data.content` 是否定义 | P3 | 加守卫 |
| FJ-004 | 112-113 | `'done'` 后迟到 segment 仍可渲染 | P3 | `streamComplete` 标志 |
| FJ-005 | 126-129 | 固定 3s 重连无退避无上限 | P1 | 指数退避 + 最大 10 次 |
| FJ-006 | 128 | 重连风暴风险 | P1 | 同上 |
| FJ-007 | 185 | 角色名硬编码"星" | P0 | 服务端 `/api/name` 返回名称 |
| FJ-008 | 246-248 | 心跳 `setInterval` 在重连时翻倍 | P2 | 开始新连接前 clearInterval |
| FJ-009 | 217-241 | REST 回退 `fetch` 无超时 | P2 | 添加 AbortController 超时 |
| FJ-010 | 38-87 | `splitSegments` 与后端 `_split_segments` 逻辑不同步 | P3 | 消除前端分段 |

#### `web/static/index.html`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| FH-001 | 3-7 | 无 CSP meta 标签 | P2 | 添加 `Content-Security-Policy` |
| FH-002 | 3-7 | 无 `referrer` 策略 | P3 | `<meta name="referrer" content="no-referrer">` |
| FH-003 | 11,13 | 标题"小星" vs 气泡头像"星"不一致 | P1 | 统一从服务端获取 |
| FH-004 | 30 | `textarea` 无 `aria-label` | P3 | 添加 ARIA |

#### `web/static/style.css`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| FC-001 | 全局 | 颜色值（`#1a1a2e`、`#667eea` 等）散布 229 行无 CSS 变量 | P2 | 定义为 `:root` 自定义属性 |

---

### 2.10 Security 安全

（已分布在各模块中，此节仅汇总跨文件安全问题的 **P0** 级别）

| ID | 问题 | 涉及文件 | 优先级 |
|----|------|---------|--------|
| SEC-001 | NotifyTool PowerShell 转义错误 → 命令注入 | `tools/notify_tool.py:48-49` | P0 |
| SEC-002 | 文件路径 `abspath` 不解析符号链接 → 白名单绕过 | `tools/file_tools.py:52`, `search_tools.py:16`, `music_tool.py:55` | P1 |
| SEC-003 | ReDoS — `regex.search` 无超时 → CPU 耗尽 | `tools/search_tools.py:164-169` | P1 |
| SEC-004 | Agent 1 持有完整工具注册表 → 架构隔离失效 | `core/inner_drive.py:99` | P0 |
| SEC-005 | API Key 明文在 config.json Git 历史中 | `config.json:3` | P0 |
| SEC-006 | Session ID 客户端控制 | `web/session.py:141` | P1 |
| SEC-007 | Cookie 缺 HttpOnly/Secure/SameSite | `web/static/app.js:34-36` | P1 |
| SEC-008 | WebSocket Origin 校验可被 `localhost.evil.com` 绕过 | `web/server.py:219` | P1 |
| SEC-009 | 无 CSP 头、无 X-Frame-Options | `web/server.py:29` | P2 |
| SEC-010 | 无速率限制 | 全局 | P1 |
| SEC-011 | 日志文件无轮转 → 无限增长 | `core/logging_setup.py:26` | P1 |
| SEC-012 | 情绪日志泄露用户输入内容 | 多处 | P2 |

---

### 2.11 CLI/UI 终端界面

#### `ui/display.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| DP-001 | 13 | `print(ch, end="", flush=True)` CJK 字符在 Windows CP437 终端上可能 `UnicodeEncodeError` | P3 | 错误处理 |
| DP-002 | 50-63 | `_word_wrap` 用 `len()` 计 CJK 为 1 列 → 行实际宽度减半 | P2 | 用 `wcwidth` 库 |
| DP-003 | 50-63 | `_word_wrap` 不处理 ANSI 转义码 → 缩进偏移 | P3 | `visible_len()` 剥离转义码 |
| DP-004 | 56-57 | CJK 无空格时 `width//2` 内找不到断点 → 在语义单元中间截断 | P2 | CJK 断点优化 |
| DP-005 | 1 | `import sys` 未使用 | P3 | 删除 |
| DP-006 | 7-8 | 默认 `typing_speed=0.02` 与配置 `0.005` 不同 | P3 | 同步默认值 |
| DP-007 | 22 | 终端宽度硬编码上限 80 列 | P3 | 暴露为可配置参数 |
| DP-008 | 26 | `width - len(prefix) - 2` 当 prefix 超宽时为负值 | P3 | 截断 prefix |
| DP-009 | 38-48 | ANSI 转义码硬编码无 Windows VT 兼容处理 | P3 | 用 colorama 或 isatty 检查 |
| DP-010 | 13 | `\n` 在 sentence-ending pause 中产生双重延迟 | P2 | 移除 `\n` 从中断集 |
| DP-011 | 35 | `show_thinking()` 缺 `flush=True` | P3 | 添加 |

#### `ui/cli.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| CL-001 | 45 | `DisplayEngine.__init__` 不接收 `typing_speed` 参数 → 配置的 0.005 永不生效 | P0 | 从 config 传入 |

---

### 2.12 Config/Startup 配置启动

#### `config.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| CF-001 | 6,48-78 | `load_config` 中日志在 `setup_logging` 前 → 日志丢失 | P2 | 调换顺序或 basicConfig |
| CF-002 | 9-43 | 所有数值字段无范围验证 | P2 | 添加 `validate_config()` |
| CF-003 | 15-16,31 | 字符串枚举字段无 `Literal` 约束（thinking, reasoning_effort, log_level） | P2 | 添加 `Literal` 类型 |
| CF-004 | 12 | 空 `api_key` 无早期验证 → 运行时静默失败 | P2 | 添加 logger.warning |
| CF-005 | 15 | `thinking: str = "disabled"` 是空值真 → API 发送 `{"thinking": {"type": "disabled"}}` | P2 | 默认空字符串 |
| CF-006 | 32-38 | Windows 绝对路径 `D:\音乐` `D:\桌面` 在 Linux 上无效 | P2 | 从默认值移除 |
| CF-007 | 48-78 | `load_config` 中 `logger.info` 在 logging 未配置前发出 | P2 | 同上 |
| CF-008 | 58-59 | `except (json.JSONDecodeError, OSError)` 中 `OSError` 本应失败 | P1 | 仅 `FileNotFoundError` |
| CF-009 | 64-70 | 仅 5 个环境变量被映射 → 大量配置无法通过环境变量覆盖 | P2 | 补全映射 |
| CF-010 | 72-76 | 环境变量值都是字符串 → `web_port="8080"` 而非 `int` | P2 | 类型推断转换 |
| CF-011 | 74 | KEY 子字符串掩码漏 SECRET/TOKEN，误掩 KEYBOARD_LAYOUT | P1 | 改为后缀模式集合 |
| CF-012 | 81-83 | `save_config()` 是死代码（无调用者）且写回 API key | P2 | 移除或排除 api_key |
| CF-013 | 81-83 | `save_config()` 无错误处理 → OSError 崩溃 | P3 | 添加 try/except |

#### `main.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| MA-001 | 35-94 | 所有初始化步骤无异常处理 | P2 | 添加 try/except 给出友好错误 |
| MA-002 | 59-66 | `llm_generate`/`llm_rerank` 代码重复 | P3 | 删除 `llm_rerank` |
| MA-003 | 61 | `temperature` 参数接受但不传给 `provider.generate()` | P1 | 传 temperature |
| MA-004 | 111 | `agent.run()` 在 async 函数中是同步的 | P2 | 改为 async |
| MA-005 | 115 | `db.close()` 无 `await` → coroutine 被丢弃，连接从不关闭 | P0 | `await db.close()` |

#### `web_main.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| WM-001 | 16-17 | `getattr(config, 'web_host', '0.0.0.0')` 对必含字段多余 | P3 | 直接用 `config.web_host` |
| WM-002 | 22-24 | `print()` 输出到 stdout 而非 logger | P3 | 替换为 `logger.info()` |
| WM-003 | 26-32 | `reload=False`, `log_level="info"` 硬编码 | P2 | 从 config 读取 |
| WM-004 | 26-32 | uvicorn 无优雅关闭处理 | P3 | 添加 try/except |
| WM-005 | 30-31 | `log_level` 硬编码 "info" 而非用 `config.log_level` | P2 | 传 `config.log_level.lower()` |

---

### 2.13 Prompts 提示词

#### `prompts/system.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| SY-001 | 51-52,56 | Agent 1 facts/exps 数量硬编码（8/3） | P3 | 命名常量 |
| SY-002 | 60-84 | Agent 1 输出格式为自然语言 → `_parse_decision` 关键词解析脆弱 | P2 | 切换到结构化 JSON |
| SY-003 | 253-276 | 8 个对话示例 ~600 tokens 每次全量注入 | P2 | 前 2 次后移除，或配置化 |
| SY-004 | 279,309 | `emotion_desc["afraid"]` vs `emotion_behavior["fearful"]` 键名不一致 | P1 | 统一 |
| SY-005 | 288,318 | `"afraid"` 在 behavior 中找不到 → 行为描述为空 | P1 | 统一键名 |
| SY-006 | 298-306 | `primary_map` 和 `strong_primary` 计算但没用 | P3 | 移除或使用 |
| SY-007 | 309-319 | 10 种情绪行为全量加载但只用当前情绪 1 条 | P2 | 仅注入当前 dominant_emotion |
| SY-008 | 384 | `'梦' in e.get('trigger', '')` → 用户说"我的梦想"触发假梦境 | P2 | 添加 `event_type` 字段 |
| SY-009 | 398-402 | 梦境和主动行为同时注入时冲突（一个说做梦，一个说搭话） | P3 | prompt 消除歧义 |
| SY-010 | 414-422 | Agent 3 有 tool_call 格式示例但 Agent 1 没有 → Agent 1 需调用 recall/remember 时无格式参考 | P2 | 给 Agent 1 补充示例 |
| SY-011 | 296,320 | `emotion_behavior.get(mood, "")` mood 是中文键但 dict 是英文键 → 总是返回空 | P2 | 用 `emotion.dominant_emotion` 查 |
| SY-012 | 429-430 | `tc["success"]` 等用 `[]` 而非 `.get()` → KeyError 崩溃 | P2 | 改 `.get("success", False)` |
| SY-013 | 30,224 | `from datetime import datetime` 在函数体内（重复） | P3 | 移到模块顶部 |
| SY-014 | 222 | `**kwargs` 隐藏三个不同参数（idle_duration/tool_call_history/explore_mode） | P2 | 改为显式参数 |
| SY-015 | 243-249 | `personality.name` 等为 None 时注入 "None" 文本 | P3 | 添加 `or "未知"` 回退 |

#### `prompts/templates.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| TM-001 | 1-99 | 所有模板 `.format()` 调用无输入清洗 → KeyError 风险 | P1 | 用 `replace()` 或检查 |
| TM-002 | 3 | `FACT|` 管道分隔格式而非 JSON → 解析脆弱 | P2 | 改为 JSON |
| TM-003 | 14 | "fact_type: 固定填 user_fact" 错误引导（解析器支持多类型） | P2 | 更新 prompt |
| TM-004 | 77 | `REFLECTION_PROMPT` f-string 中 `relationship[trust]` 是 Python 变量而非字符串键 → 可能 KeyError | P2 | 确认调用者传参正确 |
| TM-005 | 140 | `EMOTION_ANALYSIS_PROMPT` 输出 JSON 但 LLM 可能加 markdown 包裹 | P1 | 提取 JSON 前 strip markdown |
| TM-006 | 1-2 | 三个死导入（MemoryContext/PersonalityConfig/EmotionalState 从未使用） | P3 | 删除 |

---

### 2.14 Models 数据模型

#### `models/memory.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| MM-001 | 7-21 | `UserFact.composite_score` 语义混（运行时 vs 持久化） | P1 | 加 `runtime_score` 字段 |
| MM-002 | 7-21 | `UserFact` 缺 `__post_init__` 范围验证 | P2 | 添加验证 |
| MM-003 | 11 | `fact_type: str` → `Literal["user_fact", "agent_fact", "system_fact"]` | P2 | 用 Literal |
| MM-004 | 24-37 | `Experience` 缺枚举约束和范围验证 | P2 | 添加 `EmotionalTone` 枚举 |
| MM-005 | 40-47 | `Reflection` 缺 `insight_type` 枚举约束 | P2 | 添加枚举 |
| MM-006 | 47+ | `Reflection` 缺 `level`/`parent_ids` 字段（分层反思 L1/L2/L3） | P2 | 添加字段 |

#### `models/conversation.py`

| ID | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|--------|------|
| MC-001 | 8-14 | `Turn.timestamp` 用 `datetime.now()` 默认 → 非 JSON 可序列化 | P2 | `to_dict()` 转 ISO 8601 |
| MC-002 | 10-11 | `Turn.role: str` → 可传 "system", "bot" 等 ┸ `Literal["user", "assistant"]` | P2 | 使用 Literal |
| MC-003 | 18-24 | `MemoryContext.relationship` 硬编码默认值 → 掩盖空数据 | P2 | 改为空 dict |

---

### 2.15 Cross-cutting 横切关注点

#### 异常处理（跨文件）

| ID | 文件 | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|------|--------|------|
| XC-001 | tools/search_tools.py | 202 | except Exception: continue 跳过不可读文件不记录 | P1 | 记录 warning |
| XC-002 | memory/retrieval.py | 134,165 | except Exception: pass 损坏 embedding 静默忽略 | P1 | 添加 logger.debug |
| XC-003 | memory/retrieval.py | 154 | except Exception: return all_exp 无日志 | P1 | 记录 warning |
| XC-004 | core/sleep_manager.py | 117 | except Exception: logger.debug 梦境失败 debug 级别不可见 | P2 | 提到 warning |
| XC-005 | tools/notify_tool.py | 68 | except Exception: pass 通知错误静默 | P1 | 添加 warning |
| XC-006 | tools/search_tools.py | 25 | except Exception: pass 路径解析失败 | P3 | except OSError |
| XC-007 | storage/database.py | 163 | except Exception: pass 关闭时 WAL 检查点 | P3 | 可接受 |
| XC-008 | memory/embeddings.py | 116,126 | except Exception: pass / return False 健康检查 | P3 | 可接受 |
| XC-009 | config.py | 58-59 | except (json.JSONDecodeError, OSError) 太宽泛 | P1 | 仅 FileNotFoundError |

#### 日志

| ID | 文件 | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|------|--------|------|
| LG-001 | core/logging_setup.py | 22-37 | setup_logging 无条件添加 handler 导致重复 | P1 | 检查已有 handler |
| LG-002 | core/logging_setup.py | 26 | FileHandler 无轮转 无限增长 | P1 | TimedRotatingFileHandler |
| LG-003 | core/logging_setup.py | 10-12 | 日志文件/目录缺权限控制 其他用户可读 | P1 | os.chmod 0o600 |
| LG-004 | core/logging_setup.py | 14-15 | 跨日不轮转 | P2 | TimedRotatingFileHandler midnight |
| LG-005 | core/logging_setup.py | 23 | level.upper() 若 level 非字符串则崩溃 | P3 | str(level).upper() |
| LG-006 | 多处 | - | INFO 级别记录用户输入内容 | P2 | 降级到 DEBUG |

#### 资源泄漏

| ID | 文件 | 行号 | 问题 | 优先级 | 修复 |
|----|------|------|------|--------|------|
| RL-001 | core/provider.py | 86-87 | 流式响应异常时不关闭 连接池泄漏 | P1 | with self.session.post |
| RL-002 | tools/web_tools.py | 66-68 | 每次调用新建 requests.Session | P1 | 模块级单例 |
| RL-003 | memory/embeddings.py | 21 | EmbeddingEngine session 从不关闭 | P2 | 添加 close() |
| RL-004 | web/session.py | 43-49 | 每个 WebAgent 独立 provider session 无 close | P2 | 添加 WebAgent.close() |
| RL-005 | web/session.py | 149-156 | remove() 不关闭 provider session | P2 | 同上 |
| RL-006 | core/agent.py | 247-249 | react_messages 异常后不重置 | P0 | try/finally |
| RL-007 | models/personality.py | 261-262 | emotion_events.pop(0) O(n) | P3 | deque(maxlen=20) |
| RL-008 | main.py | 115 | db.close() 无 await | P0 | await db.close() |
| RL-009 | core/provider.py | 25 | DeepSeekProvider HTTP session 从不关闭 | P2 | 添加 close() |
| RL-010 | core/provider.py | 87-128 | 流式 parse 错误时不消费 body | P2 | try/finally resp.close() |
| RL-011 | web/server.py | 22-26 | lifespan 不关数据库 | P2 | await db.close() |
| RL-012 | tools/web_tools.py | 68-69 | HTTP 错误时不关响应 | P3 | with session.post |
| RL-013 | memory/embeddings.py | 45-50 | embedding API 错误时不消费 | P3 | context manager |
| RL-014 | memory/consolidation.py | 414-427 | sync 操作 async 连接 TypeError 静默 | P2 | 改为异步 |
| RL-015 | core/logging_setup.py | 28,36 | setup_logging 重复添加 handler | P1 | 清空旧 handler |
| RL-016 | core/async_utils.py | 26 | run_async 每次调创建新线程池 | P2 | 模块级单例 |
| RL-017 | web/server.py | 166+ | 默认 ThreadPoolExecutor 永不关闭 | P3 | 专用 executor |
| RL-018 | core/message_handler.py | 157,222 | tool_call_history 异常时超上限 | P2 | deque(maxlen=20) |
| RL-019 | tools/file_tools.py | 34-35 | 每次读文件调用 load_config() | P3 | 缓存 config |
| RL-020 | tools/notify_tool.py | 64-68 | subprocess 超时变僵尸进程 | P3 | 捕获 TimeoutExpired kill |
| RL-021 | web/static/app.js | 246-248 | ping 定时器断开时不清理 | P3 | clearInterval on onclose |

#### 竞态条件（总结）

| ID | 问题 | 关键文件 | 优先级 |
|----|------|---------|--------|
| RC-001 | Repository.session_id 跨会话竞态 | storage/repository.py + web/session.py | P0 |
| RC-002 | Agent 无 per-instance 消息处理锁 | core/agent.py + web/server.py | P0 |
| RC-003 | run_async() 嵌套事件循环绕过 asyncio.Lock | core/async_utils.py | P0 |
| RC-004 | SessionManager threading.Lock 错误 | web/session.py | P1 |
| RC-005 | Personality.save() 多线程写竞争 | core/personality.py | P0 |
| RC-006 | EmotionalState 无线程安全锁 | models/personality.py | P1 |
| RC-007 | ConversationBuffer._next_id 锁外读取 | memory/short_term.py | P0 |
| RC-008 | ContextManager._compressing 无锁 | core/context_manager.py | P1 |
| RC-009 | MemoryConsolidator._pending_buffer 无锁 | memory/consolidation.py | P2 |
| RC-010 | EmbeddingCache OrderedDict 线程不安全 | memory/embeddings.py | P1 |
| RC-011 | MessageHandler 惰性初始化双实例 | core/message_handler.py | P2 |
| RC-012 | tool_call_history append 无锁 | core/agent.py | P2 |
| RC-013 | tool_call_history 在 message_handler 中同样未保护 | core/message_handler.py | P2 |
| RC-014 | WebSocket proactive task 新旧冲突 | web/server.py + session.py | P1 |
| RC-015 | sleep_state 全局文件竞态 | core/sleep_manager.py | P1 |
| RC-016 | _embed_new_items get_connection() 绕过锁 | memory/consolidation.py | P1 |

---

## 3. 优先级总表

| 优先级 | 模块 | 关键数量 | 预计工时 |
|--------|------|---------|---------|
| **P0** | Storage | 8 | 4h |
| **P0** | Agent Core | 5 | 3h |
| **P0** | Personality | 2 | 2h |
| **P0** | Web | 3 | 3h |
| **P0** | Config/Startup | 1 | 0.5h |
| | **P0 合计** | **18** | **12.5h** |
| **P1** | Storage | 10 | 4h |
| **P1** | Memory | 12 | 6h |
| **P1** | Agent Core | 12 | 6h |
| **P1** | Infrastructure | 12 | 5h |
| **P1** | Personality | 8 | 3h |
| **P1** | Tools | 10 | 5h |
| **P1** | Web | 15 | 6h |
| **P1** | Frontend | 8 | 3h |
| **P1** | Security | 6 | 2h |
| **P1** | Config/Startup | 2 | 1h |
| | **P1 合计** | **98** | **42h** |
| **P2** | 全部模块 | 210 | 75h |
| **P3** | 全部模块 | 199 | 48h |
| | **总计** | **525** | **~177.5h** |

---

## 4. 按文件统计

| 文件 | P0 | P1 | P2 | P3 | 合计 |
|------|-----|-----|-----|-----|------|
| `storage/database.py` | 1 | 5 | 4 | 2 | 12 |
| `storage/repository.py` | 8 | 6 | 5 | 3 | 22 |
| `memory/short_term.py` | 1 | 1 | 1 | 2 | 5 |
| `memory/long_term.py` | 0 | 0 | 2 | 1 | 3 |
| `memory/retrieval.py` | 0 | 6 | 4 | 1 | 11 |
| `memory/consolidation.py` | 0 | 5 | 5 | 4 | 14 |
| `memory/embeddings.py` | 0 | 3 | 2 | 3 | 8 |
| `memory/fact_checker.py` | 1 | 1 | 2 | 1 | 5 |
| `core/agent.py` | 2 | 5 | 5 | 2 | 14 |
| `core/message_handler.py` | 2 | 4 | 5 | 2 | 13 |
| `core/inner_drive.py` | 1 | 3 | 3 | 2 | 9 |
| `core/tool_agent.py` | 1 | 3 | 2 | 0 | 6 |
| `core/cli_controller.py` | 1 | 3 | 3 | 0 | 7 |
| `core/dispatcher.py` | 1 | 3 | 4 | 1 | 9 |
| `core/provider.py` | 0 | 6 | 4 | 1 | 11 |
| `core/context_manager.py` | 1 | 3 | 2 | 2 | 8 |
| `core/async_utils.py` | 0 | 2 | 2 | 1 | 5 |
| `core/sleep_manager.py` | 0 | 3 | 3 | 8 | 14 |
| `core/proactivity.py` | 0 | 3 | 10 | 2 | 15 |
| `core/personality.py` | 0 | 2 | 3 | 3 | 8 |
| `models/personality.py` | 2 | 6 | 14 | 5 | 27 |
| `models/memory.py` | 0 | 1 | 5 | 0 | 6 |
| `models/conversation.py` | 0 | 0 | 3 | 0 | 3 |
| `tools/web_tools.py` | 0 | 3 | 2 | 3 | 8 |
| `tools/file_tools.py` | 0 | 3 | 2 | 1 | 6 |
| `tools/search_tools.py` | 0 | 3 | 3 | 3 | 9 |
| `tools/music_tool.py` | 0 | 2 | 1 | 1 | 4 |
| `tools/notify_tool.py` | 1 | 1 | 2 | 1 | 5 |
| `tools/traits.py` | 0 | 1 | 2 | 1 | 4 |
| `tools/memory_tools.py` | 0 | 0 | 2 | 1 | 3 |
| `web/server.py` | 2 | 12 | 9 | 3 | 26 |
| `web/session.py` | 3 | 7 | 4 | 2 | 16 |
| `web/static/app.js` | 1 | 3 | 5 | 14 | 23 |
| `web/static/index.html` | 0 | 1 | 3 | 4 | 8 |
| `web/static/style.css` | 0 | 0 | 2 | 7 | 9 |
| `ui/display.py` | 0 | 0 | 4 | 5 | 9 |
| `ui/cli.py` | 1 | 0 | 2 | 5 | 8 |
| `config.py` | 0 | 2 | 6 | 2 | 10 |
| `main.py` | 1 | 1 | 2 | 1 | 5 |
| `web_main.py` | 0 | 0 | 1 | 2 | 3 |
| `prompts/system.py` | 0 | 2 | 5 | 2 | 9 |
| `prompts/templates.py` | 0 | 2 | 2 | 1 | 5 |
| 测试文件 | 0 | 0 | 0 | 5 | 5 |
| Cross-cutting | 0 | 7 | 6 | 3 | 16 |
| **合计** | **18** | **98** | **210** | **199** | **525** |
