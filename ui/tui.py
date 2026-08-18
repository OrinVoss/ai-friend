"""Full-screen TUI（prompt_toolkit Application），视觉参考 Claude Code：
滚动聊天区 + Frame 边框固定输入框 + 底部 dim 状态行 + F2 日志面板。

TUI-1（2026-08-18，B 方案）：聊天内容与日志统一写入 ChatModel，渲染交给
Application；前端回调可来自任意线程（后台消息线程 / driver），模型加锁、
经 call_soon_threadsafe(invalidate) 刷新。

TUI-2（同日，Claude Code 风格）：
- Frame 边框输入框；状态行移到输入框下方、dim 弱化；
- 消息层级：用户 "> "，AI "● 名字: "，舞台指示（…）dim，块间空行；
- 生成中状态行 spinner + 已用秒数 + esc 中断提示（ticker 线程驱动动画）；
- Esc 中断首段流式：on_token 抛 StreamAborted 断流，不落库。

注意：Application.run() 内部 asyncio.run()，不能嵌套在已运行的循环里
（main() 是 async）——因此 run_blocking() 把 app 放到专用 worker 线程
（与 #305 的 read_input 桥同型），主线程阻塞等待退出。
"""
from __future__ import annotations

import logging
import re
import threading
import time
from collections import deque

from prompt_toolkit import Application
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    ConditionalContainer, Float, FloatContainer, HSplit, Layout, VSplit, Window)
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets.base import Border

from core.provider import StreamAborted
from ui.cli import SLASH_COMMANDS
from ui.display import DisplayEngine, _cjk_aware_width, mood_icon

logger = logging.getLogger(__name__)

_SCROLL_BOTTOM = 10 ** 9  # Window.write_to_screen 会 clamp 到内容底部

_STYLE = Style.from_dict({
    "user": "ansiyellow bold",
    "accent": "ansicyan bold",
    "dim": "ansibrightblack",
    "err": "ansired",
    "status": "ansibrightblack",
    "frame": "ansibrightblack",
})

_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
# 舞台指示（括号动作/表情）在 AI 回复里以 dim 弱化（CC 的工具行风格）
_STAGE_RE = re.compile(r"（[^）]*）")


def _left_title_frame(body: Window, title: str,
                      style: str = "class:frame") -> HSplit:
    """CC 风格左对齐标题边框：╭─ 标题 ────╮。

    prompt_toolkit 的 Frame 标题两侧是等宽弹性填充（居中），不满足需求，
    这里用原语自拼：左固定 1 格、标题、右弹性填充。
    """
    def fill(char: str = "", width: int | None = None) -> Window:
        return Window(height=1, width=width, char=char, style=style)

    top = VSplit([
        fill(Border.TOP_LEFT, 1),
        fill(Border.HORIZONTAL, 1),
        Window(FormattedTextControl(f" {title} "), height=1,
               dont_extend_width=True, style=style),
        fill(Border.HORIZONTAL),
        fill(Border.TOP_RIGHT, 1),
    ], height=1)
    mid = VSplit([
        Window(width=1, char=Border.VERTICAL, style=style),
        body,
        Window(width=1, char=Border.VERTICAL, style=style),
    ])
    bottom = VSplit([
        fill(Border.BOTTOM_LEFT, 1),
        fill(Border.HORIZONTAL),
        fill(Border.BOTTOM_RIGHT, 1),
    ], height=1)
    return HSplit([top, mid, bottom])


def _ai_content_fragments(text: str) -> list[tuple[str, str]]:
    """AI 回复行拆片段：舞台指示（…）dim，对白默认色。"""
    frags: list[tuple[str, str]] = []
    pos = 0
    for m in _STAGE_RE.finditer(text):
        if m.start() > pos:
            frags.append(("", text[pos:m.start()]))
        frags.append(("class:dim", m.group(0)))
        pos = m.end()
    if pos < len(text):
        frags.append(("", text[pos:]))
    return frags


