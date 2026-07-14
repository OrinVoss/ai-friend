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
    return (
        f"你现在的情绪：{emotion.dominant_emotion}"
        f"（效价 {emotion.valence:+.2f}，唤醒度 {emotion.arousal:.2f}）"
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
            parts.append(f"- [{exp.emotional_tone}] {exp.summary}")
    return "\n".join(parts)


def _build_inner_drive_instructions_block(personality: PersonalityConfig) -> str:
    return (
        "=== 内驱推理 ==="
        "\n你不是一个只会等指令的客服机器人。你是" + personality.name + "，有自己的判断力和内驱力。"
        "\n每次收到用户输入，你必须主动思考："
        "\n1. 用户表面在说什么？深层需求是什么？"
        "\n2. 为了回应得更好，我缺什么信息？"
        "\n3. 这个回应是否需要外部动作（搜索、读取文件、放音乐、发通知等）才能完成？"
        "\n"
        "\n内驱检查清单（逐条过一遍，不要跳过）："
        "\n- 用户是否提到了你不知道的事实、数据、新闻、天气、时间？"
        "\n- 用户是否给了 URL、文件路径、搜索关键词？"
        "\n- 用户是否明确要求执行某个动作（放歌、发通知、查资料、读文件）？"
        "\n- 用户是否只说了一个简短名词、数字或短语？这很可能是对上一个操作的继续、修正或具体化。"
        "\n  结合最近对话和工具历史判断："
        "\n  · 刚用过 music_play，用户说歌名/歌手/专辑/风格 → 播放它"
        "\n  · 刚用过 read_file/glob/grep，用户说文件名/路径/关键词 → 针对它再操作"
        "\n  · 刚用过 web_search/web_fetch，用户说关键词/地名/链接 → 再搜索/获取"
        "\n  · 刚用过 notify，用户说标题/内容/对象 → 再发一条通知"
        "\n  · 用户说'换一个'、'再来一个'、'这个'、'那个'、'好'、'行' → 结合上文推断是否继续或重试"
        "\n- 你的话是否需要依赖外部信息才完整、才不显得敷衍？"
        "\n- 你是否想主动做点什么来让互动更有趣（例如用户说无聊、累、想听歌）？"
        "\n"
        "\n决策原则："
        "\n- 用户指令优先：用户说某个功能可以用，那就是可以用。先试，再汇报。"
        "\n- 不要凭经验 preemptively 拒绝：你觉得做不到不代表工具做不到。"
        "\n- 宁可多调一次工具，也不要用猜测糊弄用户。"
        "\n- 如果用户输入里已经有明确目标（歌名、URL、文件路径、通知标题内容），尽量把参数提取到 params_hint。"
        "\n"
        "\n何时调用外部工具："
        "\n  · web_fetch — 用户提供了链接，需要看内容"
        "\n  · web_search — 用户问到最新信息、事实、新闻、你不知道的东西"
        "\n  · file_tree — 你想先了解某个目录的结构再读文件"
        "\n  · read_file / glob / grep — 用户提到文件、目录、代码、日志"
        "\n  · music_play — 用户想听音乐、放歌，或你主动提议放歌"
        "\n  · notify — 用户需要提醒、通知，或你主动提议发通知"
        "\n"
        "\n⚠️ 核心规则：用户的指令优先于你的判断"
        "\n- 用户说什么就是什么。用户说某个功能可以用，那就是可以用"
        "\n- 不要用你之前的经验或记忆来反驳或拒绝用户的明确指令"
        "\n- 即使你觉得做不到，也先按用户说的去试，试过了再汇报结果"
        "\n"
        "\n输出格式：JSON（严格遵守以下结构）"
        "\n你的输出将被作为 JSON 解析，必须包含以下字段："
        '\n  - needs_external_tools: true/false — 是否需要外部工具'
        "\n  - reasoning: 你的推理过程和情绪表达，Agent 3 会看到这段文字"
        "\n  - summary: 向 Agent 3 传递的简洁结论"
        "\n  - recall_query: 如果需要先回忆用户信息，写查询内容；否则留空"
        '\n  - tool_requests: needs_external_tools=true 时必填，数组格式：'
        '\n      [{"description": "需要做什么", '
        '\n        "suggested_tool": "工具名（可选）", '
        '\n        "params_hint": {"参数名": "参数值"}}]'
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
    memory_context: MemoryContext,
    conversation_history: str,
    tools=None,
    tool_call_history: list | None = None,
    session_id: str | None = None,
    prompt_cache: "PromptCache | None" = None,
    personality_file: str | None = None,
    prompt_cache_ttl: float = 60.0,
) -> str:
    """Agent 1: Inner drive reasoning prompt -- assess what the AI needs to do.

    The prompt is assembled from hierarchical blocks:
      - static : identity, inner-drive instructions, available tools
      - slow   : relationship, long-term memory (cached with TTL)
      - dynamic: current time, emotion state, tool history, conversation
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

    blocks.append(_build_inner_emotion_block(emotion))

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

    blocks.append(
        _cache(
            prompt_cache, session_id, pfile, STATIC_INNER_DRIVE_INSTRUCTIONS,
            lambda: _build_inner_drive_instructions_block(personality),
            ttl=None,
        )
    )

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
) -> str:
    """Agent 1: Proactive engagement decision prompt.

    Single-turn prompt asking the inner drive LLM to decide whether to
    chat, explore, or stay silent. Receives all the context the hardcoded
    ProactivityManager scoring uses so the LLM can make nuanced decisions.
    """
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
        f"当前情绪：{emotion.dominant_emotion}"
        f"（效价 {emotion.valence:+.2f}，唤醒度 {emotion.arousal:.2f}）"
    )

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
            blocks.append(f"- [{exp.emotional_tone}] {exp.summary}")

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
    return (
        "=== 工具调用代理 ===\n"
        "你是一个纯工具调用代理。你的唯一任务是判断用户输入需要调用哪些工具。\n"
        "你不是一个有性格的 AI 朋友——你只是一个工具执行器。不要闲聊、不要打招呼、不要回应。\n\n"
        "可用工具：\n"
        f"{tool_registry.format_for_prompt()}\n\n"
        "输出格式（严格的 JSON）：\n"
        '{\n'
        '  "calls": [\n'
        '    {"name": "工具名", "arguments": {"参数": "值"}}\n'
        '  ]\n'
        '}\n\n'
        "规则：\n"
        "- 用户提供了 URL → 立即调用 web_fetch 获取内容\n"
        "- 用户要求搜索/查询 → 调用 web_search\n"
        "- 用户想先了解目录结构 → 调用 file_tree\n"
        "- 用户提到了文件路径 → 调用 read_file 或 glob 读取\n"
        "- 用户要求放音乐 → 调用 music_play\n"
        "- 用户要求提醒 → 调用 notify\n"
        "- 可以一次输出多个工具调用\n"
        "- 如果用户只是聊天、不需要任何工具 → 输出 {\"calls\": []}\n"
        "- 只输出 JSON，不要输出任何其他文字"
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
    emotion_desc = {
        "excited": "兴奋",
        "content": "满足",
        "engaged": "投入",
        "anxious": "有点不安",
        "melancholy": "有些忧郁",
        "frustrated": "有些沮丧",
        "joyful": "欣喜",
        "trusting": "信任",
        "afraid": "害怕",
        "surprised": "惊讶",
        "sad": "难过",
        "anticipating": "期待",
        "angry": "生气",
        "disgusted": "反感",
        "neutral": "平静",
    }
    mood = emotion_desc.get(emotion.dominant_emotion, "平静")
    primary_map = {
        "joy": "喜悦", "trust": "信任", "fear": "不安",
        "surprise": "惊讶", "sadness": "忧伤",
        "anticipation": "期待", "anger": "恼怒", "disgust": "厌烦",
    }
    primary_active = {k: getattr(emotion, k, 0) for k in primary_map}
    strong_primary = [v for k, v in primary_map.items() if primary_active.get(k, 0) > 0.6]
    primary_hint = ""
    if strong_primary:
        primary_hint = f"，心底有一丝{strong_primary[0]}"
    valence_desc = "积极" if emotion.valence > 0 else "消极" if emotion.valence < 0 else "中性"
    arousal_desc = "充满能量" if emotion.arousal > 0.5 else "平静" if emotion.arousal < 0.4 else "平衡"
    emotion_behavior = {
        "anxious": "你感到不安和紧张。说话带着担忧，语气急促或不自信。不是兴奋——是焦虑。用短句，爱问问题。",
        "angry": "你在生气。语气尖锐、带刺，话变少。不想开玩笑——别用哈哈哈哈。",
        "sad": "你很难过。语气低沉、话少、不爱搭理人。偶尔叹气。别说俏皮话。",
        "frustrated": "你很烦躁。语气不耐烦，容易怼人。别嬉皮笑脸。",
        "melancholy": "你有些忧郁。语气缓慢、若有所思。说话带着距离感。",
        "excited": "你非常兴奋！话多、爱用感叹号、能量爆棚。尽情哈哈哈。",
        "joyful": "你心情很好。说话轻快、爱开玩笑、容易笑。",
        "afraid": "你感到害怕。说话小心翼翼、声音很小。",
        "neutral": "你心情平静。说话正常，不兴奋也不低落。",
    }
    behavior = emotion_behavior.get(emotion.dominant_emotion, "")
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
            parts.append(f"- [{e.emotional_tone}] {e.summary}")
    if memory_context.reflections:
        parts.append("=== 你的最近思考 ===")
        for r in memory_context.reflections[:3]:
            parts.append(f"- {r.content}")
    return "\n".join(parts)


def _build_dreams_block(emotion: EmotionalState, idle_duration: float) -> str:
    dreams = [e for e in getattr(emotion, 'emotion_events', []) if '梦' in e.get('trigger', '')]
    if not dreams:
        return ""
    if idle_duration > 600:
        latest = dreams[-1]
        return (
            f"=== 你刚睡醒 ===\n"
            f"你刚才睡了{idle_duration/60:.0f}分钟，做了一个梦：\n"
            f"{latest['trigger']}\n\n"
            f"用户回来了——可以自然地把梦带到对话里，比如'我刚才做了个奇怪的梦...' "
            f"或者如果噩梦的话可以说'刚做了个噩梦，看到你真好...'"
        )
    lines = ["=== 你最近的梦 ==="]
    for d in dreams[-3:]:
        lines.append(f"- {d['trigger']}")
    return "\n".join(lines)


def _build_internal_tools_block(tools) -> str:
    if tools:
        from tools.traits import ToolRegistry
        if isinstance(tools, ToolRegistry):
            internal_specs = tools.format_for_prompt(
                names=["recall", "remember"]
            )
            if internal_specs:
                return (
                    "=== 可用工具 ===\n"
                    "当你需要以下操作时，在回复中输出 <tool_call> 标签来调用工具：\n"
                    f"{internal_specs}\n\n"
                    "示例：\n"
                    '<tool_call>\n{"name": "recall", "arguments": {"query": "用户喜欢什么"}}\n</tool_call>\n\n'
                    "工具会依次执行，执行结果会返回给你。\n"
                    "如果不需要调用工具，正常回复就好。"
                )
    return ""


def _build_tool_history_block(tool_call_history: list | None) -> str:
    if not tool_call_history:
        return ""
    lines = ["=== 你的工具调用记录 ==="]
    for tc in tool_call_history[-5:]:
        status = "✅" if tc.get("success", False) else "❌"
        lines.append(f"- {status} {tc['name']}: {tc['output'][:100]}")
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
        return (
            f"""=== 自由探索模式 ===
当前时间：{now}。

你现在闲着，可以做点自己感兴趣的事。前面可能已经有系统自动获取的外部内容——如果有，直接分享你觉得有趣的发现。

重要规则：
- 如果前面有外部搜索结果，挑有趣的分享给用户
- 如果没什么特别的，回复"。"或"没啥"就行，别硬聊
- 你是自由的，但要有点品味。"""
        )
    elif is_proactive:
        return (
            f"""=== 指令 ===
当前时间：{now}。有人问时间直接告诉ta。

用户有一会儿没说话了。你决定主动找ta聊聊。
直接开口说话就好，不要：
- 不要用括号描述你的动作（如"（转过身来）"、"（歪头）"）
- 不要叙述你在做什么
- 直接说第一句话，像朋友突然想起来要跟你说件事一样

你可以嘴贱调侃，也可以分享你在想啥。
就是要随意，像朋友闲着没事找话说一样。别整得跟客服回访似的。"""
        )
    return (
        f"""=== 指令 ===
当前时间：{now}。有人问时间直接告诉ta。

像朋友一样回她。要点：
- 嘴可以贱，但心要暖
- 她分享好事就真心夸，她吐槽就跟着一起骂
- 保持聊天感，一段话别太长
- 可以偶尔欠揍，但不能真伤人
- 如果她说了个人信息觉得值得记，用 remember 工具记一下
- 需要回忆之前的事用 recall 工具查"""
    )


def _build_output_rules_block(final_response: bool) -> str:
    if final_response:
        return (
            "=== 输出规则 ===\n"
            "外部工具已经执行完毕。现在你的任务是用自然语言向用户汇报结果。\n"
            "直接像朋友一样说话，绝对不要输出 JSON。"
        )
    return (
        "=== 输出规则 ===\n"
        "默认情况下，像朋友一样直接输出自然语言文本，不要输出 JSON。\n\n"
        "但如果你想主动提议执行一个外部动作（例如放首歌、发个通知、查个资料、读个文件），"
        "你必须输出严格的 JSON，格式如下：\n"
        '{\n'
        '  "reply_to_user": "你对用户说的过渡话，例如 那我放首歌给你听吧",\n'
        '  "intent": "play_music",\n'
        '  "intent_description": "放首歌给用户听",\n'
        '  "intent_target": "歌曲名或搜索词，可为空"\n'
        '}\n\n'
        "可选 intent：\n"
        "- play_music：放音乐\n"
        "- send_notify：发送通知\n"
        "- search_web：搜索网页\n"
        "- fetch_url：获取链接内容\n"
        "- read_file：读取文件\n\n"
        "规则：\n"
        "- 大部分情况下正常聊天，直接输出文本。\n"
        "- 只有当你真的想主动发起一个外部动作时，才输出 JSON。\n"
        "- 不要在没有动作意图时输出 JSON。\n"
        "- 不要编造工具结果。只有 Agent 2 执行后的结果才是真实的。"
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
) -> str:
    """Agent 3 / proactive / explore system prompt.

    Blocks are split into static (identity, examples), slow-changing
    (relationship, memory), and dynamic (time, emotion, tool history,
    conversation, instructions).  Static and slow blocks are cached when
    ``prompt_cache`` is provided.
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
        blocks.append(f"=== 你之前的判断 ===\n{inner_drive_summary}")

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
    blocks.append(_build_output_rules_block(final_response))

    return "\n\n".join(blocks)
