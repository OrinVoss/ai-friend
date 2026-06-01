# ── Fact Extraction ──
FACT_EXTRACTION_PROMPT = """从这段对话中提取**关于用户**的事实信息。
每个事实输出一行，格式：
FACT|分类|关键词|值|置信度|重要性|fact_type

分类: preference（偏好）, identity（身份）, event（事件）, relationship（关系）, routine（日常）
置信度: 0.0 ~ 1.0，事实有多可靠
重要性: 0.0 ~ 1.0，这条信息在多久后还有用
  0.0~0.3 = 临时（如今天吃了什么、临时心情）
  0.3~0.6 = 短期（如本周计划、当前项目）
  0.6~0.8 = 长期（如爱好、偏好、习惯）
  0.8~1.0 = 永久（如名字、身份、核心价值观）
fact_type: 固定填 user_fact

=== 重要：只提取用户说的关于自己的信息 ===
以下内容**不算用户事实，不要提取**：
- AI 的行为（AI唱了歌、AI查了资料、AI发了通知）
- AI 的承诺（AI说"我记住了"、"我学会了"、"以后注意"）
- AI 对用户的评价（"你真有趣"）
- 系统属性（"我有双阶段架构"、"代码有bug"）
- 无法验证的推测（"用户电脑有600首歌"除非用户明确说过）
- 对话中只有AI在说话、用户没提供新信息的轮次

只输出明确出现或高度可推断的**用户自身信息**。不确定的置信度给低分(0.3-0.5)。
如果对话中没有新的用户信息，输出空行即可。

对话：
{text}

事实：
"""


# ── Experience Summarization ──
EXPERIENCE_SUMMARIZATION_PROMPT = """将这段对话总结为一段共享体验。
输出格式：
SUMMARY: <一行总结>
TONE: <情感色调，如: 温暖/兴奋/忧伤/平静/幽默>
SIGNIFICANCE: <0.0~1.0 重要程度>
IMPORTANCE: <0.0~1.0 这条体验在多久后还有意义，0.0=转瞬即逝 0.5=几天 1.0=永远>
TAGS: <逗号分隔的关键词>

对话：
{text}

总结：
"""


# ── Reflection Generation ──
REFLECTION_PROMPT = """回顾你和用户的最近互动，以及你已有的反思和掌握的事实，产生新的深度洞察。

你的反思可以是：
- self_discovery: 对你自己（AI）的新认识、情绪变化、行为模式
- user_discovery: 对用户性格、习惯、偏好、情感模式的新发现
- relationship_insight: 对你们关系动态、信任变化、默契程度的新观察
- pattern: 注意到用户行为或对话中反复出现的模式
- prediction: 基于已知信息对用户未来行为或偏好的预测

输出格式：
TYPE: <insight_type>
CONTENT: <反思内容（具体、有洞察，不要笼统）>
SIGNIFICANCE: <0.0~1.0>
RELATED_EXPERIENCES: <相关体验ID，逗号分隔>

最近的体验：
{experiences}

已有的反思：
{reflections}

你了解的用户事实：
{facts}

你的情绪状态：{current_emotion}
关系动态：trust={relationship[trust]:.2f} familiarity={relationship[familiarity]:.2f} intimacy={relationship[intimacy]:.2f}

写一条有实际内容的反思。不要"用户是个好人"这种废话。

新的反思：
"""


# ── Emotional Analysis ──
EMOTION_ANALYSIS_PROMPT = """分析用户这条消息的情感倾向。
输出格式（一行JSON）：
{{"sentiment": <float -1.0~1.0>, "personal_sharing": <true/false>, "topic_energy": <float 0.0~1.0>}}

sentiment: 负面到正面
personal_sharing: 是否在分享个人信息或感受
topic_energy: 话题的活跃/激烈程度

用户消息：{text}

分析：
"""


# ── Memory Reranking ──
MEMORY_RERANK_PROMPT = """用户说: "{query}"

哪些记忆和当前话题相关？回复序号，逗号分隔。
如果不确定，回复 "NONE"。

候选记忆：
{candidates}

相关序号：
"""
