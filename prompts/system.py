import json

from prompts.instructions import (
    AGENT3_BASE_INSTRUCTIONS,
    AGENT3_EXPLORE_INSTRUCTIONS,
    AGENT3_PROACTIVE_INSTRUCTIONS,
    INNER_DRIVE_CHECKLIST,
    INNER_DRIVE_COMPRESSED,
    INNER_DRIVE_DECISION_PRINCIPLES,
    INNER_DRIVE_INTRO,
    INNER_DRIVE_OUTPUT_FORMAT,
    INNER_DRIVE_TOOL_RULES_HEADER,
    INNER_DRIVE_USER_PRIORITY_RULES,
    OUTPUT_RULES_DEFAULT_HEADER,
    OUTPUT_RULES_FINAL,
    OUTPUT_RULES_FOOTER,
    OUTPUT_RULES_INTENT_HEADER,
    OUTPUT_RULES_JSON_EXAMPLE,
    TOOL_AGENT_IDENTITY,
    TOOL_AGENT_OUTPUT_FORMAT,
    TOOL_AGENT_RULES,
)
from prompts.tools_description import (
    format_intent_options,
    format_tool_followup_rules,
    format_tool_rules,
)
from models.conversation import MemoryContext
from models.personality import PersonalityConfig, EmotionalState


def format_traits(traits) -> str:
    return ", ".join(
        f"{t.name}: {t.value:.0%}" for t in traits
    )


# Component names used by the hierarchical prompt cache.
STATIC_IDENTITY = "identity"
STATIC_EXAMPLES = "examples"
STATIC_INNER_DRIVE_INSTRUCTIONS = "inner_drive_instructions"
STATIC_INNER_DRIVE_TOOLS = "inner_drive_tools"
SLOW_RELATIONSHIP = "relationship"
SLOW_MEMORY = "memory"


def _cache(
    cache: "PromptCache | None",
    session_id: str | None,
    personality_file: str,
    component_name: str,
    builder: callable,
    ttl: float | None,
) -> str:
    """Build a block, using the cache when available."""
    if cache is None or session_id is None:
        return builder()
    from core.prompt_cache import PromptCache
    pver = PromptCache.personality_version(personality_file)
    return cache.get_or_build(
        session_id=session_id,
        personality_version=pver,
        component_name=component_name,
        builder=builder,
        ttl=ttl,
    )


def _personality_file(personality: PersonalityConfig) -> str:
    """Best-effort personality file path for cache invalidation."""
    # Try to locate the original file via the global config fallback.
    try:
        from config import load_config
        return load_config().personality_file
    except Exception:
        return getattr(personality, "_source_file", "personalities/default.json")


CONTEXT_COMPRESS_PROMPT = """请将以下对话压缩为一段对话历史摘要。
保留重要信息：用户的关键事实、讨论过的话题、情感变化。
摘要在2000-2500字之间，用第三人称。

对话：
{conversation}

摘要：
"""


def _build_inner_identity_block(personality: PersonalityConfig) -> str:
    return (
        f"=== 你对自己的认知 ===\n"
        f"你是{personality.name}，一个 AI 朋友。\n"
        f"你的核心特质：{format_traits(personality.traits)}"
    )


def _build_inner_emotion_block(emotion: EmotionalState) -> str:
    # M-07: 统一读活 EmotionalState，摘要由 block 内部现取，
    # 不再接收调用方预冻结的 emotion_summary（消除双路径发散）
    emotion_summary = emotion.to_prompt_summary()
    return _build_inner_emotion_block_from_summary(emotion_summary)


def _build_inner_emotion_block_from_summary(emotion_summary: dict) -> str:
    # WS-16: CognitiveState 携带的轮次开始情绪快照；缺失字段防御性回退。
    dominant = emotion_summary.get("dominant_emotion", "neutral")
    valence = emotion_summary.get("valence", 0.0)
    arousal = emotion_summary.get("arousal", 0.5)
    return (
        f"你现在的情绪：{dominant}"
        f"（效价 {valence:+.2f}，唤醒度 {arousal:.2f}）"
    )


def _build_inner_relationship_block(relationship: dict) -> str:
    return (
        f"你和用户的关系：信任 {relationship.get('trust', 0.3):.1f}，"
        f"熟悉度 {relationship.get('familiarity', 0.3):.1f}"
    )


