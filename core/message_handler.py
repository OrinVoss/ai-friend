"""Three-layer Agent orchestration.

Agent 1 (InnerDrive) -- assess intent, decide if external tools needed
Agent 2 (ToolAgent)  -- execute external tools with retry
Agent 3 (Roleplay)   -- personality-driven final response
"""

import logging
import random
import time

from core.context_manager import estimate_tokens, COMPRESS_THRESHOLD

logger = logging.getLogger(__name__)


class MessageHandler:
    """Orchestrates the three-Agent pipeline."""

    def __init__(self, agent):
        self._agent = agent
        self._tool_agent = None  # lazy init
        self._inner_drive = None  # lazy init

    @property
    def a(self):
        return self._agent

    def _ensure_inner_drive(self):
        if self._inner_drive is None:
            from core.inner_drive import InnerDriveAgent
            a = self.a
            self._inner_drive = InnerDriveAgent(
                provider=a.provider,
                personality=a.personality,
                ltm=a.ltm,
                retriever=a.retriever,
                short_term=a.short_term,
                tool_registry=a._tool_registry,
            )

    def _ensure_tool_agent(self):
        if self._tool_agent is None:
            from core.tool_agent import ToolAgent
            self._tool_agent = ToolAgent(
                provider=self.a.provider,
                tool_registry=self.a._tool_registry,
            )

    def _make_internal_registry(self):
        from tools.traits import ToolRegistry
        r = ToolRegistry()
        for name in ("recall", "remember"):
            tool = self.a._tool_registry.get(name)
            if tool:
                r.register(tool)
        return r

    def handle_message(self, user_input: str, on_token=None) -> str:
        from prompts.system import build_system_prompt
        a = self.a

        if a._sleeping:
            a.last_activity_time = time.time()
            return random.choice(["zzz...ZZZ...💤", "Zzzz...[翻身]", "zzzz...（小声梦话）", "Zzz...💤"])

        logger.info(f"[msg] turn={a.turn_count} len={len(user_input)}")
        a.current_input = user_input
        a.last_activity_time = time.time()
        a.short_term.add_turn("user", user_input)

        # ── Agent 1: Inner Drive ──
        self._ensure_inner_drive()
        drive_result = self._inner_drive.assess(user_input)

        if not drive_result.needs_external_tools:
            # No external tools needed → straight to Agent 3
            logger.info(f"[msg] agent1: no external tools needed")
            return self._run_agent3(user_input, drive_result, tool_result=None,
                                   on_token=on_token)

        # ── Agent 2: Multi-round tool execution ──
        # Agent 1 can call Agent 2 multiple times (e.g. search → fetch → more search)
        # Each round: Agent 1 requests → Agent 2 executes (with retries) → Agent 1 reviews
        self._ensure_tool_agent()
        from core.tool_agent import ToolAttemptTracker

        MAX_AGENT2_ROUNDS = 3
        all_tool_results = []  # accumulate results from all rounds
        tool_records = ""
        round_num = 0

        while round_num < MAX_AGENT2_ROUNDS and drive_result.needs_external_tools:
            round_num += 1
            request_text = drive_result.tool_requests[0].description if drive_result.tool_requests else user_input
            logger.info(f"[msg] agent2: round {round_num}/{MAX_AGENT2_ROUNDS}, request={request_text[:80]}")

            # Execute with retry
            tracker = ToolAttemptTracker()
            tool_result = self._tool_agent.run_with_request(request_text)
            tracker.total_attempts += 1
            track_failures(tracker, tool_result)

            # In-round retries on failure
            while tracker.can_retry_in_round and not tool_result.any_success:
                tracker.retry_count += 1
                logger.info(f"[msg] agent2: retry {tracker.retry_count}/3")
                tool_result = self._tool_agent.run_with_request(request_text)
                tracker.total_attempts += 1
                track_failures(tracker, tool_result)

            if tool_result and tool_result.has_results:
                all_tool_results.append(tool_result)

            # Build accumulated results for Agent 1 review
            combined_records = ""
            for i, r in enumerate(all_tool_results):
                combined_records += self._tool_agent.format_for_phase2(r) + "\n"

            if tool_result and tool_result.any_success and round_num < MAX_AGENT2_ROUNDS:
                # Success -- let Agent 1 review and possibly request more
                drive_result = self._inner_drive.review(
                    user_input, combined_records,
                    round_num=round_num, max_rounds=MAX_AGENT2_ROUNDS,
                )
                if drive_result.needs_external_tools:
                    logger.info(f"[msg] agent1: needs more tools after round {round_num}")
            elif tool_result and not tool_result.any_success:
                # All retries failed -- Agent 1 re-decide
                if tracker.can_start_new_round:
                    logger.info(f"[msg] agent1: re-decide after failures")
                    drive_result = self._inner_drive.re_decide(user_input, tracker.failure_log)
                else:
                    break
            else:
                break

        # Build final combined tool records for Agent 3
        parts = []
        for r in all_tool_results:
            part = self._tool_agent.format_for_phase2(r)
            if part:
                parts.append(part)
        tool_records = "\n".join(parts)
        if tool_records:
            total = sum(r.total_calls for r in all_tool_results)
            ok = sum(r.success_count for r in all_tool_results)
            logger.info(f"[msg] agent2: {len(all_tool_results)} rounds, {total} calls, {ok} ok")

        # ── Agent 3: Emotional expression ──
        return self._run_agent3(user_input, drive_result, tool_result, on_token=on_token)

    def handle_proactive(self, on_token=None) -> str:
        from prompts.system import build_system_prompt
        a = self.a
        mem_ctx = a.retriever.retrieve_for_query("")
        topic = a._pick_proactive_topic()
        conv_hist = a.short_term.format_for_prompt(max_chars=3000)
        sys_prompt = build_system_prompt(
            personality=a.personality.config, emotion=a.personality.emotion,
            memory_context=mem_ctx, conversation_history=conv_hist,
            compressed_summary=a._context.compressed_summary,
            tools=a._tool_registry,
            is_proactive=True,
            consecutive_negative=a._consecutive_negative,
        )
        messages = self._build_messages(sys_prompt, user_input=f"[主动开启对话] 主题方向：{topic}")
        logger.info(f"[proactive] chat: topic={topic}")
        return a._react_loop(messages, on_token, add_to_history=False)

    def handle_explore(self) -> str | None:
        from prompts.system import build_system_prompt
        a = self.a
        mem_ctx = a.retriever.retrieve_for_query("")
        topic = a._pick_proactive_topic()
        conv_hist = a.short_term.format_for_prompt(max_chars=3000)

        self._ensure_tool_agent()
        explore_prompt = f"[自由探索] 可以搜搜关于{topic}的内容。用 web_search 和 web_fetch。"
        tool_result = self._tool_agent.run(explore_prompt)
        tool_records = self._tool_agent.format_for_phase2(tool_result)

        sys_prompt = build_system_prompt(
            personality=a.personality.config, emotion=a.personality.emotion,
            memory_context=mem_ctx, conversation_history=conv_hist,
            compressed_summary=a._context.compressed_summary,
            tools=a._tool_registry,
            is_proactive=True,
            consecutive_negative=a._consecutive_negative,
            explore_mode=True,
            tool_records=tool_records,
        )
        messages = self._build_messages(sys_prompt, user_input=None)
        interests = getattr(a.personality.config, 'interests', [])
        if interests:
            picked = random.sample(interests, min(2, len(interests)))
            messages.append({
                "role": "user",
                "content": f"[自由探索] 系统已获取了一些内容。关于{'/'.join(picked)}，有特别的就分享。"
            })
        logger.info(f"[explore] start: topic={topic}")
        phase2_registry = self._make_internal_registry() if tool_records else None
        result = a._react_loop(messages, on_token=None, add_to_history=False,
                              tool_registry=phase2_registry)
        if result and len(result.strip()) > 30 and not result.startswith("搜索"):
            logger.info(f"[explore] shared: {len(result)} chars")
            return result
        logger.debug(f"[explore] silent: result={result[:80] if result else 'None'}")
        return None

    def _run_agent3(self, user_input: str, drive_result, tool_result,
                    on_token=None) -> str:
        """Run Agent 3: emotional expression with inner drive + tool results."""
        from prompts.system import build_system_prompt
        a = self.a

        mem_ctx = a.retriever.retrieve_for_query(user_input)
        a.current_memory_context = mem_ctx
        a.ltm.repo.insert_turn(a.turn_count, "user", user_input,
                               str(a.personality.emotion.to_dict()))

        conv_hist = a.short_term.format_for_prompt(max_chars=3000)
        tool_records = self._tool_agent.format_for_phase2(tool_result) if tool_result else ""

        sys_prompt = build_system_prompt(
            personality=a.personality.config, emotion=a.personality.emotion,
            memory_context=mem_ctx, conversation_history=conv_hist,
            compressed_summary=a._context.compressed_summary,
            tools=a._tool_registry,
            consecutive_negative=a._consecutive_negative,
            tool_call_history=a._tool_call_history,
            tool_records=tool_records,
            inner_drive_summary=drive_result.summary if drive_result else "",
        )
        messages = self._build_messages(sys_prompt, user_input=f"用户输入：{user_input}")
        phase2_registry = self._make_internal_registry() if tool_records else None
        return a._react_loop(messages, on_token, add_to_history=True,
                            tool_registry=phase2_registry)

    def _build_messages(self, sys_prompt: str, user_input: str | None) -> list[dict]:
        a = self.a
        messages = [{"role": "system", "content": sys_prompt}]
        overflow = False
        for t in a.short_term.get_all_reversed():
            role = "assistant" if t.role == "assistant" else "user"
            if estimate_tokens(" ".join(m["content"][:200] for m in messages[-5:] if m["role"] != "system")) + estimate_tokens(t.content) > COMPRESS_THRESHOLD:
                overflow = True
                break
            messages.insert(1, {"role": role, "content": t.content})
        if overflow and a._context.compressed_summary:
            messages.insert(1, {"role": "system", "content": f"[对话历史摘要] {a._context.compressed_summary}"})
        if user_input:
            msg_tokens = sum(estimate_tokens(m["content"][:500]) for m in messages if m["role"] != "system")
            if msg_tokens + estimate_tokens(user_input) > COMPRESS_THRESHOLD:
                a._context.compress(messages)
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
