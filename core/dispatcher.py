"""Parse <tool_call> XML tags from LLM responses and execute tools."""

import json
import logging
import re
from typing import Optional

from tools.traits import ToolRegistry, ToolResult

logger = logging.getLogger(__name__)

TOOL_CALL_PATTERN = re.compile(r'<tool_call>(.*?)</tool_call>', re.DOTALL)
THINK_PATTERN = re.compile(r'<think>.*?</think>', re.DOTALL)


def parse_tool_calls(response: str) -> tuple[str, list[dict]]:
    """Parse LLM response, extract tool calls, return (cleaned_text, parsed_calls).

    Each parsed_call: {"name": str, "arguments": dict}
    Strips <think>...</think> blocks and <tool_call>...</tool_call> from visible text.
    """
    text = response

    # Strip <think> blocks
    text = THINK_PATTERN.sub("", text)

    # Extract <tool_call> blocks
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

        try:
            parsed = json.loads(raw_json)
            name = parsed.get("name") or parsed.get("tool", "")
            arguments = parsed.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            # Normalize argument field names
            arguments = _normalize_args(arguments)
            if name:
                calls.append({"name": name, "arguments": arguments})
            else:
                logger.warning(f"Tool call missing name: {raw_json[:100]}")
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse tool_call JSON: {e} | {raw_json[:100]}")

        remaining = remaining[m.end():]

    cleaned = "".join(cleaned_parts).strip()

    # Fallback: try to parse entire response as bare JSON tool call
    if not calls:
        trimmed = response.strip()
        try:
            obj = json.loads(trimmed)
            if isinstance(obj, dict):
                name = obj.get("name") or obj.get("tool", "")
                if name:
                    args = _normalize_args(obj.get("arguments", {}))
                    calls.append({"name": name, "arguments": args})
                    cleaned = ""
        except json.JSONDecodeError:
            pass

    return cleaned, calls


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

        import asyncio
        try:
            import inspect
            if inspect.iscoroutinefunction(tool.execute):
                result: ToolResult = asyncio.run(tool.execute(args))
            else:
                result: ToolResult = tool.execute(args)
            results.append({
                "name": name,
                "success": result.success,
                "output": result.output,
            })
        except Exception as e:
            logger.error(f"Tool {name} execution error: {e}")
            results.append({
                "name": name,
                "success": False,
                "output": str(e),
            })

    return results


def format_tool_results(results: list[dict]) -> str:
    """Format tool execution results into prompt-friendly text."""
    parts = []
    for r in results:
        tag = "成功" if r["success"] else "失败"
        parts.append(
            f'<tool_result name="{r["name"]}">\n'
            f"工具 {r['name']} 执行{tag}:\n"
            f"{r['output']}\n"
            f"</tool_result>"
        )
    return "\n".join(parts)


def contains_fake_action(text: str) -> bool:
    """Detect if LLM claims to have done something without tool call."""
    keywords = ["已发送", "已通知", "已经为你", "已经为您", "已为您", "已记住", "已回忆"]
    return any(kw in text for kw in keywords)


def _normalize_args(args: dict) -> dict:
    """Map common aliases to canonical field names."""
    aliases = [
        (("query", "search", "keyword", "question"), "query"),
        (("text", "msg", "content"), "content"),
        (("person", "who", "user", "target"), "name"),
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