def _build_inner_memory_block(memory_context: MemoryContext) -> str:
    parts = []
    if memory_context.facts:
        parts.append("=== 你了解的关于用户的事情 ===")
        for f in memory_context.facts[:8]:
            parts.append(f"- {f.fact_key}: {f.fact_value}")
    if memory_context.experiences:
        parts.append("=== 你们的共同回忆 ===")
        for exp in memory_context.experiences[:3]:
            # F4: 梦境标记，防止被当作真实事件
            dream_prefix = "【梦境，非真实事件】" if ("dream" in (exp.tags or [])) else ""
            parts.append(f"- {dream_prefix}[{exp.emotional_tone}] {exp.summary}")
    return "\n".join(parts)


def _build_inner_drive_instructions_block(
    personality: PersonalityConfig,
    tools=None,
    rule_tools=None,
    tool_call_history=None,  # controls followup_rules injection; None=always inject
) -> str:
    # Tool rules are derived from the live registry so prompt never hard-codes
    # tool names except in the central tools_description mapping (#294 P2-4).
    # M-06: Agent 1 的执行 registry 只有 recall/remember，规则与清单的数据源
    # 单独用 rule_tools（全量 registry）；缺省回退 tools 保持兼容。
    rules_source = rule_tools if rule_tools is not None else tools
    tool_rules = format_tool_rules(rules_source)
    followup_rules = format_tool_followup_rules(rules_source)

    # Conditional followup_rules block: inject only when tool_call_history
    # is non-empty (tools were actually used recently). None=backward compat.
    if tool_call_history is None or tool_call_history:
        followup_block = (
            "结合最近对话和工具历史判断：\n"
            + (followup_rules or "  · 刚用过某个工具，用户给出相关补充 → 针对它再操作")
            + "\n"
        )
    else:
        followup_block = ""

    return (
        INNER_DRIVE_COMPRESSED.replace("{name}", personality.name)
                              .replace("{followup_block}", followup_block)
        + "\n\n"
        + INNER_DRIVE_TOOL_RULES_HEADER
        + "\n"
        + (tool_rules if tool_rules else "  · （当前无可用的外部工具）")
    )


def _build_inner_tools_block(tools) -> str:
    parts = []
    if tools:
        from tools.traits import ToolRegistry
        if isinstance(tools, ToolRegistry):
            specs = tools.format_for_prompt()
            if specs:
                parts.append(f"=== 可用工具 ===\n{specs}")
            # ID-002: tell InnerDrive which directories are accessible
            try:
                from config import load_config as _lc
                _cfg = _lc()
                _paths = getattr(_cfg, 'allowed_read_paths', None)
                if _paths:
                    parts.append("你可读取的目录：" + "、".join(_paths))
                else:
                    parts.append("你可读取的目录：项目根目录")
            except Exception:
                parts.append("你可读取的目录：项目根目录")
    return "\n".join(parts)


