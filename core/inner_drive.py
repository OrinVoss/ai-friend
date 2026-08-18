"""Agent 1: Inner Drive -- self-aware reasoning loop that decides what the AI needs.

Perceive user input → retrieve memory → identify information gaps → decide:
  - No external tools needed → direct to Agent 3 (expression)
  - External tools needed → structured tool request to Agent 2

Uses JSON Schema response_format instead of keyword/regex parsing. (#ID-001)
"""
import logging
import re
import typing
from dataclasses import dataclass, field

from core.cognitive_state import CognitiveState
from core.cognitive_state import MemoryContextProvider
from core.cognitive_state import render_memory_light
from prompts.tools_description import INTENT_TO_TOOL

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
    memory_confidence: float | None = None     # WS-20: memory_agent 置信度透传


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
                # 改进3: 要求 2-4 句详细决策依据，便于追踪边界情况
                "description": "推理过程：2-4 句详细说明决策依据——用户输入触发了什么判断、考虑过哪些选项、为什么选择/排除工具。带情绪表达，Agent 3 会看到这段文字",
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


# Proactive think loop (proactive-think-loop.md): structured output for each
# reflection round. recall_query non-empty → run internal recall and think
# again; empty → the action field is the final decision. care_updates is the
# loop's only allowed side effect (the AI's own care list).
PROACTIVE_LOOP_SCHEMA = {
    "type": "json_object",
    "schema": {
        "type": "object",
        "properties": {
            "thought": {
                "type": "string",
                "description": "当前的想法，自由内容，带情绪色彩",
            },
            "recall_query": {
                "type": "string",
                "description": "想查证的记忆内容，如'用户最近提到的烦心事'；不需要查证则留空",
            },
            "action": {
                "type": "string",
                "enum": ["chat", "explore", "silent"],
                "description": "最终决定。recall_query 非空时本字段忽略",
            },
            "topic_hint": {
                "type": "string",
                "description": "聊天或探索的话题方向",
            },
            "reasoning": {
                "type": "string",
                # 改进3: 要求 2-4 句详细决策依据，便于追踪边界情况
                "description": "决策理由：2-4 句详细说明——为什么现在说话/探索/沉默、依据哪些上下文（近期话题、关系阶段、情绪状态）。会作为 inner_drive_summary 传给 Agent 3",
            },
            "care_updates": {
                "type": "object",
                "description": "挂念清单更新，可选",
                "properties": {
                    "add": {
                        "type": "array",
                        "items": {
                            "oneOf": [
                                {"type": "string"},
                                {
                                    "type": "object",
                                    "properties": {
                                        "content": {"type": "string"},
                                        "type": {
                                            "type": "string",
                                            "enum": ["care", "curiosity",
                                                     "reflection", "plan", "idea"],
                                        },
                                        "priority": {"type": "number"},
                                        "expires_at": {
                                            "type": "string",
                                            "description": "ISO 时间，plan 类建议填写",
                                        },
                                    },
                                    "required": ["content"],
                                },
                            ],
                        },
                    },
                    "remove": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "required": ["thought", "action", "reasoning"],
    },
}

PROACTIVE_ACTIONS = {"chat", "explore", "silent"}


def _positive_int(value, default: int) -> int:
    """Coerce a config value to a positive int; bad types → default."""
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


class InnerDriveAgent:
    """Agent 1: Self-aware reasoning before any external tool execution."""

    def __init__(self, provider, personality, ltm, retriever, short_term,
                 tool_registry, max_iterations: int = 5,
                 max_tokens_assess: int = 1024,
                 max_tokens_proactive: int = 256,
                 max_tokens_review: int = 1024,
                 conv_hist_tokens: int = 3600,
                 tool_call_history: list | None = None,
                 session_id: str | None = None,
                 prompt_cache=None,
                 prompt_cache_ttl: float = 60.0,
                 memory_agent=None,
                 rule_tools_registry=None,
                 proactive_think_loop: bool = True,
                 proactive_think_max_rounds: int = 2,  # F2: 默认 2 轮
                 inner_drive_state=None):
        self._provider = provider
        self._personality = personality
        self._ltm = ltm
        self._retriever = retriever
        self._short_term = short_term
        self._full_registry = tool_registry
        # M-06: prompt 里的工具规则/清单数据源（全量 registry）；
        # 为 None 时 build_inner_drive_prompt 回退到 tool_registry。
        self._rule_tools_registry = rule_tools_registry
        self._max_iterations = max_iterations
        self._max_tokens_assess = max_tokens_assess
        self._max_tokens_proactive = max_tokens_proactive
        self._max_tokens_review = max_tokens_review
        self._conv_hist_tokens = conv_hist_tokens
        self._tool_call_history = tool_call_history or []
        self._session_id = session_id
        self._prompt_cache = prompt_cache
        self._prompt_cache_ttl = prompt_cache_ttl
        # MA-001: when provided (use_memory_agent), memory comes from
        # memory_agent.answer() instead of retriever.retrieve_for_query()
        self._memory_agent = memory_agent
        # Proactive think loop (proactive-think-loop.md): bounded reflection
        # loop on the proactive path; inner_drive_state is the persistent
        # care list read at Round 1 and updated via care_updates.
        self._think_loop = proactive_think_loop
        self._think_max_rounds = _positive_int(proactive_think_max_rounds, 2)  # F2: 默认 2 轮
        self._inner_drive_state = inner_drive_state
        # R1: memory-context assembly 抽离到 MemoryContextProvider，同消息内
        # answer/review/re_decide 复用同一 MemoryAnswer，避免重复调用。
        self._memory_provider = MemoryContextProvider(self._retriever, self._memory_agent)

    def _decision_loop(
        self, messages: list[dict], *,
        on_parse_failed: typing.Callable[[], InnerDriveResult],
        source: str = "inner_drive",
        max_tokens: int | None = None,
    ) -> InnerDriveResult:
        """T5: 公共决策循环——LLM 生成 + JSON 解析 + recall_query 子循环。

        assess()/review()/re_decide() 各自的 prompt 构建、日志 tag、兜底文案
        在此统一处理。Callers 提供 messages（已含 system+user）和 on_parse_failed
        工厂（JSON 解析失败及 max iterations 耗尽时调用）。
        """
        from core.dispatcher import execute_tool_calls

        max_tokens = max_tokens or self._max_tokens_assess

        for _idx in range(self._max_iterations):
            resp = self._provider.generate(
                messages, stream=False, max_tokens=max_tokens,
                response_format=INNER_DRIVE_SCHEMA, source=source,
                temperature=0.3,
            )
            result = self._parse_json_decision(resp)
            if result is None:
                logger.warning(f"[inner_drive] {source}: JSON parse failed, fallback")
                return on_parse_failed()

            # recall_query → execute internal recall and loop
            if result.recall_query:
                logger.info(
                    f"[inner_drive] {source}: internal recall: {result.recall_query[:60]}"
                )
                messages.append({"role": "assistant", "content": resp})
                calls = [{"name": "recall",
                          "arguments": {"query": result.recall_query}}]
                exec_results = execute_tool_calls(self._full_registry, calls)
                messages.append(
                    {"role": "user",
                     "content": self._format_internal_results(exec_results)}
                )
                continue

            # No recall → final decision
            logger.info(
                f"[inner_drive] {source}: "
                f"needs_tools={result.needs_external_tools} "
                f"requests={len(result.tool_requests)} "
                f"reason={result.reasoning}"
            )
            return result

        logger.warning(
            f"[inner_drive] {source}: max iterations, fallback"
        )
        return on_parse_failed()

    def assess(self, user_input: str,
               cognitive_state: CognitiveState | None = None) -> InnerDriveResult:
        """Run inner drive reasoning, return structured decision via JSON schema.

        WS-21: cognitive_state 存在时，跳过本方法内部的记忆检索，直接消费状态
        中的 memory_summary / emotion_summary，实现每轮只检索一次。
        """
        from prompts.system import build_inner_drive_prompt

        logger.info(f"[inner_drive] start len={len(user_input)}")

        if cognitive_state is not None:
            # WS-22: 使用统一状态中的记忆与情绪快照
            cs_agent1 = cognitive_state.memory_summary
            memory_confidence = cognitive_state.memory_confidence
            ma = getattr(cognitive_state, "memory_answer", None)
            cs_agent3 = render_memory_light(ma, fallback=cs_agent1)
            # 二期 4.2：挂念浮现仍由 InnerDrive 处理（轻量向量操作，不增加 LLM 成本）
            care_block = self._surface_care_for(user_input)
            if care_block:
                cs_agent3 = f"{cs_agent3}\n\n{care_block}" if cs_agent3 else care_block
            mem_ctx = None
            emotion_summary = cognitive_state.emotion_summary
        else:
            # MA-001: with use_memory_agent, one MemoryAgent.answer() call feeds
            # both this prompt's memory block and the context_summary passed to
            # Agent 3 (memory-agent.md 7.1). Otherwise the classic retriever path.
            use_ma = self._memory_agent is not None
            mem_ctx = None
            ma = self._memory_answer_for(user_input) if use_ma else None
            cs = self._context_summary_for(user_input) if use_ma else ""
            if not use_ma:
                mem_ctx = self._retriever.retrieve_for_query(user_input)
                cs = self._build_context_summary(mem_ctx)
            # Agent 3 的轻量上下文（L3-3）：与 Agent 1 的同一份记忆，按 profile 渲染
            if ma is not None:
                from memory.retrieval_pipeline import ContextBuilder
                light = ContextBuilder().build("agent3", ma)
                cs_agent3 = light if light else cs   # 轻量为空（无相关记忆）时退回 cs
            else:
                cs_agent3 = cs
            # 二期 4.2：对话触发的挂念浮现——用户聊到的事和某条挂念相关时，
            # 它自然浮上来，经 context_summary 链路同流到 Agent 3，调用侧零改动
            care_block = self._surface_care_for(user_input)
            if care_block:
                cs_agent3 = f"{cs_agent3}\n\n{care_block}" if cs_agent3 else care_block
            cs_agent1 = cs
            memory_confidence = ma.confidence if ma is not None else None
            emotion_summary = None

        conv_hist = self._short_term.format_for_prompt(max_tokens=self._conv_hist_tokens)
        sys_prompt = build_inner_drive_prompt(
            personality=self._personality.config,
            emotion=self._personality.emotion,
            memory_context=mem_ctx,
            conversation_history=conv_hist,
            tools=self._full_registry,
            tool_call_history=self._tool_call_history,
            session_id=self._session_id,
            prompt_cache=self._prompt_cache,
            prompt_cache_ttl=self._prompt_cache_ttl,
            memory_context_summary=cs_agent1,
            rule_tools=self._rule_tools_registry,
            emotion_summary=emotion_summary,
        )
        if self._prompt_cache is not None:
            self._prompt_cache.maybe_log_stats(logger, tag="inner_drive")

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"用户输入：{user_input}\n\n请进行内驱推理，输出 JSON 决策。"},
        ]

        def _assess_fallback() -> InnerDriveResult:
            return InnerDriveResult(
                needs_external_tools=False,
                reasoning="评估分析提前终止，默认不需要外部工具",
                summary="",
                context_summary=cs_agent3,
                memory_confidence=memory_confidence,
            )

        result = self._decision_loop(
            messages,
            on_parse_failed=_assess_fallback,
            source="inner_drive",
        )
        result.context_summary = cs_agent3
        result.memory_confidence = memory_confidence
        return result

    def _surface_care_for(self, user_input: str) -> str:
        """响应路径的挂念浮现块（inner-drive-state.md 4.2）：相关度超过
        阈值的活跃挂念注入上下文，可自然提及，不要硬塞。"""
        if self._inner_drive_state is None or not user_input.strip():
            return ""
        try:
            hits = self._inner_drive_state.surface_for_query(user_input)
            if not hits:
                return ""
            from core.inner_drive_state import TYPE_LABELS
            lines = "\n".join(
                f"- [{TYPE_LABELS.get(e.type, e.type)}] {e.content}" for e in hits)
        except Exception as e:
            logger.debug(f"[inner_drive] care surface_for_query failed: {e}")
            return ""
        logger.info(f"[inner_drive] care surfaced on-topic: "
                    f"{[e.content[:30] for e in hits]}")
        return ("=== 你在意的事（与当前对话相关，可自然提及，不要硬塞）===\n"
                + lines)

    def _build_context_summary(self, mem_ctx) -> str:
        """Delegate to MemoryContextProvider: format memory/relationship blocks."""
        return self._memory_provider.build_summary(mem_ctx)

    def _memory_answer_for(self, user_input: str):
        """Delegate to MemoryContextProvider: cached MemoryAnswer per message."""
        return self._memory_provider.answer_for(user_input)

    def _context_summary_for(self, user_input: str) -> str:
        """Delegate to MemoryContextProvider: full memory context for Agent 1."""
        return self._memory_provider.summary_for(user_input)

    @staticmethod
    def _format_memory_answer(ma) -> str:
        """Delegate to MemoryContextProvider: backward-compatible formatter."""
        return MemoryContextProvider.format_memory_answer(ma)

    def assess_proactive(self, idle_duration: float,
                         recent_topics: list | None = None) -> ProactiveIntent:
        """Decide whether and how to proactively engage the user.

        Called after ProactivityManager's cheap scoring triggers.
        With proactive_think_loop on (default), runs a bounded reflection
        loop (proactive-think-loop.md): think → optionally recall → decide,
        with the persistent care list as Round-1 input and care_updates as
        the only allowed side effect. Off → legacy single-shot decision.
        #177: recent_topics 来自 ProactivityManager 的去重队列，
        prompt 中告知 LLM 避开近期已聊话题。
        """
        if not self._think_loop:
            return self._assess_proactive_single(idle_duration, recent_topics)

        from datetime import datetime
        from prompts.system import build_inner_drive_proactive_prompt
        from core.dispatcher import execute_tool_calls

        now = datetime.now()
        # M-04: 记忆上下文走 _context_summary_for（尊重 use_memory_agent），
        # query 与原逻辑一致为空字符串
        cs = self._context_summary_for("")
        conv_hist = self._short_term.format_for_prompt(max_tokens=self._conv_hist_tokens)
        # 二期：按浮现规则（priority × 情绪类型权重 × 时效）取挂念，非全量倾倒
        care_list: list[str] = []
        if self._inner_drive_state is not None:
            try:
                from core.inner_drive_state import TYPE_LABELS
                care_list = [
                    f"[{TYPE_LABELS.get(e.type, e.type)}] {e.content}"
                    for e in self._inner_drive_state.surface(
                        emotion=self._personality.emotion)
                ]
            except Exception as e:
                logger.warning(f"[inner_drive] care surface failed: {e}")

        sys_prompt = build_inner_drive_proactive_prompt(
            personality=self._personality.config,
            emotion=self._personality.emotion,
            memory_context=None,
            conversation_history=conv_hist,
            idle_duration=idle_duration,
            current_time=now,
            memory_context_summary=cs,
            recent_topics=recent_topics,
            care_list=care_list,
            think_loop=True,
        )

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": (
                f"用户已经 {idle_duration:.0f} 秒没有说话。"
                f"现在是 {now.strftime('%H:%M')}。\n"
                "这是一段独处的时间。自由地想一想，输出本轮思考的 JSON。\n"
                "如果想查证什么，先填 recall_query；"
                "想清楚了，recall_query 留空并给出最终决定。"
            )},
        ]

        logger.info(f"[inner_drive] proactive think loop start "
                    f"idle={idle_duration:.0f}s care={len(care_list)}")
        for round_num in range(1, self._think_max_rounds + 1):
            logger.info(f"[inner_drive] think round={round_num}/{self._think_max_rounds}")
            resp = self._provider.generate(
                messages, stream=False, max_tokens=self._max_tokens_proactive,
                response_format=PROACTIVE_LOOP_SCHEMA, source="proactive",
                temperature=0.3,
            )
            parsed = self._parse_proactive_json(resp)
            if parsed is None:
                logger.warning("[inner_drive] think JSON parse failed, regex fallback")
                intent = self._parse_proactive_intent(resp)
                logger.info(
                    f"[inner_drive] proactive decision (fallback): action={intent.action} "
                    f"topic={intent.topic_hint[:60]} reason={intent.reasoning}"
                )
                return intent

            self._apply_care_updates(parsed.get("care_updates"))
            if parsed["thought"]:
                logger.info(f"[inner_drive] thought: {parsed['thought'][:80]}")

            recall_query = parsed["recall_query"]
            if recall_query and round_num < self._think_max_rounds:
                logger.info(f"[inner_drive] think recall: {recall_query[:60]}")
                messages.append({"role": "assistant", "content": resp})
                calls = [{"name": "recall", "arguments": {"query": recall_query}}]
                exec_results = execute_tool_calls(self._full_registry, calls)
                messages.append({"role": "user", "content": self._format_internal_results(exec_results)})
                continue
            if recall_query:
                # Last round still asking for recall — no rounds left; use
                # its action if valid, otherwise _to_intent falls to silent.
                logger.info("[inner_drive] think: max rounds reached with pending recall")
            return self._to_proactive_intent(parsed)

        # Unreachable (loop always returns), but keep a safe default.
        return ProactiveIntent(action="silent", reasoning="沉思循环异常终止")

    def _assess_proactive_single(self, idle_duration: float,
                                 recent_topics: list | None = None) -> ProactiveIntent:
        """Legacy single-shot proactive decision (proactive_think_loop=false)."""
        from datetime import datetime
        from prompts.system import build_inner_drive_proactive_prompt

        now = datetime.now()
        cs = self._context_summary_for("")
        conv_hist = self._short_term.format_for_prompt(max_tokens=self._conv_hist_tokens)

        sys_prompt = build_inner_drive_proactive_prompt(
            personality=self._personality.config,
            emotion=self._personality.emotion,
            memory_context=None,
            conversation_history=conv_hist,
            idle_duration=idle_duration,
            current_time=now,
            memory_context_summary=cs,
            recent_topics=recent_topics,
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
        resp = self._provider.generate(messages, stream=False, max_tokens=self._max_tokens_proactive, source="proactive", temperature=0.3)
        intent = self._parse_proactive_intent(resp)
        logger.info(
            f"[inner_drive] proactive decision: action={intent.action} "
            f"topic={intent.topic_hint[:60]} reason={intent.reasoning}"
        )
        return intent

    def _to_proactive_intent(self, parsed: dict) -> ProactiveIntent:
        """Convert a parsed think-loop round into the final ProactiveIntent."""
        action = parsed["action"]
        if action not in PROACTIVE_ACTIONS:
            action = "silent"
        intent = ProactiveIntent(
            action=action,
            topic_hint=parsed["topic_hint"][:100],
            reasoning=parsed["reasoning"][:300],
        )
        logger.info(
            f"[inner_drive] proactive decision: action={intent.action} "
            f"topic={intent.topic_hint[:60]} reason={intent.reasoning}"
        )
        return intent

    def _apply_care_updates(self, care_updates) -> None:
        """Apply care_updates to the persistent care list. This is the only
        write action the think loop is allowed to have; failures are ignored
        (the inner world degrades to in-memory for this trigger)."""
        if not care_updates or self._inner_drive_state is None:
            return
        add = care_updates.get("add")
        remove = care_updates.get("remove")
        try:
            self._inner_drive_state.apply_updates(
                add=add if isinstance(add, list) else None,
                remove=remove if isinstance(remove, list) else None,
            )
        except Exception as e:
            logger.warning(f"[inner_drive] care updates failed: {e}")

    def _parse_proactive_json(self, resp: str) -> dict | None:
        """Parse one think-loop round's JSON output. None → caller falls back
        to the legacy regex parser."""
        import json
        text = re.sub(r'<think>.*?</think>', '', resp.strip(), flags=re.DOTALL).strip()
        data = None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            brace_start = text.find('{')
            brace_end = text.rfind('}')
            if 0 <= brace_start < brace_end:
                try:
                    data = json.loads(text[brace_start:brace_end + 1])
                except json.JSONDecodeError:
                    data = None
        if not isinstance(data, dict):
            return None
        care = data.get("care_updates")
        return {
            "thought": str(data.get("thought", "") or ""),
            "recall_query": str(data.get("recall_query", "") or "").strip(),
            "action": str(data.get("action", "") or "").strip(),
            "topic_hint": str(data.get("topic_hint", "") or ""),
            "reasoning": str(data.get("reasoning", "") or ""),
            "care_updates": care if isinstance(care, dict) else None,
        }

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

        # M-04: 走 _context_summary_for，use_memory_agent 开关对 review 同样生效；
        # retriever 直接调用仅保留在 _context_summary_for 内部作回退。
        # 注意：review 结果的 context_summary 不填，避免改变 Agent 3 prompt 组成。
        cs = self._context_summary_for(user_input)
        conv_hist = self._short_term.format_for_prompt(max_tokens=self._conv_hist_tokens)

        sys_prompt = build_inner_drive_prompt(
            personality=self._personality.config,
            emotion=self._personality.emotion,
            memory_context=None,
            conversation_history=conv_hist,
            tools=self._full_registry,
            tool_call_history=self._tool_call_history,
            session_id=self._session_id,
            prompt_cache=self._prompt_cache,
            prompt_cache_ttl=self._prompt_cache_ttl,
            memory_context_summary=cs,
            rule_tools=self._rule_tools_registry,
        )
        if self._prompt_cache is not None:
            self._prompt_cache.maybe_log_stats(logger, tag="inner_drive_review")

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

        def _review_fallback() -> InnerDriveResult:
            return InnerDriveResult(
                needs_external_tools=False,
                reasoning="分析终止，默认不需要更多工具",
                summary=tool_records_text[:200],
            )

        return self._decision_loop(
            messages,
            on_parse_failed=_review_fallback,
            source="review",
            max_tokens=self._max_tokens_review,
        )

    def re_decide(self, user_input: str, failure_log: list[dict]) -> InnerDriveResult:
        """Re-decide after Agent 2 tool failures. Try alternative approaches."""
        from prompts.system import build_inner_drive_prompt

        # M-04: 同 review，记忆上下文走 _context_summary_for（尊重 use_memory_agent）
        cs = self._context_summary_for(user_input)
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
            memory_context=None,
            conversation_history=conv_hist,
            tools=self._full_registry,
            tool_call_history=self._tool_call_history,
            session_id=self._session_id,
            prompt_cache=self._prompt_cache,
            prompt_cache_ttl=self._prompt_cache_ttl,
            memory_context_summary=cs,
            rule_tools=self._rule_tools_registry,
        )
        if self._prompt_cache is not None:
            self._prompt_cache.maybe_log_stats(logger, tag="inner_drive_redecide")

        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"用户输入：{user_input}\n\n{chr(10).join(fail_lines)}"},
        ]

        logger.info(f"[inner_drive] re-decide after {len(failure_log)} failures")

        def _redecide_fallback() -> InnerDriveResult:
            return InnerDriveResult(
                needs_external_tools=False,
                reasoning="分析终止，默认放弃工具调用",
                summary="",
            )

        return self._decision_loop(
            messages,
            on_parse_failed=_redecide_fallback,
            source="re_decide",
            max_tokens=self._max_tokens_review,
        )

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

        # M-04: 同 review，记忆上下文走 _context_summary_for（尊重 use_memory_agent）
        cs = self._context_summary_for(user_input)
        conv_hist = self._short_term.format_for_prompt(max_tokens=self._conv_hist_tokens)
        sys_prompt = build_inner_drive_prompt(
            personality=self._personality.config,
            emotion=self._personality.emotion,
            memory_context=None,
            conversation_history=conv_hist,
            tools=self._full_registry,
            tool_call_history=self._tool_call_history,
            session_id=self._session_id,
            prompt_cache=self._prompt_cache,
            prompt_cache_ttl=self._prompt_cache_ttl,
            memory_context_summary=cs,
            rule_tools=self._rule_tools_registry,
        )
        if self._prompt_cache is not None:
            self._prompt_cache.maybe_log_stats(logger, tag="inner_drive_intent")

        # intent→tool 映射单一出处在 prompts/tools_description.py（由
        # _TOOL_INTENT_ALIASES 反向派生），不再在此硬编码
        suggested_tool = INTENT_TO_TOOL.get(intent, "")

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
            temperature=0.3,
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
            f"reason={result.reasoning}"
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
