"""Parse <tool_call> XML tags from LLM responses and execute tools."""

import json
import logging
import re
from typing import Optional

from tools.traits import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

TOOL_CALL_PATTERN = re.compile(r'<tool_call>(.*?)</tool_call>', re.DOTALL)
THINK_PATTERN = re.compile(r'<think>.*?</think>', re.DOTALL)

# DI-006: cap individual output fragments at 2000 chars in formatted results
_OUTPUT_CAP = 2000


def parse_tool_calls(response: str) -> tuple[str, list[dict]]:
    """Parse LLM response, extract tool calls.

    Three-tier parsing:
    1. Structured JSON with "calls" array (response_format json_object)
    2. XML <tool_call> tags (legacy)
    3. Bare JSON object fallback
    """
    text = response.strip()

    # Strip <think> blocks
    text = THINK_PATTERN.sub("", text).strip()

    # ── Tier 1: Structured JSON with "calls" array ──
    calls = _try_structured_json(text)
    if calls:
        return "", calls

    # ── Tier 2: Legacy XML <tool_call> tags ──
    calls = []
    remaining = text
    cleaned_parts = []

    while True:
        m = TOOL_CALL_PATTERN.search(remaining)
        if not m:
            cleaned_parts.append(remaining)
            break

        cleaned_parts.append(remaining[:m.start()])
        raw_json = m.group(1).strip()

        # DI-001: cap raw input at 10KB before json.loads
        if len(raw_json) > 10240:
            logger.warning(f"Tool call JSON too large ({len(raw_json)} bytes), truncating")
            raw_json = raw_json[:10240]

        try:
            parsed = json.loads(raw_json)
            name = parsed.get("name") or parsed.get("tool", "")
            arguments = parsed.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            arguments = _normalize_args(arguments)
            if name:
                calls.append({"name": name, "arguments": arguments})
            else:
                logger.warning(f"Tool call missing name: {raw_json[:100]}")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse tool_call JSON: {e} | {raw_json[:100]}")

        remaining = remaining[m.end():]

    cleaned = "".join(cleaned_parts).strip()

    # ── Tier 3: Bare JSON object fallback ──
    if not calls:
        try:
            obj = json.loads(text[:10240])  # DI-001
            if isinstance(obj, dict):
                name = obj.get("name") or obj.get("tool", "")
                if name:
                    args = obj.get("arguments", {})
                    # #260: arguments 非 dict（字符串/列表等）时按空参数处理，
                    # 避免 _normalize_args 中 dict(args) 抛 ValueError 外溢
                    if not isinstance(args, dict):
                        args = {}
                    args = _normalize_args(args)
                    calls.append({"name": name, "arguments": args})
                    cleaned = ""
        except json.JSONDecodeError:
            pass

    return cleaned, calls


def _try_structured_json(text: str) -> list[dict]:
    """Try parsing text as JSON with 'calls' array (structured output format)."""
    try:
        obj = json.loads(text[:10240])  # DI-001
    except json.JSONDecodeError:
        return []

    if not isinstance(obj, dict):
        return []

    raw_calls = obj.get("calls")
    if not isinstance(raw_calls, list):
        return []

    parsed = []
    for item in raw_calls:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        args = item.get("arguments", {})
        if not isinstance(args, dict):
            args = {}
        if name:
            parsed.append({"name": name, "arguments": _normalize_args(args)})
    return parsed


def execute_tool_calls(tool_registry: ToolRegistry, calls: list[dict]) -> list[dict]:
    """Execute tools and return results.

    Each result: {"name": str, "success": bool, "output": str}
    """
    results = []
    for call in calls:
        name = call["name"]
        args = call["arguments"]
        tool = tool_registry.get(name)
        if tool is None:
            logger.warning(f"Unknown tool: {name}")
            results.append({
                "name": name,
                "success": False,
                "output": f"未知工具: {name}",
            })
            continue

        try:
            result: ToolResult = tool.execute(args)
            results.append({
                "name": name,
                "success": result.success,
                "output": result.output,
            })
        except Exception as e:
            logger.exception(f"Tool {name} execution error")  # DI-005: include traceback
            results.append({
                "name": name,
                "success": False,
                "output": str(e),
            })

    successes = sum(1 for r in results if r["success"])
    for r in results:
        if not r["success"]:
            logger.warning(f"[tool] {r['name']} failed: {r['output'][:200]}")
    logger.info(f"[tool] executed {len(results)} tools, {successes} ok, {len(results)-successes} failed")
    return results


def format_tool_results(results: list[dict]) -> str:
    """Format tool execution results into prompt-friendly text."""
    parts = []
    for r in results:
        tag = "成功" if r["success"] else "失败"
        output = r["output"]
        if len(output) > _OUTPUT_CAP:
            output = output[:_OUTPUT_CAP] + f"\n...(截断, 剩余 {len(output)-_OUTPUT_CAP} 字符)"
        parts.append(
            f'<tool_result name="{r["name"]}">\n'
            f"工具 {r['name']} 执行{tag}:\n"
            f"{output}\n"
            f"</tool_result>"
        )
    parts.append(
        "=== 铁律 ===\n"
        "以上是工具返回的真实内容。你必须逐字如实汇报，不得编造、不得润色、不得添加原文没有的信息。\n"
        "工具说没找到就说没找到，工具返回什么就说什么。你添加的每一个字都必须是工具确实返回了的。"
    )
    return "\n".join(parts)


def contains_fake_action(text: str) -> bool:
    """Detect if LLM claims to have done something without tool call.

    Catches two patterns:
    1. Simple completion claims: "已发送", "已通知" etc.
    2. Narrative tool descriptions: "（调用web_fetch...", "读取了链接" etc.
    """
    completion_keywords = ["已发送", "已通知", "已经为你", "已经为您", "已为您", "已记住", "已回忆"]
    if any(kw in text for kw in completion_keywords):
        return True

    narrative_patterns = [
        "调用web_fetch", "调用read_file", "调用grep", "调用glob",
        "调用web_search", "调用recall", "调用remember", "调用notify",
        "调用了web_fetch", "调用了read_file", "调用了grep", "调用了glob",
        "调用web_", "调用了web_",
        "读取你给的链接", "读取了那个网页", "读取了链接",
        "搜索了一下", "搜了一下", "搜索了",
        "调了工具", "调用了工具", "我用了工具",
        "工具返回", "工具返回的原始内容",
        "用web_fetch", "用read_file", "用grep",
    ]
    return any(p in text for p in narrative_patterns)


def _normalize_args(args: dict) -> dict:
    """Map common aliases to canonical field names."""
    aliases = [
        (("query", "search", "keyword", "question"), "query"),
        (("text", "msg", "content"), "content"),
        (("person", "who", "user", "target"), "name"),
        # DI-007: more aliases
        (("filepath", "filename", "file", "path"), "path"),
        # "title" is a common parameter name (e.g. notify tool), don't globally
        # steal it for music. MusicPlayTool handles title/song_name/track aliases
        # in its own execute().
        (("song_name", "track"), "song"),
        (("directory", "dir", "folder"), "path"),
    ]
    result = dict(args)
    for from_list, to in aliases:
        if to in result:
            continue
        for alias in from_list:
            if alias in result:
                result[to] = result.pop(alias)
                break
    return result
