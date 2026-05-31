"""Tests for core/personality.py"""
import json
import os
import tempfile
import unittest

from models.personality import PersonalityConfig, EmotionalState


class TestEstimateEmotionalImpact(unittest.TestCase):
    def setUp(self):
        from core.personality import Personality
        config = PersonalityConfig(
            name="Test", traits={},
            speaking_style="", backstory="", interests=[],
            emotional_baseline={"valence": 0.4, "arousal": 0.3},
            emotional_decay_rate=0.05,
        )
        self.p = Personality(config)

    def test_positive_sentiment_threshold(self):
        dv, da, primaries = self.p.estimate_emotional_impact(0.5, False, 0.5)
        self.assertGreater(dv, 0)
        self.assertIn("joy", primaries)

    def test_negative_sentiment_threshold(self):
        dv, da, primaries = self.p.estimate_emotional_impact(-0.5, False, 0.5)
        self.assertLess(dv, 0)

    def test_neutral_sentiment(self):
        dv, da, primaries = self.p.estimate_emotional_impact(0.0, False, 0.5)
        self.assertEqual(dv, 0.0)

    def test_exact_boundary_0_3(self):
        dv, da, primaries = self.p.estimate_emotional_impact(0.3, False, 0.5)
        self.assertNotIn("joy", primaries)  # >0.3 triggers, not >=0.3

    def test_exact_boundary_neg_0_3(self):
        dv, da, primaries = self.p.estimate_emotional_impact(-0.3, False, 0.5)
        self.assertNotIn("sadness", primaries)

    def test_personal_sharing_boost(self):
        dv, _, primaries = self.p.estimate_emotional_impact(0.2, True, 0.5)
        self.assertGreater(dv, 0)
        self.assertIn("trust", primaries)

    def test_high_energy_topic(self):
        _, _, primaries = self.p.estimate_emotional_impact(0.0, False, 0.8)
        self.assertIn("surprise", primaries)
        self.assertIn("anticipation", primaries)


class TestApplyEmotionalShift(unittest.TestCase):
    def setUp(self):
        from core.personality import Personality
        config = PersonalityConfig(
            name="Test", traits={},
            speaking_style="", backstory="", interests=[],
            emotional_baseline={"valence": 0.4, "arousal": 0.3},
            emotional_decay_rate=0.05,
        )
        self.p = Personality(config)

    def test_positive_shift(self):
        old_v = self.p.emotion.valence
        self.p.apply_emotional_shift(0.5, False, 0.5)
        self.assertGreater(self.p.emotion.valence, old_v)

    def test_negative_shift(self):
        old_v = self.p.emotion.valence
        self.p.apply_emotional_shift(-0.5, False, 0.5)
        self.assertLess(self.p.emotion.valence, old_v)


class TestLoadSave(unittest.TestCase):
    def setUp(self):
        from core.personality import Personality
        config = PersonalityConfig(
            name="Test", traits={},
            speaking_style="", backstory="", interests=[],
            emotional_baseline={"valence": 0.4, "arousal": 0.3},
            emotional_decay_rate=0.05,
        )
        self.p = Personality(config)
        self.tmpdir = tempfile.mkdtemp()

    def test_load_nonexistent_file(self):
        from core.personality import Personality
        p = Personality.load(os.path.join(self.tmpdir, "nonexistent.json"))
        self.assertIsNotNone(p)

    def test_load_corrupted_json(self):
        path = os.path.join(self.tmpdir, "corrupted.json")
        with open(path, "w") as f:
            f.write("{broken json")
        from core.personality import Personality
        p = Personality.load(path)
        self.assertIsNotNone(p)

    def test_save_load_roundtrip(self):
        path = os.path.join(self.tmpdir, "roundtrip.json")
        self.p.emotion.anger = 0.5
        self.p.save(path)
        from core.personality import Personality
        p2 = Personality.load(path)
        self.assertEqual(p2.emotion.anger, 0.5)


if __name__ == "__main__":
    unittest.main()
