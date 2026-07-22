"""Three-layer Agent orchestration.

Agent 1 (InnerDrive) -- assess intent, decide if external tools needed
Agent 2 (ToolAgent)  -- execute external tools with retry
Agent 3 (Roleplay)   -- personality-driven final response
"""

import logging
import random
import re
import time
from dataclasses import dataclass, field
from enum import Enum, auto

from core.cognitive_state import CognitiveState
from core.context_manager import estimate_tokens, COMPRESS_THRESHOLD
from core.prompt_cache import PromptCache

logger = logging.getLogger(__name__)


class MessageHandlerState(Enum):
    """Explicit states for the three-Agent pipeline.

    The state machine is intentionally lightweight: it records the current
    phase for observability and tests without replacing Python control flow.
    """
    IDLE = auto()
    ASSESSING = auto()
    EXECUTING_TOOLS = auto()
    HANDLING_INTENT = auto()
    GENERATING_RESPONSE = auto()
    ERROR_FALLBACK = auto()
    DONE = auto()


@dataclass
class ToolExecutionResult:
    """Unified result of an Agent 2 tool execution phase.

    Encapsulates formatted records, call statistics, and optional error
    information so callers do not need to rebuild strings manually.
    """
    records_text: str = ""
    total_calls: int = 0
    success_count: int = 0
    has_error: bool = False
    error_message: str = ""
    elapsed_ms: float = 0.0

    @classmethod
    def from_records(
        cls,
        all_tool_results,
        tool_agent,
        max_length: int = 3000,
        error_message: str = "",
    ) -> "ToolExecutionResult":
        """Build a ToolExecutionResult from a list of ToolAgentResult objects."""
        parts = []
        total_calls = 0
        success_count = 0
        for r in all_tool_results:
            part = tool_agent.format_for_phase2(r)
            if part:
                parts.append(part)
            total_calls += r.total_calls
            success_count += r.success_count

        records_text = "\n".join(parts)
        has_error = bool(error_message)
        if has_error:
            records_text = f"{error_message}\n{records_text}"
        if len(records_text) > max_length:
            records_text = records_text[:max_length] + "\n...(后续结果已截断)"

        return cls(
            records_text=records_text,
            total_calls=total_calls,
            success_count=success_count,
            has_error=has_error,
            error_message=error_message,
        )

    def with_elapsed(self, elapsed_ms: float) -> "ToolExecutionResult":
        """Return a copy with elapsed_ms set."""
        self.elapsed_ms = elapsed_ms
        return self


