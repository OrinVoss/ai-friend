"""Real API tests for dream generation."""
import tempfile, os
import sys, unittest

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
        from core.personality import Personality
        cls.personality = Personality.load(cfg.personality_file)

    def test_generate_dream(self):
        """Dream generation with sync DB (avoids _run_sync threading issue)."""
        import sqlite3
        conn = sqlite3.connect(":memory:")
        from storage.repository import Repository
        from storage.database import Database

        # Minimal sync DB for this test
        class SyncMinimalDB:
            def __init__(self): self.conn = conn
            def get_connection(self): return self.conn

        db = SyncMinimalDB()
        repo = Repository.__new__(Repository)
        repo.db = db

        # Override repo methods to return minimal test data (as coroutines)
        from models.memory import UserFact, Experience
        test_facts = [
            UserFact(id=1, category="interest", fact_key="爱好", fact_value="音乐",
                     confidence=1.0, importance=0.5, created_at="2026-01-01",
                     source_turn=1, recall_count=1, is_active=True, composite_score=0.8),
        ]
        test_exps = [
            Experience(id=1, summary="和朋友聊了整晚的音乐", emotional_tone="joyful",
                       significance=0.7, created_at="2026-01-01", tags=["音乐", "朋友"],
                       recall_count=1, is_archived=False, composite_score=0.7),
        ]

        async def _active_facts(limit=50): return test_facts
        async def _recent_exps(limit=5): return test_exps
        repo.get_active_facts = _active_facts
        repo.get_recent_experiences = _recent_exps

        from memory.long_term import LongTermMemory
        ltm = LongTermMemory(repo)

        from core.sleep_manager import SleepManager
        with tempfile.NamedTemporaryFile(mode="w", suffix=".sleep", delete=False) as f:
            f.write("0")
            tmp = f.name
        try:
            sm = SleepManager(
                sleep_state_file=tmp,
                personality=self.personality,
                ltm=ltm,
                provider=self.provider,
            )
            dream = sm.generate_dream()
            self.assertIsInstance(dream, str)
            self.assertGreater(len(dream.strip()), 0,
                              f"Expected non-empty dream, got '{dream}'")
        finally:
            os.unlink(tmp)


if __name__ == "__main__":
    unittest.main()
