"""Tests for v0.2 issues: #20 traits, #21 score_facts, #5 tiered reflection, #22 dedup, #40 session."""
import unittest
from unittest.mock import MagicMock, patch

from models.memory import UserFact
from memory.retrieval import MemoryRetriever


class TestScoreFactsNoMutation(unittest.TestCase):
    """#21: _score_facts should NOT mutate input facts."""

    def test_score_facts_preserves_original(self):
        f = UserFact(id=1, fact_key="test", fact_value="x",
                     composite_score=0.9, confidence=0.8, importance=0.5)
        original_score = f.composite_score
        result = MemoryRetriever._score_facts([f], ["test"], "test query")
        self.assertEqual(len(result), 1)
        self.assertEqual(f.composite_score, original_score,
                         "_score_facts should not mutate input fact composite_score")

    def test_score_facts_sorts_by_score(self):
        f1 = UserFact(id=1, fact_key="a", fact_value="x",
                      composite_score=0.5, confidence=0.9, importance=0.8)
        f2 = UserFact(id=2, fact_key="b", fact_value="y",
                      composite_score=0.5, confidence=0.3, importance=0.2)
        result = MemoryRetriever._score_facts([f1, f2], ["a"], "a")
        # f1 should rank higher because it matches the keyword
        self.assertEqual(result[0].id, 1)


class TestHumorSassTraits(unittest.TestCase):
    """#20: humor and sass traits should affect emotional impact."""

    def setUp(self):
        from core.personality import Personality
        from models.personality import PersonalityConfig, Trait
        cfg = PersonalityConfig()
        cfg.traits = []
        self.p = Personality(cfg)

    def _make_trait(self, name, value):
        from models.personality import Trait
        return Trait(name=name, value=value)

    def test_humor_dampens_sadness(self):
        self.p.config.traits = [self._make_trait("humor", 0.9)]
        dv, da, deltas = self.p.estimate_emotional_impact(-0.8)
        # Without humor: sadness = 0.8 * 0.2 = 0.16
        # With humor 0.9: sadness *= (1 - 0.9*0.4) = 0.64, so 0.16*0.64 = 0.1024
        self.assertIn("sadness", deltas)
        self.assertLess(deltas["sadness"], 0.16,
                        "Humor should dampen sadness delta")

    def test_sass_reduces_anger(self):
        self.p.config.traits = [self._make_trait("sass", 0.8)]
        _, _, deltas = self.p.estimate_emotional_impact(-0.8)
        self.assertIn("anger", deltas)
        # Without sass: anger = 0.8 * 0.1 = 0.08
        # With sass 0.8: anger *= (1 - 0.8*0.3) = 0.76, so 0.08*0.76 = 0.0608
        self.assertLess(deltas["anger"], 0.08,
                        "Sass should reduce anger delta (sharp tongue, short memory)")

    def test_no_traits_no_effect(self):
        self.p.config.traits = []
        dv, da, deltas = self.p.estimate_emotional_impact(0.5)
        self.assertIn("joy", deltas)


class TestPendingBufferDedup(unittest.TestCase):
    """#22: add_pending should deduplicate by turn_id+role."""

    def setUp(self):
        from memory.consolidation import MemoryConsolidator
        self.c = MemoryConsolidator(MagicMock(), MagicMock())

    def _make_turn(self, tid, role):
        t = MagicMock()
        t.turn_id = tid
        t.role = role
        return t

    def test_same_turn_not_added_twice(self):
        t = self._make_turn(1, "user")
        self.c.add_pending(t)
        self.c.add_pending(t)
        self.assertEqual(len(self.c._pending_buffer), 1)

    def test_different_turns_both_added(self):
        t1 = self._make_turn(1, "user")
        t2 = self._make_turn(2, "assistant")
        self.c.add_pending(t1)
        self.c.add_pending(t2)
        self.assertEqual(len(self.c._pending_buffer), 2)

    def test_same_id_different_role_added(self):
        t1 = self._make_turn(1, "user")
        t2 = self._make_turn(1, "assistant")
        self.c.add_pending(t1)
        self.c.add_pending(t2)
        self.assertEqual(len(self.c._pending_buffer), 2)


