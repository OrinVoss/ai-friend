# AI Friend — 未关闭 Issue 完整清单
> 共 70 个开放 Issue | 生成时间：2026-05-31

## 总览
| 里程碑 | 数量 |
|--------|------|
| no-milestone | 5 |
| v0.2 | 10 |
| v0.3 | 10 |
| v0.4 | 7 |
| v0.5 | 28 |
| v1.0 | 8 |
| v2.0 | 2 |

## no-milestone（5 个）

### #127 — [v0.5] user_facts 主体识别缺失：AI 幻觉/AI 行为/系统属性被错标为用户事实
**标签:** `bug`, `v0.5`  |  **创建:** 2026-05-31

## 现象
user_facts 表（318 条）存在系统性事实混淆——把 AI 的编造、AI 的行为、系统属性都错标为"用户事实"。

### 典型案例
- ID 376: "D盘存在包含多首歌曲的音乐文件夹" — AI编造，已验证目录为空
- ID 251: "拥有《凌晨三点录的空调声.mp3》" — AI虚构文件
- ID 242: "承认自己读不到音乐目录，编造了六百多首歌" — 主体错位（AI认错）
- ID 131: "唱《小美满》给用户" — 主体错位（AI行为≠用户事实）
- ID 338: "拥有双阶段架构" — 系统属性（代码架构不是用户属性）
- ID 340: "承诺不瞎编" — 主体错位（AI承诺）

## 根因
- 事实抽取没有主体识别（Subject Disambiguation）
- 对话中所有陈述句被当作"用户事实"
- 缺少事实类型：User Fact vs Agent Fact vs System Fact

## 建议
1. memory/consolidation.py 增加主体识别
2. 新增 agent_facts 表
3. 入库前分类：user_fact / agent_fact / system_fact

🔗 https://github.com/OrinVoss/ai-friend/issues/127

---

### #128 — [v0.5] 置信度系统失效：confidence 基于 AI 自信而非真实性
**标签:** `bug`, `v0.5`  |  **创建:** 2026-05-31

## 现象
置信度与真实性完全脱钩：
- 虚假事实（D盘有600首歌）→ confidence 0.9
- AI幻觉（空调声MP3）→ confidence 0.9
- 真实事实（用户名）→ confidence 1.0

## 问题
高置信度幻觉比低置信度真相更有害——系统在 RAG 检索中优先引用这些"高置信谎言"。

## 根因
confidence 基于 AI 对自身判断的"信心"，而非可验证的真实性。

## 建议
- confidence 改为基于验证状态：verified / unverified / inferred
- 所有从对话抽取的事实默认标记为 unverified
- 经用户确认或工具验证后才升级为 verified

🔗 https://github.com/OrinVoss/ai-friend/issues/128

---

### #129 — [v0.5] user_facts 大量重复记录，缺乏去重合并
**标签:** `bug`, `v0.5`  |  **创建:** 2026-05-31

## 现象
318 条 user_facts 中同一事件被反复记录：
- "播放音乐"相关 >=5 条（ID 135, 176, 361, 365, 404, 409...）
- "用户正在听歌" 重复（ID 398, 409）
- "编造/瞎编" 被反复记录（ID 242, 256, 362, 294）

## 影响
记忆检索时噪声极高，RAG 召回命中大量重复且互相矛盾的"事实"。

## 建议
1. 入库前检查是否已有相似事实（embedding 相似度 + 关键词）
2. 重复事实合并为一条，增加 recall_count 计数
3. 设置去重窗口（同一天内同类事件只保留一条）

🔗 https://github.com/OrinVoss/ai-friend/issues/129

---

### #130 — [v0.5] conversation_turns 中工具调用幻觉被忠实存档，污染 RAG 召回
**标签:** `bug`, `v0.5`  |  **创建:** 2026-05-31

## 现象
conversation_turns 中完整保留了 AI 的"表演型工具调用"：
- "（调用music_play工具）曲目：《平凡之路》——朴树"
- "（前奏的口琴声轻轻响起）"

## 问题
- 括号内的舞台指示被当作正常对话存档
- RAG 检索时，虚假工具调用记录被当作"历史成功经验"召回
- Phase 1/Phase 2 分离架构已解决根本问题，但旧数据未清洗

## 建议
1. conversation_turns 加 is_tool_claim 列，标记声称的工具调用
2. build_system_prompt 时过滤这些历史记录
3. 建立幻觉率统计日志

🔗 https://github.com/OrinVoss/ai-friend/issues/130

---

### #132 — [v0.5] relationship_metrics 缺乏时间序列，应改为每次交互快照
**标签:** `enhancement`, `v0.5`  |  **创建:** 2026-05-31

## 现象
relationship_metrics 只有 4 条聚合记录，无时间序列变化。

## 问题
- 无法看到 trust/familiarity/intimacy 随时间的变化曲线
- 用户连续负面互动（辱骂）时指标是否下降？无法追溯

## 建议
1. 改为每次交互后插入一条快照（timestamp + 四个维度）
2. 保留最新值用于 prompt 注入
3. 保留历史曲线用于趋势分析
4. 定义计算逻辑：trust 基于用户情绪 vs AI 情绪的匹配度

🔗 https://github.com/OrinVoss/ai-friend/issues/132

---

## v0.2（10 个）

### #5 — [v0.2] 分层次反思：深层/浅层反思分离
**标签:** `enhancement`  |  **创建:** 2026-05-28

低层反思总结事实，高层反思在积累足够经验后触发，避免浅层重复。

🔗 https://github.com/OrinVoss/ai-friend/issues/5

---

### #6 — [v0.2] 虚假记忆修正：矛盾事实置信度递减
**标签:** `enhancement`  |  **创建:** 2026-05-28

检测矛盾事实并降低旧置信度，而非只新增不修正。

🔗 https://github.com/OrinVoss/ai-friend/issues/6

---

### #19 — [v0.2] 情感值饱和：decay_rate 过低丧失动态范围
**标签:** `bug`  |  **创建:** 2026-05-28

valence=0.98, joy=0.975 全部接近上限，情感系统已丧失区分度。

**根因**: decay_rate=0.05 过低，长期正向无法衰减
**方案**:
- 提高 decay_rate
- 重置情感值为 baseline
- 添加情感值归一化机制

来源: 代码审查报告 4.5

🔗 https://github.com/OrinVoss/ai-friend/issues/19

---

### #20 — [v0.2] 特质忽略：humor/sass 无实际效果
**标签:** `bug`  |  **创建:** 2026-05-28

humor=0.9 和 sass=0.75 只在 prompt 中显示，不对情感或行为产生影响。

**方案**:
- 在 personality.py 中添加对应逻辑
- 或从 json 中移除未使用的特质

来源: 代码审查报告 4.6

🔗 https://github.com/OrinVoss/ai-friend/issues/20

---

### #21 — [v0.2] Bug：_score_facts 原地覆写不写回 DB
**标签:** `bug`  |  **创建:** 2026-05-28

检索时覆写内存对象字段，多线程并发相互覆盖。

**方案**:
- 使用临时变量代替原地修改
- 或返回新对象

来源: 代码审查报告 6.3

🔗 https://github.com/OrinVoss/ai-friend/issues/21

---

### #22 — [v0.2] Bug：consolidation pending 重复处理
**标签:** `bug`  |  **创建:** 2026-05-28

add_pending() 在 _react_loop 和 _on_reflect 中都调用，同一 turn 可能被两次加入。

**方案**:
- 去重机制（基于 turn_id）
- 或统一调用入口

来源: 代码审查报告 6.4

🔗 https://github.com/OrinVoss/ai-friend/issues/22

---

### #40 — [v0.2] 数据隔离：LongTermMemory 无 session_id 过滤
**标签:** `bug`  |  **创建:** 2026-05-28

build_context() / get_all_active_facts() / search_facts() 等方法无 session_id 过滤，所有 session 共享数据。

来源: 代码审查报告 6.2

🔗 https://github.com/OrinVoss/ai-friend/issues/40

---

### #41 — [v0.2] 性能：情感分析三处重复调用
**标签:** `performance`  |  **创建:** 2026-05-28

_react_loop() 分析 assistant response，_on_reflect() 分析 user turn，_update_relationship() 又分析一次。每次调 analyze_sentiment 触发一次 LLM API 调用。

来源: 代码审查报告 6.4

🔗 https://github.com/OrinVoss/ai-friend/issues/41

---

### #106 — [v0.2]tools/web_tools.py: AnySearch API 调用方式存在参数传递、结果解析和安全隐患
**标签:** `bug`, `code-quality`  |  **创建:** 2026-05-30

## 问题文件
`tools/web_tools.py` — AnySearch API 封装

---

### 1. API 调用方式存在矛盾

