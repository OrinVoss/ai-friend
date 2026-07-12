"""Tests for in-memory rate limiter (#24)."""
import time
import unittest
from unittest.mock import MagicMock

from web.rate_limit import RateLimiter, RateLimitMiddleware, get_client_ip


class TestRateLimiter(unittest.TestCase):
    def test_allowed_under_limit(self):
        rl = RateLimiter()
        for _ in range(5):
            self.assertTrue(rl.is_allowed("1.2.3.4", "/api/chat", 10, 60))

    def test_blocked_over_limit(self):
        rl = RateLimiter()
        for _ in range(3):
            self.assertTrue(rl.is_allowed("1.2.3.4", "/api/chat", 3, 60))
        self.assertFalse(rl.is_allowed("1.2.3.4", "/api/chat", 3, 60))

    def test_different_ips_independent(self):
        rl = RateLimiter()
        for _ in range(3):
            self.assertTrue(rl.is_allowed("1.2.3.4", "/api/chat", 3, 60))
        self.assertTrue(rl.is_allowed("5.6.7.8", "/api/chat", 3, 60))

    def test_window_slides(self):
        rl = RateLimiter()
        self.assertTrue(rl.is_allowed("1.2.3.4", "/api/chat", 1, 1))
        self.assertFalse(rl.is_allowed("1.2.3.4", "/api/chat", 1, 1))
        time.sleep(1.1)
        self.assertTrue(rl.is_allowed("1.2.3.4", "/api/chat", 1, 1))

    def test_unknown_path_unlimited(self):
        rl = RateLimiter()
        for _ in range(100):
            self.assertTrue(rl.check("1.2.3.4", "/unknown"))


class TestGetClientIp(unittest.TestCase):
    def test_forwarded_for(self):
        req = MagicMock()
        req.headers = {"x-forwarded-for": "203.0.113.1, 70.41.3.18"}
        req.client = MagicMock(host="10.0.0.1")
        self.assertEqual(get_client_ip(req), "203.0.113.1")

    def test_direct_client(self):
        req = MagicMock()
        req.headers = {}
        req.client = MagicMock(host="10.0.0.1")
        self.assertEqual(get_client_ip(req), "10.0.0.1")


if __name__ == "__main__":
    unittest.main()
