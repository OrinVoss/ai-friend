"""Tests for web/session.py — WebAgent proactive wrappers (#125)."""
import unittest
from unittest.mock import MagicMock

from core.inner_drive import ProactiveIntent


class TestWebAgentProactive(unittest.TestCase):
    def setUp(self):
        from web.session import WebAgent
        from config import Config

        cfg = Config()
        cfg.max_tokens = 512
        cfg.personality_file = "personality.json"
        cfg.web_port = 8000

        self.agent = WebAgent.__new__(WebAgent)
        self.agent.config = cfg
        self.agent.personality = MagicMock()
        self.agent.personality.config.name = "TestBot"
        self.agent.personality.save = MagicMock()
        self.agent.personality.emotion.dominant_emotion = "neutral"
        self.agent.agent = MagicMock()
        self.agent._on_token_callback = None

    def test_process_proactive_with_intent(self):
        intent = ProactiveIntent(
            action="chat", topic_hint="旅行", reasoning="用户有空"
        )
        self.agent.agent.process_proactive = MagicMock(return_value="嗨！")
        result = self.agent.process_proactive_with_intent(intent)
        self.assertEqual(result, "嗨！")
        self.agent.agent.process_proactive.assert_called_once_with(
            on_token=None, intent=intent,
        )

    def test_process_explore_with_intent(self):
        intent = ProactiveIntent(
            action="explore", topic_hint="AI新闻", reasoning="程序员用户"
        )
        self.agent.agent.process_explore = MagicMock(return_value="发现一篇有趣文章")
        result = self.agent.process_explore_with_intent(intent)
        self.assertEqual(result, "发现一篇有趣文章")
        self.agent.agent.process_explore.assert_called_once_with(intent=intent)

    def test_process_proactive_without_intent(self):
        self.agent.agent.process_proactive = MagicMock(return_value="你好！")
        result = self.agent.process_proactive()
        self.assertEqual(result, "你好！")
        self.agent.agent.process_proactive.assert_called_once_with(
            on_token=None, intent=None,
        )

    def test_process_explore_without_intent(self):
        self.agent.agent.process_explore = MagicMock(return_value=None)
        result = self.agent.process_explore()
        self.assertIsNone(result)
        self.agent.agent.process_explore.assert_called_once_with(intent=None)


if __name__ == "__main__":
    unittest.main()
