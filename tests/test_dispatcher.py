"""Tests for core/dispatcher.py"""
import unittest

from core.dispatcher import (
    parse_tool_calls, execute_tool_calls, format_tool_results,
    contains_fake_action, _normalize_args,
)
from tests.mocks import mock_tool_registry


class TestParseToolCalls(unittest.TestCase):
    def test_single_call(self):
        text = 'Hello <tool_call>{"name": "recall", "arguments": {"query": "test"}}</tool_call> world'
        cleaned, calls = parse_tool_calls(text)
        self.assertEqual(cleaned, "Hello  world")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "recall")
        self.assertEqual(calls[0]["arguments"]["query"], "test")

    def test_multiple_calls(self):
        text = (
            'First <tool_call>{"name": "a", "arguments": {}}</tool_call> '
            'Second <tool_call>{"name": "b", "arguments": {}}</tool_call>'
        )
        _, calls = parse_tool_calls(text)
        self.assertEqual(len(calls), 2)

    def test_no_calls(self):
        text = "Just a normal response"
        cleaned, calls = parse_tool_calls(text)
        self.assertEqual(cleaned, text)
        self.assertEqual(len(calls), 0)

    def test_think_stripping(self):
        text = '<think>some reasoning</think>Response <tool_call>{"name": "test", "arguments": {}}</tool_call>'
        cleaned, calls = parse_tool_calls(text)
        self.assertNotIn("some reasoning", cleaned)
        self.assertIn("Response", cleaned)
        self.assertEqual(len(calls), 1)

    def test_bare_json_fallback(self):
        text = '{"name": "web_search", "arguments": {"query": "news"}}'
        cleaned, calls = parse_tool_calls(text)
        self.assertEqual(cleaned, "")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "web_search")

    def test_invalid_json_silent(self):
        text = '<tool_call>{invalid json}</tool_call> normal text'
        cleaned, calls = parse_tool_calls(text)
        self.assertEqual(cleaned.strip(), "normal text")
        self.assertEqual(len(calls), 0)

    def test_missing_name(self):
        text = '<tool_call>{"arguments": {"q": "x"}}</tool_call>'
        _, calls = parse_tool_calls(text)
        self.assertEqual(len(calls), 0)

    def test_empty_response(self):
        cleaned, calls = parse_tool_calls("")
        self.assertEqual(cleaned, "")
        self.assertEqual(len(calls), 0)

    def test_nested_tags(self):
        text = '<tool_call>{"name": "outer", "arguments": {"desc": "inner xml"}}</tool_call>'
        _, calls = parse_tool_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["name"], "outer")


class TestExecuteToolCalls(unittest.TestCase):
    def setUp(self):
        self.registry = mock_tool_registry()

    def test_execute_single(self):
        calls = [{"name": "web_search", "arguments": {"query": "test"}}]
        results = execute_tool_calls(self.registry, calls)
        self.assertEqual(len(results), 1)
        self.assertTrue(results[0]["success"])

    def test_execute_unknown_tool(self):
        reg = mock_tool_registry()
        reg.get.side_effect = None  # remove side_effect
        reg.get.return_value = None  # no tool found
        calls = [{"name": "nonexistent", "arguments": {}}]
        results = execute_tool_calls(reg, calls)
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["success"])

    def test_execute_multiple(self):
        calls = [
            {"name": "web_search", "arguments": {"query": "a"}},
            {"name": "web_fetch", "arguments": {"url": "https://x.com"}},
        ]
        results = execute_tool_calls(self.registry, calls)
        self.assertEqual(len(results), 2)


class TestFormatToolResults(unittest.TestCase):
    def test_success_format(self):
        results = [{"name": "web_search", "success": True, "output": "found results"}]
        formatted = format_tool_results(results)
        self.assertIn("web_search", formatted)
        self.assertIn("成功", formatted)
        self.assertIn("found results", formatted)

    def test_failure_format(self):
        results = [{"name": "web_fetch", "success": False, "output": "timeout"}]
        formatted = format_tool_results(results)
        self.assertIn("失败", formatted)

    def test_mixed_format(self):
        results = [
            {"name": "a", "success": True, "output": "ok"},
            {"name": "b", "success": False, "output": "fail"},
        ]
        formatted = format_tool_results(results)
        self.assertIn("成功", formatted)
        self.assertIn("失败", formatted)

    def test_iron_law_injection(self):
        results = [{"name": "test", "success": True, "output": "data"}]
        formatted = format_tool_results(results)
        self.assertIn("铁律", formatted)


class TestContainsFakeAction(unittest.TestCase):
    def test_completion_claim(self):
        self.assertTrue(contains_fake_action("已发送消息"))

    def test_narrative_tool_description(self):
        self.assertTrue(contains_fake_action("我调用了web_fetch读取了链接"))

    def test_search_claim(self):
        self.assertTrue(contains_fake_action("我搜索了一下相关内容"))

    def test_tool_result_claim(self):
        self.assertTrue(contains_fake_action("工具返回了以下内容"))

    def test_legitimate_text(self):
        self.assertFalse(contains_fake_action("今天天气真好"))
        self.assertFalse(contains_fake_action("用户说他想看电影"))

    def test_auto_fetch_claim(self):
        self.assertTrue(contains_fake_action("已发送消息通知"))
        self.assertTrue(contains_fake_action("调用了web_fetch读取你给的链接"))
        self.assertTrue(contains_fake_action("读取了那个网页"))
        self.assertTrue(contains_fake_action("调了工具"))


class TestNormalizeArgs(unittest.TestCase):
    def test_query_alias(self):
        args = {"search": "hello"}
        result = _normalize_args(args)
        self.assertEqual(result["query"], "hello")
        self.assertNotIn("search", result)

    def test_content_alias(self):
        args = {"text": "message"}
        result = _normalize_args(args)
        self.assertEqual(result["content"], "message")
        self.assertNotIn("text", result)

    def test_name_alias(self):
        args = {"who": "Alice"}
        result = _normalize_args(args)
        self.assertEqual(result["name"], "Alice")
        self.assertNotIn("who", result)

    def test_existing_field_kept(self):
        args = {"query": "hello", "keyword": "world"}
        result = _normalize_args(args)
        self.assertEqual(result["query"], "hello")
        # keyword stays because query already exists (group skipped)
        self.assertIn("keyword", result)


if __name__ == "__main__":
    unittest.main()