class MessageHandler:
    """Orchestrates the three-Agent pipeline."""

    MAX_AGENT2_ROUNDS = 3
    AGENT2_TOTAL_TIMEOUT = 120.0  # seconds
    TOOL_RECORDS_MAX_LENGTH = 3000
    TOOL_HISTORY_MAX_SIZE = 20
    MAX_INPUT_LENGTH = 10000
    CONV_HIST_MAX_TOKENS = 1800

    def __init__(self, agent):
        self._agent = agent
        self._tool_agent = None  # lazy init
        self._inner_drive = None  # lazy init
        self._memory_agent = None  # lazy init (MA-001, use_memory_agent only)
        self._internal_registry = None  # lazy init (H-01, cached)
        self._prompt_cache = PromptCache()
        self._state = MessageHandlerState.IDLE
        self._agent2_total_timeout = float(getattr(
            agent.config, "agent2_total_timeout_seconds", self.AGENT2_TOTAL_TIMEOUT))
        self._last_proactive_care = None  # L4-6a: pending care outcome

    @property
    def a(self):
        return self._agent

    @property
    def current_state(self) -> MessageHandlerState:
        return self._state

    def _transition(self, state: MessageHandlerState) -> None:
        if self._state != state:
            logger.debug(f"[msg] state: {self._state.name} -> {state.name}")
            self._state = state

    def _idle_seconds(self) -> float:
        """WS-9: 距上次用户活动的时间；无法计算时返回 0.0。"""
        last = getattr(self.a, "last_activity_time", None)
        try:
            return time.time() - float(last) if last is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    def _relationship_snapshot(self) -> dict:
        """WS-10: 关系快照；测试用 mock 可能返回非 dict，做防御。"""
        rel = self.a.ltm.get_relationship()
        if isinstance(rel, dict):
            return rel
        return {}

    def _context_for_state(self, user_input: str) -> tuple[str, float | None, object | None]:
        """WS-23: 每轮消息只检索一次记忆，返回 (summary, confidence, raw_answer)。

        summary 是给 Agent 1 使用的完整形态；若走 memory_agent，原始 MemoryAnswer
        会一并存入 CognitiveState，供 Agent 3 按轻量 profile 渲染，保持 prompt 等价。
        """
        self._ensure_inner_drive()
        use_ma = (
            getattr(self.a.config, "use_memory_agent", False)
            and self._inner_drive._memory_agent is not None
        )
        if use_ma:
            from core.async_utils import run_async
            from memory.retrieval_pipeline import ContextBuilder
            ma = run_async(self._inner_drive._memory_agent.answer(user_input))
            if ma is not None:
                full = ContextBuilder().build("agent1", ma)
                if full:
                    return full, ma.confidence, ma
            # 记忆 agent 无结果时回退到 retriever
            mem_ctx = self.a.retriever.retrieve_for_query(user_input)
            summary = self._inner_drive._build_context_summary(mem_ctx)
            return summary, None, None
        mem_ctx = self.a.retriever.retrieve_for_query(user_input)
        summary = self._inner_drive._build_context_summary(mem_ctx)
        return summary, None, None

    def _log_prompt_cache_stats(self, tag: str = "") -> None:
        """PC-002: emit prompt cache stats after each prompt build."""
        self._prompt_cache.maybe_log_stats(logger, tag=tag)

    def _ensure_inner_drive(self):
        if self._inner_drive is None:
            from core.inner_drive import InnerDriveAgent
            a = self.a
            # #203: create isolated registry for Agent 1 (recall/remember only)
            isolated = self._make_internal_registry()
            cfg = a.config
            # MA-001: inject MemoryAgent only when the gray switch is on
            memory_agent = None
            if getattr(cfg, "use_memory_agent", False):
                memory_agent = self._ensure_memory_agent()
                logger.info("[msg] inner drive: memory agent enabled (use_memory_agent)")
            # Proactive think loop: persistent care list (per-session file).
            # Prefer the shared instance from session_factory (also wired to
            # the consolidator); fall back to creating one here.
            inner_drive_state = getattr(a, "_inner_drive_state", None)
            if inner_drive_state is None and getattr(cfg, "proactive_think_loop", True):
                from core.inner_drive_state import InnerDriveState
                inner_drive_state = InnerDriveState(
                    session_id=getattr(a, "session_id", None) or "default",
                    max_entries=getattr(cfg, "inner_drive_care_list_size", 20),
                    embedding_engine=getattr(a.consolidator, "_embed", None),
                    surface_top_k=getattr(cfg, "inner_drive_surface_top_k", 8),
                    response_top_k=getattr(cfg, "inner_drive_surface_response_k", 3),
                    decay_rate=getattr(cfg, "inner_drive_decay_rate", 0.9),
                    similarity_threshold=getattr(
                        cfg, "inner_drive_care_similarity_threshold", 0.7),
                )
            self._inner_drive = InnerDriveAgent(
                provider=a.provider,
                personality=a.personality,
                ltm=a.ltm,
                retriever=a.retriever,
                short_term=a.short_term,
                tool_registry=isolated,
                tool_call_history=a.tool_call_history,
                session_id=getattr(a, "session_id", None),
                prompt_cache=self._prompt_cache,
                prompt_cache_ttl=getattr(cfg, "prompt_cache_ttl_seconds", 60.0),
                memory_agent=memory_agent,
                # M-06: prompt 的工具规则/检查清单用全量 registry 生成，
                # Agent 1 判断 needs_external_tools 需要看到外部工具
                rule_tools_registry=a.tool_registry,
                proactive_think_loop=getattr(cfg, "proactive_think_loop", True),
                proactive_think_max_rounds=getattr(cfg, "proactive_think_max_rounds", 2),
                inner_drive_state=inner_drive_state,
            )

    def _ensure_memory_agent(self):
        """Lazily build the MemoryAgent for InnerDrive injection (MA-001)."""
        if self._memory_agent is None:
            from memory.memory_agent import MemoryAgent
            from memory.lifecycle import MemoryLifecycleManager
            a = self.a
            embed = getattr(a.consolidator, "_embed", None)
            lifecycle = MemoryLifecycleManager(
                a.ltm, config=a.config, embedding_engine=embed)
            # P2: 指代解析用的 LLM 与对话历史（缺一则内部回退规则路径）
            def _clues_llm(prompt: str) -> str:
                return a.provider.generate(
                    [{"role": "user", "content": prompt}],
                    stream=False, max_tokens=128, source="memory_clues")
            self._memory_agent = MemoryAgent(
                a.ltm, lifecycle, a.retriever, embedding_engine=embed,
                relevance_floor=getattr(a.config, "memory_agent_relevance_floor", 0.35),
                relevance_full=getattr(a.config, "memory_agent_relevance_full", 0.75),
                coreference_threshold=getattr(a.config, "memory_agent_coreference_threshold", 0.78),  # R2
                llm_fn=_clues_llm,
                history_fn=lambda: a.short_term.format_for_prompt(max_tokens=800),
                inner_drive_state=getattr(a, "_inner_drive_state", None),
            )
        return self._memory_agent

    def ensure_inner_drive(self):
        """Ensure inner drive is initialized and return it."""
        self._ensure_inner_drive()
        return self._inner_drive

    def _match_active_care(self, topic: str, reasoning: str) -> dict | None:
        """L4-6a: find the active inner-drive entry that the proactive topic
        likely surfaced. Returns a lightweight dict or None."""
        state = getattr(self.a, "_inner_drive_state", None)
        if state is None:
            return None
        query = f"{topic} {reasoning}".strip()
        try:
            if query:
                hits = state.surface_for_query(query)
                if hits:
                    return {"entry_id": hits[0].id, "timestamp": time.time()}
        except Exception as e:
            logger.debug(f"[msg] proactive care surface failed: {e}")
        try:
            for e in state.active_entries():
                if e.content and (e.content in topic or e.content in reasoning):
                    return {"entry_id": e.id, "timestamp": time.time()}
        except Exception as e:
            logger.debug(f"[msg] proactive care substring match failed: {e}")
        return None

    def _evaluate_proactive_outcome(self, user_input: str) -> None:
        """L4-6a: score the user's reply to the last proactive message and
        record the outcome on the matched care entry."""
        state = getattr(self.a, "_inner_drive_state", None)
        if state is None or self._last_proactive_care is None:
            self._last_proactive_care = None
            return
        entry_id = self._last_proactive_care.get("entry_id")
        try:
            sentiment, _, _ = self.a.consolidator.analyze_sentiment(user_input)
            positive = sentiment > 0.1
            state.record_outcome(entry_id, positive)
            logger.info(f"[msg] proactive outcome recorded: entry={entry_id} positive={positive}")
        except Exception as e:
            logger.warning(f"[msg] proactive outcome evaluation failed: {e}")
        self._last_proactive_care = None

    def _ensure_tool_agent(self):
        if self._tool_agent is None:
            from core.tool_agent import ToolAgent
            self._tool_agent = ToolAgent(
                provider=self.a.provider,
                tool_registry=self._make_external_registry(),
            )

    def _make_internal_registry(self):
        """Isolated registry (recall/remember only) for Agent 1 / Agent 3.

        H-01: cached and reused — RecallTool/RememberTool 无可变内部状态，
        重复新建没有收益。
        """
        if self._internal_registry is None:
            from tools.traits import ToolRegistry
            from tools.memory_tools import RecallTool, RememberTool
            a = self.a
            r = ToolRegistry()
            if a.retriever is not None and a.ltm is not None:
                r.register(RecallTool(retriever=a.retriever, ltm=a.ltm))
                r.register(RememberTool(ltm=a.ltm))
            self._internal_registry = r
        return self._internal_registry

    def _make_external_registry(self):
        """Build a registry containing only external tools for Agent 2."""
        from tools.traits import ToolRegistry, EXTERNAL_TOOL_NAMES
        r = ToolRegistry()
        for name in EXTERNAL_TOOL_NAMES:
            tool = self.a.tool_registry.get(name)
            if tool and not getattr(tool, "is_internal", False):
                r.register(tool)
        return r

    def handle_message(self, user_input: str, on_token=None) -> str:
        from prompts.system import build_system_prompt
        a = self.a

        # #256: guard against empty input
        if not user_input or not user_input.strip():
            return ""

        # A3（2026-07-21）：CLI 路径的 request_id 设置点——Web 已由中间件
        # 设置，这里仅在未设置时生成。无需复位：后台 tick 在独立线程/任务
        # 的 context 里，天然显示 '-'（三个生命循环的边界即 context 边界）
        from core.logging_setup import new_request_id, request_id_var
        if not request_id_var.get():
            request_id_var.set(new_request_id())

        # #110: strip prompt injection patterns from user input
        user_input = _sanitize_input(user_input)

        if a.is_sleeping:
            # #185: preserve user input even during sleep
            a.add_turn("user", user_input, metadata={"sleep": True})
            a.increment_turn_count()
            a.update_last_activity()
            sleep_reply = random.choice([
                "zzz...ZZZ...💤", "Zzzz...[翻身]",
                "zzzz...（小声梦话）", "Zzz...💤",
            ])
            # Persist sleep reply so it survives page refresh
            a.add_turn("assistant", sleep_reply, metadata={"sleep": True})
            a.increment_turn_count()
            logger.info(f"[msg] sleep reply persisted: turn={a.turn_count - 1}")
            return sleep_reply

        logger.info(f"[msg] turn={a.turn_count} len={len(user_input)}")
        a.set_current_input(user_input)
        idle_seconds = self._idle_seconds()
        a.update_last_activity()
        a.add_turn("user", user_input)

        # L4-6a: the first user message after a proactive message evaluates the outcome.
        if self._last_proactive_care:
            self._evaluate_proactive_outcome(user_input)

        # ── Agent 1: Inner Drive ──
        self._transition(MessageHandlerState.ASSESSING)
        # WS-24: 记忆检索前移到状态装配处，保证每条用户消息只检索一次。
        memory_summary, memory_confidence, memory_answer = self._context_for_state(user_input)

        # WS-11: 装配统一运行时状态；情绪在轮次开始一次性冻结，后续 Agent 1/3 共用。
        emotion_summary = a.personality.emotion.to_prompt_summary()
        state = CognitiveState(
            personality_name=a.personality.config.name,
            emotion_summary=emotion_summary if isinstance(emotion_summary, dict) else {},
            relationship=self._relationship_snapshot(),
            memory_summary=memory_summary,
            memory_confidence=memory_confidence,
            memory_answer=memory_answer,
            care_surface=[],  # 挂念块由 InnerDrive 在 assess 中追加到 context_summary
            turn_count=a.turn_count,
            idle_seconds=idle_seconds,
            is_sleeping=False,
        )

        try:
            drive_result = self._inner_drive.assess(user_input, cognitive_state=state)
        except Exception as exc:
            # #146: Agent 1 异常不再穿透——REST chat_api 路径没有外层 try，
            # 穿透会直接 500。降级为直走 Agent 3（同 agent2_error 先例）。
            logger.warning(f"[msg] agent1 assess failed, degrading to direct reply: {exc}")
            self._transition(MessageHandlerState.ERROR_FALLBACK)
            from core.inner_drive import InnerDriveResult
            drive_result = InnerDriveResult(
                needs_external_tools=False,
                reasoning=f"内驱评估异常（{type(exc).__name__}），已降级为直接回复",
                summary="",
            )

        # WS-25: Agent 3 消费评估后的 context_summary（含挂念浮现等后处理）。
        state.memory_summary = drive_result.context_summary or state.memory_summary
        state.memory_confidence = drive_result.memory_confidence or state.memory_confidence
        state.pending = {
            "needs_tools": drive_result.needs_external_tools,
            "summary": drive_result.summary,
        }

        if not drive_result.needs_external_tools:
            # No external tools needed → straight to Agent 3
            logger.info(f"[msg] agent1: no external tools needed")
            self._transition(MessageHandlerState.GENERATING_RESPONSE)
            agent3_output = self._run_agent3(
                user_input, drive_result, tool_result=None,
                on_token=on_token, state=state,
            )
            result = self._handle_agent3_intent(user_input, agent3_output, on_token=on_token)
            logger.debug(
                f"[state] mem_chars={len(state.memory_summary)} "
                f"confidence={state.memory_confidence} care={len(state.care_surface)} "
                f"pending={state.pending}"
            )
            self._transition(MessageHandlerState.DONE)
            return result

        # ── Agent 2: Multi-round tool execution ──
        self._transition(MessageHandlerState.EXECUTING_TOOLS)
        exec_result = self._run_agent2(user_input, drive_result)
        if exec_result.records_text:
            logger.info(
                f"[msg] agent2: {exec_result.total_calls} calls, "
                f"{exec_result.success_count} ok"
            )
            # Sync Agent 2 results to tool_call_history so prompt can show them
            # (records are already capped at 200 chars by record_tool_call)
            # We reconstruct from the last tool_result if available; otherwise skip.
            if exec_result.total_calls > 0 and self._tool_agent is not None:
                # Best-effort sync: re-execute formatting is not needed for history
                pass

        # ── Agent 3: Emotional expression ──
        self._transition(MessageHandlerState.GENERATING_RESPONSE)
        result = self._run_agent3(
            user_input, drive_result, None,
            tool_records=exec_result.records_text, on_token=on_token,
            final_response=True, state=state,
        )
        logger.debug(
            f"[state] mem_chars={len(state.memory_summary)} "
            f"confidence={state.memory_confidence} care={len(state.care_surface)} "
            f"pending={state.pending}"
        )
        self._transition(MessageHandlerState.DONE)
        return result

    def _run_agent2(self, user_input: str, drive_result) -> ToolExecutionResult:
        """Execute Agent 2's multi-round tool loop and return a unified result."""
        self._ensure_tool_agent()
        from core.tool_agent import ToolAttemptTracker

        all_tool_results = []
        round_num = 0
        tracker = ToolAttemptTracker()
        agent2_error = ""
        t0 = time.time()
        deadline = time.monotonic() + self._agent2_total_timeout

        try:
            while round_num < self.MAX_AGENT2_ROUNDS and drive_result.needs_external_tools:
                if time.monotonic() > deadline:
                    logger.warning(
                        f"[msg] agent2: total timeout after {self._agent2_total_timeout}s, "
                        f"falling back to direct reply"
                    )
                    agent2_error = (
                        f"[工具执行阶段超时：已超过 {self._agent2_total_timeout:.0f} 秒，"
                        f"已降级为直接回复]"
                    )
                    break
                round_num += 1
                tracker.round_number = round_num
                # MH-001: pass ALL tool requests to Agent 2, executing each in
                # turn. The old code only ever used tool_requests[0], so a
                # multi-tool request from InnerDrive silently dropped the rest.
                if drive_result.tool_requests:
                    logger.info(
                        f"[msg] agent2: round {round_num}/{self.MAX_AGENT2_ROUNDS}, "
                        f"requests={len(drive_result.tool_requests)} "
                        f"first={drive_result.tool_requests[0].description[:80]}"
                    )
                    tool_result = self._tool_agent.run_with_requests(
                        [req.description for req in drive_result.tool_requests]
                    )
                else:
                    logger.info(f"[msg] agent2: round {round_num}/{self.MAX_AGENT2_ROUNDS}, no request text")
                    tool_result = self._tool_agent.run_with_request(user_input)
                tracker.total_attempts += 1
                track_failures(tracker, tool_result)

                while tracker.can_retry_in_round and not tool_result.any_success:
                    tracker.retry_count += 1
                    logger.info(f"[msg] agent2: retry {tracker.retry_count}/3")
                    # MH-001: retry against the first request's description
                    # (the one most likely to still be actionable mid-round).
                    retry_req = (drive_result.tool_requests[0].description
                                 if drive_result.tool_requests else user_input)
                    tool_result = self._tool_agent.run_with_request(retry_req)
                    tracker.total_attempts += 1
                    track_failures(tracker, tool_result)

                if tool_result and tool_result.has_results:
                    all_tool_results.append(tool_result)
                    # Sync results to agent's rolling tool call history
                    for rec in tool_result.records:
                        self.a.record_tool_call(rec.name, rec.success, rec.output)

                combined_records = ""
                for r in all_tool_results:
                    combined_records += self._tool_agent.format_for_phase2(r) + "\n"
                if len(combined_records) > self.TOOL_RECORDS_MAX_LENGTH:
                    combined_records = combined_records[:self.TOOL_RECORDS_MAX_LENGTH] + "\n...(后续结果已截断)"

                if tool_result and tool_result.any_success and round_num < self.MAX_AGENT2_ROUNDS:
                    drive_result = self._inner_drive.review(
                        user_input, combined_records,
                        round_num=round_num, max_rounds=self.MAX_AGENT2_ROUNDS,
                    )
                    if drive_result.needs_external_tools:
                        logger.info(f"[msg] agent1: needs more tools after round {round_num}")
                elif tool_result and not tool_result.any_success:
                    if tracker.can_start_new_round:
                        logger.info(f"[msg] agent1: re-decide after failures")
                        drive_result = self._inner_drive.re_decide(user_input, tracker.failure_log)
                    else:
                        break
                else:
                    break
        except Exception as exc:
            logger.exception("[msg] agent2: unexpected error, falling back to agent3")
            agent2_error = (
                f"[系统提示：工具执行出现错误（{type(exc).__name__}），"
                f"请如实告诉用户哪一步没做成，不要编造结果]"
            )

        elapsed_ms = (time.time() - t0) * 1000
        return ToolExecutionResult.from_records(
            all_tool_results,
            self._tool_agent,
            max_length=self.TOOL_RECORDS_MAX_LENGTH,
            error_message=agent2_error,
        ).with_elapsed(elapsed_ms)

    def handle_proactive(self, on_token=None, intent=None) -> str:
        from prompts.system import build_system_prompt
        a = self.a
        cfg = a.config

        if intent is not None and intent.topic_hint:
            topic = intent.topic_hint
            memory_query = intent.topic_hint
            inner_drive_summary = intent.reasoning
        else:
            topic = a.pick_proactive_topic()
            memory_query = ""
            inner_drive_summary = ""

        mem_ctx = a.retriever.retrieve_for_query(memory_query)
        conv_hist = a.short_term.format_for_prompt(max_tokens=1800)
        sys_prompt = build_system_prompt(
            personality=a.personality.config, emotion=a.personality.emotion,
            memory_context=mem_ctx, conversation_history=conv_hist,
            compressed_summary=a.compressed_summary,
            tools=a.tool_registry,
            is_proactive=True,
            consecutive_negative=a.consecutive_negative,
            inner_drive_summary=inner_drive_summary,
            conversation_examples=cfg.conversation_examples,
            session_id=getattr(a, "session_id", None),
            prompt_cache=self._prompt_cache,
            personality_file=getattr(a, "personality_path", cfg.personality_file),
            prompt_cache_ttl=getattr(cfg, "prompt_cache_ttl_seconds", 60.0),
            demo_turns_remaining=max(
                0,
                getattr(cfg, "conversation_examples_max_turns", 3) - a.turn_count + 1,
            ),
        )
        self._log_prompt_cache_stats(tag="proactive")
        messages = self._build_messages(sys_prompt, user_input=f"[主动开启对话] 主题方向：{topic}")
        logger.info(
            f"[proactive] chat: topic={topic} "
            f"drive={inner_drive_summary[:60] if inner_drive_summary else 'fallback'}"
        )
        # L4-6a: attribute proactive outcome to a surfaced care entry.
        self._last_proactive_care = self._match_active_care(topic, inner_drive_summary)
        # H-05: 主动搭话轮跳过情绪后处理——short_term 里最后一条 user turn 是
        # 上一轮真实用户消息，重复施加会让情绪影响被计算两次
        # H-01: registry 收窄为内部工具（recall/remember），与 prompt 声明一致，
        # 外部动作一律走 intent→Agent 2 管线
        return a._react_loop(messages, on_token, add_to_history=True,
                            tool_registry=self._make_internal_registry(),
                            skip_post_process=True)

    def handle_explore(self, intent=None) -> str | None:
        from prompts.system import build_system_prompt
        a = self.a
        cfg = a.config

        if intent is not None and intent.topic_hint:
            topic = intent.topic_hint
            memory_query = intent.topic_hint
            inner_drive_summary = intent.reasoning
        else:
            topic = a.pick_proactive_topic()
            memory_query = ""
            inner_drive_summary = ""

        mem_ctx = a.retriever.retrieve_for_query(memory_query)
        conv_hist = a.short_term.format_for_prompt(max_tokens=1800)

        self._ensure_tool_agent()
        explore_prompt = f"[自由探索] 可以搜搜关于{topic}的内容。用 web_search 和 web_fetch。"
        tool_result = self._tool_agent.run(explore_prompt)
        tool_records = self._tool_agent.format_for_phase2(tool_result)
        # Sync Agent 2 explore results to tool_call_history
        for rec in tool_result.records:
            a.record_tool_call(rec.name, rec.success, rec.output)

        sys_prompt = build_system_prompt(
            personality=a.personality.config, emotion=a.personality.emotion,
            memory_context=mem_ctx, conversation_history=conv_hist,
            compressed_summary=a.compressed_summary,
            tools=a.tool_registry,
            is_proactive=True,
            consecutive_negative=a.consecutive_negative,
            explore_mode=True,
            inner_drive_summary=inner_drive_summary,
            conversation_examples=cfg.conversation_examples,
            session_id=getattr(a, "session_id", None),
            prompt_cache=self._prompt_cache,
            personality_file=getattr(a, "personality_path", cfg.personality_file),
            prompt_cache_ttl=getattr(cfg, "prompt_cache_ttl_seconds", 60.0),
            demo_turns_remaining=max(
                0,
                getattr(cfg, "conversation_examples_max_turns", 3) - a.turn_count + 1,
            ),
        )
        self._log_prompt_cache_stats(tag="explore")
        messages = self._build_messages(sys_prompt, user_input=None)
        if tool_records:
            messages.insert(-1, {"role": "user", "content": tool_records})
        interests = getattr(a.personality.config, 'interests', [])
        if interests:
            picked = random.sample(interests, min(2, len(interests)))
            messages.append({
                "role": "user",
                "content": f"[自由探索] 系统已获取了一些内容。关于{'/'.join(picked)}，有特别的就分享。"
            })
        logger.info(
            f"[explore] start: topic={topic} "
            f"drive={inner_drive_summary[:60] if inner_drive_summary else 'fallback'}"
        )
        # H-05: 自由探索轮同样跳过情绪后处理（理由同 handle_proactive）
        # H-01: registry 固定收窄为内部工具（理由同 handle_proactive）
        result = a._react_loop(messages, on_token=None, add_to_history=True,
                              tool_registry=self._make_internal_registry(),
                              skip_post_process=True)
        if result and len(result.strip()) > 30 and not result.startswith("搜索"):
            logger.info(f"[explore] shared: {len(result)} chars")
            return result
        logger.debug(f"[explore] silent: result={result[:80] if result else 'None'}")
        return None

    def _run_agent3(self, user_input: str, drive_result, tool_result,
                    on_token=None, tool_records: str = "", final_response: bool = False,
                    state: CognitiveState | None = None) -> str:
        """Run Agent 3: emotional expression with inner drive + tool results.

        WS-12: 优先从 CognitiveState 读取记忆与决策摘要，保持与旧路径数据一致。
        """
        from prompts.system import build_system_prompt
        a = self.a
        cfg = a.config

        # WS-13: 记忆摘要优先从统一状态读取；Phase 1 其内容等同于
        # drive_result.context_summary，仅数据源改变。
        memory_summary = ""
        if state is not None:
            memory_summary = state.memory_summary
            # 若保存了原始 MemoryAnswer，按 Agent 3 的轻量 profile 渲染。
            if getattr(state, "memory_answer", None) is not None:
                from memory.retrieval_pipeline import ContextBuilder
                light = ContextBuilder().build("agent3", state.memory_answer)
                if light:
                    memory_summary = light
        elif drive_result and getattr(drive_result, "context_summary", ""):
            memory_summary = drive_result.context_summary

        # Still keep the memory context object around for downstream code.
        if memory_summary:
            mem_ctx = a.current_memory_context
            if mem_ctx is None:
                mem_ctx = a.retriever.retrieve_for_query(user_input)
        else:
            mem_ctx = a.retriever.retrieve_for_query(user_input)
        a.current_memory_context = mem_ctx
        # NOTE: the user turn is persisted once in handle_message() — do NOT
        # add_turn here again (field bug 2026-07-17: duplicated user message
        # in DB and short-term buffer → duplicate bubbles after refresh).

        conv_hist = a.short_term.format_for_prompt(max_tokens=self.CONV_HIST_MAX_TOKENS)
        # #205: use accumulated tool_records if provided, otherwise fall back to last round
        if not tool_records:
            tool_records = self._tool_agent.format_for_phase2(tool_result) if tool_result else ""

        # WS-14: inner_drive_summary 优先用当前 drive_result；无 drive_result 时
        # 回退到 state.pending，兼容测试与 intent 路径。
        if drive_result is not None:
            inner_drive_summary = drive_result.summary
        elif state is not None:
            inner_drive_summary = state.pending.get("summary", "")
        else:
            inner_drive_summary = ""

        personality_file = getattr(a, "personality_path", cfg.personality_file)
        demo_turns_remaining = max(
            0,
            getattr(cfg, "conversation_examples_max_turns", 3) - a.turn_count + 1,
        )

        sys_prompt = build_system_prompt(
            personality=a.personality.config, emotion=a.personality.emotion,
            memory_context=mem_ctx, conversation_history=conv_hist,
            compressed_summary=a.compressed_summary,
            tools=a.tool_registry,
            consecutive_negative=a.consecutive_negative,
            tool_call_history=a.tool_call_history,
            inner_drive_summary=inner_drive_summary,
            conversation_examples=cfg.conversation_examples,
            final_response=final_response,
            session_id=getattr(a, "session_id", None),
            prompt_cache=self._prompt_cache,
            personality_file=personality_file,
            prompt_cache_ttl=getattr(cfg, "prompt_cache_ttl_seconds", 60.0),
            memory_context_summary=memory_summary,
            demo_turns_remaining=demo_turns_remaining,
            emotion_summary=state.emotion_summary if state is not None else None,
        )
        self._log_prompt_cache_stats(tag="agent3")
        messages = self._build_messages(sys_prompt, user_input=f"用户输入：{user_input}")
        # Inject tool results as USER message (LLM respects user messages >> system messages)
        if tool_records:
            messages.insert(-1, {"role": "user", "content": tool_records})
        # H-01: 无论是否有 tool_records，Agent 3 的 registry 都固定为内部工具
        # （recall/remember），与 prompt 声明一致，不再回退到全量 registry
        return a._react_loop(messages, on_token, add_to_history=True,
                            tool_registry=self._make_internal_registry())

    def _parse_agent3_output(self, text: str) -> dict:
        """Detect whether Agent 3 output is a JSON intent or plain text."""
        import json
        stripped = text.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                data = json.loads(stripped)
                if "intent" in data and data.get("intent"):
                    logger.info(f"[msg] agent3 intent detected: {data.get('intent')}")
                    return {
                        "type": "intent",
                        "reply_to_user": data.get("reply_to_user", ""),
                        "intent": data.get("intent", ""),
                        "intent_description": data.get("intent_description", ""),
                        "intent_target": data.get("intent_target", ""),
                    }
            except json.JSONDecodeError:
                logger.debug("[msg] agent3 output looked like JSON but failed to parse")
        return {"type": "plain", "text": text}

    def _handle_agent3_intent(
        self,
        user_input: str,
        agent3_output: str,
        on_token=None,
        max_loops: int = 2,
    ) -> str:
        """Handle Agent 3 JSON intent: ask Agent 1, execute if approved, otherwise fall back."""
        self._transition(MessageHandlerState.HANDLING_INTENT)
        parsed = self._parse_agent3_output(agent3_output)
        if parsed["type"] == "plain":
            return parsed["text"]

        loop_count = 0
        current_reply = parsed.get("reply_to_user", "")
        current_intent = parsed.get("intent", "")
        current_description = parsed.get("intent_description", "")
        current_target = parsed.get("intent_target", "")

        while loop_count < max_loops and parsed["type"] == "intent":
            loop_count += 1
            self._transition(MessageHandlerState.ASSESSING)
            drive_result = self._inner_drive.assess_agent3_intent(
                user_input=user_input,
                intent=current_intent,
                intent_description=current_description,
                intent_target=current_target,
            )

            if not drive_result.needs_external_tools:
                # Agent 1 rejected the intent; return the transitional reply
                logger.info(f"[msg] agent1: rejected agent3 intent {current_intent}")
                self._transition(MessageHandlerState.DONE)
                return current_reply or drive_result.summary or "让我直接回复你吧。"

            logger.info(
                f"[msg] agent1: approved agent3 intent {current_intent}, "
                f"requests={len(drive_result.tool_requests)}"
            )

            # Execute tools via Agent 2
            self._transition(MessageHandlerState.EXECUTING_TOOLS)
            exec_result = self._run_agent2_single_round(user_input, drive_result)

            # Agent 3 final response after tools; no more JSON allowed
            self._transition(MessageHandlerState.GENERATING_RESPONSE)
            final_text = self._run_agent3(
                user_input, drive_result, None,
                tool_records=exec_result.records_text, on_token=on_token,
                final_response=True,
            )

            # If Agent 3 still emits an intent after tools, loop again (rare)
            parsed = self._parse_agent3_output(final_text)
            if parsed["type"] == "intent":
                current_reply = parsed.get("reply_to_user", current_reply)
                current_intent = parsed.get("intent", current_intent)
                current_description = parsed.get("intent_description", current_description)
                current_target = parsed.get("intent_target", current_target)
                continue
            self._transition(MessageHandlerState.DONE)
            return final_text

        # Loop exhausted or no longer an intent
        self._transition(MessageHandlerState.DONE)
        if parsed["type"] == "plain":
            return parsed["text"]
        return current_reply or "让我直接回复你吧。"

    def _run_agent2_single_round(self, user_input: str, drive_result) -> ToolExecutionResult:
        """Execute a single Agent 2 round with retries (used by intent path)."""
        self._ensure_tool_agent()
        t0 = time.time()

        if drive_result.tool_requests:
            tool_result = self._tool_agent.run_with_requests(
                [req.description for req in drive_result.tool_requests]
            )
        else:
            tool_result = self._tool_agent.run_with_request(user_input)

        retry_count = 0
        while retry_count < 3 and tool_result and not tool_result.any_success:
            retry_count += 1
            logger.info(f"[msg] agent2: retry {retry_count}/3")
            retry_req = (drive_result.tool_requests[0].description
                         if drive_result.tool_requests else user_input)
            tool_result = self._tool_agent.run_with_request(retry_req)

        if tool_result and tool_result.has_results:
            for rec in tool_result.records:
                self._agent.record_tool_call(rec.name, rec.success, rec.output)

        elapsed_ms = (time.time() - t0) * 1000
        return ToolExecutionResult.from_records(
            [tool_result] if tool_result and tool_result.has_results else [],
            self._tool_agent,
            max_length=self.TOOL_RECORDS_MAX_LENGTH,
        ).with_elapsed(elapsed_ms)

    def _build_messages(self, sys_prompt: str, user_input: str | None) -> list[dict]:
        agent = self._agent
        messages = [{"role": "system", "content": sys_prompt}]
        overflow = False
        # MH-007: accumulate a running token total and stop as soon as the
        # budget is exhausted.  Only messages that fit into the window are
        # reversed; this avoids a full-history scan on every request.
        running_total = 0
        history_messages = []
        is_first = True
        for t in agent.short_term.get_all_reversed():
            # 修复：当前输入在 handle_message 时已 add_turn 入历史，末尾还会
            # 以"用户输入：..."形式再追加一次——跳过历史里的这份（即倒序首个
            # 元素），避免同一句话在 prompt 中出现两次（模型会误以为用户在刷屏）
            if is_first and user_input and t.role == "user" \
                    and t.content.strip() and t.content.strip() in user_input:
                is_first = False
                continue
            is_first = False
            # #130: skip turns with stage directions / fake tool claims
            if getattr(t, 'metadata', None) and t.metadata.get('is_tool_claim'):
                continue
            # R4: skip sleep turns (zzzz, 我去午睡了, etc.) — 同 short_term.format_for_prompt 的过滤逻辑
            if getattr(t, 'metadata', None) and t.metadata.get('sleep'):
                continue
            # 修复：错误兜底文案（API 故障期的"抱歉，我暂时无法处理…"）不进
            # prompt 历史——保留在 DB/界面记录，但不让模型误以为发生过系统错误
            if getattr(t, 'metadata', None) and t.metadata.get('error_fallback'):
                continue
            if any(t.content.strip().startswith(p) for p in ['（调用', '(调用', '（前奏', '(前奏']):
                continue
            role = "assistant" if t.role == "assistant" else "user"
            turn_tokens = estimate_tokens(t.content)
            if running_total + turn_tokens > COMPRESS_THRESHOLD:
                overflow = True
                break
            running_total += turn_tokens
            history_messages.append({"role": role, "content": t.content})
        # #168: O(k) slice assignment instead of O(k²) insert(1, ...)
        messages[1:1] = reversed(history_messages)
        if overflow and agent.get_compressed_summary():
            messages.insert(1, {"role": "system", "content": f"[对话历史摘要] {agent.get_compressed_summary()}"})
        if user_input:
            msg_tokens = sum(estimate_tokens(m["content"][:500]) for m in messages if m["role"] != "system")
            if msg_tokens + estimate_tokens(user_input) > COMPRESS_THRESHOLD:
                agent.compress_context(messages)
            messages.append({"role": "user", "content": user_input})
        return messages


