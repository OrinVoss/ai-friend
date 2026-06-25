import sys
import threading
from queue import Queue, Empty


class NonBlockingInputReader:
    """Background daemon thread for non-blocking stdin reading."""

    def __init__(self):
        self._queue: Queue[str] = Queue()
        self._sentinel = threading.Event()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._thread.start()

    def stop(self) -> None:
        self._sentinel.set()

    def read_line(self, timeout: float = 0) -> str | None:
        """Non-blocking read. Returns None if no input available."""
        try:
            return self._queue.get_nowait()
        except Empty:
            return None

    def _reader(self) -> None:
        while not self._sentinel.is_set():
            line = sys.stdin.readline()
            if not line:
                break
            self._queue.put(line.rstrip("\n"))


class ConsoleInterface:
    def __init__(self, typing_speed: float = 0.02):
        self._typing_speed = typing_speed
        self.reader = NonBlockingInputReader()
        self.display: "DisplayEngine | None" = None

    def start(self) -> None:
        from ui.display import DisplayEngine
        self.display = DisplayEngine(typing_speed=self._typing_speed)
        self.reader.start()

    def stop(self) -> None:
        self.reader.stop()

    @staticmethod
    def display_banner(name: str) -> None:
        print(f"\033[1;36m{'=' * 50}\033[0m")
        print(f"\033[1;36m   ✦ {name} ✦\033[0m")
        print(f"\033[1;36m   你的 AI 朋友\033[0m")
        print(f"\033[1;36m{'=' * 50}\033[0m")
        print("输入 /help 查看命令，/exit 退出\n")

    @staticmethod
    def display_help() -> None:
        commands = [
            ("/exit 或 /quit", "保存并退出"),
            ("/save", "强制记忆合并"),
            ("/mood", "查看当前心情"),
            ("/status", "查看关系状态和统计"),
            ("/forget", "清除短期记忆"),
            ("/help", "显示此帮助"),
        ]
        print("\n\033[1m内置命令：\033[0m")
        for cmd, desc in commands:
            print(f"  \033[33m{cmd:<20}\033[0m {desc}")
        print()
