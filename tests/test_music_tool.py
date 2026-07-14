"""Tests for tools/music_tool.py"""
import os
import tempfile
import unittest
from unittest.mock import patch

from tools.music_tool import MusicListTool, MusicPlayTool


class TestMusicTools(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.music_dir = self.tmpdir.name
        # Create dummy audio files
        self.song_a = os.path.join(self.music_dir, "a.mp3")
        self.song_b = os.path.join(self.music_dir, "sub", "b.flac")
        os.makedirs(os.path.dirname(self.song_b), exist_ok=True)
        open(self.song_a, "w").close()
        open(self.song_b, "w").close()

    def tearDown(self):
        self.tmpdir.cleanup()

    @patch("tools.music_tool.MUSIC_DIR")
    def test_music_list_root(self, mock_dir):
        mock_dir.__str__ = lambda _: self.music_dir
        mock_dir.__fspath__ = lambda _: self.music_dir
        # MUSIC_DIR is used as a string, so patch the actual value
        with patch("tools.music_tool.MUSIC_DIR", self.music_dir):
            tool = MusicListTool()
            result = tool.execute({})
            self.assertTrue(result.success)
            self.assertIn("a.mp3", result.output)

    @patch("tools.music_tool.MUSIC_DIR", new_callable=lambda: tempfile.TemporaryDirectory().name)
    def test_music_play_random(self, _mock_dir):
        # Use a temp dir via patch on the module constant for this test method
        with patch("tools.music_tool.MUSIC_DIR", self.music_dir), \
             patch("tools.music_tool.os.startfile") as mock_start:
            tool = MusicPlayTool()
            result = tool.execute({"song": "random"})
            self.assertTrue(result.success, result.output)
            self.assertIn("正在播放", result.output)
            mock_start.assert_called_once()

    @patch("tools.music_tool.MUSIC_DIR", new_callable=lambda: tempfile.TemporaryDirectory().name)
    def test_music_play_random_empty(self, _mock_dir):
        empty_dir = tempfile.TemporaryDirectory().name
        with patch("tools.music_tool.MUSIC_DIR", empty_dir):
            tool = MusicPlayTool()
            result = tool.execute({"song": "random"})
            self.assertFalse(result.success)
            self.assertIn("没有可播放", result.output)

    def test_music_play_exact_path(self):
        with patch("tools.music_tool.MUSIC_DIR", self.music_dir), \
             patch("tools.music_tool.os.startfile") as mock_start:
            tool = MusicPlayTool()
            result = tool.execute({"song": "a.mp3"})
            self.assertTrue(result.success, result.output)
            self.assertIn("正在播放", result.output)
            mock_start.assert_called_once()
            args, _ = mock_start.call_args
            self.assertTrue(args[0].endswith("a.mp3"))


if __name__ == "__main__":
    unittest.main()
