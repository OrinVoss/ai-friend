"""Tests for ui/display.py — CLI-UI 视觉层（panel/rel_bar/mood/banner）。"""
import io
import unittest
from contextlib import redirect_stdout

from ui.display import (
    DisplayEngine, _cjk_aware_width, mood_icon, panel, rel_bar,
)


class TestRelBar(unittest.TestCase):
    def test_values(self):
        self.assertEqual(rel_bar(0.0), "▱" * 10)
        self.assertEqual(rel_bar(1.0), "▰" * 10)
        self.assertEqual(rel_bar(0.5), "▰" * 5 + "▱" * 5)

    def test_clamps_and_garbage(self):
        self.assertEqual(rel_bar(1.7), "▰" * 10)
        self.assertEqual(rel_bar(-0.2), "▱" * 10)
        self.assertEqual(rel_bar("x"), "▱" * 10)


class TestMoodIcon(unittest.TestCase):
    def test_known_and_fallback(self):
        self.assertEqual(mood_icon("joyful"), "😊")
        self.assertEqual(mood_icon("angry"), "😠")
        self.assertEqual(mood_icon("nonexistent-emotion"), "😐")


class TestPanel(unittest.TestCase):
    def _strip_ansi(self, s: str) -> str:
        import re
        return re.sub(r"\033\[[0-9;]*m", "", s)

    def test_cjk_rows_align(self):
        out = self._strip_ansi(panel("状态", [("轮次: 183", ""), ("信任 ▰▰▱▱ 0.62", "")]))
        lines = out.split("\n")
        # 所有行显示宽度一致（CJK 字符按 2 列计）
        widths = {_cjk_aware_width(line) for line in lines}
        self.assertEqual(len(widths), 1, f"边框未对齐: {widths}")

    def test_tuple_color_row(self):
        out = panel("t", [("红色行", "\033[31m")])
        self.assertIn("\033[31m", out)

    def test_empty_title_short_rows(self):
        out = self._strip_ansi(panel("", [("x", "")]))
        self.assertTrue(out.startswith("╭"))


class TestBannerAndHelp(unittest.TestCase):
    def test_banner_contains_name_and_hint(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            DisplayEngine.print_banner("小星")
        out = buf.getvalue()
        self.assertIn("小星", out)
        self.assertIn("/help", out)
        self.assertIn("╭", out)

    def test_help_lists_commands(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            DisplayEngine.print_help([("/exit", "退出"), ("/mood", "看心情")])
        out = buf.getvalue()
        self.assertIn("/exit", out)
        self.assertIn("/mood", out)


class TestPrintMood(unittest.TestCase):
    def test_with_valence_arousal(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            DisplayEngine.print_mood("joyful", 0.62, 0.41)
        out = buf.getvalue()
        self.assertIn("😊", out)
        self.assertIn("joyful", out)
        self.assertIn("0.62", out)

    def test_unknown_emotion_safe(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            DisplayEngine.print_mood("weird")
        self.assertIn("😐", buf.getvalue())


if __name__ == "__main__":
    unittest.main()


class TestReadInput(unittest.TestCase):
    """#305: read_input 必须用 patch_stdout 上下文，而非 prompt() 关键字参数。"""

    def test_uses_patch_stdout_context_manager(self):
        from unittest.mock import MagicMock, patch
        from ui.cli import ConsoleInterface
        ui = ConsoleInterface()
        ui.session = MagicMock()
        ui.session.prompt.return_value = "你好"
        with patch("ui.cli._patch_stdout") as mock_ps:
            self.assertEqual(ui.read_input(), "你好")
            mock_ps.assert_called_once_with()
        _, kwargs = ui.session.prompt.call_args
        self.assertNotIn("patch_stdout", kwargs)

    def test_fallback_to_builtin_input_without_session(self):
        from unittest.mock import patch
        from ui.cli import ConsoleInterface
        ui = ConsoleInterface()
        ui.session = None  # 非控制台环境
        with patch("builtins.input", return_value="hi") as mock_input:
            self.assertEqual(ui.read_input(), "hi")
            mock_input.assert_called_once()
