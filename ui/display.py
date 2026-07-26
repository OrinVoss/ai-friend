"""CLI display engine: typewriter effect, word wrapping, terminal helpers."""
import shutil
import sys
import time

# ── Palette (CLI-UI 2026-07-26: 集中调色，替换散落的魔数颜色码) ──
C_RESET = "\033[0m"
C_BOLD = "\033[1m"
C_DIM = "\033[2m"
C_NAME = "\033[1;36m"    # AI 名字/前缀（青）
C_USER = "\033[33m"     # 用户相关（黄）
C_PANEL = "\033[36m"    # 面板边框（暗青）
C_SYSTEM = "\033[2;37m"  # 系统提示（灰白 dim）
C_ERROR = "\033[31m"
C_MOOD = "\033[35m"

# 情绪 → (emoji, ANSI 颜色)。未知情绪回退 neutral。
_MOOD_MAP = {
    "joyful": ("😊", "\033[33m"), "excited": ("🤩", "\033[1;33m"),
    "sad": ("😢", "\033[34m"), "melancholy": ("😔", "\033[34m"),
    "angry": ("😠", "\033[31m"), "fear": ("😨", "\033[35m"),
    "surprised": ("😮", "\033[36m"), "engaged": ("🙂", "\033[32m"),
    "trusting": ("🥰", "\033[32m"), "neutral": ("😐", "\033[37m"),
}

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


def mood_icon(emotion: str) -> str:
    """情绪 → emoji（未知回退 neutral）。"""
    return _MOOD_MAP.get(emotion, _MOOD_MAP["neutral"])[0]


def rel_bar(value: float, width: int = 10) -> str:
    """关系指标进度条：0.62 → ▰▰▰▰▰▰▱▱▱▱"""
    try:
        v = max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        v = 0.0
    filled = round(v * width)
    return "▰" * filled + "▱" * (width - filled)


def panel(title: str, rows: list[str], max_width: int = 60) -> str:
    """通用边框面板（CJK 对齐），返回含 ANSI 的多行字符串。

    rows 元素可为 (text, color) 二元组或纯文本；纯文本不加色。
    """
    norm = [r if isinstance(r, tuple) else (r, "") for r in rows]
    inner = max(
        [_cjk_aware_width(t) for t, _ in norm] + [_cjk_aware_width(title) + 2, 10],
    )
    inner = min(inner, max_width)
    top = f"╭─ {title} " + "─" * max(0, inner - _cjk_aware_width(title) - 1) + "╮"
    bot = "╰" + "─" * (inner + 2) + "╯"
    out = [f"{C_PANEL}{top}{C_RESET}"]
    for text, color in norm:
        pad = inner - _cjk_aware_width(text)
        body = f"{color}{text}{C_RESET if color else ''}" if color else text
        out.append(f"{C_PANEL}│{C_RESET} {body}{' ' * pad} {C_PANEL}│{C_RESET}")
    out.append(f"{C_PANEL}{bot}{C_RESET}")
    return "\n".join(out)


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
            print(f"{C_NAME}{prefix}:{C_RESET} ", end="", flush=True)
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
        print(f"{C_SYSTEM}[系统] {msg}{C_RESET}")

    @staticmethod
    def print_error(msg: str) -> None:
        print(f"{C_ERROR}[错误] {msg}{C_RESET}")

    @staticmethod
    def print_mood(emotion: str, valence: float | None = None,
                   arousal: float | None = None) -> None:
        icon, color = _MOOD_MAP.get(emotion, _MOOD_MAP["neutral"])
        extra = ""
        if valence is not None and arousal is not None:
            extra = f" (v={valence:.2f} a={arousal:.2f})"
        print(f"{color}[心情: {icon} {emotion}{extra}]{C_RESET}")

    @staticmethod
    def print_status(msg: str) -> None:
        """阶段状态提示（dim），如「她在翻工具箱…」。"""
        print(f"{C_DIM}  ⏳ {msg}{C_RESET}")

    @staticmethod
    def separator() -> None:
        width = min(shutil.get_terminal_size().columns, 60)
        print(f"{C_DIM}{'─' * width}{C_RESET}")

    @staticmethod
    def print_banner(name: str) -> None:
        rows = [
            (f"✦ {name} ✦", C_NAME),
            ("你的 AI 朋友", C_DIM),
            ("输入 /help 查看命令 · /exit 退出", C_DIM),
        ]
        print()
        print(panel("欢迎", rows, max_width=46))
        print()

    @staticmethod
    def print_help(commands: list[tuple[str, str]]) -> None:
        width = max(_cjk_aware_width(c) for c, _ in commands)
        rows = [(f"{c:<{width}}  {d}", C_USER) for c, d in commands]
        print(panel("内置命令", rows))

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
