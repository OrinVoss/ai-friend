"""Tests for core/inner_drive.py"""
import unittest
from unittest.mock import MagicMock

from core.inner_drive import (
    InnerDriveAgent, InnerDriveResult, ToolRequest,
    ProactiveIntent,
)
from tools.traits import EXTERNAL_TOOL_NAMES
from tests.mocks import mock_tool_registry


def _make_memory_mock():
    m = MagicMock()
    m.facts = []
    m.experiences = []
    m.reflections = []
    m.relationship = {"trust": 0.5, "familiarity": 0.5, "intimacy": 0.5, "playfulness": 0.5}
    return m


def _no_tools_json():
    return (
        '{"needs_external_tools": false, "reasoning": "只是闲聊", "summary": "", '
        '"tool_requests": []}'
    )


def _fetch_json(url="https://example.com"):
    return (
        '{"needs_external_tools": true, "reasoning": "需要获取网页", "summary": "", '
        '"tool_requests": [{"description": "获取 %s", "suggested_tool": "web_fetch", '
        '"params_hint": {"url": "%s"}}]}' % (url, url)
    )


def _search_json(query="最新AI新闻"):
    return (
        '{"needs_external_tools": true, "reasoning": "需要搜索", "summary": "", '
        '"tool_requests": [{"description": "搜索 %s", "suggested_tool": "web_search", '
        '"params_hint": {"query": "%s"}}]}' % (query, query)
    )


class TestInnerDriveResult(unittest.TestCase):
    def test_default_no_tools(self):
        r = InnerDriveResult()
        self.assertFalse(r.needs_external_tools)
        self.assertEqual(r.tool_requests, [])

    def test_with_tools(self):
        r = InnerDriveResult(
            needs_external_tools=True,
            reasoning="需要获取网页",
            tool_requests=[ToolRequest(description="fetch url", suggested_tool="web_fetch")],
        )
        self.assertTrue(r.needs_external_tools)
        self.assertEqual(len(r.tool_requests), 1)


class TestParseJsonDecision(unittest.TestCase):
    def setUp(self):
        self.agent = InnerDriveAgent(
            provider=MagicMock(),
            personality=MagicMock(),
            ltm=MagicMock(),
            retriever=MagicMock(),
            short_term=MagicMock(),
            tool_registry=mock_tool_registry(),
        )

    def test_no_tools(self):
        result = self.agent._parse_json_decision(_no_tools_json())
        self.assertIsNotNone(result)
        self.assertFalse(result.needs_external_tools)
        self.assertEqual(result.reasoning, "只是闲聊")

    def test_needs_web_fetch(self):
        result = self.agent._parse_json_decision(_fetch_json("https://example.com"))
        self.assertTrue(result.needs_external_tools)
        self.assertEqual(len(result.tool_requests), 1)
        self.assertEqual(result.tool_requests[0].suggested_tool, "web_fetch")
        self.assertIn("https://example.com", result.tool_requests[0].description)

    def test_needs_web_search(self):
        result = self.agent._parse_json_decision(_search_json("最新AI新闻"))
        self.assertTrue(result.needs_external_tools)
        self.assertEqual(len(result.tool_requests), 1)
        self.assertEqual(result.tool_requests[0].suggested_tool, "web_search")
        self.assertIn("最新AI新闻", result.tool_requests[0].description)

    def test_multiple_requests(self):
        text = (
            '{"needs_external_tools": true, "reasoning": "需要多个工具", "summary": "", '
            '"tool_requests": ['
            '{"description": "获取 https://a.com", "suggested_tool": "web_fetch", "params_hint": {"url": "https://a.com"}}, '
            '{"description": "搜索 test query", "suggested_tool": "web_search", "params_hint": {"query": "test query"}}'
            ']}'
        )
        result = self.agent._parse_json_decision(text)
        self.assertTrue(result.needs_external_tools)
        self.assertEqual(len(result.tool_requests), 2)
        tools = [r.suggested_tool for r in result.tool_requests]
        self.assertIn("web_fetch", tools)
        self.assertIn("web_search", tools)

    def test_strips_think_blocks(self):
        text = '<think>让我想想</think>' + _no_tools_json()
        result = self.agent._parse_json_decision(text)
        self.assertIsNotNone(result)
        self.assertFalse(result.needs_external_tools)

    def test_invalid_json_returns_none(self):
        result = self.agent._parse_json_decision("这不是 JSON")
        self.assertIsNone(result)

    def test_missing_needs_tools_defaults_to_false(self):
        result = self.agent._parse_json_decision('{"reasoning": "缺少 needs_external_tools"}')
        self.assertIsNotNone(result)
        self.assertFalse(result.needs_external_tools)

    def test_empty_tool_requests(self):
        text = '{"needs_external_tools": false, "reasoning": "x", "summary": "y"}'
        result = self.agent._parse_json_decision(text)
        self.assertIsNotNone(result)
        self.assertEqual(result.tool_requests, [])


