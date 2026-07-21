# ── Fact Extraction ──
import logging

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
fact_type: user_fact / agent_fact / system_fact（事实主体类型，默认 user_fact）


=== 重要：只提取用户说的关于自己的信息 ===
以下内容**不算用户事实，不要提取**：
- AI 的行为（AI唱了歌、AI查了资料、AI发了通知）
- AI 的承诺（AI说"我记住了"、"我学会了"、"以后注意"）
- AI 对用户的评价（"你真有趣"）
- **AI 对用户的复述/画像/总结**——AI 回复里"你是…""你喜欢…""你有…"这类第二人称描述，是 AI 的转述，不是用户亲口说的。**只有用户本人说的（"用户:" 开头的行）才能提取**；即使 AI 的总结内容是对的，也不要从 AI 的回复里提取
- 系统属性（"我有双阶段架构"、"代码有bug"）
- 无法验证的推测（"用户电脑有600首歌"除非用户明确说过）
- 对话中只有AI在说话、用户没提供新信息的轮次

只输出明确出现或高度可推断的**用户自身信息**。不确定的置信度给低分(0.3-0.5)。
如果对话中没有新的用户信息，输出空行即可。

对话：
{text}

事实：
"""


# ── Coreference Rewrite（Memory Agent P2：指代解析，2026-07-20）──
COREFERENCE_REWRITE_PROMPT = """把用户的最后一句话改写成一个自足、明确的句子，用于记忆检索。
要求：
- 解析其中的指代（这个/那个/它/这首歌等），用最近对话里出现的具体名称替换
- 不要回答问题，不要解释，只输出改写后的句子
- 如果没有指代需要解析，原样输出

最近对话：
{history}

用户最后一句话：{query}

改写结果："""


# ── Contradiction Verification（Bug 3，2026-07-20：LLM 复核候选矛盾）──
CONTRADICTION_VERIFY_PROMPT = """判断两条关于用户的信息是否真正矛盾。

已有记录：{old_key} = {old_value}
新的信息：{new_key} = {new_value}

判断标准：
- 复述/近义/补充说明/更具体的描述 → NOT_CONTRADICT
  例：「云指导」vs「自称云指导」、「喜欢吉森信」vs「喜欢吉森信的某首歌」
- 真正互相排斥、不能同时成立 → CONTRADICT
  例：「住北京」vs「住上海」、「喜欢」vs「讨厌」

只输出一个词：CONTRADICT 或 NOT_CONTRADICT"""


# ── Care Clue Extraction（内驱状态二期：consolidation 自动写入挂念线索）──
CARE_CLUE_PROMPT = """从这段对话中找出值得「惦记」的未完成线索——未来需要 follow-up 的事。
输出 JSON：
{{"clues": [{{"content": "一句话描述", "type": "care|curiosity|reflection|plan|idea", "expires_at": "YYYY-MM-DD 或空"}}]}}

类型说明：
- care：对用户的关心（用户最近失眠，问问好点没）
- curiosity：想搞明白的事（用户推荐的那本书讲了什么）
- plan：带时间点的约定/期待（用户明天面试，晚上问结果）——有明确时间的填 expires_at
- idea：想分享的东西
- reflection：自己行为上值得注意的点

只提取对话中**明确提到**的线索，不要推测。没有值得惦记的就输出 {{"clues": []}}。

对话：
{text}
"""


# ── Experience Summarization ──
EXPERIENCE_SUMMARIZATION_PROMPT = """将这段对话总结为一段共享体验。
输出格式：
SUMMARY: <一行总结>
TONE: <情感色调，如: 温暖/兴奋/忧伤/平静/幽默>
SIGNIFICANCE: <0.0~1.0 重要程度>
IMPORTANCE: <0.0~1.0 这条体验在多久后还有意义，0.0=转瞬即逝 0.5=几天 1.0=永远>
TAGS: <逗号分隔的关键词>

注意分清行为主体：「你:」开头的是 AI 的回复，「用户:」开头的才是用户说的。
不要把 AI 做的事记到用户头上（例如 AI 总结了用户的特征，主体是 AI 不是用户）。

对话：
{text}

总结：
"""


# ── Insight Generation（Layer 1 二期，2026-07-20：替代 REFLECTION_*）──
# 输出统一为 JSON：hypothesis / insight_type / evidence / confidence /
# needs_more_evidence。JSON 示例里的花括号已 doubled 以兼容 safe_format。
INSIGHT_GENERATION_PROMPT = """基于以下事实和体验，生成一个假设性洞察。

