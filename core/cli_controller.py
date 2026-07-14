"""CLI state machine: run loop + _on_* handlers + command processing.

Only used by main.py (CLI path). Web path (web/server.py) bypasses this entirely.
Two-phase architecture: Phase 1 (ToolAgent) runs in _on_perceive, results injected in _on_think."""

import logging
import random
import time

from core.dispatcher import parse_tool_calls, execute_tool_calls, format_tool_results, contains_fake_action
from core.context_manager import estimate_tokens, COMPRESS_THRESHOLD

logger = logging.getLogger(__name__)


class CliController:
    """CLI state machine handler. Operates on an Agent instance's state."""

    def __init__(self, agent):
        self._agent = agent  # Agent instance, used to access all shared state
        self._tool_agent = None  # lazy init
        self._inner_drive = None  # lazy init
        self._tool_records = ""  # Agent 2 results for current turn
        self._inner_drive_result = None  # Agent 1 result for current turn

    def _ensure_inner_drive(self):
        if self._inner_drive is None:
            from core.inner_drive import InnerDriveAgent
            a = self.a
            self._inner_drive = InnerDriveAgent(
                provider=a.provider, personality=a.personality,
                ltm=a.ltm, retriever=a.retriever, short_term=a.short_term,
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

    # ── Property shortcuts ──
    @property
    def a(self):
        return self._agent

    # ── Main run loop ──

    def run(self) -> None:
        from core.agent import AgentState
        a = self.a
        if a.ui:
            a.ui.start()
            a.ui.display_banner(a.personality.config.name)
        a.state = AgentState.BOOT
        self._on_boot()
        while a._running and a.state != AgentState.SHUTDOWN:
            try:
                handler = {
                    AgentState.IDLE: self._on_idle,
                    AgentState.PERCEIVE: self._on_perceive,
                    AgentState.THINK: self._on_think,
                    AgentState.ACT: self._on_act,
                    AgentState.REFLECT: self._on_reflect,
                }.get(a.state)
                if handler:
                    handler()
            except KeyboardInterrupt:
                a.state = AgentState.SHUTDOWN
            except Exception as e:
                logger.error(f"Error in state {a.state}: {e}", exc_info=True)
                if a.ui:
                    a.ui.display.print_error(str(e))
                a._reset_react()
                time.sleep(1)
                a.state = AgentState.IDLE
        self._on_shutdown()

    def _on_boot(self) -> None:
        from core.agent import AgentState
        a = self.a
        greeting = a.personality.config.first_run_greeting
        if not greeting:
            greeting = f"你好呀！我是{a.personality.config.name}，很高兴认识你~"
        if a.ui:
            a.ui.display.respond(greeting, prefix=a.personality.config.name)
        a.state = AgentState.IDLE

    def _on_idle(self) -> None:
        from core.agent import AgentState
        a = self.a
        if not a._prompt_shown:
            print("\033[33m用户输入: \033[0m", end="", flush=True)
            a._prompt_shown = True
        user_input = a.ui.reader.read_line() if a.ui else None
        if user_input is not None:
            a.current_input = user_input
            a.state = AgentState.PERCEIVE
            return
        idle_duration = time.time() - a.last_activity_time
        if idle_duration > a.config.proactive_min_idle:
            if random.random() < a._calculate_proactivity(idle_duration):
                a.current_input = None
                a.state = AgentState.THINK
                return
        time.sleep(0.1)

    def _on_perceive(self) -> None:
        from core.agent import AgentState
        a = self.a
        user_input = a.current_input or ""
        if user_input.startswith("/"):
            self._handle_command(user_input)
            a.current_input = None
            a.state = AgentState.IDLE if a._running else AgentState.SHUTDOWN
            return
        a.short_term.add_turn("user", user_input)
        a.current_memory_context = a.retriever.retrieve_for_query(user_input)
        a.ltm.repo.insert_turn_sync(a.turn_count, "user", user_input, str(a.personality.emotion.to_dict()))

        # Agent 1: Inner drive reasoning
        self._ensure_inner_drive()
        self._inner_drive_result = self._inner_drive.assess(user_input)
        self._tool_records = ""
        a.state = AgentState.THINK

    def _on_think(self) -> None:
        from core.agent import AgentState
        from prompts.system import build_system_prompt
        a = self.a
        is_proactive = a.current_input is None
        if a._react_messages is None:
            if is_proactive:
                a.current_memory_context = a.retriever.retrieve_for_query("")
                user_message = f"[主动开启对话] 主题方向：{a._pick_proactive_topic()}"
            else:
                user_message = f"用户输入：{a.current_input or ''}"
            # Agent 2: Multi-round tool execution (same pattern as message_handler)
            from core.tool_agent import ToolAttemptTracker
            drive_result = getattr(self, '_inner_drive_result', None)
            if drive_result and drive_result.needs_external_tools and not is_proactive:
                self._ensure_tool_agent()
                tracker = ToolAttemptTracker()
                max_rounds = 3
                all_tool_results = []
                round_num = 0
                try:
                    while round_num < max_rounds and drive_result.needs_external_tools:
                        round_num += 1
                        tracker.round_number = round_num
                        logger.info(f"[cli] agent2 round {round_num}/{max_rounds}")
                        request_text = (drive_result.tool_requests[0].description
                                       if drive_result.tool_requests else user_message)
                        # Use run_with_requests if multiple requests
                        if len(drive_result.tool_requests) > 1:
                            reqs = [r.description for r in drive_result.tool_requests]
                            logger.info(f"[cli] agent2 multi-request: {len(reqs)} tools")
                            tool_result = self._tool_agent.run_with_requests(reqs)
                        else:
                            tool_result = self._tool_agent.run_with_request(request_text)
                        tracker.total_attempts += 1
                        # In-round retries
                        while tracker.can_retry_in_round and not tool_result.any_success:
                            tracker.retry_count += 1
                            logger.info(f"[cli] agent2 in-round retry {tracker.retry_count}")
                            tool_result = self._tool_agent.run_with_request(request_text)
                            tracker.total_attempts += 1
                        if tool_result and tool_result.has_results:
                            all_tool_results.append(tool_result)
                        combined = ""
                        for r in all_tool_results:
                            combined += self._tool_agent.format_for_phase2(r) + "\n"
                        if tool_result and tool_result.any_success and round_num < max_rounds:
                            logger.info(f"[cli] agent2 review after round {round_num}")
                            drive_result = self._inner_drive.review(
                                user_message, combined,
                                round_num=round_num, max_rounds=max_rounds,
                            )
                        elif tool_result and not tool_result.any_success:
                            if tracker.can_start_new_round:
                                logger.info(f"[cli] agent2 re-decide after failures round={round_num}")
                                drive_result = self._inner_drive.re_decide(user_message, tracker.failure_log)
                            else:
                                logger.info("[cli] agent2 giving up after max retries")
                                break
                        else:
                            break
                    parts = [self._tool_agent.format_for_phase2(r) for r in all_tool_results]
                    merged = "\n".join(p for p in parts if p)
                    if merged:
                        self._tool_records = merged
                        logger.info(f"[cli] agent2 merged {len(all_tool_results)} tool result(s)")
                except Exception:
                    logger.exception("[cli] agent2 error, continuing with partial results")

            drive_summary = drive_result.summary if drive_result else ""
            sys_prompt = build_system_prompt(
                personality=a.personality.config, emotion=a.personality.emotion,
                memory_context=a.current_memory_context,
                conversation_history=a.short_term.format_for_prompt(max_tokens=1800),
                is_proactive=is_proactive, compressed_summary=a._context.compressed_summary,
                tools=a._tool_registry,
                consecutive_negative=a._consecutive_negative,
                inner_drive_summary=drive_summary,
                conversation_examples=a.config.conversation_examples,
            )
            messages = [{"role": "system", "content": sys_prompt}]
            a._context.reset_estimate(estimate_tokens(sys_prompt))
            for t in a.short_term.get_all_reversed():
                role = "assistant" if t.role == "assistant" else "user"
                msg_tokens = estimate_tokens(t.content)
                if a._context.estimated_tokens + msg_tokens > COMPRESS_THRESHOLD:
                    break
                messages.append({"role": role, "content": t.content})
                a._context.add_estimate(msg_tokens)
            messages = [messages[0]] + list(reversed(messages[1:]))
            # Inject tool results as USER message (LLM respects user messages >> system messages)
            if self._tool_records:
                messages.append({"role": "user", "content": self._tool_records})
            if not is_proactive:
                user_msg = {"role": "user", "content": user_message}
                if a._context.estimated_tokens + estimate_tokens(user_message) <= COMPRESS_THRESHOLD:
                    messages.append(user_msg)
                    a._context.add_estimate(estimate_tokens(user_message))
                else:
                    a._context.compress(messages)
            a._react_messages = messages
            a._react_iteration = 0
        else:
            messages = a._react_messages
        a._prompt_shown = False
        max_tok = a._max_tokens_for_emotion()
        if a._react_iteration > 0:
            if a.ui:
                a.ui.display.print_system(f"思考中... (第{a._react_iteration}轮)")
            try:
                full_response = a.provider.generate(messages, stream=False, max_tokens=384, source="cli_react")
            except ConnectionError as e:
                if a.ui:
                    a.ui.display.print_error(f"网络连接失败：{e}")
                a._reset_react()
                a.state = AgentState.REFLECT
                return
        else:
            if a.ui:
                a.ui.display.show_thinking()
            accumulated = []
            stream_done = False
            def on_token(tok: str) -> None:
                if tok and not stream_done:
                    if not accumulated and a.ui:
                        print("\r", end="", flush=True)
                        print(f"\033[1;36m{a.personality.config.name}:\033[0m ", end="", flush=True)
                    accumulated.append(tok)
                    if a.ui:
                        print(tok, end="", flush=True)
            try:
                full_response = a.provider.generate(messages, stream=True, on_token=on_token, max_tokens=max_tok, source="cli_react")
            except ConnectionError as e:
                if a.ui:
                    a.ui.display.print_error(f"网络连接失败：{e}")
                a._reset_react()
                a.state = AgentState.REFLECT
                return
            stream_done = True
            if a.ui:
                print()
        cleaned_text, tool_calls = parse_tool_calls(full_response)
        a.current_response = cleaned_text
        a._tool_calls_pending = tool_calls
        a._react_iteration += 1
        if a._react_messages is not None:
            a._react_messages.append({"role": "assistant", "content": full_response})
        a.state = AgentState.ACT

    def _on_act(self) -> None:
        from core.agent import AgentState
        a = self.a
        tool_calls = getattr(a, '_tool_calls_pending', []) or []
        if tool_calls:
            if a._react_iteration > a._max_tool_iterations:
                if a.ui:
                    a.ui.display.print_system("工具调用次数已达上限")
                self._finish_react_response()
                return
            if a.ui:
                a.ui.display.print_system(f"执行 {len(tool_calls)} 个工具...")
            # Phase 2: use filtered registry if Phase 1 already ran external tools
            active_registry = a._tool_registry
            if self._tool_records:
                active_registry = self._make_internal_registry()
            results = execute_tool_calls(active_registry, tool_calls)
            result_text = format_tool_results(results)
            if a._react_messages is not None:
                a._react_messages.append({"role": "user", "content": result_text})
            if all(not r["success"] for r in results) and contains_fake_action(a.current_response):
                a._react_messages.append({"role": "user", "content": "你刚才说自己已经执行了操作，但没有成功调用任何工具。如果需要执行操作，请使用 <tool_call> 调用对应的工具。如果不需要工具，直接回复用户即可。"})
            a.state = AgentState.THINK
            return
        self._finish_react_response()

    def _finish_react_response(self) -> None:
        from core.agent import AgentState
        a = self.a
        if a.current_response:
            if a._react_iteration > 1 and a.ui:
                a.ui.display.respond(a.current_response, prefix=a.personality.config.name)
            a.short_term.add_turn("assistant", a.current_response)
            a.ltm.repo.insert_turn_sync(a.turn_count, "assistant", a.current_response, str(a.personality.emotion.to_dict()))
            a.turn_count += 1
            a.last_activity_time = time.time()
        a._reset_react()
        self._tool_records = ""
        self._inner_drive_result = None
        a.state = AgentState.REFLECT

    def _on_reflect(self) -> None:
        from core.agent import AgentState
        a = self.a
        ei = abs(a.personality.emotion.valence)
        idle = time.time() - a.last_activity_time
        if a.consolidator.should_consolidate(a.turn_count, ei, idle, a.config):
            a.consolidator.consolidate(a.short_term, a.personality,
                                        max_facts=a.config.max_facts,
                                        max_experiences=a.config.max_experiences,
                                        max_reflections=a.config.max_reflections)
        for t in list(a.short_term.get_all())[-2:]:
            a.consolidator.add_pending(t)
        if a.turn_count % 10 == 0:
            a.personality.save(a.config.personality_file)
        a.current_response = ""
        a.state = AgentState.IDLE

    def _on_shutdown(self) -> None:
        a = self.a
        a.consolidator.consolidate(a.short_term, a.personality,
                                    max_facts=a.config.max_facts,
                                    max_experiences=a.config.max_experiences,
                                    max_reflections=a.config.max_reflections)
        a.personality.save(a.config.personality_file)
        if a.ui:
            a.ui.stop()
        print(f"\n\033[1;36m{a.personality.config.name} 记下了你们的对话。下次见~\033[0m")

    def _handle_command(self, cmd: str) -> None:
        a = self.a
        if cmd in ("/exit", "/quit"):
            a._running = False
        elif cmd == "/save":
            a.consolidator.consolidate(a.short_term, a.personality,
                                        max_facts=a.config.max_facts,
                                        max_experiences=a.config.max_experiences,
                                        max_reflections=a.config.max_reflections)
            a.personality.save(a.config.personality_file)
            if a.ui:
                a.ui.display.print_system("记忆已保存")
        elif cmd == "/mood" and a.ui:
            e = a.personality.emotion
            a.ui.display.print_mood(f"{e.dominant_emotion} (v={e.valence:.2f} a={e.arousal:.2f})")
        elif cmd == "/status" and a.ui:
            rel = a.ltm.get_relationship()
            a.ui.display.print_system(f"轮次: {a.turn_count} | 事实: {len(a.ltm.get_all_active_facts())}")
            for k, v in rel.items():
                a.ui.display.print_system(f"  {k}: {v:.2f}")
            # #132: show relationship trend from snapshots
            history = a.ltm.get_relationship_history(days=7)
            if history:
                by_dim = {}
                for h in history:
                    by_dim.setdefault(h["dimension"], []).append(h["value"])
                for dim, values in by_dim.items():
                    if len(values) >= 2:
                        delta = values[-1] - values[0]
                        arrow = "↑" if delta > 0.01 else "↓" if delta < -0.01 else "→"
                        a.ui.display.print_system(f"  {dim} 趋势(7d): {values[0]:.2f}→{values[-1]:.2f} {arrow}")
        elif cmd == "/forget":
            a.short_term.clear()
            if a.ui:
                a.ui.display.print_system("短期记忆已清除")
        elif cmd == "/help" and a.ui:
            a.ui.display_help()
        elif a.ui:
            a.ui.display.print_system(f"未知命令: {cmd}")
