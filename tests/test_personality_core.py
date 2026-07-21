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


class TestSaveMerge(unittest.TestCase):
    """H-06: save() 合并保存——静态人格段以磁盘为准，只写 emotional_state。"""

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
        self.path = os.path.join(self.tmpdir, "role.json")

    def _read_disk(self):
        with open(self.path, encoding="utf-8") as f:
            return json.load(f)

    def test_save_preserves_disk_personality_edits(self):
        """运行时手工编辑磁盘 JSON：save 后编辑与未知字段保留，情绪段被更新。"""
        self.p.save(self.path)  # 先落一份基线
        disk = self._read_disk()
        disk["personality"]["traits"] = {"curiosity": 0.1}   # 手工改 traits
        disk["personality"]["custom_field"] = "用户新增"       # 未知字段
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(disk, f, ensure_ascii=False)

        self.p.emotion.anger = 0.9
        self.p.save(self.path)

        merged = self._read_disk()
        self.assertEqual(merged["personality"]["traits"], {"curiosity": 0.1})
        self.assertEqual(merged["personality"]["custom_field"], "用户新增")
        self.assertEqual(merged["emotional_state"]["anger"], 0.9)

    def test_save_corrupted_disk_falls_back_to_memory(self):
        """磁盘 JSON 损坏时回退内存全量快照，不抛异常。"""
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{broken json")
        self.p.emotion.anger = 0.7
        self.p.save(self.path)
        data = self._read_disk()
        self.assertIn("personality", data)
        self.assertEqual(data["emotional_state"]["anger"], 0.7)

    def test_save_missing_personality_section_falls_back(self):
        """磁盘缺少 personality 段时回退内存全量快照。"""
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"other": 1}, f)
        self.p.save(self.path)
        data = self._read_disk()
        self.assertIn("personality", data)
        self.assertIn("emotional_state", data)


class TestFromDictNoMutation(unittest.TestCase):
    """H-06: PersonalityConfig.from_dict 不得原地修改入参。"""

    def test_from_dict_does_not_mutate_input(self):
        d = {"name": "X", "traits": {"curiosity": 0.9}, "unknown_field": 1}
        snapshot = {"name": "X", "traits": {"curiosity": 0.9}, "unknown_field": 1}
        cfg = PersonalityConfig.from_dict(d)
        self.assertEqual(d, snapshot)  # 入参未被改
        self.assertEqual(cfg.name, "X")
        # traits 被正确转换为 Trait 列表
        self.assertTrue(any(t.name == "curiosity" and t.value == 0.9
                            for t in cfg.traits))
        # 未知字段被丢弃但不炸
        self.assertFalse(hasattr(cfg, "unknown_field"))


if __name__ == "__main__":
    unittest.main()