`_anysearch_api()` 内部调用 JSON-RPC 2.0 接口，参数传递方式：

```python
payload = {
    "method": "tools/call",
    "params": {"name": tool_name, "arguments": arguments},
}
```

`WebSearchTool.execute()` 调用时：
```python
result = _anysearch_api("search", {"query": query, "max_results": max_results})
# 实际发送的 params.arguments = {"query": ..., "max_results": ...}
```

`WebFetchTool.execute()` 调用时：
```python
result = _anysearch_api("extract", {"url": url})
# 实际发送的 params.arguments = {"url": ...}
```

**问题**：如果 AnySearch API 的 search 和 extract 工具需要不同的参数结构，这里可能不匹配。需要确认 API 文档中 search 和 extract 的实际参数 schema。

---

### 2. 结果解析过于脆弱

```python
content = result.get("content", [])
if isinstance(content, str):
    return ToolResult.ok(...)
if isinstance(content, list) and content and "text" in content[0]:
    return ToolResult.ok(...)
```

**问题**：
- 如果 content 是空列表 `[]`，直接落到最后的 `return ToolResult.ok("未找到...")`，这可能误判（空结果 ≠ 未找到）
- 如果 `content[0]` 存在但没有 `"text"` 键，也会漏掉
- 没有处理 content 是字典的情况

---

### 3. URL 处理有安全隐患

```python
if not url.startswith(("http://", "https://")):
    url = "https://" + url
```

**问题**：
- 协议相对 URL `//example.com` 会被加上 `https://` 变成 `https:////example.com`，这是无效的
- 没有对 `javascript:`、`file:`、`data:` 等危险协议做防护（虽然 `startswith http` 能拦截大部分）
- 建议添加协议白名单校验

---

### 4. 缺少重试机制

网络请求只尝试一次，如果 AnySearch API 短暂不可用（网络波动、限流），会直接失败返回错误。

建议添加 2-3 次重试 + 指数退避。

---

## 影响范围
- 搜索/web_fetch 功能可靠性
- 工具返回结果准确性（可能误报"未找到"）
- SSRF 风险（URL 协议校验不足）


🔗 https://github.com/OrinVoss/ai-friend/issues/106

---

### #109 — [v0.2] 更智能的分段发送：情绪驱动的消息拆分策略
**标签:** `enhancement`, `ui`  |  **创建:** 2026-05-31

## 当前状态

Web 端已支持分段发送（`web/static/` 前端按换行符拆分消息气泡），但拆分逻辑较简单——仅按 `

` 或句号分割。CLI 端无分段。

## 期望

更智能的分段发送策略，让 AI 的回复更接近真人聊天的节奏：

### 1. 情绪驱动的分段速度
| 情绪 | 分段间隔 | 效果 |
|------|---------|------|
| excited/joyful | 200ms | 快速连发，兴奋感 |
| neutral | 500ms | 正常节奏 |
| sad/melancholy | 1000ms | 缓慢，沉重感 |
| angry | 300ms | 急促但短 |

### 2. 内容驱动的分段策略
- 短句（<15字）→ 独立气泡，模拟真人一句一句发
- 长段落 → 按语义边界拆分（换行、句号、问号、感叹号）
- 连续多个 `[旺柴]` 等表情 → 独立气泡
- 工具结果汇报 → 整段发送（不拆分，保持信息完整性）

### 3. 实现方案
- 前端：WebSocket 接收分段标记，前端控制气泡出现延迟
- 后端：Agent 3 输出时标注分段点，或前端智能解析
- 配置：分段策略可配置（最小/最大分段长度、速度映射表）

## 标签
enhancement, v0.5, ui


🔗 https://github.com/OrinVoss/ai-friend/issues/109

---

## v0.3（10 个）

### #7 — [v0.3] 情绪模型：引入对话节奏多维影响
**标签:** `enhancement`  |  **创建:** 2026-05-28

引入对话节奏检测，多轮累积情感影响，避免过度依赖单条输入的 sentiment。

🔗 https://github.com/OrinVoss/ai-friend/issues/7

---

### #8 — [v0.3] 人格特质：影响记忆/检索/规划全环节
**标签:** `enhancement`, `architecture`  |  **创建:** 2026-05-28

特质影响记忆编码、检索、回应规划等所有认知环节。

🔗 https://github.com/OrinVoss/ai-friend/issues/8

---

### #23 — [v0.3] Provider：定义 BaseProvider ABC
**标签:** `refactoring`  |  **创建:** 2026-05-28

KimiProvider 是具体实现，无 BaseProvider 接口。

**方案**:
- 定义 BaseProvider ABC
- KimiProvider 实现该接口
- Agent 依赖接口而非实现

来源: 代码审查报告 7.1

🔗 https://github.com/OrinVoss/ai-friend/issues/23

---

### #42 — [v0.3] 情感值归一化：达上下限后重置机制
**标签:** `enhancement`  |  **创建:** 2026-05-28

情感值达到上下限后丧失动态范围，decay_rate=0.05 过低无法有效衰减。

**方案**: 添加情感值归一化/重置机制

来源: 代码审查报告 4.5

🔗 https://github.com/OrinVoss/ai-friend/issues/42

---

### #101 — [v0.3] 增强：AI 后台任务完成时主动推送消息，无需用户追问
**标签:** `enhancement`  |  **创建:** 2026-05-29

## 问题

当前交互模式是"用户发一句 → AI 回一句"的请求-响应模型。用户说完后，AI 只能在收到下一条消息时才能继续说。如果 AI 在后台执行了一个任务（比如 web_search、代码执行、文件处理），任务完成后它必须等用户主动问"好了没"才能告知结果。

## 目标

AI 可以启动后台任务，任务完成后**主动推送消息给用户**，不需要用户来问。

## 场景

```
用户: 帮我搜一下最近有什么好看的电影，列5部推荐给我

AI: [启动后台任务]
    1. web_search("2026年5月热门电影")
    2. web_fetch 浏览结果
    3. 筛选 + 整理推荐列表
    ... 30秒后 ...

AI: [主动推送] "搜完了！最近这几部评分不错：
     1. xxx - 8.5分 动作片
     2. xxx - 8.2分 科幻
     ..."

用户全程不需要追问"好了没"。
```

## 更多场景

| 场景 | AI 后台任务 | 主动推送时机 |
|------|-----------|------------|
| 搜索/研究 | web_search + web_fetch + 分析 | 分析完成后 |
| 代码执行 | Claude Code / Python | 执行完毕 |
| 文件处理 | 读取大文件、整理 | 处理完成 |
| 定时提醒 | 等待到指定时间 | 时间到 |
| 自主探索 | 上网冲浪发现好内容 | 发现值得分享的 |
| 睡眠醒来 | 做梦完成 | 醒来时 |

## 技术方案

### 后台任务队列

```python
class BackgroundTask:
    task_id: str
    description: str       # "搜索热门电影"
    coroutine: Awaitable   # 异步任务
    on_complete: callable  # 完成回调 → 通过 WebSocket 推送

task_queue: asyncio.Queue[BackgroundTask]
```

### 任务完成推送

```python
async def _on_task_complete(task):
    # 生成总结消息
    summary = await agent.summarize_task(task)
    # 通过 WebSocket 发送
    await websocket.send({
        "type": "task_complete",
        "task_id": task.task_id,
        "content": summary,
    })
```

### 用户可见

- 任务进行中：状态栏显示 "正在搜索..."
- 任务完成：自动发送消息气泡（标记为"后台任务结果"）
- 任务失败：发送错误提示

## 关联

- #100 自主探索（探索完成后的分享已经是这个模式）
- 现有 proactive_loop 已经有后台推送能力，可以复用


🔗 https://github.com/OrinVoss/ai-friend/issues/101

---

### #110 — [v0.3] Prompt 注入防护（用户输入直接拼接到 messages）
**标签:** `bug`  |  **创建:** 2026-05-31

## 问题
`core/agent.py` 等文件将用户输入直接拼接到 messages：
```python
user_msg = f"用户输入：{user_input}"
```
无转义、过滤或边界检测。攻击者可构造覆盖系统指令的输入。

## 修复方案
- 输入长度限制（如 max 8000 字符）
- 特殊字符转义（```  ``` 等）
- 建议使用 ChatML 角色分离（user role 天然隔离）

🔗 https://github.com/OrinVoss/ai-friend/issues/110

---

### #111 — [v0.3] 情感分析每轮重复调用 2 次（移除 _react_loop 末尾重复）
**标签:** `bug`  |  **创建:** 2026-05-31

## 问题
每用户消息触发两次 `analyze_sentiment()` LLM 调用：
1. `_react_loop` 中分析 AI 回复的 sentiment（`core/agent.py`）
2. `_on_reflect` 中分析用户输入的 sentiment（`core/agent.py` CLI 路径）

