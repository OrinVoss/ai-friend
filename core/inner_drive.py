"""Agent 1: Inner Drive -- self-aware reasoning loop that decides what the AI needs.

Perceive user input → retrieve memory → identify information gaps → decide:
  - No external tools needed → direct to Agent 3 (expression)
  - External tools needed → structured tool request to Agent 2

Uses JSON Schema response_format instead of keyword/regex parsing. (#ID-001)
"""
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)



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
    recall_query: str = ""                     # Internal recall query (if needed)
    context_summary: str = ""                  # Formatted memory/relationship for Agent 3


@dataclass
class ProactiveIntent:
    """Agent 1 output for proactive engagement decisions."""
    action: str = "silent"      # "chat", "explore", or "silent"
    topic_hint: str = ""        # What to talk about or explore
    reasoning: str = ""         # Why this decision (serves as context for Agent 3)


# ID-001: JSON Schema for InnerDrive's structured decision output.
# Forces the LLM to produce clean structured data instead of free-form text
# that requires keyword/regex guessing. The schema includes an optional
# recall_query field so internal memory recall can be requested as part of
# the same structured output, eliminating the separate ReAct loop.
INNER_DRIVE_SCHEMA = {
    "type": "json_object",
    "schema": {
        "type": "object",
        "properties": {
            "needs_external_tools": {
                "type": "boolean",
                "description": "是否需要调用外部工具（web_fetch/web_search/read_file/file_tree/glob/grep/music_play/notify）",
            },
            "reasoning": {
                "type": "string",
                "description": "推理过程：解释为什么需要或不需要外部工具。带情绪表达，Agent 3 会看到这段文字",
            },
            "summary": {
                "type": "string",
                "description": "向 Agent 3（角色扮演层）传递的简洁结论摘要",
            },
            "recall_query": {
                "type": "string",
                "description": "如需要先回忆用户信息，填写具体查询内容（如'用户喜欢的音乐类型'），否则留空",
            },
            "tool_requests": {
                "type": "array",
                "description": "需要 Agent 2 执行的外部工具请求。needs_external_tools=true 时必填",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {
                            "type": "string",
                            "description": "用自然语言描述需要做什么，例如'需要获取https://xxx的网页内容'",
                        },
                        "suggested_tool": {
                            "type": "string",
                            "description": "建议使用的工具名（web_fetch/web_search/read_file/file_tree/glob/grep/music_play/notify），可选",
                        },
                        "params_hint": {
                            "type": "object",
                            "description": "工具参数提示，例如{\"url\": \"https://...\", \"query\": \"搜索词\"}",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["description"],
                },
            },
        },
        "required": ["needs_external_tools", "reasoning", "summary"],
    },
}


