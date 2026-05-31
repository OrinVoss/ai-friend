"""Real API tests for dream generation."""
import sys
import unittest

sys.path.insert(0, ".")

from tests.real_api.conftest import RealAPITestCase


class TestRealDream(RealAPITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from config import load_config
        cfg = load_config()

        from core.provider import KimiProvider
        cls.provider = KimiProvider(
            endpoint=cfg.api_endpoint, api_key=cfg.api_key,
            model=cfg.api_model, timeout=cfg.api_timeout,
        )

        from storage.database import Database
        from storage.repository import Repository
        cls.db = Database(":memory:")
        cls.run_async(cls.db.open())
        cls.repo = Repository(cls.db)
        from memory.long_term import LongTermMemory
        cls.ltm = LongTermMemory(cls.repo)
        from core.personality import Personality
        cls.personality = Personality.load(cfg.personality_file)

    def test_generate_dream(self):
        from core.sleep_manager import SleepManager
        sm = SleepManager(
            sleep_state_file=":memory:",
            personality=self.personality,
            ltm=self.ltm,
            provider=self.provider,
        )
        dream = sm.generate_dream()
        self.assertIsInstance(dream, str)
        self.assertGreater(len(dream), 0)


if __name__ == "__main__":
    unittest.main()
