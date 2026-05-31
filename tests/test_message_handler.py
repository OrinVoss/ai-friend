"""Tests for core/message_handler.py"""
import unittest
from unittest.mock import MagicMock, patch

from core.message_handler import MessageHandler
from core.inner_drive import ProactiveIntent
from tests.mocks import mock_tool_registry


def _make_memory_mock():
    """Create a mock MemoryContext with proper numeric relationship values."""
    m = MagicMock()
    m.facts = []
    m.experiences = []
    m.reflections = []
    m.relationship = {"trust": 0.5, "familiarity": 0.5, "intimacy": 0.5, "playfulness": 0.5}
    return m


class TestMessageHandler(unittest.TestCase):
    def setUp(self):
        self.agent = MagicMock()
        self.agent._sleeping = False
        self.agent.turn_count = 0
        self.agent._consecutive_negative = 0
        self.agent._tool_call_history = []
        self.agent._tool_registry = mock_tool_registry()
        self.agent._context = MagicMock()
        self.agent._context.compressed_summary = ""
        self.agent._context.compress = MagicMock()
        self.agent.short_term.get_all_reversed.return_value = []
        self.agent.short_term.format_for_prompt.return_value = ""
        self.agent.short_term.get_all.return_value = []
        self.agent.retriever.retrieve_for_query.return_value = _make_memory_mock()
        self.agent.ltm.repo.insert_turn = MagicMock()
        self.agent.personality.config.name = "TestBot"
        self.agent.personality.config.interests = ["music", "art"]
        self.agent.personality.emotion.dominant_emotion = "neutral"
        self.agent.personality.emotion.valence = 0.4
        self.agent.personality.emotion.arousal = 0.5
        self.agent.personality.emotion.resentment = 0.0
        self.agent.personality.emotion.emotion_events = []
        self.agent.personality.emotion.record_emotion_event = MagicMock()
        self.agent.personality.config.traits = []
        self.agent.provider.generate.return_value = "NO_TOOLS"
        self.agent._react_loop.return_value = "Hello!"
        self.agent._pick_proactive_topic.return_value = "聊聊天气"

        self.handler = MessageHandler(self.agent)

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_message_normal(self, _mock):
        result = self.handler.handle_message("你好")
        self.assertEqual(result, "Hello!")
        self.agent._react_loop.assert_called_once()

    def test_handle_message_sleeping(self):
        self.agent._sleeping = True
        result = self.handler.handle_message("你好")
        self.assertIn("zzz", result.lower())
        self.agent._react_loop.assert_not_called()

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_proactive(self, _mock):
        result = self.handler.handle_proactive()
        self.assertEqual(result, "Hello!")
        self.agent._react_loop.assert_called_once()

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_explore_share(self, _mock):
        self.agent._react_loop.return_value = "我发现了一篇非常非常有趣的文章，关于人工智能技术的最新突破进展！"
        result = self.handler.handle_explore()
        self.assertIsNotNone(result)
        self.assertIn("人工智能", result)

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_explore_silent(self, _mock):
        self.agent._react_loop.return_value = "没啥"
        result = self.handler.handle_explore()
        self.assertIsNone(result)

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_explore_short_result(self, _mock):
        self.agent._react_loop.return_value = "ok"
        result = self.handler.handle_explore()
        self.assertIsNone(result)

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_build_messages_overflow(self, _mock):
        mock_turn = MagicMock()
        mock_turn.role = "user"
        mock_turn.content = "x" * 100000
        self.agent.short_term.get_all_reversed.return_value = [mock_turn]
        self.agent._context.compressed_summary = "previous summary"
        result = self.handler.handle_message("hello")
        self.assertEqual(result, "Hello!")

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_proactive_with_intent(self, _mock):
        intent = ProactiveIntent(
            action="chat", topic_hint="旅行计划",
            reasoning="上次聊到旅行，可以继续"
        )
        result = self.handler.handle_proactive(intent=intent)
        self.assertEqual(result, "Hello!")
        self.agent._react_loop.assert_called_once()
        # Should NOT have called pick_proactive_topic (intent was provided)
        self.agent._pick_proactive_topic.assert_not_called()

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_proactive_without_intent_fallback(self, _mock):
        result = self.handler.handle_proactive()  # no intent
        self.assertEqual(result, "Hello!")
        self.agent._react_loop.assert_called_once()
        # Should fall back to pick_proactive_topic
        self.agent._pick_proactive_topic.assert_called()

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_explore_with_intent(self, _mock):
        self.agent._react_loop.return_value = "我发现了一篇关于机器学习的有趣文章，内容非常有启发性值得大家阅读！"
        intent = ProactiveIntent(
            action="explore", topic_hint="机器学习最新动态",
            reasoning="用户是程序员，可能对ML感兴趣"
        )
        result = self.handler.handle_explore(intent=intent)
        self.assertIsNotNone(result)
        self.agent._pick_proactive_topic.assert_not_called()


if __name__ == "__main__":
    unittest.main()