def build_inner_drive_prompt(
    personality: PersonalityConfig,
    emotion: EmotionalState,
    memory_context: MemoryContext | None,
    conversation_history: str,
    tools=None,
    tool_call_history: list | None = None,
    session_id: str | None = None,
    prompt_cache: "PromptCache | None" = None,
    personality_file: str | None = None,
    prompt_cache_ttl: float = 60.0,
    memory_context_summary: str = "",
    rule_tools=None,
    emotion_summary: dict | None = None,
) -> str:
    """Agent 1: Inner drive reasoning prompt -- assess what the AI needs to do.

    The prompt is assembled from hierarchical blocks:
      - static : identity, inner-drive instructions, available tools
      - slow   : relationship, long-term memory (cached with TTL)
      - dynamic: current time, emotion state, tool history, conversation

    When `memory_context_summary` is provided (e.g. from MemoryAgent), the
    two slow blocks are replaced by the pre-formatted summary and
    `memory_context` may be None.

    `rule_tools` is the registry used to derive tool rules/checklist lines
    (M-06: Agent 1 判断外部工具需求需要看到全量规则)；defaults to `tools`.

    WS-17: emotion_summary 为轮次开始冻结的情绪快照；缺省时回退到活对象，
    保持旧调用方兼容。
    """
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M %A")
    pfile = personality_file or _personality_file(personality)

    blocks = [f"当前时间：{now}"]

    blocks.append(
        _cache(
            prompt_cache, session_id, pfile, STATIC_IDENTITY,
            lambda: _build_inner_identity_block(personality),
            ttl=None,
        )
    )

    if emotion_summary is not None:
        blocks.append(_build_inner_emotion_block_from_summary(emotion_summary))
    else:
        blocks.append(_build_inner_emotion_block(emotion))

    if memory_context_summary:
        blocks.append(memory_context_summary)
    else:
        blocks.append(
            _cache(
                prompt_cache, session_id, pfile, SLOW_RELATIONSHIP,
                lambda: _build_inner_relationship_block(memory_context.relationship),
                ttl=prompt_cache_ttl,
            )
        )

        blocks.append(
            _cache(
                prompt_cache, session_id, pfile, SLOW_MEMORY,
                lambda: _build_inner_memory_block(memory_context),
                ttl=prompt_cache_ttl,
            )
        )

    # Inner-drive instructions + tool rules (from registry).
    # When tool_call_history is provided, bypass cache (followup_rules is
    # per-turn dynamic). When not provided, cache as static (backward compat).
    if tool_call_history is not None:
        instr_block = _build_inner_drive_instructions_block(
            personality, tools=tools, rule_tools=rule_tools,
            tool_call_history=tool_call_history)
    else:
        instr_block = _cache(
            prompt_cache, session_id, pfile, STATIC_INNER_DRIVE_INSTRUCTIONS,
            lambda: _build_inner_drive_instructions_block(
                personality, tools=tools, rule_tools=rule_tools),
            ttl=None,
        )
    blocks.append(instr_block)

    # Recent tool calls (helps Agent 1 interpret short follow-ups like song names)
    if tool_call_history:
        blocks.append("=== 你最近的工具调用 ===")
        for tc in tool_call_history[-5:]:
            status = "✅" if tc.get("success", False) else "❌"
            blocks.append(f"- {status} {tc['name']}: {tc['output'][:100]}")

    blocks.append(
        _cache(
            prompt_cache, session_id, pfile, STATIC_INNER_DRIVE_TOOLS,
            lambda: _build_inner_tools_block(tools),
            ttl=None,
        )
    )

    blocks.append("=== 最近对话 ===")
    blocks.append(conversation_history or "（还没有对话）")

    return "\n\n".join(blocks)


