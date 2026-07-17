"""Tests for core/embedding_server.py — H-04 启动端口与 embedding_endpoint 一致。"""
import unittest
from unittest.mock import MagicMock, patch

import core.embedding_server as es


class TestPortFromEndpoint(unittest.TestCase):
    def test_default_port(self):
        self.assertEqual(
            es._port_from_endpoint("http://localhost:8080/v1/embeddings"), 8080)

    def test_custom_port(self):
        self.assertEqual(
            es._port_from_endpoint("http://localhost:18080/v1/embeddings"), 18080)

    def test_no_port_falls_back_8080(self):
        self.assertEqual(es._port_from_endpoint("http://localhost/v1/embeddings"), 8080)

    def test_garbage_falls_back_8080(self):
        self.assertEqual(es._port_from_endpoint("not a url"), 8080)
        self.assertEqual(es._port_from_endpoint("http://localhost:abc/v1"), 8080)


class TestStartLlamaServerPort(unittest.TestCase):
    """H-04: llama-server 启动参数端口必须与 endpoint 端口一致。"""

    def _start_args(self, endpoint):
        # 强制走 exe 分支（无 bat），Mock Popen 捕获启动参数
        with patch.object(es.os.path, "exists", return_value=False), \
             patch.object(es.subprocess, "Popen") as mock_popen, \
             patch("builtins.open", MagicMock()):
            es._start_llama_server("/proj", "/tmp/embed.log", endpoint=endpoint)
        return mock_popen.call_args[0][0]

    def test_custom_endpoint_port(self):
        args = self._start_args("http://localhost:18080/v1/embeddings")
        self.assertEqual(args[args.index("--port") + 1], "18080")

    def test_default_endpoint_port(self):
        args = self._start_args(es.DEFAULT_EMBEDDING_ENDPOINT)
        self.assertEqual(args[args.index("--port") + 1], "8080")


class TestAutoStartForwardsEndpoint(unittest.TestCase):
    def test_endpoint_forwarded_to_start(self):
        with patch.object(es, "_is_server_ready", return_value=False), \
             patch.object(es, "kill_existing_llama"), \
             patch.object(es.os.path, "exists", return_value=True), \
             patch.object(es.os, "makedirs"), \
             patch.object(es, "_start_llama_server",
                          return_value=MagicMock()) as mock_start, \
             patch.object(es.threading, "Thread"):
            es.auto_start_embedding(endpoint="http://localhost:18080/v1/embeddings")
        self.assertEqual(mock_start.call_args[0][2],
                         "http://localhost:18080/v1/embeddings")


if __name__ == "__main__":
    unittest.main()
