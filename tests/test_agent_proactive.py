"""Tests for Agent proactive methods (part of #125)."""
import os
import tempfile
import unittest
from unittest.mock import ANY, MagicMock, patch

from core.inner_drive import ProactiveIntent


class TestAgentProactive(unittest.TestCase):
    """Test Agent.decide_proactive_action and process_proactive/explore with intent."""

    @classmethod
    def setUpClass(cls):
        cls._tmpdir = tempfile.mkdtemp()

    def setUp(self):
        from core.agent import Agent
        from config import Config

        cfg = Config()
        cfg.max_tokens = 512
        cfg.personality_file = os.path.join(self._tmpdir, "role.json")

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
        ltm = MagicMock()
        retriever = MagicMock()
        consolidator = MagicMock()
        short_term = MagicMock()
        short_term.get_all_reversed.return_value = []
        short_term.format_for_prompt.return_value = ""

        self.agent = Agent(
            personality=personality,
            provider=provider,
            ltm=ltm,
            retriever=retriever,
            consolidator=consolidator,
            short_term=short_term,
            config=cfg,
        )
        self.agent._tool_registry = MagicMock()

    def test_decide_proactive_action_returns_intent(self):
        """decide_proactive_action should call inner drive and return ProactiveIntent."""
        mock_inner = MagicMock()
        mock_inner.assess_proactive.return_value = ProactiveIntent(
            action="chat", topic_hint="旅行",
            reasoning="用户好久没说话，关系不错"
        )
        self.agent._messages._inner_drive = mock_inner

        intent = self.agent.decide_proactive_action(300)
        self.assertEqual(intent.action, "chat")
        self.assertEqual(intent.topic_hint, "旅行")
        # #177: Agent 把 ProactivityManager 的近期话题传给 inner drive
        mock_inner.assess_proactive.assert_called_once_with(300, recent_topics=ANY)

    def test_decide_proactive_action_silent(self):
        """inner drive may choose silent."""
        mock_inner = MagicMock()
        mock_inner.assess_proactive.return_value = ProactiveIntent(
            action="silent", reasoning="深夜不适合打扰"
        )
        self.agent._messages._inner_drive = mock_inner

        intent = self.agent.decide_proactive_action(1800)
        self.assertEqual(intent.action, "silent")

    def test_process_proactive_with_intent(self):
        """process_proactive should pass intent to message handler."""
        intent = ProactiveIntent(
            action="chat", topic_hint="天气",
            reasoning="用户有空"
        )
        self.agent._messages.handle_proactive = MagicMock(return_value="今天天气不错！")
        result = self.agent.process_proactive(intent=intent)
        self.assertEqual(result, "今天天气不错！")
        self.agent._messages.handle_proactive.assert_called_once_with(
            on_token=None, intent=intent
        )

    def test_process_proactive_without_intent(self):
        """process_proactive without intent should still work (backward compat)."""
        self.agent._messages.handle_proactive = MagicMock(return_value="嗨！")
        result = self.agent.process_proactive()
        self.assertEqual(result, "嗨！")
        self.agent._messages.handle_proactive.assert_called_once_with(
            on_token=None, intent=None
        )

    def test_process_explore_with_intent(self):
        """process_explore should pass intent to message handler."""
        intent = ProactiveIntent(
            action="explore", topic_hint="AI新闻",
            reasoning="用户是程序员"
        )
        self.agent._messages.handle_explore = MagicMock(
            return_value="我发现了一篇关于AI的有趣文章，内容非常有深度值得分享给大家！"
        )
        result = self.agent.process_explore(intent=intent)
        self.assertIsNotNone(result)
        self.agent._messages.handle_explore.assert_called_once_with(intent=intent)

    def test_process_explore_without_intent(self):
        """process_explore without intent should still work (backward compat)."""
        self.agent._messages.handle_explore = MagicMock(return_value=None)
        result = self.agent.process_explore()
        self.assertIsNone(result)

    def test_sleep_state_file_uses_session_id(self):
        """Agent should namespace sleep state file by session_id."""
        self.assertEqual(self.agent._sleep._session_id, "default")
        self.assertTrue(
            self.agent._sleep._sleep_state_file.endswith(".sleep_state.default")
        )


class TestAgentSessionId(unittest.TestCase):
    """Test that Agent accepts and uses explicit session_id."""

    def setUp(self):
        from core.agent import Agent
        from config import Config

        self.cfg = Config()
        self.cfg.max_tokens = 512
        self.cfg.personality_file = "personalities/default.json"
        self.cfg.db_path = ":memory:"

        personality = MagicMock()
        personality.config.name = "TestBot"
        personality.config.interests = []
        personality.config.traits = []
        personality.emotion.dominant_emotion = "neutral"
        personality.emotion.valence = 0.4
        personality.emotion.arousal = 0.5
        personality.emotion.anger = 0.0
        personality.emotion.sadness = 0.0
        personality.emotion.disgust = 0.0
        personality.emotion.resentment = 0.0
        personality.emotion.emotion_events = []

        self.agent = Agent(
            personality=personality,
            provider=MagicMock(),
            ltm=MagicMock(),
            retriever=MagicMock(),
            consolidator=MagicMock(),
            short_term=MagicMock(),
            config=self.cfg,
            session_id="小星",
        )

    def test_sleep_state_file_uses_custom_session_id(self):
        self.assertEqual(self.agent._sleep._session_id, "小星")
        self.assertTrue(
            self.agent._sleep._sleep_state_file.endswith(".sleep_state.小星")
        )


if __name__ == "__main__":
    unittest.main()
