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


# Mapping from canonical tool name to the intent alias used by Agent 3 when it
# proactively proposes an external action.  Empty means "no proactive intent".
_TOOL_INTENT_ALIASES: dict[str, str] = {
    "music_play": "play_music",
    "notify": "send_notify",
    "web_search": "search_web",
    "web_fetch": "fetch_url",
    "read_file": "read_file",
}


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
