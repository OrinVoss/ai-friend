"""Tool-trigger rules derived from the live ToolRegistry.

Replaces hard-coded tool names in prompts/system.py (#294 P2-4).
Adding a new external tool only requires registering it in the main registry
and adding a rule description here.
"""

from tools.traits import ToolRegistry


# Mapping from canonical tool name to the Chinese trigger rule shown to the LLM.
# Keep descriptions concise and aligned with the tool's actual purpose.
_TOOL_RULES: dict[str, str] = {
    "web_fetch": "用户提供了 URL → 立即调用 web_fetch 获取内容",
    "web_search": "用户要求搜索/查询 → 调用 web_search",
    "file_tree": "用户想先了解目录结构 → 调用 file_tree",
    "read_file": "用户提到了文件路径 → 调用 read_file 读取",
    "glob": "用户想按模式找文件 → 调用 glob",
    "grep": "用户想搜索文件内容 → 调用 grep",
    "music_play": "用户要求放音乐 → 调用 music_play",
    "notify": "用户要求提醒/通知 → 调用 notify",
}


# Mapping from canonical tool name to the follow-up interpretation rule shown
# in Agent 1's checklist: how to read a short user reply right after the tool
# was used.  Lives next to _TOOL_RULES so tool names stay centralized here
# instead of being hard-coded in prompts/instructions.py (#294 P2-4, M-06).
_TOOL_FOLLOWUP_RULES: dict[str, str] = {
    "music_play": "刚用过 music_play，用户说歌名/歌手/专辑/风格 → 播放它",
    "read_file": "刚用过 read_file，用户说文件名/路径 → 再读一次",
    "glob": "刚用过 glob，用户说文件名/模式 → 再找一次",
    "grep": "刚用过 grep，用户说关键词 → 再搜一次",
    "web_search": "刚用过 web_search，用户说关键词/地名 → 再搜索",
    "web_fetch": "刚用过 web_fetch，用户说链接 → 再获取",
    "notify": "刚用过 notify，用户说标题/内容/对象 → 再发一条通知",
    "file_tree": "刚用过 file_tree，用户说目录名 → 再看目录结构",
}


# Mapping from canonical tool name to the intent alias used by Agent 3 when it
# proactively proposes an external action.  Empty means "no proactive intent".
_TOOL_INTENT_ALIASES: dict[str, str] = {
    "music_play": "play_music",
    "notify": "send_notify",
    "web_search": "search_web",
    "web_fetch": "fetch_url",
    "read_file": "read_file",
}

# Reverse mapping (intent alias → canonical tool name), derived so the two
# directions can never drift apart.  Agent 1 的 assess_agent3_intent 用它把
# Agent 3 提议的 intent 翻译回工具名（原硬编码于 inner_drive.py）。
INTENT_TO_TOOL: dict[str, str] = {v: k for k, v in _TOOL_INTENT_ALIASES.items()}


def format_tool_rules(registry: ToolRegistry | None) -> str:
    """Return a markdown list of trigger rules for tools present in registry."""
    if not registry:
        return ""
    rules = []
    for spec in registry.list_specs():
        rule = _TOOL_RULES.get(spec.name)
        if rule:
            rules.append(f"  · {rule}")
    return "\n".join(rules)


def format_tool_followup_rules(registry: ToolRegistry | None) -> str:
    """Return checklist follow-up lines for tools present in registry (M-06)."""
    if not registry:
        return ""
    present = {spec.name for spec in registry.list_specs()}
    return "\n".join(
        f"  · {rule}"
        for tool_name, rule in _TOOL_FOLLOWUP_RULES.items()
        if tool_name in present
    )


def format_intent_options(registry: ToolRegistry | None) -> str:
    """Return a markdown list of proactive intent options for Agent 3 output rules."""
    if not registry:
        return ""
    lines = []
    present = {spec.name for spec in registry.list_specs()}
    for tool_name, intent_alias in _TOOL_INTENT_ALIASES.items():
        if tool_name in present:
            description = _TOOL_RULES.get(tool_name, "").split(" → ")[0]
            if description:
                lines.append(f"- {intent_alias}：{description}")
    return "\n".join(lines)
