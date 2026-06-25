"""CLI display engine: typewriter effect, word wrapping, terminal helpers."""
import sys
import time
import shutil


# DP-002: rough CJK character width estimation — CJK chars occupy ~2 columns,
# ASCII/Latin chars ~1 column.  Used in _cjk_aware_width / _cjk_slice for
# word-wrap and line-break logic.
_CJK_RANGE = (
    (0x2E80, 0x2EFF),   # CJK Radicals Supplement
    (0x3000, 0x303F),   # CJK Symbols and Punctuation
    (0x3040, 0x309F),   # Hiragana
    (0x30A0, 0x30FF),   # Katakana
    (0x3400, 0x4DBF),   # CJK Unified Extension A
    (0x4E00, 0x9FFF),   # CJK Unified
    (0xF900, 0xFAFF),   # CJK Compatibility
    (0xFF00, 0xFFEF),   # Fullwidth forms (部分)
)


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGE)


def _cjk_aware_width(text: str) -> int:
    """DP-002: compute display width where CJK chars count as 2 columns."""
    return sum(2 if _is_cjk(ch) else 1 for ch in text)


def _cjk_break(text: str, max_width: int) -> tuple[str, str]:
    """DP-004: split text at max_width, respecting CJK character boundaries.
    Returns (segment, remainder)."""
    width = 0
    for i, ch in enumerate(text):
        ch_w = 2 if _is_cjk(ch) else 1
        if width + ch_w > max_width:
            if i == 0:
                return text[:max_width], text[max_width:]
            return text[:i], text[i:]
        width += ch_w
    return text, ""


class DisplayEngine:
    def __init__(self, typing_speed: float = 0.02):
        self.typing_speed = typing_speed

    def typewrite(self, text: str, end: str = "\n") -> None:
        for ch in text:
            print(ch, end="", flush=True)
            # DP-010: only delay on actual sentence-ending periods, not on \n
            # which is already a line break.  The old code grouped \n with
            # punctuation, causing a double-delay on newlines.
            if ch in ".!?。！？":
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

    @classmethod
    def _word_wrap(cls, text: str, width: int) -> list[str]:
        """DP-002/004: CJK-aware word wrap using display-width instead of
        len(), and CJK-safe break points instead of blindly cutting mid-char.

        Falls back to the old ASCII-space-split algorithm when the text
        contains no CJK characters (fast path).
        """
        if width < 20:
            width = 20

        # Fast path: no CJK chars — use the original space-split logic
        has_cjk = any(_is_cjk(ch) for ch in text)
        if not has_cjk:
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

        # CJK path: use display-width aware slicing
        lines = []
        for paragraph in text.split("\n"):
            while _cjk_aware_width(paragraph) > width:
                seg, paragraph = _cjk_break(paragraph, width)
                lines.append(seg)
            if paragraph:
                lines.append(paragraph)
        return lines
