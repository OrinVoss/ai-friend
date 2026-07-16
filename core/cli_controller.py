"""CLI controller: input loop + command layer over the unified ConversationEngine.

Only used by main.py (CLI path). The pipeline itself lives in
MessageHandler/ConversationEngine — this file is just the terminal
frontend: read input, dispatch commands, render events (unified-pipeline
P1-P3; the legacy inline ReAct state machine was removed in P3).
"""

import logging
import time

from core.conversation_engine import ConversationEngine, Frontend

logger = logging.getLogger(__name__)


class CliController:
    """CLI input loop over the shared ConversationEngine."""

    def __init__(self, agent):
        self._agent = agent  # Agent instance, used to access all shared state

    @property
    def a(self):
        return self._agent

    # ── Main run loop ──

    def run(self) -> None:
        """CLI over the unified ConversationEngine — the same pipeline as Web.

        A RuntimeDriver runs in a daemon thread, so the CLI also sleeps,
        dreams and reaches out proactively — same rhythm as the Web.
        """
        from core.agent import AgentState
        from core.runtime_driver import RuntimeDriver
        a = self.a
        if a.ui:
            a.ui.start()
            a.ui.display_banner(a.personality.config.name)
        a.state = AgentState.BOOT
        self._on_boot()
        engine = ConversationEngine(a)
        frontend = _CliFrontend(a.ui, a.personality.config.name)
        driver = RuntimeDriver(engine, frontend)
        driver.start_in_thread()
        try:
            while a._running:
                if a.ui:
                    print("\033[33m用户输入: \033[0m", end="", flush=True)
                user_input = a.ui.reader.read_line() if a.ui else None
                if user_input is None:
                    time.sleep(0.1)
                    continue
                if user_input.startswith("/"):
                    self._handle_command(user_input)
                    continue
                try:
                    engine.handle_message(user_input, frontend)
                except Exception as e:
                    logger.error(f"[cli] engine error: {e}", exc_info=True)
                    if a.ui:
                        a.ui.display.print_error(str(e))
                if a.turn_count > 0 and a.turn_count % 10 == 0:
                    a.personality.save(a.config.personality_file)
        except KeyboardInterrupt:
            pass
        finally:
            driver.stop()
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


class _CliFrontend(Frontend):
    """Terminal frontend: typewriter streaming with a lazy name prefix.

    Only the first generation pass streams (tool rounds don't), so a reply
    that never streamed is rendered whole via display.respond on done.
    """

    def __init__(self, ui, name: str):
        self._ui = ui
        self._name = name
        self._streamed = False

    def on_token(self, token: str) -> None:
        if not token:
            return
        if not self._streamed and self._ui:
            print("\r", end="", flush=True)
            print(f"\033[1;36m{self._name}:\033[0m ", end="", flush=True)
        self._streamed = True
        if self._ui:
            print(token, end="", flush=True)

    def on_message_done(self, text: str) -> None:
        if self._streamed:
            print()
        elif self._ui and text:
            self._ui.display.respond(text, prefix=self._name)
        self._streamed = False

    def on_sleep_reply(self, text: str) -> None:
        if self._ui:
            self._ui.display.respond(text, prefix=self._name)

    def on_proactive(self, text: str) -> None:
        if self._ui:
            print()  # break the input prompt line before the proactive bubble
            self._ui.display.respond(text, prefix=self._name)

    def on_error(self, error: str) -> None:
        if self._ui:
            self._ui.display.print_error(error)