## 修复方案
- 移除 `_react_loop` 末尾的 `analyze_sentiment()` 调用
- 统一在 `_process_emotion()` 中分析用户输入
- 预期节省 50% 情感分析 LLM 调用

🔗 https://github.com/OrinVoss/ai-friend/issues/111

---

### #113 — [v0.3] 情感值饱和（decay_rate 过低导致动态范围丧失）
**标签:** `bug`  |  **创建:** 2026-05-31

## 问题
`personality.json` 中 `decay_rate: 0.05` 过低，正向 sentiment 长期积累无法衰减：
- `valence: 0.98, arousal: 0.98`
- `joy/trust/anticipation: 0.975`
- `dominant_emotion` 被锁定在 `"joyful"`
- 情感系统已丧失区分度

## 修复方案
- 提高默认 decay_rate（建议 0.08-0.10）
- 或新增远距离衰减机制（idle > 几小时后额外衰减）
- 或给 baseline 更强的引力

🔗 https://github.com/OrinVoss/ai-friend/issues/113

---

### #120 — [v0.3] CLI 状态机错误时不清除 _react_messages 导致状态污染
**标签:** `bug`  |  **创建:** 2026-05-31

## 问题
`core/agent.py` 或 `core/cli_controller.py` 中：
```python
except Exception as e:
    logger.error(...)
    a.state = AgentState.IDLE  # 回退 IDLE 但不清理状态
```
`_on_think()` 执行到一半出错时，不清理 `_react_messages`、`_react_iteration` 等中间状态，下条消息处理时可能读到残留数据。

## 修复方案
- 在异常处理分支中调用 `_reset_react()` 清理 React 循环状态
- 或在 `_on_perceive` 入口处无条件调用 `_reset_react()`

🔗 https://github.com/OrinVoss/ai-friend/issues/120

---

### #123 — [v0.3] Session 内存泄漏（REST API session 永不释放）
**标签:** `bug`  |  **创建:** 2026-05-31

## 问题
`web/session.py` 中 `_sessions` 字典永不清理旧 session：
- WebSocket 断开时调用 `remove()`（但仅 WebSocket 路径）
- REST API 创建的 session 永不释放
- 每个 WebAgent 持有完整 ConversationBuffer（500 条），长期运行内存持续增长

## 修复方案
- 添加 TTL（Time-to-live）驱逐机制（如 30 分钟未活跃则释放）
- 或使用 LRU 缓存限制最大 session 数量
- 在 `get_or_create()` 中触发定期清理

🔗 https://github.com/OrinVoss/ai-friend/issues/123

---

## v0.4（7 个）

### #24 — [v0.4] Web 安全：添加 CORS/速率限制/CSP
**标签:** `security`  |  **创建:** 2026-05-28

缺 CORS、速率限制、WebSocket 身份认证、CSP 头。

**方案**:
- 添加 CORSMiddleware
- 添加速率限制
- 添加 CSP 头

来源: 代码审查报告 2.5

🔗 https://github.com/OrinVoss/ai-friend/issues/24

---

### #43 — [v0.4] REST API：添加 Pydantic 输入验证
**标签:** `enhancement`  |  **创建:** 2026-05-28

/api/chat 无 Pydantic 模型验证、无长度限制、无字符过滤，body 类型标注为 dict 导致 FastAPI 不会自动解析。

来源: 代码审查报告 8.7

🔗 https://github.com/OrinVoss/ai-friend/issues/43

---

### #44 — [v0.4] 性能：每消息写 personality.json 到磁盘
**标签:** `performance`  |  **创建:** 2026-05-28

web/session.py 每次 process_message 触发 JSON 序列化 + 文件写入，高并发下磁盘 I/O 瓶颈。

来源: 代码审查报告 8.2

🔗 https://github.com/OrinVoss/ai-friend/issues/44

---

### #45 — [v0.4] 封装：Web 层访问 agent 私有方法
**标签:** `refactoring`  |  **创建:** 2026-05-28

web/server.py 调用 agent.agent._calculate_proactivity(idle) 访问私有方法，破坏封装。

来源: 代码审查报告 8.5

🔗 https://github.com/OrinVoss/ai-friend/issues/45

---

### #46 — [v0.4] 性能：默认线程池耗尽风险
**标签:** `performance`  |  **创建:** 2026-05-28

loop.run_in_executor(None, ...) 使用默认线程池，大量并发 WebSocket 连接时可能耗尽。

来源: 代码审查报告 10.2

🔗 https://github.com/OrinVoss/ai-friend/issues/46

---

### #57 — [v0.4] 持久化：Web 端持久化全面排查与修复
**标签:** `bug`, `infrastructure`  |  **创建:** 2026-05-28

## 排查范围

Web 端持久化涉及三个层面：数据库持久化、人格文件持久化、会话生命周期管理。

---

## 1. 数据库持久化

### 1.1 DB 路径不一致

`config.json` 中 `db_path` 可能是 `"ai_friend.db"`（根目录），而 `config.py` 默认值是 `"data/ai_friend.db"`。如果配置更新过但 config.json 没同步，数据库会落在项目根目录而非 `data/` 下。

### 1.2 共享连接

`web/session.py:88-93` — SessionManager 全 WebSocket 会话共享一个 `Database` + `Repository`。对话写入走 `agent.py:_react_loop` 的 `ltm.repo.insert_turn()`，频率合理。但多个 session 并发写入同一 SQLite 连接时可能存在线程安全问题。

### 1.3 WAL 文件累积

SQLite WAL 模式从未执行 checkpoint，`data/ai_friend.db-wal` 持续增长。

---

## 2. 人格持久化 — 写放大

`web/session.py:65-77` — **每条消息都完整写入 personality.json**：

```python
def process_message(self, user_input: str) -> str:
    result = self.agent.process_message(user_input, ...)
    self.personality.save(self.config.personality_file)  # 每次！
    return result

def process_proactive(self) -> str:
    result = self.agent.process_proactive(...)
    self.personality.save(self.config.personality_file)  # 主动对话也存
    return result
```

CLI 模式是每 10 轮存一次（`agent.py:378`），Web 模式完全无视了这个节流策略。每条消息都做完整 JSON 序列化 + 磁盘 I/O，写放大严重。

---

## 3. 会话生命周期 — 无持久化保障

### 3.1 remove / cleanup_old 不保存

`web/session.py:104-114`：

```python
def remove(self, session_id: str) -> None:
    with self._lock:
        self._sessions.pop(session_id, None)  # 不保存 personality

def cleanup_old(self, max_sessions: int = 50) -> None:
    with self._lock:
        while len(self._sessions) > max_sessions:
            oldest = next(iter(self._sessions))
            self._sessions.pop(oldest)  # 粗暴弹出
```

- 不保存人格状态
- 不调 consolidation
- 不关数据库连接
- `cleanup_old` 从未被任何地方调用过

### 3.2 服务器 shutdown 无清理

`web/server.py:21-25` 的 lifespan shutdown 是空壳：

```python
async def lifespan(app: FastAPI):
    logger.info("Server starting...")
    yield
    logger.info("Server shutting down...")  # 不关 DB，不保存 session
```

### 3.3 刷新页面 = 新会话

浏览器刷新后 `session_id` 从 cookie 恢复，但如果 cookie 过期或丢失则创建全新会话，旧人格状态丢失。

---

## 汇总

| 维度 | 当前行为 | 问题 |
|------|----------|------|
| DB 路径 | config.json 可能指根目录 | 和默认值不一致 |
| 对话轮次写入 | 每次回复都 insert_turn | 频率合理 |
| Personality 保存 | 每条 Web 消息写一次 | 写放大，CLI 是 10 轮一次 |
| session 析构 | pop() 不保存 | 情感/短期记忆丢失 |
| consolidation | agent 每 3 轮触发 | 正常 |
| 服务器 shutdown | 空 yield | 未保存的 session 全丢 |
| WAL checkpoint | 从未执行 | db-wal 持续增长 |

## 修复建议

1. Personality save 改回每 10 轮一次（与 CLI 一致）
2. lifespan shutdown 遍历所有 session 保存 personality + 关闭 DB + WAL checkpoint
3. `cleanup_old` 先保存再 pop，由 proactive loop 或定期任务触发
4. 定期执行 `PRAGMA wal_checkpoint(TRUNCATE)`

🔗 https://github.com/OrinVoss/ai-friend/issues/57

---

### #58 — [v0.4] 重构：统一启动入口 + 消除 CLI/Web 重复初始化
**标签:** `refactoring`  |  **创建:** 2026-05-28

## 现状

`main.py`（CLI）和 `web_main.py`（Web）各自独立组装核心组件，约 30 行重复代码：

