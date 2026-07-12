"""Agent 1: Inner Drive -- self-aware reasoning loop that decides what the AI needs.

Perceive user input → retrieve memory → identify information gaps → decide:
  - No external tools needed → direct to Agent 3 (expression)
  - External tools needed → natural language tool request to Agent 2

The inner drive is a ReAct-style reasoning loop using internal tools (recall, remember)
to build context, then producing a decision + natural language tool request.
"""

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

from tools.traits import EXTERNAL_TOOL_NAMES


@dataclass
class ToolRequest:
    """Natural language tool request from Agent 1 to Agent 2."""
    description: str = ""       # "需要获取 https://... 的网页内容"
    suggested_tool: str = ""    # "web_fetch" (optional hint)
    params_hint: dict = field(default_factory=dict)  # {"url": "https://..."}


@dataclass
class InnerDriveResult:
    """Agent 1 output: decision + optional tool requests."""
    needs_external_tools: bool = False
    reasoning: str = ""                        # Why this decision
    tool_requests: list[ToolRequest] = field(default_factory=list)
    summary: str = ""                          # Compact summary for Agent 3


@dataclass
class ProactiveIntent:
    """Agent 1 output for proactive engagement decisions."""
    action: str = "silent"      # "chat", "explore", or "silent"
    topic_hint: str = ""        # What to talk about or explore
    reasoning: str = ""         # Why this decision (serves as context for Agent 3)