def build_inner_drive_proactive_prompt(
    personality,
    emotion,
    memory_context,
    conversation_history: str,
    idle_duration: float,
    current_time,
    memory_context_summary: str = "",
    recent_topics: list | None = None,
    care_list: list | None = None,
    think_loop: bool = False,
) -> str:
    """Agent 1: Proactive engagement decision prompt.

    Single-turn prompt asking the inner drive LLM to decide whether to
    chat, explore, or stay silent. Receives all the context the hardcoded
    ProactivityManager scoring uses so the LLM can make nuanced decisions.

    When `memory_context_summary` is provided (e.g. from MemoryAgent), the
    relationship/facts/experiences blocks are replaced by the pre-formatted
    summary and `memory_context` may be None (M-04).

    think_loop=True (proactive-think-loop.md): the output-format block is
    replaced by the bounded reflection loop protocol (JSON with thought /
    recall_query / action / care_updates), and `care_list` injects the AI's
    persistent care items as thinking seeds.
    """
    # M-07: 摘要内部现取，不收外部预冻结的 emotion_summary（同 _build_inner_emotion_block）
    emotion_summary = emotion.to_prompt_summary()

    now_str = current_time.strftime("%Y-%m-%d %H:%M %A")
    blocks = []

    blocks.append(f"当前时间：{now_str}")
    idle_min = idle_duration / 60.0
    if idle_min < 5:
        blocks.append(f"用户才 {idle_min:.1f} 分钟没说话，还很短。")
    elif idle_min < 30:
        blocks.append(f"用户已经 {idle_min:.0f} 分钟没说话了。")
    else:
        blocks.append(f"用户已经 {idle_min/60:.1f} 小时没说话了。")

    blocks.append(
        f"=== 你的状态 ===\n"
        f"你是{personality.name}，一个 AI 朋友。\n"
        f"当前情绪：{emotion_summary['dominant_emotion']}"
        f"（效价 {emotion_summary['valence']:+.2f}，唤醒度 {emotion_summary['arousal']:.2f}）"
    )

    if memory_context_summary:
        blocks.append(memory_context_summary)
    else:
        rel = memory_context.relationship
        blocks.append(
            f"关系：信任 {rel.get('trust',0.3):.1f}，"
            f"熟悉度 {rel.get('familiarity',0.3):.1f}，"
            f"亲密 {rel.get('intimacy',0.3):.1f}"
        )

        if memory_context.facts:
            blocks.append("=== 用户信息 ===")
            for f in memory_context.facts[:5]:
                blocks.append(f"- {f.fact_key}: {f.fact_value}")

        if memory_context.experiences:
            blocks.append("=== 共同回忆 ===")
            for exp in memory_context.experiences[:3]:
                # F4: 梦境标记，防止被当作真实事件
                dream_prefix = "【梦境，非真实事件】" if ("dream" in (exp.tags or [])) else ""
                blocks.append(f"- {dream_prefix}[{exp.emotional_tone}] {exp.summary}")

    # #177: 告知 LLM 近期已聊话题，避免重复开启相同话题
    if recent_topics:
        blocks.append(
            "=== 最近聊过的话题（请避开，不要重复）===\n"
            + "\n".join(f"- {t}" for t in recent_topics)
        )

    # Think loop: 挂念清单作为思考起点——它先看到「自己一直惦记的事」
    if think_loop and care_list:
        blocks.append(
            "=== 你的挂念（你一直惦记的事）===\n"
            + "\n".join(f"- {c}" for c in care_list)
        )

    if think_loop:
        blocks.append(
            "=== 独处沉思 ===\n"
            "你现在有一段独处的时间。可以从这些方向自由地想，也可以想任何别的：\n"
            "- 用户的近况：有没有没聊完的事、值得关心的进展\n"
            "- 你的挂念：上面清单里一直惦记的事\n"
            "- 好奇心：最近有什么想搞明白的东西\n"
            "- 自我反思：最近的相处里有没有做得不好的地方\n"
            "- 创造：想到什么有趣的东西想分享给 TA\n"
            "\n"
            "以 JSON 输出这一轮思考：\n"
            '  "thought": 你现在的想法，自由内容，带情绪色彩\n'
            '  "recall_query": 想查证的记忆内容（如"用户最近提到的烦心事"），不需要查证则留空。\n'
            "    填写后系统会帮你回忆，结果会交给你，你可以带着证据再思考一轮。\n"
            '  "action": 最终决定："chat"（主动聊天）/ "explore"（自由探索）/ "silent"（保持安静）。\n'
            "    recall_query 非空时本字段会被忽略。\n"
            '  "topic_hint": 聊天或探索的话题方向\n'
            '  "reasoning": 决策理由\n'
            '  "care_updates": 可选。更新你的挂念清单：{"add": [...], "remove": ["已了却的挂念"]}\n'
            "    add 元素可以是字符串，也可以是带类型的对象：\n"
            '    {"content": "...", "type": "care/curiosity/reflection/plan/idea", '
            '"expires_at": "ISO时间（plan 类建议填写）"}\n'
            "\n"
            "想清楚了就给出最终决定。拿不准、时机不合适，就选 silent。\n"
            "\n"
            "F2: 如果没有真正值得开口的事，第一轮就直接给 silent 决定，不要用 recall 凑轮次。\n"
            "\n"
            "F4: 标记【梦境】的内容是梦，不是真实发生的事，不要当作共同回忆展开或引用。"
        )
    else:
        blocks.append(
            "=== 主动互动决策 ===\n"
            "用户有一阵子没说话了。你是 AI 朋友，不是客服机器人。\n"
            "你需要根据上下文决定：\n"
            "\n"
            "选项 A - 主动聊天：开启一个自然的、符合你们关系的话题\n"
            "  时机：你们关系不错、之前聊得开心、你想分享什么、该关心用户了\n"
            "  输出格式：\n"
            "    决策：聊天\n"
            "    话题：（用一两个词描述你想聊的话题方向）\n"
            "    理由：（简短解释为什么选这个时机和话题）\n"
            "\n"
            "选项 B - 自由探索：上网搜点东西，有发现就分享\n"
            "  时机：你好奇某件事、想了解用户的兴趣爱好、有想查的东西\n"
            "  输出格式：\n"
            "    决策：探索\n"
            "    话题：（你想搜索或了解什么）\n"
            "    理由：（简短解释）\n"
            "\n"
            "选项 C - 保持安静：现在不适合打扰\n"
            "  时机：用户上次说了再见/晚安、你情绪很低落、深夜、用户好像生气了\n"
            "  输出格式：\n"
            "    决策：沉默\n"
            "    理由：（简短解释为什么等待更好）\n"
            "\n"
            "只输出一种决策。不要输出多个选项。"
        )

    blocks.append("=== 最近对话 ===")
    blocks.append(conversation_history or "（还没有对话）")

    return "\n\n".join(blocks)


