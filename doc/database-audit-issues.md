# 数据库审计 — 待创建 Issue

基于 992 条记录的完整审计，发现 6 个数据质量问题。

---

## Issue 1: [v0.5] user_facts 主体识别缺失

**Label:** bug, v0.5

**Body:**

user_facts 表（318 条）存在系统性事实混淆——把 AI 的编造、AI 的行为、系统属性都错标为"用户事实"。

### 典型案例
- ID 376: "D盘存在包含多首歌曲的音乐文件夹" — AI编造，已验证目录为空
- ID 251: "拥有《凌晨三点录的空调声.mp3》" — AI虚构文件
- ID 242: "承认自己读不到音乐目录，编造了六百多首歌" — 主体错位（AI认错）
- ID 131: "唱《小美满》给用户" — 主体错位（AI行为≠用户事实）
- ID 338: "拥有双阶段架构" — 系统属性（代码架构不是用户属性）
- ID 340: "承诺不瞎编" — 主体错位（AI承诺）

### 根因
- 事实抽取没有主体识别（Subject Disambiguation）
- 对话中所有陈述句被当作"用户事实"
- 缺少事实类型：User Fact vs Agent Fact vs System Fact

### 建议
1. memory/consolidation.py 增加主体识别
2. 新增 agent_facts 表
3. 入库前分类：user_fact / agent_fact / system_fact

---

## Issue 2: [v0.5] 置信度系统失效

**Label:** bug, v0.5

**Body:**

置信度与真实性完全脱钩：
- 虚假事实（D盘有600首歌）→ confidence 0.9
- AI幻觉（空调声MP3）→ confidence 0.9
- 真实事实（用户名字）→ confidence 1.0

高置信度幻觉比低置信度真相更有害——系统在 RAG 检索中优先引用这些"高置信谎言"。

### 根因
confidence 基于 AI 对自身判断的"信心"，而非可验证的真实性。

### 建议
- confidence 改为基于验证状态：verified / unverified / inferred
- 所有从对话抽取的事实默认标记为 unverified
- 经用户确认或工具验证后才升级为 verified

---

## Issue 3: [v0.5] user_facts 大量重复记录

**Label:** bug, v0.5

**Body:**

318 条 user_facts 中同一事件被反复记录：
- "播放音乐"相关 ≥5 条（ID 135, 176, 361, 365, 404, 409...）
- "用户正在听歌" 重复（ID 398, 409）
- "编造/瞎编" 被反复记录（ID 242, 256, 362, 294）

记忆检索时噪声极高，RAG 召回命中大量重复且互相矛盾的"事实"。

### 建议
1. 入库前检查是否已有相似事实（embedding 相似度 + 关键词）
2. 重复事实合并为一条，增加 recall_count 计数
3. 设置去重窗口（同一天内同类事件只保留一条）

---

## Issue 4: [v0.5] conversation_turns 中工具调用幻觉被存档

**Label:** bug, v0.5

**Body:**

conversation_turns 中完整保留了 AI 的"表演型工具调用"：
- "（调用music_play工具）曲目：《平凡之路》——朴树"
- "（前奏的口琴声轻轻响起）"

括号内的舞台指示被当作正常对话存档。RAG 检索时，虚假工具调用记录被当作"历史成功经验"召回。Phase 1/Phase 2 分离架构已解决根本问题，但旧数据未清洗。

### 建议
1. conversation_turns 加 is_tool_claim 列，标记声称的工具调用
2. build_system_prompt 时过滤这些历史记录
3. 建立幻觉率统计日志

---

## Issue 5: [v0.5] 新增 FactChecker 模块

**Label:** enhancement, v0.5

**Body:**

涉及外部状态的事实（如"用户电脑有XX文件"）从未经验证直接入库，confidence 还高达 0.9。

### 建议
在 memory/consolidation.py 入库前增加 FactChecker：
1. 识别涉及外部状态的事实（文件存在/目录结构/系统属性）
2. 对这类事实，先调用对应工具（read_file/glob）验证
3. 验证通过 → verified + high confidence
4. 验证失败 → 记录为幻觉，不存入 user_facts
5. 无法验证 → unverified + low confidence

---

## Issue 6: [v0.5] relationship_metrics 缺乏时间序列

**Label:** enhancement, v0.5

**Body:**

relationship_metrics 只有 4 条聚合记录，无时间序列变化。无法看到 trust/familiarity/intimacy 随时间的变化曲线，用户连续负面互动时指标是否下降无法追溯。

### 建议
1. 改为每次交互后插入一条快照（timestamp + 四个维度）
2. 保留最新值用于 prompt 注入
3. 保留历史曲线用于趋势分析
4. 定义计算逻辑：trust 基于用户情绪 vs AI 情绪的匹配度