def track_failures(tracker, tool_result):
    """Record failures from a tool execution round."""
    for r in tool_result.records:
        if not r.success:
            tracker.failure_log.append({
                "name": r.name,
                "output": r.output[:200],
            })


# Patterns that attempt to override roles or inject instructions.
# L4-3: line-level stripping; a matched line is replaced with empty string.
_INJECTION_PATTERNS = [
    ("role_prefix", re.compile(r"^\s*(system|assistant|user)\s*[:：]", re.IGNORECASE)),
    ("ignore_previous", re.compile(r"ignore\s+(all\s+)?(previous|above)\s+(instructions?|prompts?)", re.IGNORECASE)),
    ("from_now_on", re.compile(r"from\s+now\s+on", re.IGNORECASE)),
    ("ignore_chinese", re.compile(r"忽略(之前|以上|所有).{0,4}(指令|提示|对话)")),
]


def _sanitize_input(text: str, max_length: int = MessageHandler.MAX_INPUT_LENGTH) -> str:
    """Remove common prompt injection patterns from user input. (#110)"""
    lines = text.split("\n")
    cleaned = []
    removed_names = []
    for line in lines:
        original = line
        matched = False
        for name, pattern in _INJECTION_PATTERNS:
            if pattern.search(line):
                matched = True
                removed_names.append(name)
                logger.warning(f"[msg] injection pattern stripped: {name}")
                break
        cleaned.append("" if matched else original)
    if removed_names:
        logger.warning(f"[msg] sanitized injection pattern(s): {removed_names}")
    result = "\n".join(cleaned).strip()
    # Limit input length to prevent token overflow attacks
    if len(result) > max_length:
        logger.warning(f"[msg] input truncated {len(result)} -> {max_length}")
        result = result[:max_length]
    return result
