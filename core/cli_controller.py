"""CLI controller: input loop + command layer over the unified ConversationEngine.

Only used by main.py (CLI path). The pipeline itself lives in
MessageHandler/ConversationEngine — this file is just the terminal
frontend: read input, dispatch commands, render events (unified-pipeline
P1-P3; the legacy inline ReAct state machine was removed in P3).
"""

import logging

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
        TUI-1（2026-08-18）：真控制台默认走全屏 TUI（ui/tui.py：滚动聊天区
        + 固定输入框 + 状态栏 + F2 日志面板；config.cli_fullscreen_ui 可关）；
        管道/CI 等无控制台环境回退行式 prompt 界面（prompt_toolkit 输入行）。
        """
        from core.agent import AgentState
        from core.runtime_driver import RuntimeDriver
        a = self.a
        if a.ui:
            a.ui.status_fn = self._status_snapshot
            a.ui.start()
        a.state = AgentState.BOOT
        engine = ConversationEngine(a)
        # Restore turn counter so restarts don't reset it (#RS-001 parity
        # with Web; also keeps conversation_turns.turn_number monotonic).
        try:
            from core.async_utils import run_async
            a.turn_count = run_async(a.ltm.repo.get_max_turn_number())
        except Exception as e:
            logger.warning(f"[cli] restore turn_count failed: {e}")

        from core.logging_setup import use_prompt_toolkit_console
        tui_app = None
        if (a.ui is not None and a.ui.session is not None
                and getattr(a.config, "cli_fullscreen_ui", True)):
            try:
                from ui.tui import TuiChatApp
                tui_app = TuiChatApp(self, engine, a.ui)
            except Exception:
                logger.exception("[cli] TUI 初始化失败，回退行式界面")
                tui_app = None

        if tui_app is not None:
            frontend = tui_app.frontend
            tui_app.preload()
            self._on_boot(sink=tui_app.post_ai)
            # 控制台 WARNING+ 日志进 F2 面板（完整日志始终在 logs/ 文件）
            use_prompt_toolkit_console(
                getattr(a.config, "console_log_level", "WARNING"),
                sink=tui_app.post_log)
        else:
            frontend = _CliFrontend(a.ui, a.personality.config.name)
            if a.ui:
                a.ui.display_banner(a.personality.config.name)
                if a.ui.session is not None:
                    # CLI-UI: 行式界面下 WARNING+ 日志经 print_formatted_text
                    # 打到输入行上方，不与对话刷屏混杂
                    use_prompt_toolkit_console(
                        getattr(a.config, "console_log_level", "WARNING"))
            self._on_boot()

        driver = RuntimeDriver(engine, frontend)
        driver.start_in_thread()
        try:
            if tui_app is not None:
                tui_app.run_blocking()
            else:
                while a._running:
                    try:
                        user_input = a.ui.read_input() if a.ui else None
                    except (EOFError, KeyboardInterrupt):
                        break
                    if user_input is None or not user_input.strip():
                        continue
                    user_input = user_input.strip()
                    if user_input.startswith("/"):
                        self._handle_command(user_input)
                        continue
                    try:
                        engine.handle_message(user_input, frontend)
                    except Exception as e:
                        logger.error(f"[cli] engine error: {e}", exc_info=True)
                        if a.ui:
                            a.ui.display.print_error(str(e))
                    if a.ui:
                        a.ui.invalidate()  # 情绪/轮次已变，刷新 bottom_toolbar
                    if a.turn_count > 0 and a.turn_count % 10 == 0:
                        a.personality.save(a.config.personality_file)
        finally:
            driver.stop()
        self._on_shutdown()

    def _status_snapshot(self) -> dict:
        """bottom_toolbar 数据源：情绪 / 轮次 / 是否睡着。"""
        a = self.a
        e = a.personality.emotion
        return {
            "emotion": e.dominant_emotion,
            "turn": a.turn_count,
            "sleeping": bool(getattr(a, "_sleeping", False)),
        }

    def _on_boot(self, sink=None) -> None:
        from core.agent import AgentState
        a = self.a
        greeting = a.personality.config.first_run_greeting
        if not greeting:
            greeting = f"你好呀！我是{a.personality.config.name}，很高兴认识你~"
        if sink is not None:
            sink(greeting)  # TUI-1：问候语进聊天区
        elif a.ui:
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

    def _handle_command(self, cmd: str, sink=None) -> None:
        """斜杠命令。sink 提供时（TUI-1）以 ANSI 字符串输出到 sink，否则直接打印。"""
        from ui.display import DisplayEngine, panel, rel_bar
        a = self.a

        def emit(text: str) -> None:
            if sink is not None:
                sink(text)
            else:
                print(text)

        if cmd in ("/exit", "/quit"):
            a._running = False
        elif cmd == "/save":
            a.consolidator.consolidate(a.short_term, a.personality,
                                        max_facts=a.config.max_facts,
                                        max_experiences=a.config.max_experiences,
                                        max_reflections=a.config.max_reflections)
            a.personality.save(a.config.personality_file)
            emit(DisplayEngine.format_system("记忆已保存"))
        elif cmd == "/mood" and a.ui:
            e = a.personality.emotion
            emit(DisplayEngine.format_mood_line(
                e.dominant_emotion, e.valence, e.arousal))
        elif cmd == "/status" and a.ui:
            rel = a.ltm.get_relationship()
            rows = [(f"轮次: {a.turn_count} │ 事实: {len(a.ltm.get_all_active_facts())}", "")]
            for k, v in rel.items():
                rows.append((f"{k:<12} {rel_bar(v)} {v:.2f}", ""))
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
                        rows.append((f"{dim} 趋势(7d): {values[0]:.2f}→{values[-1]:.2f} {arrow}",
                                     "\033[2m"))
            emit(panel("状态", rows))
        elif cmd == "/forget":
            a.short_term.clear()
            emit(DisplayEngine.format_system("短期记忆已清除"))
        elif cmd == "/help" and a.ui:
            from ui.cli import SLASH_HELP
            emit(DisplayEngine.format_help(SLASH_HELP))
        elif a.ui:
            emit(DisplayEngine.format_system(f"未知命令: {cmd}"))


class _StreamTagFilter:
    """M-15: 流式标签过滤器——迭代 0 逐 token 流式期间，<think>/<tool_call>
    块会原样泄到终端（剥离发生在完整响应返回后）。标签可能跨 chunk
    （"<tool" + "_call>"），所以缓冲未确定内容：确认是普通文本才放行，
    识别到完整开标签后进入抑制状态直到对应闭标签。"""

    _TAGS = {"<think>": "</think>", "<tool_call>": "</tool_call>"}

    def __init__(self):
        self._buf = ""
        self._close = None  # 抑制状态下等待的闭标签；None 表示正常状态

    def feed(self, token: str) -> str:
        """喂入一个 chunk，返回当前可安全输出的文本（标签内容被抑制）。"""
        self._buf += token
        out = []
        while self._buf:
            if self._close is not None:
                idx = self._buf.find(self._close)
                if idx >= 0:
                    # 丢弃到闭标签结尾，回到正常状态
                    self._buf = self._buf[idx + len(self._close):]
                    self._close = None
                    continue
                # 闭标签未到：只保留可能是闭标签前缀的尾巴，其余抑制内容丢弃
                keep = self._partial_suffix_len(self._buf, self._close)
                self._buf = self._buf[len(self._buf) - keep:] if keep else ""
                break
            lt = self._buf.find("<")
            if lt < 0:
                out.append(self._buf)
                self._buf = ""
                break
            out.append(self._buf[:lt])
            rest = self._buf[lt:]
            matched = None
            pending = False
            for tag, close in self._TAGS.items():
                if rest.startswith(tag):
                    matched = (tag, close)
                    break
                if tag.startswith(rest):
                    pending = True  # 可能是跨 chunk 的标签前缀，等后续再判定
            if matched is not None:
                tag, self._close = matched
                self._buf = rest[len(tag):]
                continue
            if pending:
                self._buf = rest
                break
            # 确定不是目标标签：'<' 本身是普通字符
            out.append("<")
            self._buf = rest[1:]
        return "".join(out)

    def flush(self) -> str:
        """流结束：返回残余缓冲中的非标签内容；抑制状态下的内容（标签未闭合）丢弃。"""
        text = "" if self._close is not None else self._buf
        self._buf = ""
        self._close = None
        return text

    @staticmethod
    def _partial_suffix_len(s: str, tag: str) -> int:
        """s 的结尾中最长能作为 tag 前缀的长度（用于跨 chunk 闭标签）。"""
        for n in range(min(len(s), len(tag) - 1), 0, -1):
            if tag.startswith(s[-n:]):
                return n
        return 0


class _CliFrontend(Frontend):
    """Terminal frontend: typewriter streaming with a lazy name prefix.

    Only the first generation pass streams (tool rounds don't), so a reply
    that never streamed is rendered whole via display.respond on done.
    """

    def __init__(self, ui, name: str):
        self._ui = ui
        self._name = name
        self._streamed = False
        self._filter = _StreamTagFilter()  # M-15: 抑制流式期间的 XML 标签

    def on_token(self, token: str) -> None:
        if not token:
            return
        text = self._filter.feed(token)
        if text:
            self._emit(text)

    def _emit(self, text: str) -> None:
        # 名字前缀惰性打印：第一个可见文本到达时才出前缀，
        # 纯标签流（如整段 <tool_call>）不会留下裸前缀
        if not self._streamed and self._ui:
            print("\r", end="", flush=True)
            print(f"\033[1;36m{self._name}:\033[0m ", end="", flush=True)
        self._streamed = True
        if self._ui:
            print(text, end="", flush=True)

    def on_message_done(self, text: str) -> None:
        rest = self._filter.flush()
        if rest:
            self._emit(rest)
        if self._streamed:
            print()
        elif self._ui and text:
            self._ui.display.respond(text, prefix=self._name)
        self._streamed = False

    def on_sleep_reply(self, text: str) -> None:
        if self._ui:
            self._ui.display.respond(text, prefix=f"💤{self._name}")

    def on_proactive(self, text: str) -> None:
        if self._ui:
            print()  # break the input prompt line before the proactive bubble
            self._ui.display.separator()
            self._ui.display.respond(text, prefix=self._name)
            self._ui.display.separator()

    def on_status(self, status: str) -> None:
        """阶段状态提示（CLI-UI）：她在想…/她在翻工具箱…/她在写回复…"""
        if self._ui:
            self._ui.display.print_status(status)

    def on_error(self, error: str) -> None:
        if self._ui:
            self._ui.display.print_error(error)