class InnerDriveAgent:
    """Agent 1: Self-aware reasoning before any external tool execution."""

    def __init__(self, provider, personality, ltm, retriever, short_term,
                 tool_registry, max_iterations: int = 5,
                 max_tokens_assess: int = 512,
                 max_tokens_proactive: int = 256,
                 max_tokens_review: int = 512,
                 conv_hist_tokens: int = 1800):
        self._provider = provider
        self._personality = personality
        self._ltm = ltm
        self._retriever = retriever
        self._short_term = short_term
        self._full_registry = tool_registry
        self._max_iterations = max_iterations
        self._max_tokens_assess = max_tokens_assess      # #257
        self._max_tokens_proactive = max_tokens_proactive
        self._max_tokens_review = max_tokens_review
        self._conv_hist_tokens = conv_hist_tokens

    def assess(self, user_input: str) -> InnerDriveResult:
        """Run inner drive reasoning loop, return decision."""
        from prompts.system import build_inner_drive_prompt
        from core.dispatcher import parse_tool_calls, execute_tool_calls

        mem_ctx = self._retriever.retrieve_for_query(user_input)
        conv_hist = self._short_term.format_for_prompt(max_tokens=self._conv_hist_tokens)
        sys_prompt = build_inner_drive_prompt(
            personality=self._personality.config,
            emotion=self._personality.emotion,
            memory_context=mem_ctx,
            conversation_history=conv_hist,
            tools=self._full_registry,
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"用户输入：{user_input}\n\n请进行内驱推理，判断是否需要外部工具。"},
        ]

        logger.info(f"[inner_drive] start len={len(user_input)}")

        for _idx in range(self._max_iterations):
            logger.debug(f"[inner_drive] iter={_idx+1}/{self._max_iterations}")
            resp = self._provider.generate(messages, stream=False, max_tokens=self._max_tokens_assess)
            cleaned, calls = parse_tool_calls(resp)

            if not calls:
                result = self._parse_decision(cleaned)
                logger.info(
                    f"[inner_drive] decision: needs_tools={result.needs_external_tools} "
                    f"requests={len(result.tool_requests)} reason={result.reasoning[:80]}"
                )
                return result

            # Internal tools called (recall/remember)
            logger.info(f"[inner_drive] internal tools: {[c['name'] for c in calls]}")
            messages.append({"role": "assistant", "content": resp})
            results = execute_tool_calls(self._full_registry, calls)
            success_count = sum(1 for r in results if r["success"])
            logger.info(f"[inner_drive] internal done: {success_count}/{len(results)} ok")
            result_text = self._format_internal_results(results)
            messages.append({"role": "user", "content": result_text})

        # Max iterations reached without decision
        logger.warning("[inner_drive] max iterations, defaulting to no tools")
        return InnerDriveResult(
            needs_external_tools=False,
            reasoning="达到最大迭代次数，默认不需要外部工具",
            summary="",
        )

    def assess_proactive(self, idle_duration: float) -> ProactiveIntent:
        """Decide whether and how to proactively engage the user.

        Called after ProactivityManager's cheap scoring triggers.
        Replaces random topic selection and the 40/60 explore/chat split
        with LLM-based reasoning about context, memory, and emotional state.
        """
        from datetime import datetime
        from prompts.system import build_inner_drive_proactive_prompt

        now = datetime.now()
        mem_ctx = self._retriever.retrieve_for_query("")
        conv_hist = self._short_term.format_for_prompt(max_tokens=self._conv_hist_tokens)

        sys_prompt = build_inner_drive_proactive_prompt(
            personality=self._personality.config,
            emotion=self._personality.emotion,
            memory_context=mem_ctx,
            conversation_history=conv_hist,
            idle_duration=idle_duration,
            current_time=now,
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": (
                f"用户已经 {idle_duration:.0f} 秒没有说话。"
                f"现在是 {now.strftime('%H:%M')}。"
                f"请决定：现在应该主动聊天、去探索点东西，还是继续安静等待？"
            )},
        ]

        logger.info(f"[inner_drive] proactive assess idle={idle_duration:.0f}s")
        resp = self._provider.generate(messages, stream=False, max_tokens=self._max_tokens_proactive)
        intent = self._parse_proactive_intent(resp)
        logger.info(
            f"[inner_drive] proactive decision: action={intent.action} "
            f"topic={intent.topic_hint[:60]} reason={intent.reasoning[:60]}"
        )
        return intent

    def review(self, user_input: str, tool_records_text: str,
               round_num: int = 1, max_rounds: int = 3) -> InnerDriveResult:
        """Review successful tool results. Decide if more tools are needed.

        Called after Agent 2 returns results. Agent 1 checks if the results are
        sufficient or if additional tool calls are needed (e.g. search then fetch).
        """
        if round_num >= max_rounds:
            logger.info(f"[inner_drive] review: max rounds ({max_rounds}) reached")
            return InnerDriveResult(
                needs_external_tools=False,
                reasoning=f"达到最大轮次 {max_rounds}，不再请求工具",
                summary=tool_records_text[:200],
            )

        from prompts.system import build_inner_drive_prompt
        from core.dispatcher import parse_tool_calls, execute_tool_calls

        mem_ctx = self._retriever.retrieve_for_query(user_input)
        conv_hist = self._short_term.format_for_prompt(max_tokens=self._conv_hist_tokens)

        sys_prompt = build_inner_drive_prompt(
            personality=self._personality.config,
            emotion=self._personality.emotion,
            memory_context=mem_ctx,
            conversation_history=conv_hist,
            tools=self._full_registry,
        )

        review_msg = (
            f"用户原始输入：{user_input}\n\n"
            f"=== 第 {round_num} 轮工具执行结果 ===\n"
            f"{tool_records_text[:3000]}\n\n"
            f"请判断：以上结果是否足够回复用户？\n"
            f"- 如果足够 → 回复 '决策：不需要外部工具' + 理由\n"
            f"- 如果还需要更多信息 → 回复 '决策：需要外部工具' + 新的工具请求\n"
            f"（还剩 {max_rounds - round_num} 轮可用）"
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": review_msg},
        ]

        logger.info(f"[inner_drive] review round={round_num}/{max_rounds}")
        resp = self._provider.generate(messages, stream=False, max_tokens=self._max_tokens_review)
        cleaned, calls = parse_tool_calls(resp)

        if calls:
            messages.append({"role": "assistant", "content": resp})
            results = execute_tool_calls(self._full_registry, calls)
            result_text = self._format_internal_results(results)
            messages.append({"role": "user", "content": result_text})
            resp = self._provider.generate(messages, stream=False, max_tokens=self._max_tokens_review)
            cleaned, _ = parse_tool_calls(resp)

        result = self._parse_decision(cleaned)
        logger.info(
            f"[inner_drive] review: needs_tools={result.needs_external_tools} "
            f"reason={result.reasoning[:80]}"
        )
        return result

    def re_decide(self, user_input: str, failure_log: list[dict]) -> InnerDriveResult:
        """Re-decide after Agent 2 tool failures. Try alternative approaches."""
        from prompts.system import build_inner_drive_prompt
        from core.dispatcher import parse_tool_calls, execute_tool_calls

        mem_ctx = self._retriever.retrieve_for_query(user_input)
        conv_hist = self._short_term.format_for_prompt(max_tokens=self._conv_hist_tokens)

        # Build failure context
        fail_lines = ["=== 之前的工具调用全部失败 ==="]
        for i, f in enumerate(failure_log[-5:], 1):
            fail_lines.append(
                f"[失败 {i}] {f.get('name', '?')}: {f.get('output', '?')[:200]}"
            )
        fail_lines.append("请重新决策：换个方式、换个工具、或者放弃并告知用户。")

        sys_prompt = build_inner_drive_prompt(
            personality=self._personality.config,
            emotion=self._personality.emotion,
            memory_context=mem_ctx,
            conversation_history=conv_hist,
            tools=self._full_registry,
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"用户输入：{user_input}\n\n{chr(10).join(fail_lines)}"},
        ]

        logger.info(f"[inner_drive] re-decide after {len(failure_log)} failures")
        resp = self._provider.generate(messages, stream=False, max_tokens=self._max_tokens_review)
        cleaned, calls = parse_tool_calls(resp)

        # Execute any internal tool calls from re-decision
        if calls:
            messages.append({"role": "assistant", "content": resp})
            results = execute_tool_calls(self._full_registry, calls)
            result_text = self._format_internal_results(results)
            messages.append({"role": "user", "content": result_text})
            resp = self._provider.generate(messages, stream=False, max_tokens=self._max_tokens_review)
            cleaned, _ = parse_tool_calls(resp)

        result = self._parse_decision(cleaned)
        logger.info(
            f"[inner_drive] re-decide: needs_tools={result.needs_external_tools} "
            f"reason={result.reasoning[:80]}"
        )
        return result

    def _parse_decision(self, text: str) -> InnerDriveResult:
        """Parse Agent 1's natural language output into structured decision."""
        text = text.strip()

        # Check for explicit "no need" signal
        no_need = any(kw in text for kw in ["NO_NEED", "不需要外部工具", "不需要工具",
                                              "无需工具", "直接回复", "没有外部工具"])
        if no_need:
            return InnerDriveResult(
                needs_external_tools=False,
                reasoning=text[:300],
                summary=text[:200],
            )

        # Check for external tool references
        has_external = any(
            name in text for name in EXTERNAL_TOOL_NAMES
        ) or any(kw in text for kw in [
            "需要调用", "需要外部", "需要获取", "需要搜索", "需要读取",
            "调用web", "用web", "需要查", "需要打开",
        ])

        if not has_external:
            return InnerDriveResult(
                needs_external_tools=False,
                reasoning=text[:300],
                summary=text[:200],
            )

        # Extract tool requests from text
        requests = self._extract_tool_requests(text)
        return InnerDriveResult(
            needs_external_tools=bool(requests),
            reasoning=text[:300],
            tool_requests=requests,
            summary=text[:200],
        )

    def _extract_tool_requests(self, text: str) -> list[ToolRequest]:
        """Extract natural language tool requests from Agent 1's output."""
        requests = []

        # Look for URL patterns to suggest web_fetch
        urls = re.findall(r'https?://[^\s一-鿿]+', text)
        for url in urls:
            url = url.rstrip('.,;:)】」\'\"')
            requests.append(ToolRequest(
                description=f"需要获取网页内容：{url}",
                suggested_tool="web_fetch",
                params_hint={"url": url},
            ))

        # Look for search intent
        search_matches = re.findall(r'(?:搜索|查询|搜一下|搜)[：:]\s*(.+?)(?:[，。,\.\n]|$)', text)
        for query in search_matches:
            if query.strip():
                requests.append(ToolRequest(
                    description=f"需要搜索：{query.strip()}",
                    suggested_tool="web_search",
                    params_hint={"query": query.strip()},
                ))

        # Look for file-related intent
        file_matches = re.findall(r'(?:读取|打开|查看)[：:]\s*(.+?)(?:[，。,\.\n]|$)', text)
        for path in file_matches:
            if path.strip():
                requests.append(ToolRequest(
                    description=f"需要读取文件：{path.strip()}",
                    suggested_tool="read_file",
                    params_hint={"path": path.strip()},
                ))

        # If no structured matches but has_external was True, make a generic request
        if not requests:
            requests.append(ToolRequest(
                description=text[:500],
                suggested_tool="",
                params_hint={},
            ))

        return requests

    def _parse_proactive_intent(self, text: str) -> ProactiveIntent:
        """Parse the LLM's proactive decision output into a ProactiveIntent."""
        text = text.strip()

        if "探索" in text:
            action = "explore"
        elif "沉默" in text or "等待" in text or "安静" in text:
            action = "silent"
        elif "聊天" in text or "说话" in text or "主动" in text:
            action = "chat"
        else:
            action = "chat"

        topic_match = re.search(r'话题[：:]\s*(.+?)(?:\n|[。！？]|$)', text)
        topic = topic_match.group(1).strip() if topic_match else ""

        reason_match = re.search(r'理由[：:]\s*(.+?)(?:\n|[。！？]|$)', text)
        reason = reason_match.group(1).strip() if reason_match else text[:200]

        return ProactiveIntent(action=action, topic_hint=topic, reasoning=reason)

    def _format_internal_results(self, results: list[dict]) -> str:
        """Format internal tool results for Agent 1's ReAct loop."""
        parts = []
        for r in results:
            tag = "成功" if r["success"] else "失败"
            parts.append(f"[内部工具 {r['name']} 执行{tag}]\n{r['output'][:1000]}")
        return "\n\n".join(parts)
