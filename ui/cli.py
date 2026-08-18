"""CLI interface: prompt_toolkit-based input layer + display wiring.

CLI-UI（2026-07-26）：输入由 prompt_toolkit 接管（历史/补全/粘贴多行/
bottom_toolbar 状态栏），替代旧的 NonBlockingInputReader 轮询线程。
后台主动消息经 patch_stdout 安全打印，不再打断输入行。
"""
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.patch_stdout import patch_stdout as _patch_stdout

from ui.display import mood_icon

SLASH_COMMANDS = ["/exit", "/quit", "/save", "/mood", "/status", "/forget", "/help"]

SLASH_HELP = [
    ("/exit 或 /quit", "保存并退出"),
    ("/save", "强制记忆合并"),
    ("/mood", "查看当前心情"),
    ("/status", "查看关系状态和统计"),
    ("/forget", "清除短期记忆"),
    ("/help", "显示此帮助"),
]


class ConsoleInterface:
    """Terminal frontend facade: owns the PromptSession and DisplayEngine.

    status_fn: 由 cli_controller 注入，返回 {"emotion": str, "turn": int,
    "sleeping": bool}，供 bottom_toolbar 实时渲染。
    """

    def __init__(self, typing_speed: float = 0.02, status_fn=None,
                 history_file: str = "data/.cli_history"):
        self._typing_speed = typing_speed
        self.status_fn = status_fn or (lambda: {})
        self._history_file = history_file
        self.display: "DisplayEngine | None" = None
        self.session: "PromptSession | None" = None

    def start(self) -> None:
        import sys
        # 输出被重定向（管道/文件）时 Windows 回退 GBK，框线/emoji 会
        # UnicodeEncodeError——仅非 tty 场景强制 UTF-8，真控制台不受影响
        if not sys.stdout.isatty():
            try:
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass
        from ui.display import DisplayEngine
        self.display = DisplayEngine(typing_speed=self._typing_speed)
        try:
            self.session = PromptSession(
                history=FileHistory(self._history_file),
                completer=WordCompleter(SLASH_COMMANDS, sentence=True),
                auto_suggest=AutoSuggestFromHistory(),
                bottom_toolbar=self._toolbar,
            )
        except Exception:
            # 非控制台环境（管道输入/CI/重定向）回退到普通 input()
            self.session = None

    def stop(self) -> None:
        pass

    def _toolbar(self) -> ANSI:
        s = {}
        try:
            s = self.status_fn() or {}
        except Exception:
            pass
        parts = []
        emotion = s.get("emotion")
        if emotion:
            parts.append(f"{mood_icon(emotion)} {emotion}")
        if s.get("turn") is not None:
            parts.append(f"轮次 {s['turn']}")
        if s.get("sleeping"):
            parts.append("💤 睡眠中")
        parts.append(datetime.now().strftime("%H:%M"))
        return ANSI("\x1b[2m" + " │ ".join(parts) + "\x1b[0m")

    def read_input(self) -> str:
        """阻塞读取一行输入；patch_stdout 上下文让后台主动消息安全插入。
        非控制台环境（session 创建失败）回退普通 input()。
        #305: patch_stdout 是上下文管理器，不是 prompt() 的参数。
        #305(二)：main() 是 async——调用线程已有运行中的事件循环，
        prompt_toolkit 同步 prompt() 内部 asyncio.run() 不能嵌套，
        此时放到无循环的专用线程里执行（worker 内 asyncio.run 合法）。"""
        if self.session is None:
            return input("你 ▸ ")
        prompt_text = ANSI("\x1b[1;32m你 ▸\x1b[0m ")
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            with _patch_stdout():
                return self.session.prompt(prompt_text)
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(self._prompt_blocking, prompt_text).result()

    def _prompt_blocking(self, prompt_text) -> str:
        """在无事件循环的 worker 线程里执行同步 prompt（read_input 的桥）。"""
        with _patch_stdout():
            return self.session.prompt(prompt_text)

    def invalidate(self) -> None:
        """触发 bottom_toolbar 重绘（情绪/轮次变化后调用，可跨线程）。"""
        try:
            if self.session is not None and self.session.app is not None:
                self.session.app.invalidate()
        except Exception:
            pass  # 提示符未激活时无 app，忽略

    @staticmethod
    def display_banner(name: str) -> None:
        from ui.display import DisplayEngine
        DisplayEngine.print_banner(name)

    @staticmethod
    def display_help() -> None:
        from ui.display import DisplayEngine
        DisplayEngine.print_help(SLASH_HELP)