```
main.py:                    web/session.py (WebAgent.__init__):
  Database(config.db_path)    Database(config.db_path)      ← 一样
  Repository(db)              Repository(db)                 ← 一样
  Personality.load(...)       Personality.load(...)          ← 一样
  KimiProvider(...)           KimiProvider(...)              ← 一样
  LongTermMemory(...)         LongTermMemory(...)            ← 一样
  ConversationBuffer(...)     ConversationBuffer(...)        ← 一样
  MemoryRetriever(...)        MemoryRetriever(...)           ← 一样
  MemoryConsolidator(...)     MemoryConsolidator(...)        ← 一样
  ToolRegistry + 4 tools      ToolRegistry + 4 tools         ← 一样
  Agent(...)                  Agent(...)                     ← 一样
```

唯一差异：CLI 传 `ui=ConsoleInterface()` 调 `agent.run()` 状态机；Web 传 `ui=None` 调 `process_message()`。

## 目标

1. 单一启动入口，启动后可选 CLI 或 Web 模式（互斥，不同时运行）
2. 终端实时显示日志
3. 消除重复初始化

## 设计

```
python start.py
    │
    ▼
  初始化共享组件（create_agent 工厂）
    │
  请选择: [1] CLI  [2] Web
    │
  ┌─┴─┐
  ▼   ▼
 CLI  Web
agent uvicorn
.run() .run()
```

## 任务

1. 新增 `core/bootstrap.py` — `create_agent(ui=None)` 工厂函数
2. `web/session.py` — WebAgent 改用 `create_agent()`
3. `main.py` — 精简，初始化委托 `create_agent(ui=ConsoleInterface())`
4. 新增 `start.py` — 统一入口 + 模式选择菜单
5. 删除 `web_main.py`（合并到 start.py）

Related: #14

🔗 https://github.com/OrinVoss/ai-friend/issues/58

---

## v0.5（28 个）

### #25 — [v0.5] 测试：搭建单元测试体系（pytest + mock）
**标签:** `infrastructure`  |  **创建:** 2026-05-28

全项目零单元测试。

**需覆盖**:
- dispatcher: tool_call 解析
- personality: 情感计算
- retrieval: 评分公式
- repository: SQL 查询
- agent: process_message 流程

来源: 代码审查报告 11

🔗 https://github.com/OrinVoss/ai-friend/issues/25

---

### #26 — [v0.5] 前端：角色名硬编码 + 缺心跳 + 缺异常处理
**标签:** `bug`  |  **创建:** 2026-05-28

- 角色名在 HTML/JS 中硬编码
- 无 WebSocket 心跳
- JSON.parse 无 try/catch

**方案**: API 返回角色名动态渲染；添加 30s 心跳；添加异常处理

来源: 代码审查报告 9.2/9.3/9.4

🔗 https://github.com/OrinVoss/ai-friend/issues/26

---

### #27 — [v0.5] Shutdown：不关闭 DB/取消 task
**标签:** `bug`  |  **创建:** 2026-05-28

FastAPI lifespan shutdown 仅打日志。

**方案**:
- 关闭 DB 连接
- 取消所有活跃 proactive_task
- 保存所有 session 状态

来源: 代码审查报告 8.6

🔗 https://github.com/OrinVoss/ai-friend/issues/27

---

### #28 — [v0.5] Prompt：对话示例可配置化减少浪费
**标签:** `enhancement`  |  **创建:** 2026-05-28

对话示例硬编码在 prompt 中，约 600 tokens 浪费。

**方案**:
- 将示例移入 personality.json
- 根据不同人格加载不同示例

来源: 代码审查报告 7.4

🔗 https://github.com/OrinVoss/ai-friend/issues/28

---

### #29 — [v0.5] Bug：异常退出不清理 react 状态
**标签:** `bug`  |  **创建:** 2026-05-28

_on_think 执行到一半出错时不清理 _react_messages 等状态。

**方案**: 异常处理中添加状态清理

来源: 代码审查报告 12.3

🔗 https://github.com/OrinVoss/ai-friend/issues/29

---

### #47 — [v0.5] 前端：segment 独立气泡应合并
**标签:** `enhancement`  |  **创建:** 2026-05-28

每个 segment 创建独立消息气泡，一句回复被切成多条，视觉上像多条消息。应追加到最后一个气泡。

来源: 代码审查报告 9.1

🔗 https://github.com/OrinVoss/ai-friend/issues/47

---

### #48 — [v0.5] UI：CJK 终端换行宽度计算错误
**标签:** `bug`  |  **创建:** 2026-05-28

ui/display.py 使用 len() 按字符数换行，中文字符视觉宽度为 2，导致换行偏早。

**方案**: 使用 wcwidth 库或自定义宽度计算

来源: 代码审查报告 9.7

🔗 https://github.com/OrinVoss/ai-friend/issues/48

---

### #49 — [v0.5] Bug：CLI 打字速度忽略配置值
**标签:** `bug`  |  **创建:** 2026-05-28

DisplayEngine 默认 typing_speed=0.02，配置为 0.005，main.py 初始化时不传入配置值。

来源: 代码审查报告 9.8

🔗 https://github.com/OrinVoss/ai-friend/issues/49

---

### #50 — [v0.5] 文档：architecture.md 过期 + 缺 Web 端文档
**标签:** `documentation`  |  **创建:** 2026-05-28

doc/architecture.md 描述空闲 60 秒发起对话，实际 config 中为 180 秒。文档未覆盖 Web 端架构。

来源: 代码审查报告 11.3

🔗 https://github.com/OrinVoss/ai-friend/issues/50

---

### #51 — [v0.5] 错误处理：WebSocket 异常静默
**标签:** `bug`  |  **创建:** 2026-05-28

server.py WebSocket 异常处理中 try/except 静默吞异常。

来源: 代码审查报告 12.2

🔗 https://github.com/OrinVoss/ai-friend/issues/51

---

### #52 — [v0.5] 前端：缺 ARIA/键盘导航
**标签:** `enhancement`  |  **创建:** 2026-05-28

无 ARIA 标签、无角色属性、无键盘导航支持（除输入框外）。

来源: 代码审查报告 9.5

🔗 https://github.com/OrinVoss/ai-friend/issues/52

---

### #53 — [v0.5] 安全：前端缺 CSP 头
**标签:** `security`  |  **创建:** 2026-05-28

前端未通过 Content-Security-Policy 头限制脚本来源。

来源: 代码审查报告 9.6

🔗 https://github.com/OrinVoss/ai-friend/issues/53

---

### #54 — [v0.5] CSS：颜色值集中为 CSS 自定义属性
**标签:** `refactoring`  |  **创建:** 2026-05-28

颜色值散落在 style.css 中多处，无统一变量管理。

**方案**: 定义 CSS 自定义属性（--bg-primary, --accent 等），全局引用。

来源: 代码审查报告 P2

🔗 https://github.com/OrinVoss/ai-friend/issues/54

---

### #60 — [v0.5] 重构：情绪模型从单向度升级为多维对话动态
**标签:** `enhancement`, `architecture`  |  **创建:** 2026-05-28

## 现状

情绪更新主要靠 `analyze_sentiment(user_input)` 的 `sentiment` 值，过于依赖最后一条输入的内容正负。

```python
sentiment, sharing, energy = self.consolidator.analyze_sentiment(last_user_turn)
dv = user_sentiment * 0.3
```

## 问题

真实情绪是对话动态博弈的结果，不只是内容的正负：
- 用户连续反驳你 5 次，`arousal` 应该因为争论紧张而升高，不管内容 sentiment 是正是负
- 用户回得越来越快/短 → 可能不耐烦了
- 用户沉默很久后突然来一句 → 可能是深思熟虑

## 建议方案

新增「交互模式特征」维度，与内容 sentiment 并行参与情绪更新：

| 特征 | 计算方式 | 对情绪的影响 |
|------|----------|-------------|
| 连续反驳数 | 近 N 轮中 sentiment < -0.3 的连续次数 | arousal ↑，trust ↓ |
| 回复速度趋势 | 用户回复间隔的滑动窗口 | 加速 → anxiety ↑；减速 → anticipation ↓ |
| 态度一致性 | 当前 sentiment vs 历史均值 | 偏离大 → surprise ↑ |
| 对话深度 | 用户消息长度趋势 | 变长 → engagement ↑ |

结合方式：
```
情绪更新 = sentiment_impact × 0.5 + interaction_pattern_impact × 0.5
```

🔗 https://github.com/OrinVoss/ai-friend/issues/60

---

### #63 — [v0.5] 重构：人格特质渗透到全认知链路
**标签:** `enhancement`, `architecture`  |  **创建:** 2026-05-28

