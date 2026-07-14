"""Phase 1: Pure tool-calling agent -- no personality, no emotion, no memory.

Receives user input, decides which external tools to call, executes them,
and returns a structured record of all tool calls and results.
"""

import logging
import time
from dataclasses import dataclass, field

from tools.traits import ToolRegistry, EXTERNAL_TOOL_NAMES

logger = logging.getLogger(__name__)


@dataclass
class ToolCallRecord:
    """A single tool execution record passed to Phase 2."""
    name: str
    arguments: dict
    success: bool
    output: str
    elapsed_ms: float = 0.0


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

    def __init__(self, provider, tool_registry: ToolRegistry, max_iterations: int = 5):
        self._provider = provider
        self._full_registry = tool_registry
        self._registry = ToolRegistry()
        for name in EXTERNAL_TOOL_NAMES:
            tool = tool_registry.get(name)
            if tool:
                self._registry.register(tool)
        self._max_iterations = max_iterations

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

        for _idx in range(self._max_iterations):
            logger.debug(f"[tool_agent] iter={_idx+1}/{self._max_iterations}")
            resp = self._provider.generate(
                messages,
                stream=False,
                max_tokens=512,
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
                messages.append({"role": "assistant", "content": resp if 'resp' in dir() else ""})
                messages.append({"role": "user", "content": (
                    f"之前的尝试失败了（{last_failure}）。"
                    "请调整方式后重新输出 JSON 格式的工具调用。"
                )})

            resp = self._provider.generate(messages, stream=False, max_tokens=512,
                                          response_format=json_schema, source="tool_agent")
            cleaned, calls = parse_tool_calls(resp)
            if not calls:
                # TA-007: explicitly track parse failures
                logger.debug("[tool_agent] no tool calls parsed from response")
                last_failure = "解析失败：未能从响应中提取有效的工具调用"
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

            last_failure = "; ".join(
                r["output"][:100] for r in results if not r["success"]
            )

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
        """MH-001: execute a batch of tool requests sequentially and merge.

        Each request is a natural-language tool need from Agent 1. They run as
        independent ToolAgent rounds (each with its own retry budget) and the
        records are collected into one merged ToolAgentResult for Agent 3.
        """
        merged = ToolAgentResult()
        if not tool_requests:
            logger.warning("[tool_agent] empty tool_requests list, returning empty result")
            return merged
        t0 = time.time()
        for req in tool_requests:
            single = self.run_with_request(req, max_retries=max_retries)
            merged.records.extend(single.records)
            merged.total_calls += single.total_calls
            merged.success_count += single.success_count
        merged.elapsed_ms = (time.time() - t0) * 1000
        return merged

    def format_for_phase2(self, result: ToolAgentResult) -> str:
        """Format Phase 2 results as a user message for Agent 3.

        #175: reuse format_tool_results from dispatcher for consistent formatting.
        """
        if not result.has_results:
            return ""

        from core.dispatcher import format_tool_results
        records = [
            {"name": r.name, "success": r.success, "output": r.output}
            for r in result.records
        ]
        return format_tool_results(records)


def _format_raw_results(results: list[dict]) -> str:
    """Minimal result formatting for Phase 1 internal ReAct loop."""
    parts = []
    for r in results:
        tag = "成功" if r["success"] else "失败"
        parts.append(f"工具 {r['name']} 执行{tag}:\n{r['output']}")
    return "\n\n".join(parts)
