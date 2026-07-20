"""Tests for models/personality.py -- EmotionalState class"""
import copy
import unittest
import tempfile
import os

from models.personality import EmotionalState, PersonalityConfig


def _make_default_state():
    """Create a fresh EmotionalState with baseline values."""
    return EmotionalState(
        valence=0.4, arousal=0.3,
        baseline_valence=0.4, baseline_arousal=0.3,
        decay_rate=0.05, inertia=0.3,
    )


class TestR5NegativeWeightAndBoundary(unittest.TestCase):
    """R5：负向效价偏移 ×1.2 + 边界停留告警升级（2026-07-20）。"""

    def test_negative_delta_amplified(self):
        e = EmotionalState(valence=0.0, arousal=0.5, inertia=0.0)
        e.shift(-0.1, 0)
        # -0.1 × 1.2（NEGATIVE_VALENCE_WEIGHT）× (1 - inertia=1.0)
        self.assertAlmostEqual(e.valence, -0.12, places=4)

    def test_positive_delta_not_amplified(self):
        e = EmotionalState(valence=0.0, arousal=0.5, inertia=0.0)
        e.shift(0.1, 0)
        self.assertAlmostEqual(e.valence, 0.1, places=4)

    def test_boundary_streak_escalates_to_warning(self):
        e = EmotionalState(valence=1.0, arousal=0.5, inertia=0.0)
        with self.assertLogs("models.personality", level="WARNING") as cm:
            for _ in range(5):
                e.shift(0.1, 0)  # 持续顶格
        self.assertTrue(any("boundary" in line for line in cm.output))

    def test_leaving_boundary_resets_streak(self):
        e = EmotionalState(valence=1.0, arousal=0.5, inertia=0.0)
        e.shift(0.1, 0)
        self.assertEqual(e._valence_boundary_count, 1)
        e.shift(-0.5, 0)  # 离开边界
        self.assertEqual(e._valence_boundary_count, 0)


class TestShift(unittest.TestCase):
    def setUp(self):
        self.e = _make_default_state()

    def test_basic_positive_shift(self):
        self.e.shift(0.5, 0.3)
        self.assertGreater(self.e.valence, 0.4)
        self.assertGreater(self.e.arousal, 0.3)

    def test_basic_negative_shift(self):
        self.e.shift(-0.5, -0.3)
        self.assertLess(self.e.valence, 0.4)

    def test_inertia_reduces_shift(self):
        self.e.inertia = 0.5
        self.e.shift(1.0, 1.0)
        # With inertia=0.5, effective delta = 0.5
        self.assertLess(self.e.valence, 1.0)

    def test_inertia_zero_full_response(self):
        self.e.inertia = 0.0
        old_valence = self.e.valence
        self.e.shift(0.6, 0.0)
        # Full delta applied when inertia=0
        self.assertAlmostEqual(self.e.valence, old_valence + 0.6)

    def test_valence_clamped_to_one(self):
        self.e.valence = 0.95
        self.e.shift(0.5, 0.0)
        self.assertLessEqual(self.e.valence, 1.0)
        self.assertGreaterEqual(self.e.valence, -1.0)

    def test_valence_clamped_to_negative_one(self):
        self.e.valence = -0.95
        self.e.shift(-0.5, 0.0)
        self.assertGreaterEqual(self.e.valence, -1.0)

    def test_arousal_clamped_to_one(self):
        self.e.arousal = 0.95
        self.e.shift(0.0, 0.5)
        self.assertLessEqual(self.e.arousal, 1.0)

    def test_primary_delta_joy(self):
        self.e.shift(0.0, 0.0, primary_deltas={"joy": 0.3})
        self.assertGreater(self.e.joy, 0.0)

    def test_primary_deltas_clamped(self):
        self.e.shift(0.0, 0.0, primary_deltas={"joy": 5.0, "anger": -3.0})
        self.assertLessEqual(self.e.joy, 1.0)
        self.assertGreaterEqual(self.e.anger, 0.0)

    def test_resentment_accumulates_when_anger_high(self):
        self.e.anger = 0.8
        self.e.shift(0.0, 0.0, primary_deltas={"anger": 0.1})
        self.assertGreater(self.e.resentment, 0.0)

    def test_resentment_not_triggered_below_threshold(self):
        self.e.anger = 0.5
        old_r = self.e.resentment
        self.e.shift(0.0, 0.0, primary_deltas={"anger": 0.05})
        self.assertEqual(self.e.resentment, old_r)

    def test_history_records(self):
        for _ in range(5):
            self.e.shift(0.1, 0.0)
        self.assertGreater(len(self.e.history), 0)

    def test_history_capped_at_ten(self):
        for _ in range(15):
            self.e.shift(0.1, 0.0)
        self.assertLessEqual(len(self.e.history), 10)


