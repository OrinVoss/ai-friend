"""H-05: 主动搭话/自由探索轮必须跳过情绪后处理，正常用户轮保持默认。"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.message_handler import MessageHandler
from core.inner_drive import ProactiveIntent
from tests.mocks import mock_tool_registry


def _make_handler_agent():
    """MagicMock agent，与 tests/test_message_handler.py 的 setUp 同款。"""
    agent = MagicMock()
    agent._sleeping = False
    agent.turn_count = 0
    agent._consecutive_negative = 0
    agent._tool_call_history = []
    agent._tool_registry = mock_tool_registry()
    agent._context = MagicMock()
    agent._context.compressed_summary = ""
    agent.short_term.get_all_reversed.return_value = []
    agent.short_term.format_for_prompt.return_value = ""
    agent.short_term.get_all.return_value = []
    agent.retriever.retrieve_for_query.return_value = MagicMock(
        facts=[], experiences=[], reflections=[],
        relationship={"trust": 0.5, "familiarity": 0.5,
                      "intimacy": 0.5, "playfulness": 0.5})
    agent.personality.config.name = "TestBot"
    agent.personality.config.interests = ["music", "art"]
    agent.personality.config.traits = []
    agent.personality.emotion.dominant_emotion = "neutral"
    agent.personality.emotion.to_prompt_summary.return_value = {
        "dominant_emotion": "neutral", "valence": 0.4, "arousal": 0.5,
    }
    agent._react_loop.return_value = "Hello!"
    agent._pick_proactive_topic.return_value = "聊聊天气"
    agent.provider.generate.return_value = "NO_TOOLS"
    agent.config.prompt_cache_ttl_seconds = 60
    agent.config.conversation_examples_max_turns = 3
    agent.config.use_memory_agent = False
    return agent


class TestProactiveSkipsPostProcess(unittest.TestCase):
    """handler 层：断言 _react_loop 调用带上了 skip_post_process=True。"""

    def setUp(self):
        self.agent = _make_handler_agent()
        self.handler = MessageHandler(self.agent)

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_proactive_passes_skip_post_process(self, _mock):
        self.handler.handle_proactive()
        _, kwargs = self.agent._react_loop.call_args
        self.assertTrue(kwargs.get("skip_post_process"))

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_handle_explore_passes_skip_post_process(self, _mock):
        self.agent._react_loop.return_value = (
            "我发现了一篇关于机器学习的有趣文章，内容非常有启发性值得大家阅读！"
        )
        result = self.handler.handle_explore()
        self.assertIsNotNone(result)
        _, kwargs = self.agent._react_loop.call_args
        self.assertTrue(kwargs.get("skip_post_process"))

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_run_agent3_keeps_post_process(self, _mock):
        """正常用户路径 _run_agent3 不传 skip_post_process（保持默认 False）。"""
        self.handler._run_agent3("你好", None, None)
        _, kwargs = self.agent._react_loop.call_args
        self.assertFalse(kwargs.get("skip_post_process", False))


class TestProactiveEndToEnd(unittest.TestCase):
    """真实 Agent + 真实 _react_loop：proactive 轮不再做情绪分析。"""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()

    def setUp(self):
        from core.agent import Agent
        from config import Config

        cfg = Config()
        cfg.max_tokens = 512
        cfg.personality_file = os.path.join(self._tmpdir, "personality.json")

        personality = MagicMock()
        personality.config.name = "TestBot"
        personality.config.interests = ["music"]
        personality.config.traits = []
        personality.emotion.dominant_emotion = "neutral"
        personality.emotion.valence = 0.4
        personality.emotion.arousal = 0.5
        personality.emotion.anger = 0.0
        personality.emotion.sadness = 0.0
        personality.emotion.disgust = 0.0
        personality.emotion.resentment = 0.0
        personality.emotion.emotion_events = []

        provider = MagicMock()
        provider.generate.return_value = "今天天气真不错，想跟你聊聊！"

        short_term = MagicMock()
        short_term.get_all_reversed.return_value = []
        short_term.format_for_prompt.return_value = ""
        # short_term 里残留上一轮真实用户消息——修复前 proactive 轮会对它
        # 再做一次 analyze_sentiment + 情绪偏移
        old_turn = MagicMock()
        old_turn.role = "user"
        old_turn.content = "上一轮用户说的话"
        short_term.get_all.return_value = [old_turn]

        self.agent = Agent(
            personality=personality,
            provider=provider,
            ltm=MagicMock(),
            retriever=MagicMock(),
            consolidator=MagicMock(),
            short_term=short_term,
            config=cfg,
        )
        self.agent._tool_registry = MagicMock()

    @patch('prompts.system.build_system_prompt', return_value="mock prompt")
    def test_proactive_does_not_analyze_sentiment(self, _mock):
        intent = ProactiveIntent(action="chat", topic_hint="天气", reasoning="测试")
        result = self.agent.process_proactive(intent=intent)
        self.assertEqual(result, "今天天气真不错，想跟你聊聊！")
        # _process_emotion 被跳过：不再分析旧消息、不再施加情绪偏移
        self.agent.consolidator.analyze_sentiment.assert_not_called()
        self.agent.personality.apply_emotional_shift.assert_not_called()


if __name__ == "__main__":
    unittest.main()