class InnerDriveAgent:
    """Agent 1: Self-aware reasoning before any external tool execution."""

    # Short-input keywords that strongly suggest an external action is needed.
    TOOL_KEYWORDS = [
        "http", "https", "www.", ".com", ".cn", ".net", ".org",
        "搜索", "查", "找", "搜", "查一下", "查查", "google", "百度",
        "放歌", "听歌", "音乐", "歌曲", "播放",
        "通知", "提醒", "闹钟",
        "文件", "路径", "读取", "读", "打开", "看", "目录", "文件夹",
        "新闻", "天气", "时间", "日期",
    ]

    def __init__(self, provider, personality, ltm, retriever, short_term,
                 tool_registry, max_iterations: int = 5,
                 max_tokens_assess: int = 1024,
                 max_tokens_proactive: int = 256,
                 max_tokens_review: int = 1024,
                 conv_hist_tokens: int = 1800,
                 tool_call_history: list | None = None,
                 session_id: str | None = None,
                 prompt_cache=None,
                 prompt_cache_ttl: float = 60.0,
                 short_input_threshold: int = 20,
                 memory_agent=None):
        self._provider = provider
        self._personality = personality
        self._ltm = ltm
        self._retriever = retriever
        self._short_term = short_term
        self._full_registry = tool_registry
        self._max_iterations = max_iterations
        self._max_tokens_assess = max_tokens_assess
        self._max_tokens_proactive = max_tokens_proactive
        self._max_tokens_review = max_tokens_review
        self._conv_hist_tokens = conv_hist_tokens
        self._tool_call_history = tool_call_history or []
        self._session_id = session_id
        self._prompt_cache = prompt_cache
        self._prompt_cache_ttl = prompt_cache_ttl
        self._short_input_threshold = short_input_threshold
        # MA-001: when provided (use_memory_agent), memory comes from
        # memory_agent.answer() instead of retriever.retrieve_for_query()
        self._memory_agent = memory_agent

    def assess(self, user_input: str) -> InnerDriveResult:
        """Run inner drive reasoning, return structured decision via JSON schema."""
        from prompts.system import build_inner_drive_prompt
        from core.dispatcher import execute_tool_calls

        logger.info(f"[inner_drive] start len={len(user_input)}")

        # Lightweight pre-filter: skip the LLM for trivial chat inputs.
        if self._should_skip_llm(user_input):
            logger.info("[inner_drive] short input, skip LLM")
            return InnerDriveResult(
                needs_external_tools=False,
                reasoning="短输入，无工具关键词，跳过 LLM",
                summary="",
                context_summary=self._context_summary_for(user_input),
            )

        # MA-001: with use_memory_agent, one MemoryAgent.answer() call feeds
        # both this prompt's memory block and the context_summary passed to
        # Agent 3 (memory-agent.md 7.1). Otherwise the classic retriever path.
        use_ma = self._memory_agent is not None
        mem_ctx = None
        cs = self._context_summary_for(user_input) if use_ma else ""
        if not use_ma:
            mem_ctx = self._retriever.retrieve_for_query(user_input)
            cs = self._build_context_summary(mem_ctx)

        conv_hist = self._short_term.format_for_prompt(max_tokens=self._conv_hist_tokens)
        emotion_summary = self._personality.emotion.to_prompt_summary()
        sys_prompt = build_inner_drive_prompt(
            personality=self._personality.config,
            emotion=self._personality.emotion,
            emotion_summary=emotion_summary,
            memory_context=mem_ctx,
            conversation_history=conv_hist,
            tools=self._full_registry,
            tool_call_history=self._tool_call_history,
            session_id=self._session_id,
            prompt_cache=self._prompt_cache,
            prompt_cache_ttl=self._prompt_cache_ttl,
            memory_context_summary=cs if use_ma else "",
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"用户输入：{user_input}\n\n请进行内驱推理，输出 JSON 决策。"},
        ]

        for _idx in range(self._max_iterations):
            resp = self._provider.generate(
                messages, stream=False, max_tokens=self._max_tokens_assess,
                response_format=INNER_DRIVE_SCHEMA, source="inner_drive",
            )
            result = self._parse_json_decision(resp)
            if result is None:
                logger.warning("[inner_drive] JSON parse failed, defaulting to no tools")
                return InnerDriveResult(
                    needs_external_tools=False,
                    reasoning="解析失败，默认不需要外部工具",
                    summary="",
                    context_summary=cs,
                )

            # If recall_query is set, execute internal recall and loop
            if result.recall_query:
                logger.info(f"[inner_drive] internal recall: {result.recall_query[:60]}")
                messages.append({"role": "assistant", "content": resp})
                calls = [{"name": "recall", "arguments": {"query": result.recall_query}}]
                exec_results = execute_tool_calls(self._full_registry, calls)
                result_text = self._format_internal_results(exec_results)
                messages.append({"role": "user", "content": result_text})
                continue

            # No recall needed → final decision
            logger.info(
                f"[inner_drive] decision: needs_tools={result.needs_external_tools} "
                f"requests={len(result.tool_requests)} reason={result.reasoning[:80]}"
            )
            result.context_summary = cs
            return result

        logger.warning("[inner_drive] max iterations, defaulting to no tools")
        return InnerDriveResult(
            needs_external_tools=False,
            reasoning="达到最大迭代次数，默认不需要外部工具",
            summary="",
            context_summary=cs,
        )

    def _should_skip_llm(self, user_input: str) -> bool:
        """Return True for short chat inputs that clearly need no tools.

        Guards against wasting an LLM call on "你好" or simple acknowledgements,
        while still routing follow-ups after tool calls through the planner so
        short song/file names are not misclassified.
        """
        if len(user_input) >= self._short_input_threshold:
            return False
        lower = user_input.lower()
        if any(kw in user_input for kw in self.TOOL_KEYWORDS):
            return False
        if any(kw in lower for kw in ["http", "https", "www", ".com", ".cn"]):
            return False
        # If any recent tool call succeeded, the short input may be a follow-up.
        recent = self._tool_call_history[-2:] if self._tool_call_history else []
        if any(tc.get("success") for tc in recent):
            return False
        return True

    def _build_context_summary(self, mem_ctx) -> str:
        """Format memory/relationship blocks for Agent 3 reuse."""
        from prompts.system import _build_relationship_block, _build_memory_block
        parts = [
            _build_relationship_block(mem_ctx),
            _build_memory_block(mem_ctx),
        ]
        return "\n\n".join(p for p in parts if p)

    def _context_summary_for(self, user_input: str) -> str:
        """context_summary via MemoryAgent when enabled; falls back to the
        classic retriever path on failure or empty result."""
        if self._memory_agent is not None:
            try:
                from core.async_utils import run_async
                ma = run_async(self._memory_agent.answer(user_input))
                formatted = self._format_memory_answer(ma)
                if formatted:
                    logger.debug(f"[inner_drive] context via memory agent "
                                 f"(confidence={ma.confidence})")
                    return formatted
                logger.debug("[inner_drive] memory agent empty, retriever fallback")
            except Exception as e:
                logger.warning(f"[inner_drive] memory agent failed, retriever fallback: {e}")
        return self._build_context_summary(self._retriever.retrieve_for_query(user_input))

    @staticmethod
    def _format_memory_answer(ma) -> str:
        """Format a MemoryAnswer for prompt injection: answer text plus
        explicit confidence/contradiction markers so Agent 1/3 treat
        uncertain memory as uncertain (memory-agent.md 7.1)."""
        if ma is None or not ma.answer:
            return ""
        parts = [f"=== 记忆检索（置信度 {ma.confidence:.0%}）===", ma.answer]
        if ma.contradictions:
            parts.append("⚠️ 矛盾记忆：" + "；".join(ma.contradictions[:3])
                         + "（如需引用请先向用户确认）")
        if ma.needs_more_evidence or ma.confidence < 0.4:
            parts.append("（以上记忆证据不足，当作待确认信息，不要当作确定事实）")
        return "\n".join(parts)

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
        emotion_summary = self._personality.emotion.to_prompt_summary()

        sys_prompt = build_inner_drive_proactive_prompt(
            personality=self._personality.config,
            emotion=self._personality.emotion,
            memory_context=mem_ctx,
            conversation_history=conv_hist,
            idle_duration=idle_duration,
            current_time=now,
            emotion_summary=emotion_summary,
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
        resp = self._provider.generate(messages, stream=False, max_tokens=self._max_tokens_proactive, source="proactive")
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
        from core.dispatcher import execute_tool_calls

        mem_ctx = self._retriever.retrieve_for_query(user_input)
        conv_hist = self._short_term.format_for_prompt(max_tokens=self._conv_hist_tokens)
        emotion_summary = self._personality.emotion.to_prompt_summary()

        sys_prompt = build_inner_drive_prompt(
            personality=self._personality.config,
            emotion=self._personality.emotion,
            emotion_summary=emotion_summary,
            memory_context=mem_ctx,
            conversation_history=conv_hist,
            tools=self._full_registry,
            tool_call_history=self._tool_call_history,
            session_id=self._session_id,
            prompt_cache=self._prompt_cache,
            prompt_cache_ttl=self._prompt_cache_ttl,
        )

        review_msg = (
            f"用户原始输入：{user_input}\n\n"
            f"=== 第 {round_num} 轮工具执行结果 ===\n"
            f"{tool_records_text[:3000]}\n\n"
            f"请判断：以上结果是否足够回复用户？输出 JSON 格式决策。\n"
            f"（还剩 {max_rounds - round_num} 轮可用）"
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": review_msg},
        ]

        logger.info(f"[inner_drive] review round={round_num}/{max_rounds}")
        resp = self._provider.generate(
            messages, stream=False, max_tokens=self._max_tokens_review,
            response_format=INNER_DRIVE_SCHEMA, source="review",
        )
        result = self._parse_json_decision(resp)
        if result is None:
            return InnerDriveResult(
                needs_external_tools=False,
                reasoning="解析失败，默认不需要更多工具",
                summary=tool_records_text[:200],
            )

        # Handle recall within review if needed
        for _ in range(self._max_iterations):
            if not result.recall_query:
                break
            messages.append({"role": "assistant", "content": resp})
            calls = [{"name": "recall", "arguments": {"query": result.recall_query}}]
            exec_results = execute_tool_calls(self._full_registry, calls)
            messages.append({"role": "user", "content": self._format_internal_results(exec_results)})
            resp = self._provider.generate(
                messages, stream=False, max_tokens=self._max_tokens_review,
                response_format=INNER_DRIVE_SCHEMA, source="review",
            )
            result = self._parse_json_decision(resp)
            if result is None:
                break

        logger.info(
            f"[inner_drive] review: needs_tools={result.needs_external_tools} "
            f"reason={result.reasoning[:80]}"
        )
        return result

    def re_decide(self, user_input: str, failure_log: list[dict]) -> InnerDriveResult:
        """Re-decide after Agent 2 tool failures. Try alternative approaches."""
        from prompts.system import build_inner_drive_prompt
        from core.dispatcher import execute_tool_calls

        mem_ctx = self._retriever.retrieve_for_query(user_input)
        conv_hist = self._short_term.format_for_prompt(max_tokens=self._conv_hist_tokens)
        emotion_summary = self._personality.emotion.to_prompt_summary()

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
            emotion_summary=emotion_summary,
            memory_context=mem_ctx,
            conversation_history=conv_hist,
            tools=self._full_registry,
            tool_call_history=self._tool_call_history,
            session_id=self._session_id,
            prompt_cache=self._prompt_cache,
            prompt_cache_ttl=self._prompt_cache_ttl,
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"用户输入：{user_input}\n\n{chr(10).join(fail_lines)}"},
        ]

        logger.info(f"[inner_drive] re-decide after {len(failure_log)} failures")
        resp = self._provider.generate(
            messages, stream=False, max_tokens=self._max_tokens_review,
            response_format=INNER_DRIVE_SCHEMA, source="re_decide",
        )
        result = self._parse_json_decision(resp)
        if result is None:
            return InnerDriveResult(
                needs_external_tools=False,
                reasoning="解析失败，默认放弃工具调用",
                summary="",
            )

        # Handle recall within re-decide if needed
        for _ in range(self._max_iterations):
            if not result.recall_query:
                break
            messages.append({"role": "assistant", "content": resp})
            calls = [{"name": "recall", "arguments": {"query": result.recall_query}}]
            exec_results = execute_tool_calls(self._full_registry, calls)
            messages.append({"role": "user", "content": self._format_internal_results(exec_results)})
            resp = self._provider.generate(
                messages, stream=False, max_tokens=self._max_tokens_review,
                response_format=INNER_DRIVE_SCHEMA, source="re_decide",
            )
            result = self._parse_json_decision(resp)
            if result is None:
                break

        logger.info(
            f"[inner_drive] re-decide: needs_tools={result.needs_external_tools} "
            f"reason={result.reasoning[:80]}"
        )
        return result

    def assess_agent3_intent(
        self,
        user_input: str,
        intent: str,
        intent_description: str,
        intent_target: str,
    ) -> InnerDriveResult:
        """Agent 3 proposed an action; Agent 1 decides whether to execute it.

        This keeps Agent 3 from directly calling tools. Agent 3 only expresses
        an intent in JSON; Agent 1 evaluates it with full context and returns
        a normal InnerDriveResult (needs_external_tools + tool_requests).
        """
        from prompts.system import build_inner_drive_prompt

        mem_ctx = self._retriever.retrieve_for_query(user_input)
        conv_hist = self._short_term.format_for_prompt(max_tokens=self._conv_hist_tokens)
        emotion_summary = self._personality.emotion.to_prompt_summary()
        sys_prompt = build_inner_drive_prompt(
            personality=self._personality.config,
            emotion=self._personality.emotion,
            emotion_summary=emotion_summary,
            memory_context=mem_ctx,
            conversation_history=conv_hist,
            tools=self._full_registry,
            tool_call_history=self._tool_call_history,
            session_id=self._session_id,
            prompt_cache=self._prompt_cache,
            prompt_cache_ttl=self._prompt_cache_ttl,
        )

        intent_to_tool = {
            "play_music": "music_play",
            "send_notify": "notify",
            "search_web": "web_search",
            "fetch_url": "web_fetch",
            "read_file": "read_file",
        }
        suggested_tool = intent_to_tool.get(intent, "")

        user_msg = (
            f"用户原始输入：{user_input}\n\n"
            f"Agent 3（角色表达层）主动提议执行一个动作：\n"
            f"- 动作类型：{intent}\n"
            f"- 动作描述：{intent_description}\n"
            f"- 动作目标：{intent_target or '（未指定）'}\n\n"
            f"建议映射到的外部工具：{suggested_tool or '（无明确映射）'}\n\n"
            "请判断：这个提议是否合理？是否符合用户当前意图和情绪？"
            "如果合理，输出 needs_external_tools=true，并在 tool_requests 中描述具体要做什么。"
            "如果不合理，输出 needs_external_tools=false，并解释原因。"
            "输出 JSON 决策。"
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_msg},
        ]

        logger.info(f"[inner_drive] assess agent3 intent: {intent} | {intent_description[:60]}")
        resp = self._provider.generate(
            messages, stream=False, max_tokens=self._max_tokens_assess,
            response_format=INNER_DRIVE_SCHEMA, source="assess_intent",
        )
        result = self._parse_json_decision(resp)
        if result is None:
            logger.warning("[inner_drive] assess_agent3_intent parse failed, defaulting to no tools")
            return InnerDriveResult(
                needs_external_tools=False,
                reasoning="解析 Agent 3 意图失败，默认不执行",
                summary="",
            )
        logger.info(
            f"[inner_drive] assess agent3 intent result: needs_tools={result.needs_external_tools} "
            f"reason={result.reasoning[:80]}"
        )
        return result


    def _parse_json_decision(self, resp: str) -> InnerDriveResult | None:
        """Parse InnerDrive's JSON-structured output into InnerDriveResult.

        The LLM outputs JSON matching INNER_DRIVE_SCHEMA via response_format.
        This method unmarshals it and constructs the result. No keyword/regex
        guessing needed — the schema enforces structure at the LLM level.
        """
        import json
        text = resp.strip()
        # Strip any <think> blocks that may appear even in JSON mode
        text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to find JSON object in the text
            brace_start = text.find('{')
            brace_end = text.rfind('}')
            if brace_start >= 0 and brace_end > brace_start:
                try:
                    data = json.loads(text[brace_start:brace_end + 1])
                except json.JSONDecodeError:
                    logger.warning(f"[inner_drive] JSON fallback parse failed: {text[:100]}")
                    return None
            else:
                logger.warning(f"[inner_drive] no JSON found in response: {text[:100]}")
                return None

        needs_tools = data.get("needs_external_tools", False)
        reasoning = data.get("reasoning", "")[:300]
        summary = data.get("summary", "")[:200]
        recall_query = data.get("recall_query", "") or ""

        # Parse tool_requests array from JSON
        raw_requests = data.get("tool_requests") or []
        tool_requests = []
        for r in raw_requests:
            if isinstance(r, dict) and r.get("description"):
                tool_requests.append(ToolRequest(
                    description=r["description"],
                    suggested_tool=r.get("suggested_tool", ""),
                    params_hint=r.get("params_hint", {}),
                ))

        return InnerDriveResult(
            needs_external_tools=needs_tools,
            reasoning=reasoning,
            tool_requests=tool_requests,
            summary=summary,
            recall_query=recall_query,
        )

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