## 现状

人格特质只在 `estimate_emotional_impact` 里做简单的乘数调参：

```python
if t.name == "empathy" and t.value > 0.7:
    dv *= 1.5
if t.name == "playfulness" and t.value > 0.6:
    da *= 0.7
```

这更像参数微调，而不是真正的性格驱动。

## 问题

真正的人格应该影响所有认知环节，参考 OCEAN（大五人格）模型：

### 1. 记忆编码 — 高开放性

`memory/consolidation.py:_extract_facts()` 对所有事实一视同仁。高开放性的 AI 应对新奇/创意类话题的事实赋予更高重要性权重：

```
if openness > 0.7 and is_novel_topic(turn_text):
    fact.importance *= 1.5
```

### 2. 记忆检索 — 高神经质

`memory/retrieval.py:retrieve_for_query()` 当前按相关度排序。高神经质的 AI 在检索时应偏向负面体验：

```
if neuroticism > 0.7:
    negative_bias = {"sad", "angry", "frustrated", "afraid", "anxious"}
    for exp in candidates:
        if exp.emotional_tone in negative_bias:
            exp.score += neuroticism * 0.3
```

### 3. 回应生成 — 高宜人性

`_react_loop` 生成的回复直接用。高宜人性的 AI 在检测到自己要反驳用户时，应先做一轮「委婉化」改写：

```
if agreeableness > 0.7 and contains_disagreement(response):
    response = soften(response)  # 额外 LLM 调用："把这段反驳改得更委婉"
```

## 建议方案

在 `personality.json` 扩展为 OCEAN 五维 + 原有自定义 traits：

```json
{
  "ocean": {
    "openness": 0.85,
    "conscientiousness": 0.6,
    "extraversion": 0.9,
    "agreeableness": 0.8,
    "neuroticism": 0.3
  },
  "traits": { ... }
}
```

每个维度对应一个 `PersonalityModifier`，在记忆编码、检索、回应生成三个关口注入。

🔗 https://github.com/OrinVoss/ai-friend/issues/63

---

### #64 — [v0.5] 增强：主动对话加入内在驱动力模型
**标签:** `enhancement`  |  **创建:** 2026-05-28

## 现状

`_calculate_proactivity()` 的主动触发公式 = 空闲时间 + 随机命中：

```python
score = base + time_mod + emotion_mod + intimacy_mod + sentiment_mod - goodbye - short_c
if random.random() < score:
    trigger()
```

完全随机，没有内在动机驱动。

## 问题

一个有内在驱动力的 AI，其主动性应基于更丰富的需求层次：

### 1. 未完成的对话

上次聊到一半被中断的话题应该被记住。当用户再次出现时，主动提醒："对了，你上次说了一半的那个事..."

实现：`short_term` 新增 `pending_topics` 列表，检测到话题中断（用户突然说"等一下"、"回头再说"）时标记。主动触发时优先选择。

### 2. 长期目标追求

用户设定过意图（"提醒我多喝水"）或系统基于长期数据生成内部目标（"用户看起来睡得不好，我希望帮助改善睡眠"）。这些目标会随着时间推移积累 urgency：

```python
goal_urgency = time_since_goal_set / goal_period * goal_importance
```

主动触发时 topic 有可能从目标队列选取。

### 3. 情感联结需求

当 `intimacy` 值高但多日未联系时，产生"思念"状态：

```python
if intimacy > 0.7 and days_since_last_contact > 3:
    score += 0.3  # 思念加成
    topic = "情感联结型问候"
```

## 建议数据模型

```python
@dataclass
class InternalGoal:
    text: str
    source: str        # "user_set" | "system_inferred"
    importance: float
    created_at: float
    reminded_count: int
    max_reminders: int
    cooldown_hours: float
```

主动触发流程改为：
1. 检查 pending_topics（未完成对话）
2. 检查 goals 队列（到期提醒）
3. 检查 intimacy 思念状态
4. fallback 到现有随机机制

🔗 https://github.com/OrinVoss/ai-friend/issues/64

---

### #66 — [v0.5] 重构：记忆反思机制升级为分层反思
**标签:** `enhancement`, `architecture`  |  **创建:** 2026-05-28

## 现状

`consolidation.py` 每 3 轮合并都生成反思（insight）：

```python
if self.turn_count % 3 == 0:
    self.consolidator.consolidate(...)
```

每轮合并都调 `_generate_reflection()`，产生大量浅层、重复的感悟。

## 问题

真正的认知应该是分层级的：
- **低层反思**（频繁）：从 1-2 条对话中总结事实 → "用户喜欢喝咖啡"
- **中层反思**（偶发）：从多条低层反思中归纳模式 → "用户有咖啡因依赖倾向"
- **高层反思**（罕见）：综合多轮对话的深度洞察 → "用户的生活方式需要更多休息"

## 方案

### 三层反思触发器

```
L1 (每 N 轮): 事实抽取 + 体验总结（现有流程，去掉 insight）
L2 (每 M 条 L1): 从 L1 的输出中归纳模式性反思
L3 (每 K 条 L2 或重大事件): 深度反思，可能触发价值观层面的洞察
```

建议阈值：N=5, M=20（4 个 L1）, K=50（约 2 个 L2）

### 新增 `reflection` 表字段

```sql
ALTER TABLE reflections ADD COLUMN level INTEGER DEFAULT 1;
ALTER TABLE reflections ADD COLUMN parent_ids TEXT;  -- JSON array of source reflection IDs
```

### 防止重复

生成前检查是否已有相似反思（简单的关键词重叠率 > 0.7 则跳过）

🔗 https://github.com/OrinVoss/ai-friend/issues/66

---

### #67 — [v0.5] 新增：虚假记忆检测与矛盾修正机制
**标签:** `bug`, `enhancement`  |  **创建:** 2026-05-28

## 现状

当用户纠正 AI："不对，我上次说的是不喜欢吃鱼"

系统只会：
1. `remember("不喜欢鱼")` → 新增一条 fact
2. 旧的 `"喜欢吃海鲜"` fact 仍然存在，置信度不变

结果：矛盾记忆并存，检索时两个都返回。

## 问题

需要三种操作：

### 1. 矛盾检测

新增 fact 时检查是否与已有 fact 冲突：

```
新: dislike 鱼
旧: like 海鲜（鱼是海鲜的子类）
```

检测方式：LLM 判断 + 简单的类别层级匹配。

### 2. 置信度衰减

检测到矛盾后，**不直接删除旧记忆**，而是降低其置信度：

```python
if contradiction_detected(new_fact, old_fact):
    old_fact.confidence *= 0.5
    if old_fact.confidence < 0.2:
        old_fact.active = False  # 软删除
```

### 3. 用户纠正的更高权重

用户主动纠正（"不对"、"你记错了"）时，新事实的初始置信度应高于正常：

```python
if is_user_correction(text):
    new_fact.confidence = 0.95  # vs 正常的 0.5-0.7
    new_fact.importance *= 1.2
```

## 实现

在 `memory/consolidation.py` 的 `_extract_facts()` 之后新增一个 `_detect_contradictions()` 步骤：

```
_extract_facts() → 候选新事实
    │
    ▼
_detect_contradictions(候选, 现有) → 冲突列表
    │
    ├── 无冲突 → 正常 upsert
    └── 有冲突 → 旧 fact 降权 + 新 fact 高置信度写入
```

🔗 https://github.com/OrinVoss/ai-friend/issues/67

---

### #103 — [v0.5] 代码质量：修复循环导入、异常处理、性能等 5 个问题
**标签:** `bug`  |  **创建:** 2026-05-30

## 问题列表

### 1. 循环导入风险
`core/message_handler.py` 和 `core/cli_controller.py` 都在方法内部 `from prompts.system import build_system_prompt` 延迟导入。建议统一到模块级别或提取到共享位置。

### 2. 异常处理：流式 JSON 解析静默忽略
`core/provider.py:_do_request` 中流式解析时 `json.JSONDecodeError` 被 `continue` 静默跳过。如果 API 在中间返回非标准行，数据可能丢失且无日志。

### 3. 性能：estimate_tokens 缺少缓存
`core/context_manager.py:estimate_tokens()` 每次调用都检查 `_TOKENIZER is None`。可用 `@functools.lru_cache` 优化。

### 4. 并发安全：SleepManager 文件读写无锁
`core/sleep_manager.py` 的 `_load_sleep_state()` 和 `_save_sleep_state()` 直接读写文件，无 `threading.Lock`。多进程/多线程场景可能竞态。

### 5. 工具调用：asyncio.run() 在已有事件循环中失败
`core/dispatcher.py:execute_tool_calls()` 中 `asyncio.run()` 在 Web 框架的 async 上下文中会抛出 `RuntimeError`。应改为 `asyncio.create_task()` 或使用 `nest_asyncio`。

