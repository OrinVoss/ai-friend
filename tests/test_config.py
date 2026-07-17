"""Tests for config.py — #255: degrade_threshold / max_fake_actions 接入 config。"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from config import Config, load_config

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
        cfg.personality_file = os.path.join(tmpdir, "personality.json")
        cfg.degrade_threshold = 7
        cfg.max_fake_actions = 5
        agent = _make_agent(cfg)
        self.assertEqual(agent._degrade_threshold, 7)
        self.assertEqual(agent._max_fake_actions, 5)

    def test_agent_defaults_match_config(self):
        tmpdir = tempfile.mkdtemp()
        cfg = Config()
        cfg.db_path = os.path.join(tmpdir, "test.db")
        cfg.personality_file = os.path.join(tmpdir, "personality.json")
        agent = _make_agent(cfg)
        self.assertEqual(agent._degrade_threshold, 3)
        self.assertEqual(agent._max_fake_actions, 3)


if __name__ == "__main__":
    unittest.main()
