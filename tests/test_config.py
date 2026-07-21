"""Tests for config.py — #255: degrade_threshold / max_fake_actions 接入 config。"""
import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from config import Config, load_config, reload_config

_MISSING = "definitely_not_exists_config.json"


def _load_without_env(**env):
    """清掉相关 env 后按给定覆盖加载。"""
    with patch.dict(os.environ, env, clear=False):
        for k in ("AI_FRIEND_DEGRADE_THRESHOLD", "AI_FRIEND_MAX_FAKE_ACTIONS"):
            if k not in env:
                os.environ.pop(k, None)
        return load_config(path=_MISSING)


class TestNewConfigFields(unittest.TestCase):
    def test_defaults(self):
        cfg = _load_without_env()
        self.assertEqual(cfg.degrade_threshold, 3)
        self.assertEqual(cfg.max_fake_actions, 3)

    def test_env_override(self):
        cfg = _load_without_env(
            AI_FRIEND_DEGRADE_THRESHOLD="7",
            AI_FRIEND_MAX_FAKE_ACTIONS="5",
        )
        self.assertEqual(cfg.degrade_threshold, 7)
        self.assertEqual(cfg.max_fake_actions, 5)

    def test_validation_clamp(self):
        cfg = _load_without_env(
            AI_FRIEND_DEGRADE_THRESHOLD="0",
            AI_FRIEND_MAX_FAKE_ACTIONS="-1",
        )
        self.assertEqual(cfg.degrade_threshold, 3)
        self.assertEqual(cfg.max_fake_actions, 3)


class TestPersonalityFileEnv(unittest.TestCase):
    def test_env_override_personality_file(self):
        # L-05: AI_FRIEND_PERSONALITY_FILE 覆盖 personality_file
        with patch.dict(os.environ, {"AI_FRIEND_PERSONALITY_FILE": "personalities/custom.json"}, clear=False):
            os.environ.pop("DEEPSEEK_API_KEY", None)
            cfg = load_config(path=_MISSING)
        self.assertEqual(cfg.personality_file, "personalities/custom.json")

    def test_default_personality_file_without_env(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AI_FRIEND_PERSONALITY_FILE", None)
            cfg = load_config(path=_MISSING)
        self.assertEqual(cfg.personality_file, "personalities/default.json")


def _make_agent(cfg):
    """真实 Agent，外部依赖全部 mock（同 test_tool_failures_reset 的模式）。"""
    from core.agent import Agent

    personality = MagicMock()
    personality.config.name = "TestBot"
    personality.config.interests = []
    personality.config.traits = []
    personality.emotion.dominant_emotion = "neutral"
    personality.emotion.valence = 0.4
    personality.emotion.arousal = 0.5
    personality.emotion.resentment = 0.0
    personality.emotion.emotion_events = []

    short_term = MagicMock()
    short_term.get_all_reversed.return_value = []
    short_term.get_all.return_value = []

    return Agent(
        personality=personality,
        provider=MagicMock(),
        ltm=MagicMock(),
        retriever=MagicMock(),
        consolidator=MagicMock(),
        short_term=short_term,
        config=cfg,
    )


class TestAgentReadsConfig(unittest.TestCase):
    def test_agent_uses_config_values(self):
        tmpdir = tempfile.mkdtemp()
        cfg = Config()
        cfg.db_path = os.path.join(tmpdir, "test.db")
        cfg.personality_file = os.path.join(tmpdir, "role.json")
        cfg.degrade_threshold = 7
        cfg.max_fake_actions = 5
        agent = _make_agent(cfg)
        self.assertEqual(agent._degrade_threshold, 7)
        self.assertEqual(agent._max_fake_actions, 5)

    def test_agent_defaults_match_config(self):
        tmpdir = tempfile.mkdtemp()
        cfg = Config()
        cfg.db_path = os.path.join(tmpdir, "test.db")
        cfg.personality_file = os.path.join(tmpdir, "role.json")
        agent = _make_agent(cfg)
        self.assertEqual(agent._degrade_threshold, 3)
        self.assertEqual(agent._max_fake_actions, 3)


class TestLoadConfigCache(unittest.TestCase):
    """CF-010: load_config() process-level cache for default path."""

    def setUp(self):
        # Ensure a clean cache state for every test.
        import config as _config_module
        _config_module._CACHED_CONFIG = None

    def tearDown(self):
        import config as _config_module
        _config_module._CACHED_CONFIG = None

    def test_default_path_uses_cache(self):
        # Use a real temp file as the default config path cannot be overridden
        # without changing CONFIG_PATH; instead patch open to count disk reads.
        with patch("config.open") as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = "{}"
            cfg1 = load_config()
            cfg2 = load_config()
            self.assertIs(cfg1, cfg2)
            # builder path: os.path.exists + open read = disk touches once
            mock_open.assert_called_once()

    def test_reload_config_clears_cache(self):
        cfg1 = load_config()
        with patch("config.open") as mock_open:
            mock_open.return_value.__enter__.return_value.read.return_value = "{}"
            cfg2 = reload_config()
            mock_open.assert_called_once()
        self.assertIsNot(cfg1, cfg2)

    def test_custom_path_bypasses_cache(self):
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json", encoding="utf-8") as f:
            json.dump({"max_tokens": 111}, f)
            path1 = f.name
        with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".json", encoding="utf-8") as f:
            json.dump({"max_tokens": 222}, f)
            path2 = f.name
        try:
            cfg1 = load_config(path=path1)
            cfg2 = load_config(path=path2)
            self.assertEqual(cfg1.max_tokens, 111)
            self.assertEqual(cfg2.max_tokens, 222)
        finally:
            os.unlink(path1)
            os.unlink(path2)


if __name__ == "__main__":
    unittest.main()