class TestDecay(unittest.TestCase):
    def setUp(self):
        self.e = _make_default_state()
        self.e.joy = 0.9
        self.e.anger = 0.8
        self.e.sadness = 0.7
        self.e.surprise = 0.9

    def test_decay_reduces_values(self):
        self.e.decay()
        self.assertLess(self.e.joy, 0.9)
        self.assertLess(self.e.anger, 0.8)

    def test_surprise_decays_fastest(self):
        self.e.decay()
        # surprise has decay=0.33 (fastest, ~3t half-life)
        decayed_joy = 0.9 - self.e.joy
        decayed_surprise = 0.9 - self.e.surprise
        self.assertGreater(decayed_surprise, decayed_joy)

    def test_valence_drifts_toward_baseline(self):
        self.e.valence = 0.8
        self.e.decay()
        self.assertLess(self.e.valence, 0.8)

    def test_resentment_slows_anger_decay(self):
        self.e.resentment = 0.3
        self.e.anger = 0.7
        self.e.decay()
        # With resentment > 0.1, anger decay rate is reduced
        self.assertGreater(self.e.anger, 0.0)

    def test_resentment_self_decay(self):
        self.e.resentment = 0.5
        self.e.decay()
        self.assertLess(self.e.resentment, 0.5)

    def test_tiny_resentment_skipped(self):
        self.e.resentment = 0.0005
        self.e.decay()
        # Below 0.001 threshold, resentment decay is skipped
        self.assertEqual(self.e.resentment, 0.0005)


class TestCrossModulate(unittest.TestCase):
    def setUp(self):
        self.e = _make_default_state()

    def test_anger_suppresses_joy(self):
        self.e.joy = 0.8
        self.e.anger = 0.9
        self.e._cross_modulate()
        self.assertLess(self.e.joy, 0.8)

    def test_anger_suppresses_trust(self):
        self.e.trust = 0.8
        self.e.anger = 0.9
        self.e._cross_modulate()
        self.assertLess(self.e.trust, 0.8)

    def test_sadness_suppresses_joy(self):
        self.e.joy = 0.8
        self.e.sadness = 0.9
        self.e._cross_modulate()
        self.assertLess(self.e.joy, 0.8)

    def test_joy_counters_anger(self):
        self.e.anger = 0.8
        self.e.joy = 0.9
        self.e._cross_modulate()
        self.assertLess(self.e.anger, 0.8)

    def test_resentment_amplifies_anger_suppression(self):
        self.e.joy = 0.9
        self.e.anger = 0.8
        self.e.resentment = 0.5
        self.e._cross_modulate()
        self.assertLess(self.e.joy, 0.9)

    def test_resentment_caps_joy_ceiling(self):
        self.e.joy = 1.0
        self.e.resentment = 0.5
        self.e._cross_modulate()
        # resentment > 0.2 caps joy at 1.0 - r * 0.5 = 0.75
        self.assertLess(self.e.joy, 1.0)

    def test_trust_fear_mutual_suppression(self):
        self.e.trust = 0.9
        self.e.fear = 0.9
        self.e._cross_modulate()
        # Both should be reduced
        self.assertLess(self.e.trust + self.e.fear, 1.8)