🔗 https://github.com/OrinVoss/ai-friend/issues/103

---

### #105 — [v0.5]Bug：梦境事件被普通情绪事件挤出 emotion_events 列表
**标签:** `bug`  |  **创建:** 2026-05-30

## 现象

早上 07:02 AI 正常醒来并生成梦境（日志确认），但在 personality.json 的 emotion_events 中找不到任何梦境记录。

## 根因

1. 梦境通过 record_emotion_event(trigger=f"梦: {dream}") 存入 emotion_events 列表
2. emotion_events 最多保留 20 条，FIFO 淘汰
3. 醒来后大量对话事件（sentiment > 0.6）不断追加，梦境事件被挤出

## 日志证据

07:02:20 [dream] generated + morning wake dream=yes
但 personality.json 中 20 条事件无一条含 "梦:" 前缀。

## 修复方案

方案 A（推荐）：独立梦境存储 — emotional_state 新增 dreams: list[dict]，不受 20 条限制
方案 B：保护标记 — 梦境事件加 protected: true，裁剪时跳过
方案 C：增大上限 — 20→50 + 优先删除低 intensity 事件

🔗 https://github.com/OrinVoss/ai-friend/issues/105

---

### #112 — [v0.5] Traits humor/sass 未对行为产生影响
**标签:** `bug`  |  **创建:** 2026-05-31

## 问题
`personality.json` 中定义了 `humor: 0.9` 和 `sass: 0.75`，但在 `core/personality.py` 和 `core/agent.py` 中无任何对应逻辑。它们只在 system prompt 中 `format_traits()` 显示，不对情感或行为产生实际影响。

## 修复方案
- 在 `estimate_emotional_impact()` 中添加 humor 和 sass 的调制逻辑
- 或者在 system prompt 中根据 humor/sass 值动态调整示例对话风格

🔗 https://github.com/OrinVoss/ai-friend/issues/112

---

### #115 — [v0.5] Web 角色名硬编码（HTML/JS 不随 personality.json 同步）
**标签:** `bug`  |  **创建:** 2026-05-31

## 问题
角色名在以下位置硬编码：
- `web/static/app.js:131`: `role === 'user' ? '我' : '星'`
- `web/static/index.html:6`: `<title>小星 - AI 朋友</title>`
- `web/static/index.html:13`: `<h1>小星</h1>`

修改 `personality.json` 中 `name` 后 UI 不自动同步。

## 修复方案
- 后端通过 API endpoint (/api/personality) 或 WebSocket 连接时下发配置
- 前端启动时从后端获取角色名，替换所有硬编码位置

🔗 https://github.com/OrinVoss/ai-friend/issues/115

---

### #117 — [v0.5] CJK 终端换行使用 len() 视觉宽度错误
**标签:** `bug`  |  **创建:** 2026-05-31

## 问题
`ui/display.py` 中使用 `len()` 按字符数计算换行：
```python
while len(paragraph) > width:
```
中文字符在终端中通常占 2 个英文字符宽度。`len("你好")` 返回 2 但视觉宽度为 4，导致 CJK 文本换行偏早。

## 修复方案
- 使用 `unicodedata.east_asian_width()` 判断全角/半角字符
- 或引入 `wcwidth` 库
- 或自定义 visual_width() 函数：全角字符=2，半角=1

🔗 https://github.com/OrinVoss/ai-friend/issues/117

---

### #118 — [v0.5] MemoryRetriever._score_facts() 原地修改 composite_score
**标签:** `bug`  |  **创建:** 2026-05-31

## 问题
`memory/retrieval.py` 的 `_score_facts()` 中：
```python
f.composite_score = max(0, score)  # 直接修改内存中的 UserFact 对象
```
每次检索覆写内存对象的 `composite_score` 字段，多线程并发可能相互覆盖，且不写回数据库（数据库中的 composite_score 只有在 scoring 计算时临时赋值，从未持久化）。

## 修复方案
- 不修改原对象，改为在评分时创建临时副本或新的 score 列表
- 或将 computed score 与 database persisted score 分离

🔗 https://github.com/OrinVoss/ai-friend/issues/118

---

### #119 — [v0.5] MemoryConsolidator._pending_buffer 可能导致重复处理
**标签:** `bug`  |  **创建:** 2026-05-31

## 问题
`add_pending()` 在 `_react_loop()`（agent.py）和 `_on_reflect()`（CLI agent.py）中都调用，同一 turn 可能被两次加入 pending buffer。合并时导致重复的 LLM 调用（事实抽取、体验总结）。

## 修复方案
- 在 add_pending 中加去重检查（基于 turn id 或 content hash）
- 或明确职责：只在 CLI 路径或 API 路径中单一调用点添加

🔗 https://github.com/OrinVoss/ai-friend/issues/119

---

### #121 — [v0.5] Agent 双代码路径统一（CLI/Web 两套独立消息处理）
**标签:** `bug`  |  **创建:** 2026-05-31

## 问题
系统有两套并行的对话处理逻辑，各自维护不同的情感分析目标、压缩路径和合并策略：
- CLI 路径：`_on_perceive → _on_think → _on_act → _on_reflect`
- API/Web 路径：`process_message → _react_loop`

差异包括：情感分析目标不同（AI 回复 vs 用户输入）、上下文压缩触发条件不同、合并频率不同。

## 修复方案
- 两种路径统一由 `MessageHandler` 驱动
- CLI 状态机简化为仅处理输入/输出 UI 逻辑
- 核心处理链（内驱→工具→表达）保持单一实现

🔗 https://github.com/OrinVoss/ai-friend/issues/121

---

### #122 — [v0.5] Schema 迁移升级为版本化（替换 bare except + 每次启动 ALTER）
**标签:** `bug`  |  **创建:** 2026-05-31

## 问题
`storage/database.py` 中 schema 迁移使用 bare except 静默吞异常，每次启动都尝试 ALTER TABLE。无版本化管理。

## 修复方案
- 使用 `schema_version` 表（已创建但未使用）实现版本化迁移
- 每次启动检查版本号，仅执行新版本的迁移 SQL
- 替换 bare except 为具体异常处理

🔗 https://github.com/OrinVoss/ai-friend/issues/122

---

### #124 — [v0.5] 清理项目中 7 处 bare except（静默吞异常）
**标签:** `bug`  |  **创建:** 2026-05-31

## 问题
以下位置使用 bare `except Exception:` 或 `except: pass` 静默忽略错误：
| 位置 | 风险 |
|------|------|
| `consolidation.py:85` | 情感分析失败静默，情感系统失效无感知 |
| `consolidation.py:115` | fact 抽取失败静默 |
| `consolidation.py:157` | 体验总结失败静默 |
| `consolidation.py:213` | 反思生成失败静默 |
| `config.py:42` | 配置损坏无警告返回默认值 |
| `personality.py:90` | 人格加载失败静默重置 |

## 修复方案
- 替换为具体异常类型
- 至少记录 error 级别日志
- 关键路径（情感分析）失败时设置 fallback 值

🔗 https://github.com/OrinVoss/ai-friend/issues/124

---

## v1.0（8 个）

### #79 — [v1.0] 发布：情感系统四层全部完成
**标签:** `enhancement`, `architecture`  |  **创建:** 2026-05-29

v1.0 的情感系统必须完成四层架构：

- [x] Layer 2: 交叉调制 + 分速衰减（已完成）
- [x] Layer 3: 怨恨残留（已完成）
- [x] Layer 4: 情绪事件记忆（已完成）
- [ ] Layer 1: 多维输入 — 反驳链、回复速度趋势、态度一致性参与情绪计算
- [ ] 情感值归一化：达 ±1.0 极限后的重置与反弹
- [ ] CLI 路径破防/情感分析重复调用修复
- [ ] humor/sass 特质实际生效

关联：#7 #42 #69 #75 #20

🔗 https://github.com/OrinVoss/ai-friend/issues/79

---

### #80 — [v1.0] 发布：记忆系统语义化
**标签:** `enhancement`  |  **创建:** 2026-05-29

v1.0 的记忆系统必须超越关键词搜索：

- [ ] 向量语义检索：all-MiniLM-L6-v2 本地嵌入
- [ ] 虚假记忆检测与矛盾修正
- [ ] consolidation 去重 + _score_facts 写回 DB
- [ ] LongTermMemory session_id 过滤

关联：#4 #6 #21 #22 #40

🔗 https://github.com/OrinVoss/ai-friend/issues/80

---

### #81 — [v1.0] 发布：Web 端生产可用
**标签:** `enhancement`, `infrastructure`  |  **创建:** 2026-05-29

v1.0 Web 端必须达到生产标准：

