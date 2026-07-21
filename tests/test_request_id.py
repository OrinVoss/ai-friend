"""Tests for A3 request_id（ContextVar + Filter + monitor + run_async 传播）。"""
import asyncio
import logging
import unittest

from core.logging_setup import (RequestIdFilter, new_request_id,
                                request_id_var)


class TestRequestIdFilter(unittest.TestCase):
    def tearDown(self):
        request_id_var.set("")

    def test_unset_shows_dash(self):
        record = logging.LogRecord("t", logging.INFO, "", 1, "msg", (), None)
        RequestIdFilter().filter(record)
        self.assertEqual(record.request_id, "-")

    def test_set_shows_id(self):
        request_id_var.set("abc12345")
        record = logging.LogRecord("t", logging.INFO, "", 1, "msg", (), None)
        RequestIdFilter().filter(record)
        self.assertEqual(record.request_id, "abc12345")

    def test_new_request_id_format(self):
        rid = new_request_id()
        self.assertEqual(len(rid), 8)
        int(rid, 16)  # hex


class TestMonitorRequestId(unittest.TestCase):
    def tearDown(self):
        request_id_var.set("")

    def test_record_call_reads_contextvar_and_dated_timestamp(self):
        from core.monitor import record_call
        request_id_var.set("req00001")
        captured = {}
        import core.monitor as m
        old = m._monitor.record
        m._monitor_enabled = True
        m._monitor.record = lambda rec: captured.setdefault("rec", rec)
        try:
            record_call(model="m", messages=[], response="ok",
                        duration_ms=1.0)
        finally:
            m._monitor.record = old
        rec = captured["rec"]
        self.assertEqual(rec.request_id, "req00001")
        self.assertIn("-", rec.timestamp)  # 含日期
        self.assertIn(":", rec.timestamp)


class TestRunAsyncContextPropagation(unittest.TestCase):
    def tearDown(self):
        request_id_var.set("")

    def test_run_async_bridge_propagates_context(self):
        """有事件循环时走 _EXECUTOR 桥，copy_context 必须把 request_id
        带进 worker 线程。"""
        from core.async_utils import run_async

        async def main():
            request_id_var.set("propagate1")

            async def read_id():
                return request_id_var.get()
            return run_async(read_id())

        self.assertEqual(asyncio.run(main()), "propagate1")


if __name__ == "__main__":
    unittest.main()
