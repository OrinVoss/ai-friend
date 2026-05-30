"""Phase 1: Pure tool-calling agent -- no personality, no emotion, no memory.

Receives user input, decides which external tools to call, executes them,
and returns a structured record of all tool calls and results.
"""

import logging
import time
from dataclasses import dataclass, field

from tools.traits import ToolRegistry

logger = logging.getLogger(__name__)

EXTERNAL_TOOL_NAMES = [
    "web_fetch", "web_search", "read_file", "glob", "grep",
    "music_play", "notify",
]


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

        sys_prompt = build_tool_agent_prompt(self._registry)
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"用户输入：{user_input}"},
        ]

        for _idx in range(self._max_iterations):
            resp = self._provider.generate(
                messages,
                stream=False,
                max_tokens=512,
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
                f"[tool_agent] {result.total_calls} calls, "
                f"{result.success_count} ok, "
                f"{len(result.records) - result.success_count} failed, "
                f"{result.elapsed_ms:.0f}ms"
            )
        return result

    def format_for_phase2(self, result: ToolAgentResult) -> str:
        """Format Phase 1 results as a system message for Phase 2."""
        if not result.has_results:
            return ""

        parts = [
            "=== 系统已自动获取的外部内容 ===",
            "以下内容由工具自动获取，你不需要再调用 web_fetch、web_search、read_file 等外部工具。",
            "直接阅读这些内容，如实汇报给用户。不要编造、不要润色。",
            "",
        ]
        for i, r in enumerate(result.records, 1):
            status = "成功" if r.success else "失败"
            parts.append(
                f"[调用 {i}] {r.name}（{status}）:\n"
                f"{r.output}\n"
            )
        parts.append("=== 外部内容结束，开始回复用户 ===")
        return "\n".join(parts)


def _format_raw_results(results: list[dict]) -> str:
    """Minimal result formatting for Phase 1 internal ReAct loop."""
    parts = []
    for r in results:
        tag = "成功" if r["success"] else "失败"
        parts.append(f"工具 {r['name']} 执行{tag}:\n{r['output']}")
    return "\n\n".join(parts)
