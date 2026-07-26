"""Tests for core/tool_agent.py"""
import unittest
from unittest.mock import MagicMock

from core.tool_agent import ToolAgent, ToolAgentResult, ToolAttemptTracker, ToolCallRecord
from tests.mocks import mock_tool_registry


class TestToolAgentResult(unittest.TestCase):
    def test_empty(self):
        r = ToolAgentResult()
        self.assertFalse(r.has_results)
        self.assertFalse(r.any_success)

    def test_with_success(self):
        r = ToolAgentResult(total_calls=2, success_count=2)
        r.records = [ToolCallRecord(name="web_fetch", arguments={}, success=True, output="ok")]
        self.assertTrue(r.has_results)
        self.assertTrue(r.any_success)

    def test_all_failed(self):
        r = ToolAgentResult(total_calls=1, success_count=0)
        r.records = [ToolCallRecord(name="web_fetch", arguments={}, success=False, output="timeout")]
        self.assertTrue(r.has_results)
        self.assertFalse(r.any_success)


class TestToolAttemptTracker(unittest.TestCase):
    def test_initial_state(self):
        t = ToolAttemptTracker()
        self.assertEqual(t.round_number, 0)
        self.assertEqual(t.total_attempts, 0)
        self.assertTrue(t.can_retry_in_round)
        self.assertTrue(t.can_start_new_round)
        self.assertFalse(t.is_exhausted)

    def test_retry_limit(self):
        t = ToolAttemptTracker()
        t.retry_count = 3
        self.assertFalse(t.can_retry_in_round)

    def test_round_limit(self):
        t = ToolAttemptTracker()
        t.round_number = 3
        t.total_attempts = 9
        self.assertFalse(t.can_start_new_round)
        self.assertTrue(t.is_exhausted)

    def test_counts(self):
        t = ToolAttemptTracker()
        t.round_number = 1
        t.retry_count = 2
        t.total_attempts = 5
        self.assertTrue(t.can_retry_in_round)
        self.assertTrue(t.can_start_new_round)
        self.assertFalse(t.is_exhausted)


