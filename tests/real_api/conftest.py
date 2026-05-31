"""Skip logic for real API integration tests."""
import asyncio
import os
import sys
import unittest


def _has_api_key() -> bool:
    from config import load_config
    try:
        cfg = load_config()
        return bool(cfg.api_key and cfg.api_key != "your-api-key-here")
    except Exception:
        return False


class RealAPITestCase(unittest.TestCase):
    """Base class for real API tests. Automatically skipped without --real-api flag."""

    _db = None

    @classmethod
    def setUpClass(cls):
        if "--real-api" not in sys.argv:
            raise unittest.SkipTest("Skipped: use --real-api flag to run real API tests")
        if not _has_api_key():
            raise unittest.SkipTest("Skipped: no API key configured")

    def setUp(self):
        # Create fresh in-memory database for each test
        self._db_path = ":memory:"

    @staticmethod
    def run_async(coro):
        """Helper to run async code in sync tests."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            return pool.submit(asyncio.run, coro).result()
