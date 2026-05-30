"""Tests for core/message_handler.py"""
import unittest
from unittest.mock import MagicMock, patch

from core.message_handler import MessageHandler
from tests.mocks import mock_tool_registry


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
        self.agent.retriever.retrieve_for_query.return_value = MagicMock()
        self.agent.ltm.repo.insert_turn = MagicMock()
        self.agent.personality.config.name = "TestBot"
        self.agent.personality.config.interests = ["music", "art"]
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


if __name__ == "__main__":
    unittest.main()
