"""Tests for core/provider.py -- KimiProvider retry/error handling"""
import json
import unittest
from unittest.mock import MagicMock, patch

from requests.exceptions import ConnectionError as ReqConnectionError, HTTPError, ChunkedEncodingError, StreamConsumedError


class TestProviderRetry(unittest.TestCase):
    def setUp(self):
        from core.provider import KimiProvider
        self.provider = KimiProvider(
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
        from core.provider import KimiProvider
        p = KimiProvider(
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


if __name__ == "__main__":
    unittest.main()
