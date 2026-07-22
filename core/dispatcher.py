"""Parse <tool_call> XML tags from LLM responses and execute tools."""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Optional

from tools.traits import (
    ToolRegistry,
    ToolResult,
    ERROR_TYPE_PARAM_ERROR,
    ERROR_TYPE_NOT_FOUND,
    ERROR_TYPE_NETWORK_ERROR,
    ERROR_TYPE_PERMISSION_DENIED,
    ERROR_TYPE_INTERNAL,
)

logger = logging.getLogger(__name__)

TOOL_CALL_PATTERN = re.compile(r'<tool_call>(.*?)</tool_call>', re.DOTALL)
THINK_PATTERN = re.compile(r'<think>.*?</think>', re.DOTALL)

# Layer5-D1: unified output cap for formatted results. Individual tools may
# pre-truncate their own output to larger internal limits (e.g. web_fetch).
_OUTPUT_CAP = 2000

# Layer5-D2: cap raw input JSON at 10KB before parsing (DI-001).
_MAX_RAW_JSON_BYTES = 10240


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
        if len(raw_json) > _MAX_RAW_JSON_BYTES:
            logger.warning(f"Tool call JSON too large ({len(raw_json)} bytes), truncating")
            raw_json = raw_json[:_MAX_RAW_JSON_BYTES]

        try:
            parsed = json.loads(raw_json)
            name = parsed.get("name") or parsed.get("tool", "")
            arguments = parsed.get("arguments", {})
            if not isinstance(arguments, dict):
                arguments = {}
            # KI-1: dispatcher 不再做全局参数改名；别名归一下沉到
            # 各工具的 normalize_args（执行前由 _execute_single 调用）
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
            obj = json.loads(text[:_MAX_RAW_JSON_BYTES])  # DI-001
            if isinstance(obj, dict):
                name = obj.get("name") or obj.get("tool", "")
                if name:
                    args = obj.get("arguments", {})
                    # #260: arguments 非 dict（字符串/列表等）时按空参数处理
                    if not isinstance(args, dict):
                        args = {}
                    calls.append({"name": name, "arguments": args})
                    cleaned = ""
        except json.JSONDecodeError:
            pass

    return cleaned, calls


def _try_structured_json(text: str) -> list[dict]:
    """Try parsing text as JSON with 'calls' array (structured output format)."""
    try:
        obj = json.loads(text[:_MAX_RAW_JSON_BYTES])  # DI-001
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
            parsed.append({"name": name, "arguments": args})
    return parsed


def _validate_args(args: dict[str, Any], schema: dict) -> Optional[str]:
    """Validate arguments against a JSON schema subset.

    Returns None if valid, otherwise a human-readable error message.
    """
    if not isinstance(schema, dict):
        return None

    required = schema.get("required", [])
    properties = schema.get("properties", {})

    for key in required:
        if key not in args or args[key] in (None, ""):
            return f"缺少必填参数: {key}"

    type_map = {
        "string": str,
        "integer": int,
        "number": (int, float),
        "boolean": bool,
        "array": list,
        "object": dict,
    }

    for key, value in args.items():
        prop = properties.get(key)
        if not isinstance(prop, dict):
            continue
        expected = prop.get("type")
        if expected and expected in type_map:
            py_type = type_map[expected]
            # bool is a subclass of int; reject booleans for integer fields.
            if expected == "integer" and isinstance(value, bool):
                return f"参数 {key} 应为整数，但得到布尔值"
            if not isinstance(value, py_type):
                return f"参数 {key} 类型错误: 应为 {expected}，得到 {type(value).__name__}"
        enum = prop.get("enum")
        if enum is not None and value not in enum:
            return f"参数 {key} 的值不在允许范围内: {value}"

    return None


def _run_tool_with_timeout(tool, args: dict[str, Any]) -> ToolResult:
    """Execute a single tool with its configured timeout.

    Uses a one-off thread so sync tools (e.g. requests) do not block the caller.
    """
    timeout = getattr(tool, "timeout_seconds", 30.0)
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        timeout = 30.0
    if timeout <= 0 or timeout > 300:
        timeout = 30.0

    t0 = time.perf_counter()

    def _worker() -> ToolResult:
        try:
            return tool.execute(args)
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"Tool {tool.name()} execution error")
            return ToolResult.fail(
                f"工具执行异常: {exc}",
                error_type=ERROR_TYPE_INTERNAL,
                retryable=False,
            )

    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_worker)
            result = future.result(timeout=timeout)
    except FutureTimeoutError:
        elapsed = (time.perf_counter() - t0) * 1000
        logger.warning(f"[tool] {tool.name()} timed out after {timeout}s")
        return ToolResult.fail(
            f"工具执行超时（>{timeout}s）",
            error_type=ERROR_TYPE_NETWORK_ERROR,
            retryable=True,
            elapsed_ms=elapsed,
        )

    elapsed = (time.perf_counter() - t0) * 1000
    result.elapsed_ms = elapsed
    return result