class TestAssess(unittest.TestCase):
    def setUp(self):
        self.provider = MagicMock()
        self.provider.generate.return_value = _no_tools_json()
        self.personality = MagicMock()
        self.personality.config.traits = []
        self.personality.config.name = "TestBot"
        self.personality.emotion.dominant_emotion = "neutral"
        self.personality.emotion.valence = 0.4
        self.personality.emotion.arousal = 0.5
        self.personality.emotion.to_prompt_summary.return_value = {
            "dominant_emotion": "neutral",
            "mood": "平静",
            "primary_hint": "",
            "valence": 0.4,
            "arousal": 0.5,
            "valence_desc": "积极",
            "arousal_desc": "平衡",
            "behavior": "你心情平静。说话正常，不兴奋也不低落。",
        }
        self.retriever = MagicMock()
        self.retriever.retrieve_for_query.return_value = _make_memory_mock()
        self.short_term = MagicMock()
        self.short_term.format_for_prompt.return_value = ""

        self.agent = InnerDriveAgent(
            provider=self.provider,
            personality=self.personality,
            ltm=MagicMock(),
            retriever=self.retriever,
            short_term=self.short_term,
            tool_registry=mock_tool_registry(),
        )

    def test_assess_chat_short_input_goes_through_llm(self):
        """Short chat input goes through full Agent 1 reasoning like any other
        input (the short-input skip was removed 2026-07-16 — the API is cheap
        and keyword misclassification wasn't worth the saved call)."""
        result = self.agent.assess("你好")
        self.provider.generate.assert_called()
        self.assertFalse(result.needs_external_tools)
        self.assertIn("关系", result.context_summary)

    def test_context_summary_populated(self):
        """Assess should return a non-empty memory/relationship summary."""
        result = self.agent.assess("今天天气不错")
        self.assertTrue(result.context_summary)
        self.assertIn("信任", result.context_summary)

    def test_assess_with_url(self):
        self.provider.generate.return_value = _fetch_json("https://example.com/article")
        result = self.agent.assess("看看这个 https://example.com/article")
        self.assertTrue(result.needs_external_tools)
        self.assertEqual(result.tool_requests[0].suggested_tool, "web_fetch")

    def test_re_decide(self):
        self.provider.generate.return_value = _search_json("example article")
        result = self.agent.re_decide(
            "看看链接",
            [{"name": "web_fetch", "output": "连接超时"}],
        )
        self.assertTrue(result.needs_external_tools)
        self.assertEqual(result.tool_requests[0].suggested_tool, "web_search")

    def test_review_sufficient(self):
        """Agent 1 reviews results and decides no more tools needed."""
        self.provider.generate.return_value = _no_tools_json()
        result = self.agent.review(
            "搜索AI新闻",
            "[调用 1] web_search（成功）:\n找到了5条AI新闻...",
            round_num=1, max_rounds=3,
        )
        self.assertFalse(result.needs_external_tools)

    def test_review_needs_more(self):
        """Agent 1 reviews results and decides more tools needed."""
        self.provider.generate.return_value = _fetch_json("https://example.com")
        result = self.agent.review(
            "搜索AI新闻",
            "[调用 1] web_search（成功）:\n找到了链接 https://example.com",
            round_num=1, max_rounds=3,
        )
        self.assertTrue(result.needs_external_tools)

    def test_review_max_rounds(self):
        """Agent 1 should stop at max rounds."""
        result = self.agent.review(
            "搜索AI新闻",
            "[调用 1] web_search（成功）:\n找到了...",
            round_num=3, max_rounds=3,
        )
        self.assertFalse(result.needs_external_tools)
        self.assertIn("最大轮次", result.reasoning)

    def test_assess_agent3_intent_approved(self):
        """Agent 1 should approve a reasonable Agent 3 intent."""
        self.provider.generate.return_value = _fetch_json("https://example.com")
        result = self.agent.assess_agent3_intent(
            user_input="有点无聊",
            intent="fetch_url",
            intent_description="想分享一个有趣的链接",
            intent_target="https://example.com",
        )
        self.assertTrue(result.needs_external_tools)
        self.assertEqual(result.tool_requests[0].suggested_tool, "web_fetch")

    def test_assess_agent3_intent_rejected(self):
        """Agent 1 should reject an unreasonable Agent 3 intent."""
        self.provider.generate.return_value = _no_tools_json()
        result = self.agent.assess_agent3_intent(
            user_input="我现在很忙",
            intent="play_music",
            intent_description="放首歌给用户听",
            intent_target="",
        )
        self.assertFalse(result.needs_external_tools)

    def test_assess_agent3_intent_parse_failure(self):
        """If Agent 1 cannot parse the decision, default to no tools."""
        self.provider.generate.return_value = "invalid json"
        result = self.agent.assess_agent3_intent(
            user_input="你好",
            intent="search_web",
            intent_description="搜索天气",
            intent_target="今天天气",
        )
        self.assertFalse(result.needs_external_tools)


