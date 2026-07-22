"""Tests for core/provider.py -- DeepSeekProvider retry/error handling"""
import json
import unittest
from unittest.mock import MagicMock, patch

from requests.exceptions import (
    ConnectionError as ReqConnectionError, HTTPError, ChunkedEncodingError,
    StreamConsumedError, ReadTimeout,
)


class TestProviderRetry(unittest.TestCase):
    def setUp(self):
        from core.provider import DeepSeekProvider
        self.provider = DeepSeekProvider(
            endpoint="https://test.api/v1",
            api_key="sk-test",
            model="test-model",
            timeout=5,
        )

    @patch('requests.Session.post')
    def test_successful_call(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "Hello!"}}],
            "usage": {"total_tokens": 10, "prompt_tokens": 5, "completion_tokens": 5},
        }
        mock_post.return_value = mock_resp

        result = self.provider.generate([{"role": "user", "content": "hi"}], stream=False)
        self.assertEqual(result, "Hello!")
        mock_post.assert_called_once()

    @patch('requests.Session.post')
    def test_retry_on_connection_error(self, mock_post):
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ReqConnectionError("Connection refused")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "retry ok"}}],
                "usage": {"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2},
            }
            return mock_resp

        mock_post.side_effect = side_effect
        result = self.provider.generate([{"role": "user", "content": "hi"}], stream=False)
        self.assertEqual(result, "retry ok")
        self.assertEqual(call_count[0], 2)

    @patch('requests.Session.post')
    def test_retry_on_500(self, mock_post):
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                resp = MagicMock()
                resp.status_code = 500
                http_err = HTTPError("Server Error")
                http_err.response = resp
                raise http_err
            resp = MagicMock()
            resp.status_code = 200
            resp.json.return_value = {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2},
            }
            return resp

        mock_post.side_effect = side_effect
        result = self.provider.generate([{"role": "user", "content": "hi"}], stream=False)
        self.assertEqual(result, "ok")
        self.assertEqual(call_count[0], 3)

    @patch('requests.Session.post')
    def test_no_retry_on_400(self, mock_post):
        resp = MagicMock()
        resp.status_code = 400
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        http_err = HTTPError("Bad Request")
        http_err.response = mock_resp
        mock_post.side_effect = http_err

        with self.assertRaises(HTTPError):
            self.provider.generate([{"role": "user", "content": "hi"}], stream=False)
        mock_post.assert_called_once()

    @patch('requests.Session.post')
    def test_all_retries_exhausted(self, mock_post):
        mock_post.side_effect = ReqConnectionError("Connection refused")

        with self.assertRaises(ConnectionError):
            self.provider.generate([{"role": "user", "content": "hi"}], stream=False)
        self.assertEqual(mock_post.call_count, 3)

    @patch('requests.Session.post')
    def test_streaming_response(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        lines = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: {"choices":[{"delta":{"content":" World"}}]}',
            'data: [DONE]',
        ]
        mock_resp.iter_lines.return_value = lines

        def fake_post(*args, **kwargs):
            return mock_resp

        mock_post.side_effect = fake_post

        tokens = []
        result = self.provider.generate(
            [{"role": "user", "content": "hi"}],
            stream=True,
            on_token=lambda t: tokens.append(t),
        )
        self.assertEqual("".join(tokens), "Hello World")

    @patch('requests.Session.post')
    def test_empty_stream(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = []

        def fake_post(*args, **kwargs):
            return mock_resp

        mock_post.side_effect = fake_post
        result = self.provider.generate([{"role": "user", "content": "hi"}], stream=True)
        self.assertEqual(result, "")

    @patch('requests.Session.post')
    def test_thinking_parameter(self, mock_post):
        from core.provider import DeepSeekProvider
        p = DeepSeekProvider(
            endpoint="https://test.api/v1", api_key="sk-test",
            model="test-model", thinking="enabled",
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"total_tokens": 1, "prompt_tokens": 0, "completion_tokens": 1},
        }
        mock_post.return_value = mock_resp
        p.generate([{"role": "user", "content": "hi"}], stream=False)
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        self.assertIn("thinking", payload)
        self.assertEqual(payload["thinking"]["type"], "enabled")

    @patch('requests.Session.post')
    def test_malformed_stream_json_skipped(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        lines = [
            'data: {broken',
            'data: {"choices":[{"delta":{"content":"ok"}}]}',
            'data: [DONE]',
        ]
        mock_resp.iter_lines.return_value = lines

        def fake_post(*args, **kwargs):
            return mock_resp

        mock_post.side_effect = fake_post
        tokens = []
        result = self.provider.generate(
            [{"role": "user", "content": "hi"}],
            stream=True,
            on_token=lambda t: tokens.append(t),
        )
        self.assertEqual("".join(tokens), "ok")

    @patch('requests.Session.post')
    def test_response_format_in_payload(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"calls":[]}'}}],
            "usage": {"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2},
        }
        mock_post.return_value = mock_resp

        rf = {"type": "json_object"}
        result = self.provider.generate(
            [{"role": "user", "content": "hi"}],
            stream=False, response_format=rf,
        )
        call_args = mock_post.call_args
        payload = call_args[1]["json"]
        self.assertIn("response_format", payload)
        self.assertEqual(payload["response_format"], rf)

    @patch('requests.Session.post')
    def test_stream_done_break_closes_response(self, mock_post):
        # #213: [DONE] 提前 break（响应未读完）后必须 close，连接归还连接池
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: [DONE]',
            'data: {"choices":[{"delta":{"content":"unread"}}]}',  # 不会被消费
        ]
        mock_post.return_value = mock_resp

        result = self.provider.generate([{"role": "user", "content": "hi"}], stream=True)
        self.assertEqual(result, "Hello")
        mock_resp.close.assert_called_once()

    @patch('requests.Session.post')
    def test_stream_truncation_break_closes_response(self, mock_post):
        # #213: 1MB 截断提前 break 后同样 close
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        big_token = "a" * 1_100_000
        mock_resp.iter_lines.return_value = [
            f'data: {{"choices":[{{"delta":{{"content":"{big_token}"}}}}]}}',
            'data: [DONE]',
        ]
        mock_post.return_value = mock_resp

        result = self.provider.generate([{"role": "user", "content": "hi"}], stream=True)
        self.assertEqual(len(result), 1_100_000)
        mock_resp.close.assert_called_once()

    @patch('requests.Session.post')
    def test_non_stream_closes_response(self, mock_post):
        # #213: 非流式分支也显式 close
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }
        mock_post.return_value = mock_resp

        result = self.provider.generate([{"role": "user", "content": "hi"}], stream=False)
        self.assertEqual(result, "ok")
        mock_resp.close.assert_called_once()

    @patch('requests.Session.post')
    def test_endpoint_trailing_v1_normalized(self, mock_post):
        # #261: endpoint 以 /v1 结尾时归一化，不拼出 /v1/v1/...
        # （setUp 中 endpoint 为 "https://test.api/v1"）
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }
        mock_post.return_value = mock_resp

        self.provider.generate([{"role": "user", "content": "hi"}], stream=False)
        url = mock_post.call_args[0][0]
        self.assertEqual(url, "https://test.api/v1/chat/completions")

    @patch('requests.Session.post')
    def test_endpoint_without_v1_unchanged(self, mock_post):
        # #261: 普通 endpoint 行为不变
        from core.provider import DeepSeekProvider
        p = DeepSeekProvider(
            endpoint="https://test.api/", api_key="sk-test",
            model="test-model", timeout=5,
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {},
        }
        mock_post.return_value = mock_resp

        p.generate([{"role": "user", "content": "hi"}], stream=False)
        url = mock_post.call_args[0][0]
        self.assertEqual(url, "https://test.api/v1/chat/completions")

    @patch('requests.Session.post')
    def test_retry_on_read_timeout(self, mock_post):
        # #213: ReadTimeout 纳入重试链，不再绕过三次重试直接外抛
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise ReadTimeout("read timed out")
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "retry ok"}}],
                "usage": {},
            }
            return mock_resp

        mock_post.side_effect = side_effect
        result = self.provider.generate([{"role": "user", "content": "hi"}], stream=False)
        self.assertEqual(result, "retry ok")
        self.assertEqual(call_count[0], 2)


