"""Tests for web/session.py — WebAgent proactive wrappers (#125)."""
import unittest
from threading import Lock
from unittest.mock import MagicMock, AsyncMock

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
        self.agent.role_id = "testbot"
        self.agent.personality_path = "personalities/testbot.json"
        self.agent.personality = MagicMock()
        self.agent.personality.config.name = "TestBot"
        self.agent.personality.save = MagicMock()
        self.agent.personality.emotion.dominant_emotion = "neutral"
        self.agent.agent = MagicMock()
        self.agent._on_token_callback = None
        # #276: __new__ 绕过 __init__，手动补上防抖锁
        self.agent._save_lock = Lock()

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

    def test_last_activity_property(self):
        self.agent.agent.last_activity_time = 123.0
        self.assertEqual(self.agent.last_activity, 123.0)
        self.agent.last_activity = 456.0
        self.assertEqual(self.agent.agent.last_activity_time, 456.0)

    def test_is_sleeping_property(self):
        self.agent.agent._sleeping = True
        self.assertTrue(self.agent.is_sleeping)

    def test_get_sleep_state(self):
        import asyncio
        self.agent.agent._get_sleep_state = AsyncMock(return_value=(True, "zzz"))
        result = asyncio.run(self.agent.get_sleep_state())
        self.assertEqual(result, (True, "zzz"))

    def test_generate_dream(self):
        import asyncio
        self.agent.agent._generate_dream = AsyncMock(return_value=" dreamed ")
        result = asyncio.run(self.agent.generate_dream())
        self.assertEqual(result, " dreamed ")

    def test_calculate_proactivity(self):
        self.agent.agent._calculate_proactivity = MagicMock(return_value=0.42)
        self.assertEqual(self.agent.calculate_proactivity(120.0), 0.42)

    def test_check_rate_limit(self):
        self.agent.agent.check_rate_limit = MagicMock(return_value=True)
        self.assertTrue(self.agent.check_rate_limit("chat"))

    def test_record_rate_limit(self):
        self.agent.agent.record_rate_limit = MagicMock()
        self.agent.record_rate_limit("chat")
        self.agent.agent.record_rate_limit.assert_called_once_with("chat")

    def test_decide_proactive_action(self):
        intent = ProactiveIntent(action="chat", topic_hint="x", reasoning="y")
        self.agent.agent.decide_proactive_action = MagicMock(return_value=intent)
        result = self.agent.decide_proactive_action(60.0)
        self.assertEqual(result, intent)

    def test_save_personality(self):
        self.agent.save_personality()
        self.agent.personality.save.assert_called_once_with(self.agent.personality_path)

    def test_add_turn_forwards_to_agent(self):
        self.agent.add_turn("assistant", "zzz", metadata={"sleep": True})
        self.agent.agent.add_turn.assert_called_once_with(
            "assistant", "zzz", metadata={"sleep": True}
        )

    def test_increment_turn_count_forwards_to_agent(self):
        self.agent.increment_turn_count()
        self.agent.agent.increment_turn_count.assert_called_once()


if __name__ == "__main__":
    unittest.main()