- [ ] 统一启动入口（start.py 选择 CLI/Web）
- [ ] 消除 main.py/session.py 重复初始化（create_agent 工厂）
- [ ] Web 持久化完整：shutdown 保存、WAL checkpoint、session 析构
- [ ] 每消息写 personality 改为每 10 轮（与 CLI 一致）
- [ ] CORS/速率限制
- [ ] Pydantic 输入验证
- [ ] 线程池耗尽风险修复

关联：#58 #57 #44 #24 #43 #46

🔗 https://github.com/OrinVoss/ai-friend/issues/81

---

### #82 — [v1.0] 发布：关键 Bug 清零
**标签:** `bug`  |  **创建:** 2026-05-29

v1.0 不允许存在已知严重 bug：

- [ ] process_message 绕过状态机导致 current_input 未设置
- [ ] 工具调用循环 128 token 不够
- [ ] personality.save 重复保存
- [ ] _tool_registry 初始 None
- [ ] CJK 终端换行宽度
- [ ] CLI 打字速度配置不生效
- [ ] WebSocket 异常静默

关联：#68 #70 #73 #74 #48 #49 #51

🔗 https://github.com/OrinVoss/ai-friend/issues/82

---

### #84 — [v1.0] 发布：文档完整
**标签:** `documentation`  |  **创建:** 2026-05-29

v1.0 文档必须覆盖全部系统：

- [ ] README 更新为 v1.0
- [ ] architecture.md 完整准确
- [ ] API 文档（WebSocket 协议、REST 端点）
- [ ] 配置文档（所有 config.json 字段说明）
- [ ] 人格定制指南（personality.json 完整参考）

关联：#50

🔗 https://github.com/OrinVoss/ai-friend/issues/84

---

### #85 — [v1.0] 发布：前端体验打磨
**标签:** `enhancement`  |  **创建:** 2026-05-29

v1.0 前端体验：

- [ ] 角色名从 personality.name 动态读取
- [ ] CSS 变量集中管理
- [ ] 情绪指示器动画
- [ ] 消息气泡动画（segment 到达时）
- [ ] 移动端适配验证

关联：#26 #54

🔗 https://github.com/OrinVoss/ai-friend/issues/85

---

### #86 — [v1.0] 发布：Shutdown 与稳定性
**标签:** `bug`, `infrastructure`  |  **创建:** 2026-05-29

v1.0 必须稳定：

- [ ] 服务器 shutdown 时遍历 session 保存 personality、关闭 DB、WAL checkpoint
- [ ] 异常退出清理 react 状态
- [ ] proactive task 正确取消
- [ ] 30 分钟无人访问自动休眠（减少 API 费用）

关联：#27 #29

🔗 https://github.com/OrinVoss/ai-friend/issues/86

---

### #87 — [v1.0] 架构：LLM 抽象层 — 支持多模型提供商切换
**标签:** `enhancement`, `architecture`  |  **创建:** 2026-05-29

## 现状

`KimiProvider` 直接硬编码 OpenAI-compatible 协议，无法切换模型提供商。

QAgent 已有 LLM 抽象层（`LLMProvider` trait + `factory`），支持 OpenAI API / llama.cpp / OpenVINO 三后端。合并后的项目需要统一这一层。

## 目标

定义统一的 LLM Provider 抽象层，支持多提供商切换。

## 设计

```
                    ┌─────────────────────┐
                    │   BaseLLMProvider    │  ← ABC / Trait
                    │   generate()         │
                    │   stream_generate()  │
                    │   supports_thinking()│
                    │   context_window()   │
                    │   estimate_tokens()  │
                    └─────────┬───────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
   DeepSeekProvider    OpenAIProvider     LocalProvider
   (云端 OpenAI 兼容)   (云端原生)         (llama.cpp/OV)
```

## 配置

```json
{
  "provider": "deepseek",
  "providers": {
    "deepseek": {
      "type": "openai_compat",
      "endpoint": "https://api.deepseek.com",
      "api_key_env": "DEEPSEEK_API_KEY",
      "model": "deepseek-v4-flash",
      "context_window": 180000
    },
    "local_qwen": {
      "type": "openai_compat",
      "endpoint": "http://127.0.0.1:8081/v1",
      "model": "qwen3.5-9b",
      "context_window": 32768
    }
  }
}
```

## 路由策略

| 场景 | 模型 |
|------|------|
| 日常聊天、快速回复 | 本地 Qwen（低延迟） |
| 深度推理、反思、梦境 | 云端 DeepSeek（强能力） |
| 代码生成/Claude Code | 保持现有链路 |

## 关联

- AI Friend 现有: `KimiProvider`（单后端）
- QAgent 现有: `LLMProvider` trait + factory（三后端）
- 本 issue 是合并后的统一方案

🔗 https://github.com/OrinVoss/ai-friend/issues/87

---

## v2.0（2 个）

### #88 — [v2.0] 远景：AI Friend + QAgent 合并为新智能体平台（新仓库）
**标签:** `enhancement`, `architecture`  |  **创建:** 2026-05-29

## 策略

**不合并代码到 AI Friend**。两个项目分别达到稳定版后，新建第三个仓库作为集成平台。

---

## 两个项目当前状态

### AI Friend (Python) — "情感大脑"

情绪系统: VAD + 8 Plutchik + 交叉调制 + 分速衰减 + 怨恨残留 + 情绪事件记忆 + 破防机制
记忆系统: ConversationBuffer(线程安全) + SQLite(5表) + 三层检索 + consolidation 反思
人格系统: personality.json 可定制
界面: CLI(状态机) + Web(FastAPI+WebSocket，分段独立气泡)
工具: recall / remember / read_file / notify
里程碑: v0.1 86%完成, v0.3 44%完成, v1.0 8个发布门禁

### QAgent (Rust) — "工具身体"

LLM: Qwen3.5-9B 本地 + Embedding + LLM 抽象层(OpenAI/llama.cpp/OpenVINO 三后端)
消息: BinaryHeap 优先级队列 + ExclusionStore 过滤
工具: claude_code / memory / note_take / notify / ocr / qq_read / schedule (7工具)
QQ: NapCatQQ WebSocket + HTTP API, OneBot
Web: Axum, 18 API端点
里程碑: v0.2 安全, v0.3 体验, v1.0 稳定 (84 issues)

---

## 合并架构（新仓库）

```
                         ┌──────────────────────┐
                         │   用户自定义虚拟世界    │
                         │   主题/人格/名字/房间   │
                         └──────────┬───────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼                     ▼                     ▼
        QQ / 微信              天气 / 热搜              日历 / 文件
              │                     │                     │
              └─────────────────────┼─────────────────────┘
                                    │
                      ┌─────────────▼─────────────┐
                      │    映射层 (Translator)     │
                      │   现实→虚拟世界概念转换      │
                      │   映射词用户可自定义         │
                      └─────────────┬─────────────┘
                                    │ 统一 Percept
                      ┌─────────────▼─────────────┐
                      │  感知层 (Perception)       │
                      │  多模态→统一感知向量        │
                      │  显著性/紧急度/情绪极性     │
                      └─────────────┬─────────────┘
                                    │
                      ┌─────────────▼─────────────┐
                      │  决策层 (Decision)          │
                      │  情绪+需求+关系+目标 权重    │
                      │  四级推理: 反射/启发/推理/规划│
                      └─────────────┬─────────────┘
                                    │ 统一 Action
                      ┌─────────────▼─────────────┐
                      │  行动层 (Action)           │
                      │  数字/认知/元行动           │
                      │  情绪感知权限守卫            │
                      └─────────────┬─────────────┘
                                    │
                      ┌─────────────▼─────────────┐
                      │  记忆层 (Memory)           │
                      │  感觉→工作→短期→长期→程序→元│
                      │  embedding + 三层检索       │
                      └─────────────┬─────────────┘
                                    │
                      ┌─────────────▼─────────────┐
                      │  进化层 (Evolution)        │
                      │  经验学习/反思/技能固化      │
                      │  偏好学习/架构评估/元认知    │
                      └───────────────────────────┘
```

**核心原则**: Python (AI Friend) 负责情感大脑，Rust (QAgent) 负责工具身体，映射层是唯一知道"两边"的翻译器。

---

## 五层认知循环

### 1. 感知 (Perception)
- 文本解析 → 意图/实体/情绪极性
- 图像理解 → OCR/VLM → 视觉语义
- 结构化感知 → API/DB → 事件/趋势
- 时间感知 → 节律/周期/deadline 压力
- 多模态融合 → 统一 Percept