class TestTruncationSemantics(unittest.TestCase):
    """A2（2026-07-21，provider.md P0-1）：截断显式化。"""

    def setUp(self):
        from core.provider import DeepSeekProvider
        self.provider = DeepSeekProvider(
            endpoint="https://test.api/v1",
            api_key="sk-test",
            model="test-model",
            timeout=5,
        )

    def _non_stream_resp(self, content, finish_reason):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": content},
                         "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 5, "completion_tokens": 5},
        }
        return mock_resp

    @patch('core.provider.time.sleep', lambda *_: None)
    @patch('core.provider.record_call')
    @patch('requests.Session.post')
    def test_json_mode_truncation_retried_then_fails(self, mock_post,
                                                     mock_record):
        """response_format 调用截断 → 可重试错误，耗尽后报错而不是交半截 JSON。"""
        mock_post.return_value = self._non_stream_resp('{"a": 1', "length")
        from core.provider import TruncatedResponseError  # noqa: 确保类存在
        with self.assertRaises(ConnectionError):
            self.provider.generate(
                [{"role": "user", "content": "hi"}], stream=False,
                response_format={"type": "json_object"})
        self.assertEqual(mock_post.call_count, 3)
        mock_record.assert_not_called()  # 失败调用不记录成功记录

    @patch('core.provider.record_call')
    @patch('requests.Session.post')
    def test_text_truncation_returns_partial_and_records(self, mock_post,
                                                         mock_record):
        """纯文本路径保持现状（半截好于报错），但记录 truncated=True。"""
        mock_post.return_value = self._non_stream_resp("半截回复", "length")
        result = self.provider.generate([{"role": "user", "content": "hi"}],
                                        stream=False)
        self.assertEqual(result, "半截回复")
        self.assertTrue(mock_record.call_args.kwargs["truncated"])
        self.assertEqual(mock_record.call_args.kwargs["finish_reason"], "length")

    @patch('core.provider.record_call')
    @patch('requests.Session.post')
    def test_stream_missing_done_marked_truncated(self, mock_post, mock_record):
        """流缺 [DONE]（断流）→ truncated 记录。"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
        ]
        mock_post.return_value = mock_resp
        result = self.provider.generate([{"role": "user", "content": "hi"}],
                                        stream=True)
        self.assertEqual(result, "Hello")
        self.assertTrue(mock_record.call_args.kwargs["truncated"])

    @patch('core.provider.record_call')
    @patch('requests.Session.post')
    def test_stream_normal_done_not_truncated(self, mock_post, mock_record):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.iter_lines.return_value = [
            'data: {"choices":[{"delta":{"content":"Hello"}}]}',
            'data: [DONE]',
        ]
        mock_post.return_value = mock_resp
        self.provider.generate([{"role": "user", "content": "hi"}], stream=True)
        self.assertFalse(mock_record.call_args.kwargs["truncated"])


if __name__ == "__main__":
    unittest.main()


class TestPerCallTemperature(unittest.TestCase):
    """按调用覆盖温度（决策类任务低温）。"""

    def setUp(self):
        from core.provider import DeepSeekProvider
        self.provider = DeepSeekProvider(
            endpoint="https://api.deepseek.com", api_key="k",
            model="m", temperature=0.8)

    @patch('requests.Session.post')
    def test_temperature_override_in_payload(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2},
        }
        mock_post.return_value = mock_resp

        self.provider.generate([{"role": "user", "content": "hi"}],
                               stream=False, temperature=0.3)
        payload = mock_post.call_args[1]["json"]
        self.assertEqual(payload["temperature"], 0.3)

    @patch('requests.Session.post')
    def test_default_temperature_unchanged(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "ok"}}],
            "usage": {"total_tokens": 5, "prompt_tokens": 3, "completion_tokens": 2},
        }
        mock_post.return_value = mock_resp

        self.provider.generate([{"role": "user", "content": "hi"}], stream=False)
        payload = mock_post.call_args[1]["json"]
        self.assertEqual(payload["temperature"], 0.8)