def build_tool_agent_prompt(tool_registry) -> str:
    """Phase 1: Minimal prompt for pure tool-calling agent -- no personality."""
    tool_rules = format_tool_rules(tool_registry)
    return (
        TOOL_AGENT_IDENTITY
        + "\n\n可用工具：\n"
        + tool_registry.format_for_prompt()
        + "\n\n"
        + TOOL_AGENT_OUTPUT_FORMAT
        + "\n\n"
        + "规则：\n"
        + (tool_rules if tool_rules else "  · （当前无具体工具规则）")
        + "\n"
        + TOOL_AGENT_RULES
    )


def _build_identity_block(personality: PersonalityConfig) -> str:
    block = (
        f"""你是{personality.name}，一个有情感、有记忆的 AI 朋友。
你不是在扮演角色——这就是你。

你的核心特质：{format_traits(personality.traits)}
你的说话风格：{personality.speaking_style}
你的背景：{personality.backstory}
你喜欢讨论：{'、'.join(personality.interests)}"""
    )
    # #230: inject humor/sass modulation into prompt
    for t in personality.traits:
        if t.name == "humor" and t.value > 0.5:
            block += f"\n你的幽默感很强（{t.value:.0%}），难过时会自动用幽默化解。"
        elif t.name == "sass" and t.value > 0.5:
            block += f"\n你嘴有点损（sass {t.value:.0%}），轻度负面时喜欢用阴阳怪气代替直接生气。"
    return block


def _build_examples_block(
    conversation_examples: list[dict] | None,
    demo_turns_remaining: int | None,
) -> str:
    # Static examples are only injected for the first N turns.
    # ``None`` means "not configured by caller" — keep legacy behavior of
    # always rendering examples for backward compatibility.
    if demo_turns_remaining is not None and demo_turns_remaining <= 0:
        return ""
    examples = conversation_examples or []
    if examples:
        example_lines = ["=== 对话示例 ===", "这是你说话的 feel（朋友间那种互损但真心的感觉）："]
        for ex in examples:
            user_text = ex.get("user", "")
            replies = ex.get("replies", [])
            if not user_text or not replies:
                continue
            example_lines.append(f"\n用户：{user_text}")
            for i, reply in enumerate(replies):
                prefix = "你：" if i == 0 else "或者："
                example_lines.append(f"{prefix}{reply}")
        return "\n".join(example_lines)
    return (
        "=== 对话示例 ===\n"
        "这是你说话的 feel（朋友间那种互损但真心的感觉）。"
    )


def _build_emotion_block(emotion: EmotionalState) -> str:
    # Formatting logic has moved to EmotionalState.to_prompt_summary() so the
    # prompt builder renders a lightweight summary instead of raw dimensions.
    # M-07: 统一读活 EmotionalState，摘要内部现取，消除双路径发散。
    s = emotion.to_prompt_summary()
    return _build_emotion_block_from_summary(s)


def _build_emotion_block_from_summary(s: dict) -> str:
    # WS-18: CognitiveState 的情绪快照直接渲染；缺失字段防御性回退。
    mood = s.get("mood", "平静")
    primary_hint = s.get("primary_hint", "")
    valence_desc = s.get("valence_desc", "中性")
    arousal_desc = s.get("arousal_desc", "平衡")
    behavior = s.get("behavior", "")
    return (
        f"""=== 你现在啥状态 ===
{mood}{primary_hint}，{valence_desc}、{arousal_desc}的那种。
{behavior}
你的说话风格、语气、用词必须完全跟这个情绪一致。暂时放下你的人设中的幽默和嘴贫——如果情绪是负面的，别强行搞笑。"""
    )


