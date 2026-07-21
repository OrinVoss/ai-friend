"""Tests for A4 人格校验器 + .bak 时机修复/损坏恢复。"""
import json
import os
import tempfile
import unittest

from core.personality import Personality
from core.personality_validator import (validate_personality_data,
                                        validate_personality_file)


class TestValidatePersonalityData(unittest.TestCase):
    def test_valid_passes(self):
        data = {"personality": {"name": "小星",
                                "traits": {"curiosity": 0.9}},
                "emotional_state": {"valence": 0.5}}
        self.assertEqual(validate_personality_data(data), [])

    def test_unknown_top_level(self):
        issues = validate_personality_data({"personality": {"name": "x"},
                                            "personnality": {}})
        self.assertTrue(any("未知顶层字段" in i for i in issues))

    def test_unknown_personality_field_typo(self):
        issues = validate_personality_data(
            {"personality": {"name": "x", "speaking_stlye": "活泼"}})
        self.assertTrue(any("疑似拼写错误" in i and "speaking_stlye" in i
                            for i in issues))

    def test_missing_name(self):
        issues = validate_personality_data({"personality": {"name": ""}})
        self.assertTrue(any("缺少 name" in i for i in issues))

    def test_trait_out_of_range(self):
        issues = validate_personality_data(
            {"personality": {"name": "x", "traits": {"humor": 1.5}}})
        self.assertTrue(any("越界" in i for i in issues))

    def test_trait_unparseable(self):
        issues = validate_personality_data(
            {"personality": {"name": "x", "traits": {"humor": "很幽默"}}})
        self.assertTrue(any("不可解析" in i for i in issues))

    def test_bad_baseline(self):
        issues = validate_personality_data(
            {"personality": {"name": "x", "emotional_baseline": {"v": 1}}})
        self.assertTrue(any("emotional_baseline" in i for i in issues))

    def test_file_unparseable(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write("{not json")
            issues = validate_personality_file(p)
            self.assertEqual(len(issues), 1)
            self.assertIn("无法解析", issues[0])


class TestBakRecovery(unittest.TestCase):
    def test_corrupt_main_recovers_from_bak(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "小星.json")
            # 先写好文件并 load 一次 → .bak 成为 last-known-good
            good = {"personality": {"name": "小星"}, "emotional_state": {}}
            with open(p, "w", encoding="utf-8") as f:
                json.dump(good, f)
            Personality.load(p)
            self.assertTrue(os.path.exists(p + ".bak"))
            # 损坏主文件后 .bak 不再被覆盖，且能恢复
            with open(p, "w", encoding="utf-8") as f:
                f.write("{corrupted")
            with open(p + ".bak", encoding="utf-8") as f:
                bak_data = json.load(f)
            self.assertEqual(bak_data["personality"]["name"], "小星")
            personality = Personality.load(p)
            self.assertEqual(personality.config.name, "小星")

    def test_corrupt_without_bak_falls_back_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "bad.json")
            with open(p, "w", encoding="utf-8") as f:
                f.write("{corrupted")
            personality = Personality.load(p)
            self.assertEqual(personality.config.name,
                             type(personality.config)().name)


if __name__ == "__main__":
    unittest.main()
