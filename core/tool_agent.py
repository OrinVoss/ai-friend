"""Phase 1: Pure tool-calling agent -- no personality, no emotion, no memory.

Receives user input, decides which external tools to call, executes them,
and returns a structured record of all tool calls and results.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from tools.traits import ToolRegistry, ERROR_TYPE_PARAM_ERROR

logger = logging.getLogger(__name__)


def _truncate_request(text: str, max_len: int = 80) -> str:
    """Truncate a natural-language request for prompt attribution headers."""
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + "…"


@dataclass
class ToolCallRecord:
    """A single tool execution record passed to Phase 2."""
    name: str
    arguments: dict
    success: bool
    output: str
    elapsed_ms: float = 0.0
    error_type: str = ""
    retryable: bool = False
    request: str = ""  # MH-002: which natural-language request produced this call


@dataclass
class ToolAgentResult:
    """Complete Phase 1 result passed to Phase 2."""
    records: list[ToolCallRecord] = field(default_factory=list)
    total_calls: int = 0
    success_count: int = 0
    elapsed_ms: float = 0.0

    @property
    def has_results(self) -> bool:
        return self.total_calls > 0

    @property
    def any_success(self) -> bool:
        return self.success_count > 0


@dataclass
class ToolAttemptTracker:
    """Track retry rounds: 3 rounds x 3 retries = max 9 attempts."""
    round_number: int = 0
    retry_count: int = 0
    total_attempts: int = 0
    failure_log: list[dict] = field(default_factory=list)

    @property
    def can_retry_in_round(self) -> bool:
        return self.retry_count < 3

    @property
    def can_start_new_round(self) -> bool:
        return self.round_number < 3 and self.total_attempts < 9

    @property
    def is_exhausted(self) -> bool:
        return self.total_attempts >= 9


class ToolAgent:
    """Phase 1 agent that ONLY calls external tools, no roleplay."""

    def __init__(self, provider, tool_registry: ToolRegistry, max_iterations: int = 5,
                 output_cap: int | None = None):
        self._provider = provider
        # 注册表由调用方装配好后注入 — 唯一装配路径是
        # message_handler._make_external_registry()（已只含外部工具），
        # 此处不再重复过滤 EXTERNAL_TOOL_NAMES。
        self._registry = tool_registry
        self._max_iterations = max_iterations
        self._output_cap = output_cap

    def run(self, user_input: str) -> ToolAgentResult:
        """Run Phase 1: decide and execute external tools, return records."""
        from prompts.system import build_tool_agent_prompt
        from core.dispatcher import parse_tool_calls, execute_tool_calls

        t0 = time.time()
        result = ToolAgentResult()

        if not self._registry.list_specs():
            return result

        logger.info(f"[tool_agent] start len={len(user_input)}")
        sys_prompt = build_tool_agent_prompt(self._registry)
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"用户输入：{user_input}"},
        ]

        request_label = _truncate_request(user_input)
        for _idx in range(self._max_iterations):
            logger.debug(f"[tool_agent] iter={_idx+1}/{self._max_iterations}")
            resp = self._provider.generate(
                messages,
                stream=False,
                max_tokens=1024,
                response_format=self._registry.to_json_schema(),
                source="tool_agent",
            )
            cleaned, calls = parse_tool_calls(resp)
            if not calls:
                break

            messages.append({"role": "assistant", "content": resp})
            results = execute_tool_calls(self._registry, calls)

            for r in results:
                record = ToolCallRecord(
                    name=r["name"],
                    arguments={},
                    success=r["success"],
                    output=r["output"][:3000],
                    elapsed_ms=r.get("elapsed_ms", 0.0),
                    error_type=r.get("error_type", ""),
                    retryable=r.get("retryable", False),
                    request=request_label,
                )
                result.records.append(record)
                result.total_calls += 1
                if r["success"]:
                    result.success_count += 1

            result_text = _format_raw_results(results)
            messages.append({"role": "user", "content": result_text})

        result.elapsed_ms = (time.time() - t0) * 1000
        if result.has_results:
            logger.info(
                f"[tool_agent] done: {result.total_calls} calls, "
                f"{result.success_count} ok, "
                f"{len(result.records) - result.success_count} failed, "
                f"{result.elapsed_ms:.0f}ms"
            )
        else:
            logger.debug(f"[tool_agent] no tools needed ({result.elapsed_ms:.0f}ms)")
        return result

    def run_with_request(self, tool_request: str, max_retries: int = 3) -> ToolAgentResult:
        """Run Agent 2: receive natural language tool request, parse and execute.

        Retries up to max_retries times within a single round.
        Caller handles the round-level loop (Agent 1 re-decide).
        """
        # #258: guard against empty input
        if not tool_request or not tool_request.strip():
            logger.warning("[tool_agent] empty tool_request, returning empty result")
            return ToolAgentResult()

        from prompts.system import build_tool_agent_prompt
        from core.dispatcher import parse_tool_calls, execute_tool_calls

        t0 = time.time()
        result = ToolAgentResult()

        if not self._registry.list_specs():
            return result

        logger.info(f"[tool_agent] request len={len(tool_request)}")
        request_label = _truncate_request(tool_request)
        sys_prompt = build_tool_agent_prompt(self._registry)
        json_schema = self._registry.to_json_schema()
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": (
                f"Agent 1 的内驱推理请求：\n{tool_request}\n\n"
                "请根据以上请求，输出 JSON 格式的工具调用。"
            )},
        ]

        last_failure = None
        for attempt in range(1, max_retries + 1):
            if attempt > 1:
                logger.info(f"[tool_agent] retry {attempt}/{max_retries}")
                # TA-005: append failure context to existing messages instead of rebuilding
                # #316: 上一轮"解析成功但执行失败"时 :215 已追加过同一 resp，
                # 再追加会让模型看到两条连续相同的 assistant 消息
                _last = messages[-1] if messages else {}
                if not (_last.get("role") == "assistant" and _last.get("content") == resp):
                    messages.append({"role": "assistant", "content": resp if 'resp' in dir() else ""})
                retry_prompt = _build_retry_prompt(last_failure, attempt)
                messages.append({"role": "user", "content": retry_prompt})
                # Layer5-TA1: simple exponential backoff for retryable failures.
                if _should_backoff(last_failure):
                    backoff = 2 ** (attempt - 2)  # 1s, 2s, 4s
                    logger.debug(f"[tool_agent] backoff {backoff}s before retry")
                    time.sleep(backoff)

            resp = self._provider.generate(messages, stream=False, max_tokens=1024,
                                          response_format=json_schema, source="tool_agent")
            cleaned, calls = parse_tool_calls(resp)
            if not calls:
                # TA-007: explicitly track parse failures
                logger.debug("[tool_agent] no tool calls parsed from response")
                last_failure = {
                    "kind": "parse",
                    "error_type": "",
                    "retryable": True,
                    "message": "解析失败：未能从响应中提取有效的工具调用",
                }
                continue

            messages.append({"role": "assistant", "content": resp})
            results = execute_tool_calls(self._registry, calls)

            round_records = []
            for r in results:
                record = ToolCallRecord(
                    name=r["name"],
                    arguments={},
                    success=r["success"],
                    output=r["output"][:3000],
                    elapsed_ms=r.get("elapsed_ms", 0.0),
                    error_type=r.get("error_type", ""),
                    retryable=r.get("retryable", False),
                    request=request_label,
                )
                round_records.append(record)
                result.records.append(record)
                result.total_calls += 1
                if r["success"]:
                    result.success_count += 1

            result_text = _format_raw_results(results)
            messages.append({"role": "user", "content": result_text})

            if result.any_success:
                break

            # Layer5-TA2: classify failure for error-aware retry.
            last_failure = _summarize_failure(results)
            if last_failure and not last_failure.get("retryable", True):
                logger.info(
                    f"[tool_agent] non-retryable failure ({last_failure.get('error_type')}), "
                    "giving up early"
                )
                break

        result.elapsed_ms = (time.time() - t0) * 1000
        if result.has_results:
            logger.info(
                f"[tool_agent] done: {result.total_calls} calls, "
                f"{result.success_count} ok, "
                f"{len(result.records) - result.success_count} failed, "
                f"{result.elapsed_ms:.0f}ms"
            )
        return result

    def run_with_requests(self, tool_requests: list[str], max_retries: int = 3) -> ToolAgentResult:
        """MH-001: execute a batch of tool requests concurrently and merge.

        Each request is a natural-language tool need from Agent 1. They run as
        independent ToolAgent rounds (each with its own retry budget) and the
        records are collected into one merged ToolAgentResult for Agent 3.
        """
        merged = ToolAgentResult()
        if not tool_requests:
            logger.warning("[tool_agent] empty tool_requests list, returning empty result")
            return merged

        t0 = time.time()
        # Layer5-TA3: parallelize independent requests. Tool calls inside each
        # request are already parallelized by execute_tool_calls; this layer
        # removes the sequential delay across requests.
        if len(tool_requests) == 1:
            single = self.run_with_request(tool_requests[0], max_retries=max_retries)
            merged.records.extend(single.records)
            merged.total_calls += single.total_calls
            merged.success_count += single.success_count
        else:
            max_workers = min(len(tool_requests), 4)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [
                    executor.submit(self.run_with_request, req, max_retries)
                    for req in tool_requests
                ]
                for future in futures:
                    single = future.result()
                    merged.records.extend(single.records)
                    merged.total_calls += single.total_calls
                    merged.success_count += single.success_count

        merged.elapsed_ms = (time.time() - t0) * 1000
        return merged

    def format_for_phase2(self, result: ToolAgentResult) -> str:
        """Format Phase 2 results as a user message for Agent 3.

        #175: reuse format_tool_results from dispatcher for consistent formatting.
        MH-002: when records came from multiple natural-language requests,
        group them with small headers so Agent 3 can tell which result belongs
        to which request. Single-request output stays unchanged.
        """
        if not result.has_results:
            return ""

        from core.dispatcher import format_tool_results

        def _to_dict(r: ToolCallRecord) -> dict:
            return {
                "name": r.name,
                "success": r.success,
                "output": r.output,
                "error_type": r.error_type,
                "retryable": r.retryable,
                "elapsed_ms": r.elapsed_ms,
            }

        requests = list(dict.fromkeys(r.request for r in result.records if r.request))
        if len(requests) <= 1:
            records = [_to_dict(r) for r in result.records]
            return format_tool_results(records, output_cap=self._output_cap)

        # Multi-request: group by request, one iron rule at the end.
        parts = []
        for req in requests:
            group = [_to_dict(r) for r in result.records if r.request == req]
            group_text = format_tool_results(group, output_cap=self._output_cap,
                                             append_iron_rule=False)
            parts.append(f"【请求：{req}】\n{group_text}")
        parts.append(
            "=== 铁律 ===\n"
            "以上是工具返回的真实内容。你必须逐字如实汇报，不得编造、不得润色、不得添加原文没有的信息。\n"
            "工具说没找到就说没找到，工具返回什么就说什么。你添加的每一个字都必须是工具确实返回了的。"
        )
        return "\n\n".join(parts)


def _summarize_failure(results: list[dict]) -> dict | None:
    """Summarize the first failure result for retry decisions."""
    for r in results:
        if not r.get("success"):
            return {
                "kind": "tool",
                "error_type": r.get("error_type", ""),
                "retryable": r.get("retryable", False),
                "message": r.get("output", ""),
            }
    return None


def _should_backoff(failure: dict | None) -> bool:
    """Return True if the last failure deserves a backoff pause."""
    if failure is None:
        return False
    # Parse failures are transient model-format issues; a short pause helps
    # avoid hammering the provider. Tool-level retryable failures also back off.
    return failure.get("retryable", False) or failure.get("kind") == "parse"


def _build_retry_prompt(failure: dict | None, attempt: int) -> str:
    """Build a specific retry prompt based on the previous failure."""
    if failure is None:
        return (
            f"之前的尝试失败了（第 {attempt - 1} 次）。"
            "请调整方式后重新输出 JSON 格式的工具调用。"
        )

    kind = failure.get("kind", "tool")
    error_type = failure.get("error_type", "")
    message = failure.get("message", "")
    retryable = failure.get("retryable", False)

    if kind == "parse":
        return (
            "之前的输出无法解析为有效的 JSON 工具调用。"
            "请严格使用 JSON 格式，包含 \"calls\" 数组，每个元素有 \"name\" 和 \"arguments\"。"
        )

    parts = [f"之前的尝试失败了（第 {attempt - 1} 次）"]
    if error_type:
        parts.append(f"，错误类型：{error_type}")
    parts.append("。")

    if error_type == ERROR_TYPE_PARAM_ERROR:
        parts.append("请检查工具参数名称和类型，修正后再输出 JSON 工具调用。")
    elif error_type == "not_found":
        parts.append("目标不存在，请换一个来源或放弃。")
    elif error_type == "permission_denied":
        parts.append("你没有权限执行该操作，请换方式或放弃。")
    elif retryable:
        parts.append("这可能是临时故障，请调整后重试。")
    else:
        parts.append("请调整方式后重新输出 JSON 格式的工具调用。")

    if message:
        parts.append(f" 详情：{message[:200]}")
    return "".join(parts)


def _format_raw_results(results: list[dict]) -> str:
    """Minimal result formatting for Phase 1 internal ReAct loop."""
    parts = []
    for r in results:
        tag = "成功" if r["success"] else "失败"
        error_hint = ""
        if not r.get("success"):
            error_type = r.get("error_type", "")
            if error_type:
                error_hint = f"[{error_type}] "
        parts.append(f"工具 {r['name']} 执行{tag}:\n{error_hint}{r['output']}")
    return "\n\n".join(parts)