class _ChatWindow(Window):
    """滚轮滚动时维护 follow 状态：上滚取消跟随，滚到底自动恢复。"""

    def __init__(self, app: "TuiChatApp", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._app = app

    def _scroll_up(self) -> None:
        self._app._follow = False
        super()._scroll_up()

    def _scroll_down(self) -> None:
        super()._scroll_down()
        info = self.render_info
        if info is not None and self.vertical_scroll >= max(
                0, info.content_height - info.window_height):
            self._app._follow = True
            self._app._new_below = False


class ChatModel:
    """聊天内容模型：块（kind, prefix, text）列表 + 活动状态 + 日志环形缓冲。

    kind: user / ai / raw（含 ANSI 的面板输出）/ err / dim。
    """

    MAX_BLOCKS = 1000  # 长会话上限，丢弃最旧块

    def __init__(self):
        self.blocks: list[list[str]] = []
        self.activity = ""
        self.logs: deque[str] = deque(maxlen=200)
        self._streaming = False

    def add(self, kind: str, text: str, prefix: str = "") -> None:
        self.blocks.append([kind, prefix, text])
        self._streaming = False
        if len(self.blocks) > self.MAX_BLOCKS:
            del self.blocks[: len(self.blocks) - self.MAX_BLOCKS]

    def stream(self, kind: str, prefix: str, token: str) -> None:
        if not self._streaming:
            self.add(kind, "", prefix=prefix)
            self._streaming = True
        self.blocks[-1][2] += token

    def end_stream(self, kind: str, prefix: str, full_text: str) -> None:
        """流式回复收尾；未流式（工具轮/整段回复）则整块落一条。"""
        if self._streaming:
            self._streaming = False
        elif full_text:
            self.add(kind, full_text, prefix=prefix)

    def fragments(self) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for kind, prefix, text in self.blocks:
            lines = text.split("\n")
            indent = " " * (_cjk_aware_width(prefix) if prefix else 0)
            for i, ln in enumerate(lines):
                lead = prefix if i == 0 else indent
                if kind == "raw":
                    out.extend(to_formatted_text(ANSI(lead + ln)))
                elif kind == "ai":
                    if lead:
                        out.append(("class:accent", lead))
                    out.extend(_ai_content_fragments(ln))
                else:
                    out.append((f"class:{kind}", lead + ln))
                out.append(("", "\n"))
            out.append(("", "\n"))  # 块间空行（CC 风格留白）
        return out


class TuiChatApp:
    """全屏聊天 Application。非渲染逻辑均可无头单测。"""

    def __init__(self, controller, engine, ui, output=None):
        self._controller = controller
        self._engine = engine
        self._ui = ui
        a = controller.a
        self._agent = a
        self._name = a.personality.config.name
        self._status_fn = controller._status_snapshot
        self.model = ChatModel()
        self._lock = threading.Lock()
        self.show_logs = False
        # 滚动跟随：跟随新消息自动滚底；用户上翻时取消跟随，
        # 翻页/滚轮到底或发新消息时恢复（CC 同款行为）
        self._follow = True
        self._new_below = False  # 非跟随期间来了新消息 → 状态栏提示
        self.interrupt = threading.Event()  # TUI-2: Esc 中断
        self._generating = False
        self._activity_since: float | None = None
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self._frontend = _TuiFrontend(self)

        # ── 输入区：历史/补全/建议/Ctrl+R 搜索 ──
        self.input_buffer = Buffer(
            history=FileHistory(ui._history_file),
            completer=WordCompleter(SLASH_COMMANDS, sentence=True),
            auto_suggest=AutoSuggestFromHistory(),
            enable_history_search=True,
            # TUI-2: 输入 "/" 即弹出命令列表（默认需按 Tab 才出补全）
            complete_while_typing=True,
            multiline=False,
            accept_handler=self._on_submit,
        )
        input_control = BufferControl(buffer=self.input_buffer)
        input_win = Window(
            input_control, dont_extend_height=True, wrap_lines=True,
            get_line_prefix=lambda line_no, wrap_count:
                "> " if wrap_count == 0 else "  ",
        )

        self._chat_control = FormattedTextControl(self._chat_fragments)
        self._chat_win = _ChatWindow(self, self._chat_control, wrap_lines=True)

        self._log_control = FormattedTextControl(self._log_text)
        log_win = Window(self._log_control, wrap_lines=True, height=8,
                         dont_extend_height=True, style="class:dim")
        log_container = ConditionalContainer(
            log_win, Condition(lambda: self.show_logs))

        status_win = Window(FormattedTextControl(self._status_fragments),
                            height=1, dont_extend_height=True, style="class:status")

        kb = KeyBindings()

        @kb.add("f2")
        def _toggle_logs(event):
            self.show_logs = not self.show_logs
            event.app.invalidate()

        @kb.add("c-l")
        def _clear(event):
            with self._lock:
                self.model.blocks.clear()
            event.app.invalidate()

        @kb.add("c-c")
        @kb.add("c-d")
        def _quit(event):
            self.request_exit()

        @kb.add("escape")
        def _esc(event):
            # TUI-2: 仅在生成中生效——中断流式，不打断已完成内容
            if self._generating or self.model._streaming:
                self.interrupt.set()
                event.app.invalidate()

        @kb.add("pageup")
        def _page_up(event):
            self.scroll_chat(-1)

        @kb.add("pagedown")
        def _page_down(event):
            self.scroll_chat(1)

        @kb.add("c-end")
        def _to_bottom(event):
            self.scroll_to_bottom()

        body = HSplit([
            self._chat_win,
            log_container,
            _left_title_frame(input_win, "你"),
            status_win,
        ])
        # TUI-2 实测修复：补全菜单必须挂在 FloatContainer 的 Float 里才渲染——
        # 裸 HSplit 时 complete_while_typing 算了候选但菜单无处显示。
        # 输入框在底部时菜单自动翻到光标上方（FloatContainer 内置 flip 逻辑）。
        root = FloatContainer(
            body,
            floats=[
                Float(xcursor=True, ycursor=True, transparent=True,
                      content=CompletionsMenu(
                          max_height=12, scroll_offset=1,
                          extra_filter=has_focus(self.input_buffer))),
            ],
        )

        self.app = Application(
            layout=Layout(root, focused_element=input_control),
            key_bindings=kb,
            full_screen=True,
            style=_STYLE,
            output=output,
            mouse_support=True,  # 滚轮翻聊天区（终端选中复制用 Shift+拖拽）
        )

    # ── 渲染数据源（app 循环线程内调用）──

    def _chat_fragments(self):
        with self._lock:
            frags = self.model.fragments()
        # 仅在跟随模式滚到底（渲染时 clamp 到有效范围）；
        # 用户上翻阅读时不拽回底部
        if self._follow:
            self._chat_win.vertical_scroll = _SCROLL_BOTTOM
        return frags

    def _log_text(self):
        with self._lock:
            return "\n".join(self.model.logs)

    def _status_fragments(self):
        with self._lock:
            activity = self.model.activity
            generating = self._generating
            since = self._activity_since
            show_logs = self.show_logs
            new_below = self._new_below and not self._follow
        parts = []
        if activity or generating:
            elapsed = time.monotonic() - since if since else 0.0
            spin = _SPINNER[int(time.monotonic() * 10) % len(_SPINNER)]
            parts.append(f"{spin} {activity or '她在想…'}（{elapsed:.0f}s · esc 中断）")
        if new_below:
            parts.append("↓ 新消息（C-End 到底）")
        try:
            s = self._status_fn() or {}
        except Exception:
            s = {}
        emotion = s.get("emotion")
        if emotion:
            parts.append(f"{mood_icon(emotion)} {emotion}")
        if s.get("turn") is not None:
            parts.append(f"轮次 {s['turn']}")
        if s.get("sleeping"):
            parts.append("💤 睡眠中")
        parts.append("F2 日志" + ("·开" if show_logs else "") + " · PgUp 翻页")
        from datetime import datetime
        parts.append(datetime.now().strftime("%H:%M"))
        return [("class:status", "  ".join(parts))]

    # ── 线程安全写入（任意线程可调）──

    def _refresh(self) -> None:
        if self.app.is_running:
            self.app.loop.call_soon_threadsafe(self.app.invalidate)

    # ── 滚动控制（PgUp/PgDn/滚轮/Ctrl+End）──

    def scroll_chat(self, pages: float) -> None:
        """翻页滚动聊天区（正数向下）。上滚取消跟随，滚到底恢复。"""
        info = self._chat_win.render_info
        height = info.window_height if info is not None else 10
        if pages < 0:
            self._follow = False
        self._chat_win.vertical_scroll = max(
            0, self._chat_win.vertical_scroll + int(height * pages))
        if info is not None and self._chat_win.vertical_scroll >= max(
                0, info.content_height - info.window_height):
            self._follow = True
            self._new_below = False
        if self.app.is_running:
            self.app.invalidate()

    def scroll_to_bottom(self) -> None:
        self._follow = True
        self._new_below = False
        self._chat_win.vertical_scroll = _SCROLL_BOTTOM
        if self.app.is_running:
            self.app.invalidate()

    def post_ai(self, text: str, sleep: bool = False) -> None:
        prefix = f"{'💤' if sleep else ''}● {self._name}: "
        with self._lock:
            self.model.activity = ""
            self._generating = False
            self.model.add("ai", text, prefix=prefix)
            if not self._follow:
                self._new_below = True
        self._refresh()

    def post_user(self, text: str) -> None:
        with self._lock:
            self._follow = True  # 自己发消息 → 跳到底部
            self._new_below = False
            self.model.add("user", text, prefix="> ")
        self._refresh()

    def post_raw(self, ansi_text: str) -> None:
        """面板/系统提示等含 ANSI 码的输出（/help、/status、/mood）。"""
        with self._lock:
            self.model.add("raw", ansi_text)
        self._refresh()

    def post_error(self, error: str) -> None:
        with self._lock:
            self.model.activity = ""
            self._generating = False
            self.model.add("err", f"[错误] {error}")
        self._refresh()

    def post_log(self, line: str) -> None:
        """WARNING+ 日志行（logging handler 的 sink）。"""
        with self._lock:
            self.model.logs.append(line)
        self._refresh()

    def set_activity(self, status: str) -> None:
        with self._lock:
            if not self.model.activity:
                self._activity_since = time.monotonic()
            self.model.activity = status
        self._refresh()

    def stream_token(self, token: str) -> None:
        with self._lock:
            self.model.stream("ai", f"● {self._name}: ", token)
        self._refresh()

    def finish_stream(self, full_text: str) -> None:
        with self._lock:
            self.model.activity = ""
            self._generating = False
            self.model.end_stream("ai", f"● {self._name}: ", full_text)
        self._refresh()

    def abort_stream(self) -> None:
        """Esc 中断：给当前流式块补注记并收尾（回复不落库——
        StreamAborted 让 _react_loop 返回空串，所见与历史一致）。"""
        with self._lock:
            if self.model._streaming:
                self.model.stream("ai", "", "  …（已中断）")
                self.model.end_stream("ai", "", "")
            self._generating = False
            self.model.activity = ""
        self._refresh()

    # ── 输入处理 ──

    @property
    def frontend(self) -> "_TuiFrontend":
        return self._frontend

    def _on_submit(self, buf: Buffer) -> None:
        text = buf.text.strip()
        if not text:
            return
        if text.startswith("/"):
            if text in ("/exit", "/quit"):
                self.request_exit()
                return
            self._controller._handle_command(text, sink=self.post_raw)
            return
        self.post_user(text)
        self._dispatch_message(text)

    def _dispatch_message(self, text: str) -> None:
        """在后台线程跑三段流水线（不阻塞 app 循环）。

        daemon 线程而非 loop 默认 executor：asyncio 退出时会 join 默认
        executor，若 LLM 调用正卡在 HTTP（最长 180s），Ctrl+C//exit 会被
        拖着等它结束。daemon 线程让退出立即生效——未完成的回复不落库
        （add_turn 在生成末尾才发生），语义干净。
        """
        self.interrupt.clear()
        with self._lock:
            self._generating = True
            self._activity_since = time.monotonic()
        self._refresh()
        if self.app.is_running:
            threading.Thread(target=self._process, args=(text,),
                             daemon=True, name="tui-msg").start()
        else:  # 无头测试路径
            self._process(text)

    def _process(self, text: str) -> None:
        a = self._agent
        try:
            self._engine.handle_message(text, self._frontend)
        finally:
            with self._lock:
                self._generating = False
                self.model.activity = ""
            self._refresh()
        # 与行式 CLI 一致：每 10 轮保存一次人格
        if a.turn_count > 0 and a.turn_count % 10 == 0:
            try:
                a.personality.save(a.config.personality_file)
            except Exception as e:
                logger.warning(f"[tui] personality save failed: {e}")

    def request_exit(self) -> None:
        self._agent._running = False
        if self.app.is_running:
            self.app.loop.call_soon_threadsafe(self.app.exit)
        self._done.set()

    # ── 启动内容（横幅/问候先入模型，再进全屏）──

    def preload(self) -> None:
        """横幅先入模型（问候语由 controller._on_boot 经 sink 注入）。"""
        with self._lock:
            self.model.add("raw", DisplayEngine.format_banner(self._name))

    # ── 运行（worker 线程跑 app，调用线程阻塞等待）──

    def run_blocking(self) -> None:
        """main() 的 async 循环线程调这里；app.run() 会嵌套 asyncio.run，
        必须放到无循环的专用线程（#305 同型）。"""
        def _main():
            try:
                self.app.run()
            except Exception:
                logger.exception("[tui] application crashed")
            finally:
                self._done.set()

        # spinner 动画驱动：生成/活动状态期间周期性刷新
        def _ticker():
            while not self._done.wait(0.4):
                with self._lock:
                    busy = self._generating or bool(self.model.activity)
                if busy:
                    self._refresh()

        threading.Thread(target=_ticker, daemon=True, name="tui-ticker").start()
        self._thread = threading.Thread(target=_main, daemon=True, name="tui-app")
        self._thread.start()
        while not self._done.is_set():
            try:
                self._done.wait(0.5)
            except KeyboardInterrupt:
                self.request_exit()
        self._thread.join(timeout=3)


class _TuiFrontend:
    """Frontend 协议实现：把引擎事件写进 TuiChatApp 的模型。

    首段流式 token 未经 message_handler 清洗，可能含 <think>/<tool_call>
    片段——沿用 _StreamTagFilter。Esc 中断：on_token 抛 StreamAborted。
    """

    def __init__(self, app: TuiChatApp):
        self._app = app
        from core.cli_controller import _StreamTagFilter
        self._filter = _StreamTagFilter()

    def on_token(self, token: str) -> None:
        if not token:
            return
        if self._app.interrupt.is_set():
            self._app.abort_stream()
            raise StreamAborted()
        text = self._filter.feed(token)
        if text:
            self._app.stream_token(text)

    def on_message_done(self, text: str) -> None:
        rest = self._filter.flush()
        if rest:
            self._app.stream_token(rest)
        self._app.finish_stream(text)

    def on_proactive(self, text: str) -> None:
        self._app.post_ai(text)

    def on_sleep_reply(self, text: str) -> None:
        self._app.post_ai(text, sleep=True)

    def on_status(self, status: str) -> None:
        self._app.set_activity(status)

    def on_error(self, error: str) -> None:
        self._app.post_error(error)
