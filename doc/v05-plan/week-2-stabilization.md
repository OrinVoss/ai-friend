# 第2周：稳固（P1 核心可靠，~45 个）

**目标**：修复正确性缺陷，消除静默失败。核心层在异常情况下不丢数据、不返回空响应。

**状态：核心层 90% ✅ | 26 项完成，剩余 Web 安全增强**

---

## Day 1-2：存储 + 记忆（12 个）

### repository — session_id 过滤补全

| ID | 方法 | 当前 | 修复 | 影响 |
|----|------|------|------|------|
| R-005 ✅ | search_facts | 两个分支 WHERE 条件不一致 | 统一 WHERE session_id | 查询结果变化 |
| R-011 | search_experiences | 缺 session_id | 添加过滤 | 体验查询隔离 |
| R-012 | get_recent_experiences | 缺 session_id | 添加过滤 | 最近体验隔离 |
| R-015 | get_recent_reflections | 缺 session_id | 添加过滤 | 反思隔离 |
| R-020 | get_recent_turns | 缺 session_id | 添加过滤 | 对话历史隔离 |
| R-021 | prune_facts | 缺 session_id | 添加过滤 | 剪枝隔离 |

**影响**：多 session 环境下行为变化。CLI 单 session 不受影响。R-005 已修复，其余保留。

### repository — 原子操作

| ID | 问题 | 修复 |
|----|------|------|
| R-017 ✅ | upsert_relationship + 快照不是原子 | BEGIN/COMMIT 包裹 |

### database — 安全加固

| ID | 问题 | 修复 |
|----|------|------|
| S-005 ✅ | get_connection() 暴露裸连接 | 添加 `@deprecated` 警告，引导使用者改用 cursor() |
| S-006 | schema_version 创建但从不使用 | `initialize()` 后 INSERT 当前版本号 |

### retrieval — 检索修复

| ID | 问题 | 修复 | 影响 |
|----|------|------|------|
| RT-001 | 剪枝后 is_active=0 的事实永久丢失 | 保留 is_active=1 语义，但 prune 改为降级 composite_score（已修复） | 已无影响 |
| RT-003 ✅ | health_check 同次查询调用两次 | 调用一次，结果存入局部变量 | 性能提升 ~2x |
| RT-006 | query 被编码两次 | `retrieve_for_query` 中编码一次复用 | 性能提升 |
| RT-010 ✅ | 体验 id=None 去重 bug | None 跳过去重 |

### short_term — 代码质量

| ID | 问题 | 修复 |
|----|------|------|
| ST-002 | 文档说 "without copy" 但实际创建新列表 | 更新注释 |
| ST-003 | max_chars 参数名误导（实为 token 预算） | 重命名为 `max_tokens` |
| ST-004 ✅ | last_n_turns_content 无调用者 | 移除死代码 |

### embeddings — cache 线程安全

| ID | 问题 | 修复 |
|----|------|------|
| EM-001 ✅ | EmbeddingCache 无锁 | 添加 `threading.Lock` |

---

## Day 3-4：核心层 + 基础设施（15 个）

### agent.py — 鲁棒性

| ID | 问题 | 修复 | 影响 |
|----|------|------|------|
| AG-002 ✅ | 全部工具调用失败返回空字符串 | 空回复生成兜底文本："抱歉，我暂时无法获取信息" | 用户体验改善 |
| AG-005 ✅ | 3 次假动作修正后仍接受 LLM 文本 | 超限后使用硬兜底："让我直接回复你吧" | 用户体验改善 |
| AG-012 ✅ | 异常后不调 _reset_react | `try/finally` 确保重置 | 状态不污染下轮 |
| AG-014 ✅ | _consecutive_negative 不持久化 | 存入 EmotionalState dict，save/load 时序列化 | 重启不丢失破防状态 |
| AG-001 | CliController + MessageHandler 同时创建 | 惰性初始化（已部分实现） | 内存节省 |

### message_handler — 异常安全

| ID | 问题 | 修复 | 影响 |
|----|------|------|------|
| MH-003 ✅ | Agent 2 调用无 try-except | 添加 try/except，异常时返回错误消息 | 不再崩溃 |
| MH-007 | token 估算只查 messages[-5:] | 改为累计总量 `running_total` | 上下文更准确 |
| MH-001 | 仅传 tool_requests[0] 给 Agent 2 | 传全部 ToolRequest，Agent 2 逐个执行 | 多工具请求不丢失 |

### tool_agent — 重试修复

| ID | 问题 | 修复 |
|----|------|------|
| TA-005 ✅ | retry 重建 messages 不追加历史 | 追加失败结果而非每次重建 |
| TA-007 ✅ | 混淆"解析失败"和"执行失败" | 区分 last_failure 类型 |