class TestProactiveIntent(unittest.TestCase):
    def test_default_silent(self):
        pi = ProactiveIntent()
        self.assertEqual(pi.action, "silent")
        self.assertEqual(pi.topic_hint, "")

    def test_chat_intent(self):
        pi = ProactiveIntent(action="chat", topic_hint="天气", reasoning="用户好久没说话")
        self.assertEqual(pi.action, "chat")
        self.assertEqual(pi.topic_hint, "天气")

    def test_explore_intent(self):
        pi = ProactiveIntent(action="explore", topic_hint="AI新闻", reasoning="想了解最新动态")
        self.assertEqual(pi.action, "explore")


class TestParseProactiveIntent(unittest.TestCase):
    def setUp(self):
        self.agent = InnerDriveAgent(
            provider=MagicMock(),
            personality=MagicMock(),
            ltm=MagicMock(),
            retriever=MagicMock(),
            short_term=MagicMock(),
            tool_registry=mock_tool_registry(),
        )

    def test_parse_chat(self):
        intent = self.agent._parse_proactive_intent(
            "决策：聊天\n话题：天气\n理由：用户好久没说话了"
        )
        self.assertEqual(intent.action, "chat")
        self.assertIn("天气", intent.topic_hint)

    def test_parse_explore(self):
        intent = self.agent._parse_proactive_intent(
            "决策：探索\n话题：最新AI新闻\n理由：想知道发生了什么"
        )
        self.assertEqual(intent.action, "explore")

    def test_parse_silent(self):
        intent = self.agent._parse_proactive_intent(
            "决策：沉默\n理由：用户说了晚安"
        )
        self.assertEqual(intent.action, "silent")

    def test_parse_default_chat(self):
        intent = self.agent._parse_proactive_intent(
            "我想跟用户聊聊最近的事情"
        )
        self.assertEqual(intent.action, "chat")


class TestAssessProactive(unittest.TestCase):
    def setUp(self):
        self.provider = MagicMock()
        self.provider.generate.return_value = (
            "决策：聊天\n话题：旅行\n理由：上次聊到旅行很开心"
        )
        self.personality = MagicMock()
        self.personality.config.traits = []
        self.personality.config.name = "TestBot"
        self.personality.config.interests = ["music"]
        self.personality.emotion.dominant_emotion = "engaged"
        self.personality.emotion.valence = 0.6
        self.personality.emotion.arousal = 0.5
        self.personality.emotion.to_prompt_summary.return_value = {
            "dominant_emotion": "engaged",
            "mood": "投入",
            "primary_hint": "",
            "valence": 0.6,
            "arousal": 0.5,
            "valence_desc": "积极",
            "arousal_desc": "平衡",
            "behavior": "你心情平静。说话正常，不兴奋也不低落。",
        }
        self.retriever = MagicMock()
        self.retriever.retrieve_for_query.return_value = _make_memory_mock()
        self.short_term = MagicMock()
        self.short_term.format_for_prompt.return_value = "用户：今天天气真好"

        self.agent = InnerDriveAgent(
            provider=self.provider,
            personality=self.personality,
            ltm=MagicMock(),
            retriever=self.retriever,
            short_term=self.short_term,
            tool_registry=mock_tool_registry(),
        )

    def test_assess_proactive_chat(self):
        intent = self.agent.assess_proactive(300)
        self.assertEqual(intent.action, "chat")
        self.assertEqual(intent.topic_hint, "旅行")
        self.provider.generate.assert_called_once()

    def test_assess_proactive_explore(self):
        self.provider.generate.return_value = (
            "决策：探索\n话题：最新音乐动态\n理由：用户喜欢音乐"
        )
        intent = self.agent.assess_proactive(600)
        self.assertEqual(intent.action, "explore")
        self.assertIn("音乐", intent.topic_hint)

    def test_assess_proactive_silent(self):
        self.provider.generate.return_value = (
            "决策：沉默\n理由：深夜了，不适合打扰"
        )
        intent = self.agent.assess_proactive(1800)
        self.assertEqual(intent.action, "silent")


if __name__ == "__main__":
    unittest.main()