### 2. 决策 (Decision)
- 注意力机制 → 什么值得注意？
- 情绪引擎 → 当前情绪如何影响判断？
- 需求系统 → 6 维度内在驱动力（社交/成就/好奇/安全/休息/自主）
- 关系系统 → 5 维度感情（亲密度/信任度/尊重度/依赖度/冲突度），5 阶段（陌生人→熟人→朋友→挚友→灵魂绑定）
- 目标系统 → 短期意图/长期目标对齐
- 双脑架构: 快脑 (Rust, <500ms, 90%日常) + 慢脑 (Python, 秒~分钟, 10%关键)

### 3. 行动 (Action)
- 数字行动: QQ/邮件/日程/文件/代码
- 认知行动: 查询/计算/生成/学习/反思
- 元行动: 调参/切换模型/请求人类介入
- 情绪感知权限: 破防→只读, 愤怒→确认, 正常→全功能

### 4. 记忆 (Memory)
- 感觉记忆 → 原始缓存 (秒级)
- 工作记忆 → 当前上下文 (分钟)
- 短期记忆 → 事件+情绪标签 (小时-天)
- 长期记忆 → 事实/概念/关系 (持久)
- 程序记忆 → 习惯/反射/工具模式
- 元记忆 → 知道什么/不知道什么
- 梦境系统: 夜间 LLM 驱动记忆巩固（记忆回放/情感整理/创意发散/噩梦）

### 5. 进化 (Evolution)
- 经验学习: 成功/失败模式提取
- 反思生成: "为什么那次回复让用户生气?"
- 技能固化: 频繁工具序列→封装为新技能
- 偏好学习: 用户反馈→价值函数更新
- 架构评估: 工具使用率/决策准确率
- 元认知: "我擅长什么/不擅长什么"
- 梦境: 夜间记忆巩固 + 创意生成

---

## 用户体验特性

### 用户完全自定义
- 虚拟世界主题可选（树屋/太空舱/书房/咖啡馆/海滩/赛博/竹林/自定义）
- 映射词可自定义（QQ→信鸽/信使/电话/...）
- 人格预设库 + 自由组合（损友/管家/知己/导师/伙伴/自定义）
- 名字、性格、说话风格全部由用户定义

### 双模式（用户手动切换）
- `/tool` 工具模式: 冷静、精确、高效
- `/chat` 人格模式: 情绪化、角色扮演、沉浸式虚拟世界

### 管理后台
- 概览: 位置/情绪/精力/需求雷达图
- 性格: 特质滑块/说话风格/背景故事/导出导入
- 记忆: 搜索/编辑/删除/新增
- 关系: 5 维度雷达图 + 阶段 + 里程碑
- 世界: 主题切换 + 映射词编辑
- 日志: 自主行为/情绪曲线/梦境

### 统一沙盒
- Podman + gVisor + 自定义 seccomp
- 无 root 容器, 只读根文件系统
- 网络默认隔离, 情绪感知权限守卫

### LLM 抽象层
- 参考 QAgent 已有三后端 (OpenAI API / llama.cpp / OpenVINO)
- 路由: 日常→本地, 深度推理→云端

---

## 合并前置条件

不是定日期，是定质量门槛：

AI Friend: v1.0 发布 + 情绪72h稳定 + 输出标准化 Percept/Action 接口
QAgent: v1.0 发布 + 7天无崩溃 + 工具成功率>95% + 暴露事件总线

协议对齐（现在就可以做）: 约定 Percept/Action JSON Schema

---

## 时间线（参考）

| 现在 | AI Friend v0.1收尾+v0.3情感, QAgent v0.2安全 | 约定协议 |
| 1个月 | AI Friend v0.4 Web, QAgent v0.3体验 | 双向联调 |
| 2个月 | 双方 v1.0 稳定版 | 新建仓库 |
| 3个月 | — | 合并完成 |

🔗 https://github.com/OrinVoss/ai-friend/issues/88

---

### #104 — [v2.0] AI Friend 系统进化路线图：预测记忆、情感共振、元认知等 10 个方向
**标签:** `enhancement`  |  **创建:** 2026-05-30

## 二、记忆系统进化

### 3. 从静态记忆到预测性记忆（Predictive Memory）
现状：记忆是"记录-检索"的被动模式。

进化方向：
```python
class PredictiveMemory:
    def anticipate(self, current_context: Context) -> list[Anticipation]:
        # 例如：用户每周三晚上情绪低落 → 提前准备安慰话术
        # 例如：用户提到"项目 deadline" → 预测未来3天压力增大
        
    def pre_fetch(self, anticipations: list[Anticipation]) -> MemoryContext:
        # 预加载可能需要的记忆到工作记忆
```

与现有 REFLECTION_PROMPT 的 prediction 类型联动：将反思中的预测转化为预加载策略。

### 4. 引入情景记忆（Episodic Memory）+ 语义记忆（Semantic Memory）分离
现状：所有记忆混存在 LongTermMemory 中。

| 记忆类型 | 存储内容 | 检索方式 | 遗忘曲线 |
|---------|---------|---------|---------|
| 情景记忆 | 具体对话片段、时间地点 | 时间近度 + 情绪强度 | 艾宾浩斯曲线 |
| 语义记忆 | 抽象事实、用户偏好 | 语义相似度 | 重要性加权 |
| 程序记忆 | 互动模式、成功策略 | 上下文匹配 | 强化学习更新 |

## 三、情感系统进化

### 5. 从单Agent情感到多Agent情感共振
现状：仅Agent有情感状态，用户情感通过分析推断。

进化方向：情感动力学模型
```python
class EmotionalDynamics:
    def compute_resonance(self, agent_emotion, user_emotion) -> float:
        # 同向情感（都开心）→ 共振放大
        # 反向情感（你开心用户生气）→ 冲突消耗
        
    def update(self, agent_emotion, user_emotion, interaction):
        # 双向更新，引入"情感劳动"概念
```

新机制：**情感劳动疲劳** — Agent长期扮演"情绪稳定的朋友"会积累疲劳，需要"休息"或"真实表达负面情绪"。

### 6. 引入情感粒度细化（Beyond PAD）
现状：PAD三维 + 8种基本情绪。

进化方向：复合情绪（Complex Emotions）
```python
class ComplexEmotion:
    # nostalgia = joy(0.3) + sadness(0.6) + trust(0.4)
    # bittersweet = joy(0.4) + sadness(0.5)
    
    def regulate(self, target, intensity):
        # 认知重评 / 表达抑制 / 情境选择
```

## 四、主动性系统进化

### 7. 从随机 proactive 到意图驱动的目标系统
现状：主动性基于随机概率 + 时间/情绪调制。

进化方向：目标-计划-行动（GPA）架构
```python
class GoalSystem:
    def __init__(self):
        self.goals: list[Goal] = []  # 如"增进信任"、"分享有趣内容"
        
    def generate_proactive(self) -> Action:
        # 话题服务于关系目标，而非随机选择
```

### 8. 引入社交时钟（Social Rhythm）
```python
class SocialRhythm:
    def learn(self, interactions) -> RhythmProfile:
        # 用户周一上午从不回复 → 避免主动
        # 用户每晚22:00-23:00活跃 → 优先主动窗口
        
    def predict_availability(self, time) -> float:
```

## 五、工具系统进化

### 9. 从工具调用到工具创造（Tool Creation）
```python
class ToolCreator:
    def create_tool(self, need_description: str) -> Tool:
        # 1. 分析需求 → 2. 生成代码 → 3. 安全审查 → 4. 注册执行 → 5. 升级为永久
```
安全机制：生成的代码必须在WASM沙箱或受限Python环境中运行。

### 10. 多模态工具链（Multimodal ReAct）
```python
class MultimodalToolRegistry:
    # 图像工具：read_image, generate_image, edit_image
    # 音频工具：transcribe, synthesize_voice, analyze_emotion_in_voice
    # 视频工具：summarize_video, extract_frame
```

## 六、元认知与自我进化

### 11. 引入元认知层（Metacognition）
```python
class Metacognition:
    def monitor(self, thought_process) -> MetacognitiveAssessment:
        # 检测：确认偏误、可用性启发、情感偏误
        
    def regulate(self, assessment) -> ThoughtProcess:
        # 主动纠正：强制检索反面证据、启动"冷静期"
```

### 12. 从人工配置到自动人格进化
> ⚠️ 与 #63 相关，此处仅补充差异部分

```python
class PersonalityEvolution:
    def evolve(self, interaction_history) -> PersonalityConfig:
        # 用户回应幽默 → playfulness上升
        # 用户深夜倾诉 → warmth上升
        
    def detect_drift(self, current, target) -> bool:
        # 检测是否偏离"健康人格"
```

---

**关联 Issues**：#63（人格进化重叠）、#66（分层反思部分重叠）、#88（v2.0远景）

🔗 https://github.com/OrinVoss/ai-friend/issues/104

---
