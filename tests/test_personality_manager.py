"""Tests for core/personality_manager.py — Layer 6 role management."""
import os
import tempfile
import unittest

from core.personality import Personality
from core.personality_manager import PersonalityManager
from models.personality import PersonalityConfig, Trait


class TestPersonalityManager(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.pm = PersonalityManager(self.tmp.name)
        # Seed default role
        default = Personality(PersonalityConfig(name="Default", traits=[Trait("curiosity", 0.5)]))
        default.save(self.pm.personality_path("default"))

        # Seed 小星 role
        xing = Personality(PersonalityConfig(name="小星", traits=[Trait("warmth", 0.8)]))
        xing.save(self.pm.personality_path("小星"))

        # Seed a .bak file that must be ignored by list_roles
        open(os.path.join(self.tmp.name, "backup.json.bak"), "w").close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_roles_sorted_and_excludes_bak(self):
        roles = self.pm.list_roles()
        self.assertEqual(roles, ["default", "小星"])
        self.assertNotIn("backup", roles)

    def test_role_exists(self):
        self.assertTrue(self.pm.role_exists("default"))
        self.assertTrue(self.pm.role_exists("小星"))
        self.assertFalse(self.pm.role_exists("nonexistent"))

    def test_load_role_roundtrip(self):
        loaded = self.pm.load_role("小星")
        self.assertEqual(loaded.config.name, "小星")
        self.assertTrue(any(t.name == "warmth" and t.value == 0.8 for t in loaded.config.traits))

    def test_load_role_missing_raises(self):
        with self.assertRaises(FileNotFoundError):
            self.pm.load_role("missing")

    def test_create_role_uses_default_template(self):
        role = self.pm.create_role("newrole")
        self.assertTrue(self.pm.role_exists("newrole"))
        self.assertEqual(role.config.name, "Default")

    def test_create_role_with_base(self):
        base = Personality(PersonalityConfig(name="CustomBase", traits=[Trait("humor", 0.6)]))
        role = self.pm.create_role("custom", base=base)
        loaded = self.pm.load_role("custom")
        self.assertEqual(loaded.config.name, "CustomBase")

    def test_create_role_already_exists_raises(self):
        with self.assertRaises(FileExistsError):
            self.pm.create_role("default")

    def test_save_role(self):
        p = self.pm.load_role("default")
        p.emotion.anger = 0.5
        self.pm.save_role("default", p)
        loaded = self.pm.load_role("default")
        self.assertEqual(loaded.emotion.anger, 0.5)


if __name__ == "__main__":
    unittest.main()