输出必须是 JSON：
{{
  "hypothesis": "用户可能偏好...",
  "insight_type": "pattern",
  "evidence": [1, 2],
  "confidence": 0.47,
  "needs_more_evidence": true
}}

要求：
- hypothesis 必须是可验证的假设，不是最终结论
- insight_type: pattern / contradiction / connection / emotion / prediction / user_discovery / relationship_insight
- evidence 必须列出支持的事实 ID（数字列表，来自下方事实的 id）
- confidence 0.0~1.0
- needs_more_evidence 如果证据不足则为 true
- **R3: 只允许从列出的 evidence 可直接支持的内容推导，禁止心理学推测**
- **R3: 本批是纯功能性操作（换歌/查询/指令）或无新信息时，输出 {{"hypothesis": ""}}**

事实：
{facts}

体验：
{experiences}
"""

INSIGHT_L2_PROMPT = """回顾你和用户最近的多次互动与近期洞察，归纳一个反复出现的**行为模式**假设。

已有的用户事实：
{facts}

最近的共享体验：
{experiences}

近期的洞察：
{insights}

输出必须是 JSON：
{{
  "hypothesis": "用户每次聊到工作就会情绪低落（假设，待验证）",
  "insight_type": "pattern",
  "evidence": [1, 2],
  "confidence": 0.5,
  "needs_more_evidence": true
}}

要求：
- hypothesis 是跨多次对话的可验证模式假设，要具体不要笼统
- evidence 列出支持的事实 ID（数字列表；若主要依据是体验/洞察而非事实，可留空 []）
- confidence 0.0~1.0；证据不足时 needs_more_evidence 为 true
- **R3: 禁止无证据的心理学推测；只从列出的 evidence 可直接支持的内容推导**
"""

INSIGHT_L3_PROMPT = """基于你和用户的长期互动，提出一个**长期模式/深度动机**层面的假设性洞察。

你们的关系：{relationship}
你的情绪状态：{current_emotion}

近期的模式假设（L2）：
{patterns}

所有活跃事实：
{facts}

所有体验：
{experiences}

输出必须是 JSON：
{{
  "hypothesis": "用户深夜倾诉可能是在寻求被认可而非解决方案（假设）",
  "insight_type": "emotion",
  "evidence": [3, 7],
  "confidence": 0.55,
  "needs_more_evidence": true
}}

要求：
- hypothesis 是可验证的深层假设（动机/需求/关系本质），不是最终结论
- evidence 列出支持的事实 ID（数字列表；若主要依据是 L2 模式而非事实，可留空 []）
- confidence 0.0~1.0；证据不足时 needs_more_evidence 为 true
- **R3: 禁止无证据的心理学推测；只从列出的 evidence 可直接支持的内容推导**
"""


# ── Unified Consolidation Prompt (#164) ──
# 把事实提取、体验总结、L1 insight 生成合并为一次 LLM 调用。
# 输出三段：FACTS（与 FACT_EXTRACTION_PROMPT 同格式）、EXPERIENCE（与
# EXPERIENCE_SUMMARIZATION_PROMPT 同格式）、INSIGHT（与
# INSIGHT_GENERATION_PROMPT 同格式 JSON）。
CONSOLIDATION_UNIFIED_PROMPT = """请根据以下对话，一次性完成三件事：提取用户事实、生成一个假设性洞察、总结共享体验。

对话：
{text}

近期事实：
{facts}

近期体验：
{experiences}

请严格按以下格式输出三段，段标题必须保留。内容务必精炼：FACT 的值不超过 20 字，INSIGHT 的 hypothesis 不超过 80 字，SUMMARY 一行不超过 60 字。

FACTS:
FACT|分类|关键词|值|置信度|重要性|fact_type
（每行一条，没有则写 NONE；只提取用户亲口说的关于自身的信息）

INSIGHT:
{{"hypothesis": "...", "insight_type": "pattern", "evidence": [1, 2], "confidence": 0.5, "needs_more_evidence": true}}
（若本批无新信息可洞察，输出 {{"hypothesis": ""}}）

EXPERIENCE:
SUMMARY: <一行总结>
TONE: <情感色调>
SIGNIFICANCE: <0.0~1.0>
IMPORTANCE: <0.0~1.0>
TAGS: <逗号分隔关键词>
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


def safe_format(template: str, **kwargs) -> str:
    """Format a template with KeyError protection. Returns template unmodified on failure."""
    try:
        return template.format(**kwargs)
    except (KeyError, IndexError, ValueError) as e:
        logging.getLogger(__name__).warning(f"safe_format failed: {e}")
        return template