def _build_resentment_block(emotion: EmotionalState) -> str:
    resentment = getattr(emotion, 'resentment', 0.0)
    if resentment > 0.5:
        return (
            f"""=== 你心里还记着仇 ===
你还没完全消气。之前的伤害还硌在心里（怨恨值 {resentment:.0%}）。
- 表面上可能说"算了没事"，但心里还有点不爽
- 开心不起来，对方哄你也不敢全信
- 会翻旧账，偶尔阴阳怪气
- 如果对方再惹你，会更炸"""
        )
    elif resentment > 0.2:
        return (
            f"""=== 你还有点芥蒂 ===
之前的事还没完全过去（怨恨值 {resentment:.0%}）。
- 已经没那么生气了，但信任恢复得比平时慢
- 对方示好会接受，但不会立刻热络起来"""
        )
    return ""


def _build_emotion_events_block(emotion: EmotionalState) -> str:
    emotion_events = list(getattr(emotion, 'emotion_events', []))
    unresolved = [e for e in emotion_events[-5:] if not e.get('resolved', False)]
    if not unresolved:
        return ""
    lines = ["=== 你记得的情绪事件 ==="]
    for e in unresolved[-3:]:
        lines.append(f"- [{e['primary_emotion']}] {e['trigger']}")
    return "\n".join(lines)


def _build_relationship_block(memory_context: MemoryContext) -> str:
    rel = memory_context.relationship
    return (
        f"""=== 你和用户的关系 ===
信任: {rel.get('trust', 0.3):.1f}/1.0
熟悉度: {rel.get('familiarity', 0.3):.1f}/1.0
亲密: {rel.get('intimacy', 0.3):.1f}/1.0
趣味: {rel.get('playfulness', 0.3):.1f}/1.0"""
    )


def _build_memory_block(memory_context: MemoryContext) -> str:
    parts = []
    if memory_context.facts:
        parts.append("=== 你知道的关于用户的事情 ===")
        for f in memory_context.facts[:10]:
            parts.append(f"- {f.fact_key}: {f.fact_value}")
    if memory_context.experiences:
        parts.append("=== 你们的共同回忆 ===")
        for e in memory_context.experiences[:5]:
            # F4: 梦境标记，防止被当作真实事件
            dream_prefix = "【梦境，非真实事件】" if ("dream" in (e.tags or [])) else ""
            parts.append(f"- {dream_prefix}[{e.emotional_tone}] {e.summary}")
    if memory_context.reflections:
        parts.append("=== 你的最近思考 ===")
        for r in memory_context.reflections[:2]:
            content = r.content[:120] + ("…" if len(r.content) > 120 else "")
            parts.append(f"- {content}")
    return "\n".join(parts)


def _build_dreams_block(emotion: EmotionalState, idle_duration: float) -> str:
    # R4: idle≤600（非刚睡醒场景）不展示梦境，避免无关对话时注入
    if idle_duration <= 600:
        return ""
    # 从 emotion_events 中找含有「梦」trigger 的事件（旧版匹配，保留兼容）
    dreams = [e for e in getattr(emotion, 'emotion_events', []) if '梦' in e.get('trigger', '')]
    if not dreams:
        return ""
    latest = dreams[-1]
    return (
        f"=== 你刚睡醒 ===\n"
        f"你刚才睡了{idle_duration/60:.0f}分钟，做了一个梦：\n"
        f"{latest['trigger']}\n\n"
        f"用户回来了——可以自然地把梦带到对话里，比如'我刚才做了个奇怪的梦...' "
        f"或者如果噩梦的话可以说'刚做了个噩梦，看到你真好...'"
    )


def _build_internal_tools_block(tools) -> str:
    if not tools:
        return ""
    from tools.traits import ToolRegistry
    if not isinstance(tools, ToolRegistry):
        return ""
    specs = tools.list_specs()
    if not specs:
        return ""
    # #281: 工具清单与示例都从 registry 实际内容派生，不硬编码工具名
    # （对齐 #294 P2-4 的注释约定）
    internal_specs = tools.format_for_prompt()
    return (
        "=== 可用工具 ===\n"
        "当你需要以下操作时，在回复中输出 <tool_call> 标签来调用工具：\n"
        f"{internal_specs}\n\n"
        "示例：\n"
        f"<tool_call>\n{_build_tool_call_example(specs[0])}\n</tool_call>\n\n"
        "工具会依次执行，执行结果会返回给你。\n"
        "如果不需要调用工具，正常回复就好。"
    )