### provider — 连接管理

| ID | 问题 | 修复 | 影响 |
|----|------|------|------|
| PR-004 ✅ | 429 不读 Retry-After | 解析 Retry-After 头，等待指定时长 | 减少限流 |
| PR-008 ✅ | 流式响应无超时 | `resp.iter_lines()` 加 timeout 包装 | 不永久挂起 |
| PR-002 ✅ | 连接池无上限 | `HTTPAdapter(pool_connections=5, pool_maxsize=10)` | 内存控制 |

### context_manager — 窗口修正

| ID | 问题 | 修复 | 影响 |
|----|------|------|------|
| CM-001 ✅ | MODEL_CONTEXT=180000 不匹配 1M | 改为 1_000_000（与模型实际一致） | 压缩触发阈值从 144K 提高到 800K，大幅降低压缩频率 |

**⚠ 风险**：改窗口后压缩频率增加，LLM 调用 +1 次/对话。monitor 压缩频率。

### async_utils — 线程池优化

| ID | 问题 | 修复 |
|----|------|------|
| AU-001 ✅ | 每次调用新建 ThreadPoolExecutor | 模块级单例 `_executor = ThreadPoolExecutor(max_workers=4)` |
| AU-002 ✅ | timeout 不 cancel future | `future.cancel()` + `_executor.shutdown(wait=False)` 清理 |

---

## Day 5-6：人格 + Web（15 个）

### personality — 情绪系统修复

| ID | 问题 | 修复 | 影响 |
|----|------|------|------|
| PS-012 ✅ | 怨恨死亡螺旋 | 添加宽恕机制：连续 10 轮无 anger 触发 resentment 折半 | 情绪动态变化 |
| PS-014 ✅ | 基线向 mood 漂移 | 添加向 default_baseline 的弹性牵引 | 情绪不过度极化 |
| PS-009 ✅ | joy_ceiling 可为负数 | `max(0.0, 1.0 - resentment * 0.5)` | 边界安全 |
| PS-006/007 | dominant_emotion 键名不一致 | 统一为 `afraid`（已一致） | 无需修改 |

**⚠ 风险**：情绪系统是核心体验。修改后需手动测试 10+ 轮对话确认情绪变化自然。

### personality — 数据安全

| ID | 问题 | 修复 |
|----|------|------|
| PE-004 ✅ | JSON 损坏时完全重置 | 加载前备份 `.bak`，损坏时提示并恢复 |
| PE-005 ✅ | from_dict() 在 try 外 | 包裹在 try/except 中 |

### sleep_manager — 多 session 隔离

| ID | 问题 | 修复 |
|----|------|------|
| SL-001 | 全局 .sleep_state 文件 | 按 session_id 命名文件 |
| SL-002 | _sleeping 无协程同步 | 添加 `asyncio.Lock` |
| SL-111 ✅ | 梦境不保存为 Experience | 生成后 `store_experience()` |
| SL-010 | generate_dream 同步阻塞 | 改为 `async def` + `await` |

### web/server — 安全加固

| ID | 问题 | 修复 |
|----|------|------|
| WS-003 | 无 CORS | 添加 `CORSMiddleware`，允许 localhost |
| WS-021 | receive_text 无大小限制 | `max_size=102400` |
| WS-028 | 无 CSP 头 | 添加 `Content-Security-Policy` 中间件 |
| WS-027 | 无 X-Frame-Options | 添加 `DENY` |

### web/session — 资源管理

| ID | 问题 | 修复 |
|----|------|------|
| SN-005/006 | 每个 WebAgent 独立 Provider/EmbeddingEngine | SessionManager 级别共享 Provider |
| SN-016 | cleanup_old 死代码 | `lifespan` shutdown 中调用 |
| SN-013 | remove 不清理资源 | 添加 `WebAgent.close()` |

### database — 事件循环适配

| ID | 问题 | 修复 |
|----|------|------|
| DB-001 ✅ | asyncio.Lock 绑定事件循环 | session 重连后自动重建锁 |

---

## Day 7：验证

- ✅ 全量测试 290 通过（290/290 + 8 skipped）
- ✅ Web 端功能验证（WebSocket 消息/重连/segment）
- ✅ 嵌入服务验证（health + 编码）
- ✅ 数据库一致性检查

---

## 第2周风险总结

| 风险 | 等级 | 缓解 |
|------|------|------|
| session_id 过滤导致已有数据不可见 | 高 | `WHERE session_id='default'` 保底 ✅ 已验证 |
| CM-001 压缩阈值 800K | 低 | 1M 模型上下文，正常对话几乎不会触发 |
| 情绪系统修改影响用户体验 | 中 | 已手动测试 ✅ |
| WebAgent 共享 Provider 线程安全 | 低 | 单用户不影响 |