def _execute_single(
    tool_registry: ToolRegistry,
    call: dict,
    user_role: str,
    collect_metrics: bool = True,
) -> dict:
    """Execute one tool call: permission → validation → timeout execution."""
    name = call.get("name", "")
    args = call.get("arguments", {})
    if not isinstance(args, dict):
        args = {}

    from core.monitor import record_tool_metric

    if not name:
        return {
            "name": name,
            "success": False,
            "output": "工具调用缺少名称",
            "error_type": ERROR_TYPE_PARAM_ERROR,
            "retryable": False,
            "elapsed_ms": 0.0,
        }

    tool = tool_registry.get(name)
    if tool is None:
        _record_metric(name, False, 0.0, collect_metrics)
        return {
            "name": name,
            "success": False,
            "output": f"未知工具: {name}",
            "error_type": ERROR_TYPE_NOT_FOUND,
            "retryable": False,
            "elapsed_ms": 0.0,
        }

    # Layer5-D3: permission enforcement
    if not tool_registry.check_permission(name, user_role):
        _record_metric(name, False, 0.0, collect_metrics)
        return {
            "name": name,
            "success": False,
            "output": f"权限不足，无法调用工具: {name}",
            "error_type": ERROR_TYPE_PERMISSION_DENIED,
            "retryable": False,
            "elapsed_ms": 0.0,
        }

    # KI-1: 参数别名归一下沉到各工具（原 dispatcher 全局别名已删除），
    # 在校验前完成，required 检查看到的是规范参数名
    args = tool.normalize_args(args)

    # Layer5-D4: pre-execution parameter validation
    schema = tool.parameters_schema()
    validation_error = _validate_args(args, schema)
    if validation_error:
        _record_metric(name, False, 0.0, collect_metrics)
        return {
            "name": name,
            "success": False,
            "output": validation_error,
            "error_type": ERROR_TYPE_PARAM_ERROR,
            "retryable": False,
            "elapsed_ms": 0.0,
        }

    result = _run_tool_with_timeout(tool, args)
    _record_metric(name, result.success, result.elapsed_ms, collect_metrics)

    return {
        "name": name,
        "success": result.success,
        "output": result.output,
        "error_type": result.error_type,
        "retryable": result.retryable,
        "elapsed_ms": round(result.elapsed_ms, 2),
    }


def _record_metric(name: str, success: bool, elapsed_ms: float, enabled: bool) -> None:
    if not enabled:
        return
    try:
        from core.monitor import record_tool_metric
        record_tool_metric(name, success, elapsed_ms)
    except Exception:
        # Metrics must never break tool execution.
        pass


def execute_tool_calls(
    tool_registry: ToolRegistry,
    calls: list[dict],
    user_role: str = "user",
    parallel: bool = True,
) -> list[dict]:
    """Execute tools and return results.

    Each result: {"name": str, "success": bool, "output": str,
                  "error_type": str, "retryable": bool, "elapsed_ms": float}

    Args:
        parallel: Run independent tool calls concurrently. Defaults to True.
    """
    if not calls:
        return []

    # Layer5-D5: parallel execution. Most tools are I/O-bound, so running them
    # concurrently turns total latency from sum to max.
    if parallel and len(calls) > 1:
        max_workers = min(len(calls), 8)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [
                executor.submit(_execute_single, tool_registry, call, user_role)
                for call in calls
            ]
            results = [f.result() for f in futures]
    else:
        results = [_execute_single(tool_registry, call, user_role) for call in calls]

    successes = sum(1 for r in results if r["success"])
    for r in results:
        if not r["success"]:
            logger.warning(f"[tool] {r['name']} failed: {r['output'][:200]}")
    logger.info(f"[tool] executed {len(results)} tools, {successes} ok, {len(results)-successes} failed")
    return results


def format_tool_results(results: list[dict], output_cap: int | None = None) -> str:
    """Format tool execution results into prompt-friendly text.

    output_cap: overrides the module default _OUTPUT_CAP (Layer5-D1).
    """
    cap = output_cap if output_cap is not None else _OUTPUT_CAP
    parts = []
    for r in results:
        tag = "成功" if r["success"] else "失败"
        output = r["output"]
        if len(output) > cap:
            output = output[:cap] + f"\n...(截断, 剩余 {len(output)-cap} 字符)"
        error_hint = ""
        if not r.get("success"):
            error_type = r.get("error_type", "")
            retryable = r.get("retryable", False)
            if error_type:
                error_hint = f"[错误类型: {error_type}]"
                if retryable:
                    error_hint += "（可重试）"
                else:
                    error_hint += "（不可重试，请换方式或放弃）"
                error_hint += "\n"
        parts.append(
            f'<tool_result name="{r["name"]}">\n'
            f"工具 {r['name']} 执行{tag}:\n"
            f"{error_hint}{output}\n"
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