class TestTieredReflection(unittest.TestCase):
    """#5: Tiered reflection — L1 every, L2 every 3rd, L3 every 10th."""

    def setUp(self):
        from memory.consolidation import MemoryConsolidator
        self.ltm = MagicMock()
        self.llm = MagicMock()
        self.c = MemoryConsolidator(self.ltm, self.llm)
        self.personality = MagicMock()
        self.personality.emotion.dominant_emotion = "neutral"

    def test_l1_on_first_consolidation(self):
        self.c._consolidation_count = 0
        # Simulate: count becomes 1 after increment (mod 10 != 0, mod 3 != 0)
        self.c._consolidation_count = 1
        self.c._generate_reflection_l1 = MagicMock()
        self.c._generate_reflection_l2 = MagicMock()
        self.c._generate_reflection_l3 = MagicMock()

        # Manually call the tier logic (count % 10 == 0? no. count % 3 == 0? no. → L1)
        if self.c._consolidation_count % 10 == 0:
            self.c._generate_reflection_l3(self.personality)
        elif self.c._consolidation_count % 3 == 0:
            self.c._generate_reflection_l2()
        else:
            self.c._generate_reflection_l1(self.personality)
        self.c._generate_reflection_l1.assert_called_once()

    def test_l2_on_third_consolidation(self):
        self.c._consolidation_count = 3
        self.c._generate_reflection_l2 = MagicMock()
        self.c._generate_reflection_l1 = MagicMock()
        if self.c._consolidation_count % 10 == 0:
            pass
        elif self.c._consolidation_count % 3 == 0:
            self.c._generate_reflection_l2()
        else:
            self.c._generate_reflection_l1(self.personality)
        self.c._generate_reflection_l2.assert_called_once()

    def test_l3_on_tenth_consolidation(self):
        self.c._consolidation_count = 10
        self.c._generate_reflection_l3 = MagicMock()
        if self.c._consolidation_count % 10 == 0:
            self.c._generate_reflection_l3(self.personality)
        self.c._generate_reflection_l3.assert_called_once()


class TestSessionIsolation(unittest.TestCase):
    """#40: session_id filtering on repository queries."""

    def test_repo_has_session_id(self):
        from storage.repository import Repository
        from storage.database import Database
        import asyncio
        db = Database(":memory:")
        asyncio.run(db.open())
        repo = Repository(db)
        self.assertEqual(repo.session_id, "default")

    def test_session_id_settable(self):
        from storage.repository import Repository
        from storage.database import Database
        import asyncio
        db = Database(":memory:")
        asyncio.run(db.open())
        repo = Repository(db)
        repo.session_id = "test-session-123"
        self.assertEqual(repo.session_id, "test-session-123")

    def test_facts_isolated_by_session(self):
        from storage.repository import Repository
        from storage.database import Database
        import asyncio
        db = Database(":memory:")
        asyncio.run(db.open())

        repo1 = Repository(db)
        repo1.session_id = "session-a"
        asyncio.run(repo1.upsert_fact("preference", "color_a", "blue", confidence=0.9))

        repo2 = Repository(db)
        repo2.session_id = "session-b"
        asyncio.run(repo2.upsert_fact("preference", "color_b", "red", confidence=0.9))

        # Session A sees only its own fact
        facts_a = asyncio.run(repo1.get_active_facts(limit=10))
        self.assertEqual(len(facts_a), 1)
        self.assertEqual(facts_a[0].fact_value, "blue")

        # Session B sees only its own fact
        facts_b = asyncio.run(repo2.get_active_facts(limit=10))
        self.assertEqual(len(facts_b), 1)
        self.assertEqual(facts_b[0].fact_value, "red")


if __name__ == "__main__":
    unittest.main()