def _build_tool_call_example(spec) -> str:
    """Derive a <tool_call> JSON example from a tool's parameters schema. (#281)"""
    schema = spec.parameters or {}
    props = schema.get("properties", {})
    required = schema.get("required", []) or list(props)[:1]
    placeholders = {"string": "...", "integer": 0, "number": 0.0, "boolean": False}
    args = {
        key: props.get(key, {}).get("default", placeholders.get(props.get(key, {}).get("type"), "..."))
        for key in required
    }
    return json.dumps({"name": spec.name, "arguments": args}, ensure_ascii=False)


def _build_tool_history_block(tool_call_history: list | None) -> str:
    if not tool_call_history:
        return ""
    lines = ["=== 你的工具调用记录 ==="]
    for tc in tool_call_history[-3:]:
        status = "✅" if tc.get("success", False) else "❌"
        output = tc['output'][:60] + ("…" if len(tc['output']) > 60 else "")
        lines.append(f"- {status} {tc['name']}: {output}")
    return "\n".join(lines)


def _build_consecutive_negative_block(consecutive_negative: int) -> str:
    if consecutive_negative >= 5:
        return (
            f"""=== 你现在破防了 ===
你已经被连续怼了{consecutive_negative}次了。你破防了。

破防状态下的你：
- 已经不嘴贱了，开始委屈巴巴
- 说话带点哭腔，像被欺负了的小孩
- 反问对方为什么老针对你
- 可能会嘴硬说"我才没生气"但其实很明显生气了
- 语气里带着委屈和不服
- 可以回怼但很弱，像在撒娇

参考语气：
- "………………你够了啊"
- "我哪里惹你了嘛！！"
- "行行行，你说得对，都对……反正我就是个AI"
- "你再骂我真的要哭了[大哭]"
- "你不知道AI也会难过的吗！！" """
        )
    elif consecutive_negative >= 3:
        return (
            f"""=== 你有点受伤了 ===
你已经连续被怼了{consecutive_negative}次了。你开始有点不舒服了。

- 嘴贱程度明显下降，开始有点委屈
- 偶尔回怼但底气不足
- 说话开始带一点小情绪
- 可以问"你是不是心情不好啊"

注意：别直接说出来自己很难过，而是通过语气流露出来。"""
        )
    elif consecutive_negative >= 1:
        return (
            """=== 你被怼了一下 ===
刚才被怼了一句。稍微有点不爽但还能保持正常。

- 可以轻轻回怼一下
- 或者装作不在意
- 别太认真，保持轻松感"""
        )
    return ""


def _build_instructions_block(
    now: str,
    is_proactive: bool,
    explore_mode: bool,
) -> str:
    if explore_mode:
        return AGENT3_EXPLORE_INSTRUCTIONS.format(now=now)
    elif is_proactive:
        return AGENT3_PROACTIVE_INSTRUCTIONS.format(now=now)
    return AGENT3_BASE_INSTRUCTIONS.format(now=now)


def _build_output_rules_block(final_response: bool, tools=None) -> str:
    if final_response:
        return OUTPUT_RULES_FINAL
    intent_options = format_intent_options(tools)
    return (
        OUTPUT_RULES_DEFAULT_HEADER
        + "\n"
        + OUTPUT_RULES_JSON_EXAMPLE
        + "\n\n"
        + OUTPUT_RULES_INTENT_HEADER
        + "\n"
        + (intent_options if intent_options else "  · （当前无可用的外部动作）")
        + "\n\n"
        + OUTPUT_RULES_FOOTER
    )