class TestToolAgent(unittest.TestCase):
    def setUp(self):
        self.provider = MagicMock()
        self.provider.generate.return_value = "NO_TOOLS"
        self.registry = mock_tool_registry()
        self.agent = ToolAgent(provider=self.provider, tool_registry=self.registry)

    def test_init_uses_injected_registry(self):
        # 注册表由调用方装配（message_handler._make_external_registry 已过滤为
        # 仅外部工具），ToolAgent 不再自行过滤，直接使用注入的 registry
        self.assertIs(self.agent._registry, self.registry)

    def test_run_empty_input_returns_empty(self):
        result = self.agent.run("hello")
        self.assertFalse(result.has_results)

    def test_run_with_request(self):
        self.provider.generate.return_value = (
            '<tool_call>\n'
            '{"name": "web_fetch", "arguments": {"url": "https://example.com"}}\n'
            '</tool_call>'
        )
        result = self.agent.run_with_request("需要获取 https://example.com 的内容")
        self.assertTrue(result.has_results)

    def test_run_with_request_retry(self):
        call_count = [0]

        def mock_generate(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                return "invalid response"
            return (
                '<tool_call>\n'
                '{"name": "web_search", "arguments": {"query": "test"}}\n'
                '</tool_call>'
            )

        self.provider.generate.side_effect = mock_generate
        result = self.agent.run_with_request("搜索 test", max_retries=3)
        self.assertTrue(result.has_results)
        self.assertEqual(call_count[0], 3)

    def test_format_for_phase2(self):
        result = ToolAgentResult(total_calls=1, success_count=1)
        result.records = [
            ToolCallRecord(name="web_search", arguments={}, success=True, output="results here")
        ]
        formatted = self.agent.format_for_phase2(result)
        self.assertIn("web_search", formatted)
        self.assertIn("results here", formatted)

    def test_format_for_phase2_empty(self):
        formatted = self.agent.format_for_phase2(ToolAgentResult())
        self.assertEqual(formatted, "")

    def test_format_for_phase2_failure(self):
        result = ToolAgentResult(total_calls=1, success_count=0)
        result.records = [
            ToolCallRecord(name="web_fetch", arguments={}, success=False, output="连接超时")
        ]
        formatted = self.agent.format_for_phase2(result)
        self.assertIn("失败", formatted)

    def test_format_for_phase2_single_request_unchanged(self):
        """MH-002: single request output keeps the old flat format."""
        result = ToolAgentResult(total_calls=2, success_count=2)
        result.records = [
            ToolCallRecord(name="web_search", arguments={}, success=True,
                           output="ok", request="搜索新闻"),
            ToolCallRecord(name="web_fetch", arguments={}, success=True,
                           output="page", request="搜索新闻"),
        ]
        formatted = self.agent.format_for_phase2(result)
        self.assertNotIn("【请求", formatted)
        self.assertIn("=== 铁律 ===", formatted)

    def test_format_for_phase2_multi_request_groups(self):
        """MH-002: multiple requests are grouped with headers."""
        result = ToolAgentResult(total_calls=2, success_count=1)
        result.records = [
            ToolCallRecord(name="web_search", arguments={}, success=True,
                           output="news results", request="搜索最近的 AI 新闻"),
            ToolCallRecord(name="web_fetch", arguments={}, success=False,
                           output="timeout", request="读取 https://example.com"),
        ]
        formatted = self.agent.format_for_phase2(result)
        self.assertIn("【请求：搜索最近的 AI 新闻】", formatted)
        self.assertIn("【请求：读取 https://example.com】", formatted)
        self.assertIn("news results", formatted)
        self.assertIn("timeout", formatted)
        # Iron rule appears exactly once at the end
        self.assertEqual(formatted.count("=== 铁律 ==="), 1)

    def test_non_retryable_error_gives_up_early(self):
        """A param_error from a tool should not waste retry budget."""
        self.provider.generate.return_value = (
            '<tool_call>\n{"name": "web_search", "arguments": {"query": "x"}}\n</tool_call>'
        )
        # Patch registry.get() to return a mock that yields a non-retryable failure.
        mock_tool = MagicMock()
        from tools.traits import ToolResult, ERROR_TYPE_PARAM_ERROR
        mock_tool.execute.return_value = ToolResult.fail(
            "bad param", error_type=ERROR_TYPE_PARAM_ERROR, retryable=False
        )
        mock_tool.timeout_seconds = 30.0
        mock_tool.parameters_schema.return_value = {"type": "object", "properties": {}}
        mock_tool.name.return_value = "web_search"
        self.registry.get.side_effect = None
        self.registry.get.return_value = mock_tool

        result = self.agent.run_with_request("搜索 x", max_retries=3)
        self.assertFalse(result.any_success)
        # Provider should only be called once because the failure is non-retryable.
        self.assertEqual(self.provider.generate.call_count, 1)

    def test_retryable_error_retries(self):
        """A network_error should retry up to max_retries."""
        call_count = [0]

        def mock_generate(*args, **kwargs):
            call_count[0] += 1
            return (
                '<tool_call>\n{"name": "web_search", "arguments": {"query": "x"}}\n</tool_call>'
            )

        self.provider.generate.side_effect = mock_generate
        mock_tool = MagicMock()
        from tools.traits import ToolResult, ERROR_TYPE_NETWORK_ERROR
        mock_tool.execute.return_value = ToolResult.fail(
            "timeout", error_type=ERROR_TYPE_NETWORK_ERROR, retryable=True
        )
        mock_tool.timeout_seconds = 30.0
        mock_tool.parameters_schema.return_value = {"type": "object", "properties": {}}
        mock_tool.name.return_value = "web_search"
        self.registry.get.side_effect = None
        self.registry.get.return_value = mock_tool

        result = self.agent.run_with_request("搜索 x", max_retries=2)
        self.assertFalse(result.any_success)
        # 2 attempts, no early bail-out for retryable errors.
        self.assertEqual(call_count[0], 2)
        self.assertEqual(len(result.records), 2)


if __name__ == "__main__":
    unittest.main()