class TestDominantEmotion(unittest.TestCase):
    def setUp(self):
        self.e = _make_default_state()

    def test_neutral_by_default(self):
        self.assertEqual(self.e.dominant_emotion, "neutral")

    def test_anger_dominant(self):
        self.e.anger = 0.9
        self.e.valence = -0.5
        self.assertEqual(self.e.dominant_emotion, "angry")

    def test_joy_dominant(self):
        self.e.joy = 0.9
        self.e.valence = 0.5
        self.assertEqual(self.e.dominant_emotion, "joyful")

    def test_sadness_dominant(self):
        self.e.sadness = 0.9
        self.e.valence = -0.5
        self.assertEqual(self.e.dominant_emotion, "sad")

    def test_negative_valence_biases_negative(self):
        self.e.valence = -0.5
        self.e.anger = 0.55
        self.e.joy = 0.55
        # With negative valence, anger score amplified 1.3x, joy 0.8x
        dom = self.e.dominant_emotion
        self.assertIn(dom, ["angry", "frustrated", "sad", "melancholy", "anxious", "afraid", "disgusted"])

    def test_positive_valence_biases_positive(self):
        self.e.valence = 0.5
        self.e.joy = 0.55
        self.e.anger = 0.55
        dom = self.e.dominant_emotion
        self.assertIn(dom, ["joyful", "excited", "content", "engaged", "trusting", "surprised", "anticipating", "neutral"])


class TestSerialization(unittest.TestCase):
    def setUp(self):
        self.e = _make_default_state()
        self.e.anger = 0.7
        self.e.sadness = 0.3
        self.e.resentment = 0.2

    def test_to_dict_contains_all_fields(self):
        d = self.e.to_dict()
        self.assertIn("valence", d)
        self.assertIn("joy", d)
        self.assertIn("anger", d)
        self.assertIn("resentment", d)

    def test_from_dict_roundtrip(self):
        d = self.e.to_dict()
        restored = EmotionalState.from_dict(d)
        self.assertEqual(self.e.valence, restored.valence)
        self.assertEqual(self.e.anger, restored.anger)
        self.assertEqual(self.e.resentment, restored.resentment)

    def test_from_dict_missing_fields(self):
        d = {"valence": 0.5, "arousal": 0.3}
        restored = EmotionalState.from_dict(d)
        self.assertEqual(restored.valence, 0.5)
        self.assertGreaterEqual(restored.joy, 0.0)

    def test_from_dict_extra_fields(self):
        d = self.e.to_dict()
        d["unknown_field"] = 999
        restored = EmotionalState.from_dict(d)
        self.assertFalse(hasattr(restored, "unknown_field"))

    def test_turns_without_anger_roundtrip(self):
        # L-07: turns_without_anger 是 dataclass 字段，随序列化持久化
        self.e.turns_without_anger = 7
        restored = EmotionalState.from_dict(self.e.to_dict())
        self.assertEqual(restored.turns_without_anger, 7)

    def test_turns_without_anger_default_for_old_files(self):
        # L-07: 旧版人格文件没有该字段，加载时取默认值 0
        restored = EmotionalState.from_dict({"valence": 0.5})
        self.assertEqual(restored.turns_without_anger, 0)

    def test_shift_increments_forgiveness_counter(self):
        # L-07: shift() 在低 anger 轮次累加计数（改名后行为不变）
        self.e.anger = 0.0
        self.e.shift(0.0, 0.0)
        self.assertEqual(self.e.turns_without_anger, 1)


class TestRecordEmotionEvent(unittest.TestCase):
    def setUp(self):
        self.e = _make_default_state()

    def test_records_event(self):
        self.e.anger = 0.9
        self.e.record_emotion_event("用户说了难听的话")
        self.assertEqual(len(self.e.emotion_events), 1)

    def test_skips_low_intensity(self):
        self.e.record_emotion_event("没什么大不了")
        self.assertEqual(len(self.e.emotion_events), 0)

    def test_caps_at_twenty(self):
        self.e.anger = 0.9
        for i in range(25):
            self.e.record_emotion_event(f"event {i}")
        self.assertLessEqual(len(self.e.emotion_events), 20)

    def test_event_has_correct_structure(self):
        self.e.joy = 0.8
        self.e.record_emotion_event("用户夸我")
        event = self.e.emotion_events[0]
        self.assertIn("timestamp", event)
        self.assertIn("trigger", event)
        self.assertIn("primary_emotion", event)
        self.assertIn("intensity", event)


class TestApplyMoodShift(unittest.TestCase):
    def setUp(self):
        self.e = _make_default_state()

    def test_shifts_mood(self):
        old_mv = self.e.mood_valence
        self.e.apply_mood_shift(0.2, 0.1)
        self.assertNotEqual(self.e.mood_valence, old_mv)


if __name__ == "__main__":
    unittest.main()
