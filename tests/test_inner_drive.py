"""Tests for core/inner_drive.py"""
import unittest
from unittest.mock import MagicMock, patch

from core.inner_drive import (
    InnerDriveAgent, InnerDriveResult, ToolRequest,
    EXTERNAL_TOOL_NAMES,
)
from tests.mocks import mock_tool_registry


def _make_memory_mock():
    m = MagicMock()
    m.facts = []
    m.experiences = []
    m.reflections = []
    m.relationship = {"trust": 0.5, "familiarity": 0.5, "intimacy": 0.5, "playfulness": 0.5}
    return m


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


class TestParseDecision(unittest.TestCase):
    def setUp(self):
        self.agent = InnerDriveAgent(
            provider=MagicMock(),
            personality=MagicMock(),
            ltm=MagicMock(),
            retriever=MagicMock(),
            short_term=MagicMock(),
            tool_registry=mock_tool_registry(),
        )

    def test_no_need_explicit(self):
        result = self.agent._parse_decision("决策：不需要外部工具\n理由：只是打招呼")
        self.assertFalse(result.needs_external_tools)

    def test_no_need_NO_TOOLS(self):
        result = self.agent._parse_decision("NO_TOOLS")
        self.assertFalse(result.needs_external_tools)

    def test_needs_web_fetch(self):
        result = self.agent._parse_decision(
            "决策：需要外部工具\n理由：用户提供链接\n工具请求：需要调用 web_fetch 获取 https://example.com"
        )
        self.assertTrue(result.needs_external_tools)
        self.assertTrue(any(t.suggested_tool == "web_fetch" for t in result.tool_requests))

    def test_needs_web_search(self):
        result = self.agent._parse_decision(
            "决策：需要外部工具\n理由：用户想知道最新消息\n工具请求：需要搜索：最新AI新闻"
        )
        self.assertTrue(result.needs_external_tools)
        self.assertTrue(any(t.suggested_tool == "web_search" for t in result.tool_requests))

    def test_chat_no_tools(self):
        result = self.agent._parse_decision("用户只是打招呼，直接回复即可")
        self.assertFalse(result.needs_external_tools)

    def test_url_extraction(self):
        result = self.agent._parse_decision(
            "需要获取 https://example.com/page 和 https://test.com/doc 的内容"
        )
        self.assertTrue(result.needs_external_tools)
        self.assertGreaterEqual(len(result.tool_requests), 1)


class TestAssess(unittest.TestCase):
    def setUp(self):
        self.provider = MagicMock()
        self.provider.generate.return_value = "决策：不需要外部工具\n理由：闲聊"
        self.personality = MagicMock()
        self.personality.config.traits = []
        self.personality.config.name = "TestBot"
        self.personality.emotion.dominant_emotion = "neutral"
        self.personality.emotion.valence = 0.4
        self.personality.emotion.arousal = 0.5
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

    def test_assess_chat(self):
        result = self.agent.assess("你好")
        self.assertFalse(result.needs_external_tools)
        self.provider.generate.assert_called()

    def test_assess_with_url(self):
        self.provider.generate.return_value = (
            "决策：需要外部工具\n理由：用户给了链接\n"
            "工具请求：需要调用 web_fetch 获取 https://example.com/article"
        )
        result = self.agent.assess("看看这个 https://example.com/article")
        self.assertTrue(result.needs_external_tools)

    def test_re_decide(self):
        self.provider.generate.return_value = (
            "决策：需要外部工具\n理由：换个方式\n工具请求：需要搜索 example article"
        )
        result = self.agent.re_decide(
            "看看链接",
            [{"name": "web_fetch", "output": "连接超时"}],
        )
        self.assertTrue(result.needs_external_tools)

    def test_review_sufficient(self):
        """Agent 1 reviews results and decides no more tools needed."""
        self.provider.generate.return_value = "决策：不需要外部工具\n理由：结果足够"
        result = self.agent.review(
            "搜索AI新闻",
            "[调用 1] web_search（成功）:\n找到了5条AI新闻...",
            round_num=1, max_rounds=3,
        )
        self.assertFalse(result.needs_external_tools)

    def test_review_needs_more(self):
        """Agent 1 reviews results and decides more tools needed."""
        self.provider.generate.return_value = (
            "决策：需要外部工具\n理由：搜索结果中有链接\n工具请求：需要调用 web_fetch 获取 https://example.com"
        )
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


class TestExtractToolRequests(unittest.TestCase):
    def setUp(self):
        self.agent = InnerDriveAgent(
            provider=MagicMock(),
            personality=MagicMock(),
            ltm=MagicMock(),
            retriever=MagicMock(),
            short_term=MagicMock(),
            tool_registry=mock_tool_registry(),
        )

    def test_extract_url(self):
        requests = self.agent._extract_tool_requests(
            "需要获取 https://example.com/page 的内容"
        )
        self.assertGreaterEqual(len(requests), 1)
        self.assertEqual(requests[0].suggested_tool, "web_fetch")

    def test_extract_search(self):
        requests = self.agent._extract_tool_requests(
            "需要搜索：最新AI新闻，了解最近动态"
        )
        self.assertGreaterEqual(len(requests), 1)
        self.assertEqual(requests[0].suggested_tool, "web_search")
        self.assertIn("最新AI新闻", requests[0].description)

    def test_extract_file(self):
        requests = self.agent._extract_tool_requests(
            "需要读取：D:\\文档\\notes.txt"
        )
        self.assertGreaterEqual(len(requests), 1)
        self.assertEqual(requests[0].suggested_tool, "read_file")

    def test_multiple_requests(self):
        requests = self.agent._extract_tool_requests(
            "需要获取 https://a.com 的内容，同时搜索：test query"
        )
        self.assertGreaterEqual(len(requests), 2)


if __name__ == "__main__":
    unittest.main()