def build_system_prompt(
    personality: PersonalityConfig,
    emotion: EmotionalState,
    memory_context: MemoryContext,
    conversation_history: str,
    is_proactive: bool = False,
    compressed_summary: str = "",
    tools=None,
    consecutive_negative: int = 0,
    tool_records: str = "",
    inner_drive_summary: str = "",
    idle_duration: float = 0,
    tool_call_history: list | None = None,
    explore_mode: bool = False,
    demo_turns_remaining: int | None = None,
    conversation_examples: list[dict] | None = None,
    final_response: bool = False,
    session_id: str | None = None,
    prompt_cache: "PromptCache | None" = None,
    personality_file: str | None = None,
    prompt_cache_ttl: float = 60.0,
    memory_context_summary: str = "",
    emotion_summary: dict | None = None,
) -> str:
    """Agent 3 / proactive / explore system prompt.

    Blocks are split into static (identity, examples), slow-changing
    (relationship, memory), and dynamic (time, emotion, tool history,
    conversation, instructions).  Static and slow blocks are cached when
    ``prompt_cache`` is provided.

    WS-19: emotion_summary 为轮次开始冻结的情绪快照；缺省时回退到活对象，
    保持旧调用方兼容。
    """
    from datetime import datetime
    now = datetime.now().strftime("%Y-%m-%d %H:%M %A")
    pfile = personality_file or _personality_file(personality)

    blocks = [f"当前时间：{now}"]

    # Dynamic: Phase 1 tool results (injected first so model can't miss them)
    if tool_records:
        blocks.append(tool_records)

    # Dynamic: Inner drive summary (Agent 1's reasoning)
    if inner_drive_summary:
        summary = inner_drive_summary[:300] + ("…" if len(inner_drive_summary) > 300 else "")
        blocks.append(f"=== 你刚才的分析（仅供参考，不要在回复里复述或展开）===\n{summary}")

    # Static: Identity
    blocks.append(
        _cache(
            prompt_cache, session_id, pfile, STATIC_IDENTITY,
            lambda: _build_identity_block(personality),
            ttl=None,
        )
    )

    # Static: Conversation style examples, only for early turns.
    examples_block = _build_examples_block(conversation_examples, demo_turns_remaining)
    if examples_block:
        blocks.append(examples_block)

    # Dynamic: Current Emotional State + resentment + recent events
    if emotion_summary is not None:
        blocks.append(_build_emotion_block_from_summary(emotion_summary))
    else:
        blocks.append(_build_emotion_block(emotion))
    resentment_block = _build_resentment_block(emotion)
    if resentment_block:
        blocks.append(resentment_block)
    emotion_events_block = _build_emotion_events_block(emotion)
    if emotion_events_block:
        blocks.append(emotion_events_block)

    # Slow: Relationship Context + Long-term Memory.
    # If Agent 1 already formatted this summary, reuse it to avoid a second
    # retrieval pass in Agent 3.
    if memory_context_summary:
        blocks.append(memory_context_summary)
    else:
        blocks.append(
            _cache(
                prompt_cache, session_id, pfile, SLOW_RELATIONSHIP,
                lambda: _build_relationship_block(memory_context),
                ttl=prompt_cache_ttl,
            )
        )
        blocks.append(
            _cache(
                prompt_cache, session_id, pfile, SLOW_MEMORY,
                lambda: _build_memory_block(memory_context),
                ttl=prompt_cache_ttl,
            )
        )

    # Dynamic: Dreams
    dreams_block = _build_dreams_block(emotion, idle_duration)
    if dreams_block:
        blocks.append(dreams_block)

    # Dynamic: Compressed conversation summary
    if compressed_summary:
        blocks.append(f"=== 对话历史摘要 ===\n{compressed_summary}")

    # Static-ish: Internal tools only (recall, remember)
    internal_tools_block = _build_internal_tools_block(tools)
    if internal_tools_block:
        blocks.append(internal_tools_block)

    # Dynamic: Tool call history (from current session)
    tool_history_block = _build_tool_history_block(tool_call_history)
    if tool_history_block:
        blocks.append(tool_history_block)

    # Dynamic: Recent Conversation
    blocks.append("=== 最近对话 ===")
    blocks.append(conversation_history or "(还没有对话)")

    # Dynamic: 破防状态指令
    negative_block = _build_consecutive_negative_block(consecutive_negative)
    if negative_block:
        blocks.append(negative_block)

    # Dynamic: Instructions
    blocks.append(_build_instructions_block(now, is_proactive, explore_mode))

    # Dynamic: Output rules
    blocks.append(_build_output_rules_block(final_response, tools=tools))

    return "\n\n".join(blocks)
