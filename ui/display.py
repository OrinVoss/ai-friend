import sys
import time
import shutil


class DisplayEngine:
    def __init__(self, typing_speed: float = 0.02):
        self.typing_speed = typing_speed

    def typewrite(self, text: str, end: str = "\n") -> None:
        for ch in text:
            print(ch, end="", flush=True)
            if ch in ".!?。！？\n":
                time.sleep(self.typing_speed * 8)
            elif ch in ",;:，；：":
                time.sleep(self.typing_speed * 4)
            else:
                time.sleep(self.typing_speed)
        print(end, end="", flush=True)

    def respond(self, text: str, prefix: str = "") -> None:
        width = min(shutil.get_terminal_size().columns, 80)
        if prefix:
            print(f"{prefix}: ", end="", flush=True)
            time.sleep(self.typing_speed * 10)
        lines = self._word_wrap(text, width - len(prefix) - 2 if prefix else width)
        for i, line in enumerate(lines):
            if i > 0 and prefix:
                print(" " * (len(prefix) + 2), end="", flush=True)
            self.typewrite(line, end="")
            print()

    @staticmethod
    def show_thinking() -> None:
        print(" ...", end="", flush=True)

    @staticmethod
    def print_system(msg: str) -> None:
        print(f"\033[2;37m[系统] {msg}\033[0m")

    @staticmethod
    def print_error(msg: str) -> None:
        print(f"\033[31m[错误] {msg}\033[0m")

    @staticmethod
    def print_mood(emotion: str) -> None:
        print(f"\033[35m[心情: {emotion}]\033[0m")

    @staticmethod
    def _word_wrap(text: str, width: int) -> list[str]:
        if width < 20:
            width = 20
        lines = []
        for paragraph in text.split("\n"):
            while len(paragraph) > width:
                break_at = paragraph.rfind(" ", 0, width)
                if break_at < width // 2:
                    break_at = width
                lines.append(paragraph[:break_at])
                paragraph = paragraph[break_at:].strip()
            if paragraph:
                lines.append(paragraph)
        return lines
