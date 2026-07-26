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
from core.cognitive_state import render_memory_light
from core.context_manager import estimate_tokens
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
        # #1: error_message 不再混入 records_text，由调用方以 agent2_error 参数
        # 传入 _run_agent3，作为系统指令附加到 system prompt。
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
        self._prompt_cache = PromptCache()
        # God Object 拆分（2026-07-22）：懒加载装配迁至 core/agent_wiring.py，
        # 内部实例经下方只读 property 暴露（_inner_drive/_tool_agent/_memory_agent）
        from core.agent_wiring import AgentWiring
        self._wiring = AgentWiring(agent, self._prompt_cache)
        self._state = MessageHandlerState.IDLE
        self._agent2_total_timeout = float(getattr(
            agent.config, "agent2_total_timeout_seconds", self.AGENT2_TOTAL_TIMEOUT))
        self._last_proactive_care = None  # L4-6a: pending care outcome

    @property
    def a(self):
        return self._agent

    @property
    def _inner_drive(self):
        return self._wiring._inner_drive

    @_inner_drive.setter
    def _inner_drive(self, value):
        self._wiring._inner_drive = value

    @property
    def _tool_agent(self):
        return self._wiring._tool_agent

    @_tool_agent.setter
    def _tool_agent(self, value):
        self._wiring._tool_agent = value

    @property
    def _memory_agent(self):
        return self._wiring._memory_agent

    @_memory_agent.setter
    def _memory_agent(self, value):
        self._wiring._memory_agent = value

    @property
    def current_state(self) -> MessageHandlerState:
        return self._state

    # CLI-UI: 阶段状态提示（Frontend.on_status），仅终端前端使用
    _STATUS_HINTS = {
        "ASSESSING": "她在想…",
        "EXECUTING_TOOLS": "她在翻工具箱…",
        "GENERATING_RESPONSE": "她在写回复…",
    }

    def _transition(self, state: MessageHandlerState) -> None:
        if self._state != state:
            logger.debug(f"[msg] state: {self._state.name} -> {state.name}")
            self._state = state
            cb = getattr(self, "_status_cb", None)
            if cb is not None:
                hint = self._STATUS_HINTS.get(state.name)
                if hint:
                    try:
                        cb(hint)
                    except Exception:
                        pass  # 状态提示绝不影响主流程

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
        # God Object 拆分（2026-07-22）：实现已迁至 core/agent_wiring.py
        self._wiring.ensure_inner_drive()

    def _ensure_memory_agent(self):
        # God Object 拆分（2026-07-22）：实现已迁至 core/agent_wiring.py
        return self._wiring.ensure_memory_agent()

    def ensure_inner_drive(self):
        """Ensure inner drive is initialized and return it."""
        self._ensure_inner_drive()
        return self._inner_drive

    def _match_active_care(self, topic: str, reasoning: str) -> dict | None:
        # God Object 拆分（2026-07-22）：实现已迁至 core/proactive_outcome.py
        from core.proactivity import match_active_care
        return match_active_care(self.a, topic, reasoning)

    def _evaluate_proactive_outcome(self, user_input: str) -> None:
        # God Object 拆分（2026-07-22）：实现已迁至 core/proactive_outcome.py
        if self._last_proactive_care is None:
            return
        from core.proactivity import evaluate_proactive_outcome
        evaluate_proactive_outcome(self.a, self._last_proactive_care, user_input)
        self._last_proactive_care = None

    def _ensure_tool_agent(self):
        # God Object 拆分（2026-07-22）：实现已迁至 core/agent_wiring.py
        self._wiring.ensure_tool_agent()

    def _make_internal_registry(self, include_history_search: bool = False):
        # God Object 拆分（2026-07-22）：实现已迁至 core/agent_wiring.py；
        # include_history_search 语义不变（仅 Agent 3 带 history_search）
        return self._wiring.make_internal_registry(include_history_search)

    def _make_external_registry(self):
        # God Object 拆分（2026-07-22）：实现已迁至 core/agent_wiring.py
        return self._wiring.make_external_registry()

    def handle_message(self, user_input: str, on_token=None, on_status=None) -> str:
        from prompts.system import build_system_prompt
        a = self.a

        # #256: guard against empty input
        if not user_input or not user_input.strip():
            return ""

        # CLI-UI: 阶段状态回调（本轮有效，返回前清除，避免泄漏到主动消息路径）
        self._status_cb = on_status

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
            self._status_cb = None
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

        # WS-25: Agent 3 消费 drive_result.context_summary（含挂念浮现等后处理）。
        # CognitiveState 装配后不再修改；Agent 3 在 _run_agent3 内按需组合
        # state.memory_summary / state.memory_answer / drive_result.context_summary。
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
            self._status_cb = None
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
            agent2_error=exec_result.error_message,
        )
        logger.debug(
            f"[state] mem_chars={len(state.memory_summary)} "
            f"confidence={state.memory_confidence} care={len(state.care_surface)} "
            f"pending={state.pending}"
        )
        self._transition(MessageHandlerState.DONE)
        self._status_cb = None
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
        self._status_cb = None  # CLI-UI: 主动路径不发阶段提示

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
            tools=self._make_internal_registry(include_history_search=True),
            rule_tools=a.tool_registry,  # #301: intent 选项数据源
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
                            tool_registry=self._make_internal_registry(include_history_search=True),
                            skip_post_process=True)

    def handle_explore(self, intent=None) -> str | None:
        from prompts.system import build_system_prompt
        a = self.a
        cfg = a.config
        self._status_cb = None  # CLI-UI: 主动路径不发阶段提示

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
            tools=self._make_internal_registry(include_history_search=True),
            rule_tools=a.tool_registry,  # #301: intent 选项数据源
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
                              tool_registry=self._make_internal_registry(include_history_search=True),
                              skip_post_process=True)
        if result and len(result.strip()) > 30 and not result.startswith("搜索"):
            logger.info(f"[explore] shared: {len(result)} chars")
            return result
        logger.debug(f"[explore] silent: result={result[:80] if result else 'None'}")
        return None

    def _run_agent3(self, user_input: str, drive_result, tool_result,
                    on_token=None, tool_records: str = "", final_response: bool = False,
                    state: CognitiveState | None = None,
                    agent2_error: str = "") -> str:
        """Run Agent 3: emotional expression with inner drive + tool results.

        WS-12: 优先从 CognitiveState 读取记忆与决策摘要，保持与旧路径数据一致。

        agent2_error: 系统级错误（如 Agent 2 超时/异常），作为系统指令附加到
        system prompt，而不是混入 user message 的 tool_records。
        """
        from prompts.system import build_system_prompt
        a = self.a
        cfg = a.config

        # WS-13: 记忆摘要优先从统一状态读取；CognitiveState 装配后不再修改。
        # Agent 3 的轻量视图与 Agent 1 共用同一 MemoryAnswer，避免二次检索。
        memory_summary = ""
        if state is not None:
            memory_summary = render_memory_light(
                getattr(state, "memory_answer", None),
                fallback=state.memory_summary,
            )
        if not memory_summary and drive_result and getattr(drive_result, "context_summary", ""):
            memory_summary = drive_result.context_summary

        # Still keep the memory context object around for downstream code.
        # 若已有 memory_summary，build_system_prompt 的 SLOW 分支不会使用 mem_ctx，
        # 因此无需再 retrieve_for_query；仅在无摘要时才检索兜底。
        if memory_summary:
            mem_ctx = a.current_memory_context
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
            tools=self._make_internal_registry(include_history_search=True),
            rule_tools=a.tool_registry,  # #301: intent 选项数据源
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
        # #1: Agent 2 系统级错误作为系统指令附加，不要混进 tool_records 的 user message
        if agent2_error:
            sys_prompt = f"{sys_prompt}\n\n[系统状态] {agent2_error}"
        self._log_prompt_cache_stats(tag="agent3")
        messages = self._build_messages(sys_prompt, user_input=f"用户输入：{user_input}")
        # Inject tool results as USER message (LLM respects user messages >> system messages)
        if tool_records:
            messages.insert(-1, {"role": "user", "content": tool_records})
        # H-01: 无论是否有 tool_records，Agent 3 的 registry 都固定为内部工具
        # （recall/remember/history_search）；#301 起 prompt 侧 tools 也传同一
        # 内部 registry，声明与执行真正一致，不再回退到全量 registry
        return a._react_loop(messages, on_token, add_to_history=True,
                            tool_registry=self._make_internal_registry(include_history_search=True))

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
                agent2_error=exec_result.error_message,
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
        # God Object 拆分（2026-07-22）：实现已迁至 core/message_builder.py，
        # 这里保留薄委托维持既有调用方/测试兼容
        from core.message_builder import build_messages
        return build_messages(self._agent, sys_prompt, user_input)


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
