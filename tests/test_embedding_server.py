"""Tests for core/embedding_server.py — H-04 启动端口与 embedding_endpoint 一致。"""
import threading
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


class TestWatchdog(unittest.TestCase):
    """M-18: 崩溃自动重启看门狗。"""

    def _run_watchdog(self, ready_seq, max_wait=1):
        """以给定 ready 序列跑 watchdog；序列耗尽时设置 stop_event 退出循环。"""
        stop = threading.Event()
        calls = {"n": 0}

        def fake_ready(endpoint):
            calls["n"] += 1
            if calls["n"] > len(ready_seq):
                stop.set()
                return True
            return ready_seq[calls["n"] - 1]

        with patch.object(es, "_is_server_ready", side_effect=fake_ready), \
             patch.object(es, "kill_existing_llama") as mock_kill, \
             patch.object(es, "_start_llama_server",
                          return_value=MagicMock()) as mock_start, \
             patch.object(es, "MAX_WAIT_SECONDS", max_wait):
            es._watchdog_loop(MagicMock(), "ep", "/tmp/x", MagicMock(), "/proj",
                              interval=0, stop_event=stop)
        return mock_kill, mock_start

    def test_restart_after_threshold_failures(self):
        # 2 次就绪 → 连续 3 次不就绪 → 触发一次 kill+restart，重启后就绪
        mock_kill, mock_start = self._run_watchdog(
            [True, True, False, False, False, True, True])
        mock_kill.assert_called_once()
        mock_start.assert_called_once()

    def test_transient_failures_tolerated(self):
        # 连续失败从未达到阈值（F,F,T 循环）→ 不重启
        mock_kill, mock_start = self._run_watchdog(
            [False, False, True] * 4)
        mock_kill.assert_not_called()
        mock_start.assert_not_called()

    def test_give_up_after_max_restarts(self):
        # 永远不就绪 → 重启 WATCHDOG_MAX_RESTARTS 次后放弃（不再调 start）
        mock_kill, mock_start = self._run_watchdog([False] * 200)
        self.assertEqual(mock_start.call_count, es.WATCHDOG_MAX_RESTARTS)


if __name__ == "__main__":
    unittest.main()
