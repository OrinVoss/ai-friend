"""Real API tests for DeepSeekProvider."""
import sys
import unittest

sys.path.insert(0, ".")

from tests.real_api.conftest import RealAPITestCase


class TestRealProvider(RealAPITestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from config import load_config
        cfg = load_config()
        from core.provider import DeepSeekProvider
        cls.provider = DeepSeekProvider(
            endpoint=cfg.api_endpoint, api_key=cfg.api_key,
            model=cfg.api_model, temperature=cfg.temperature,
            max_tokens=cfg.max_tokens, timeout=cfg.api_timeout,
        )

    def test_generate_non_streaming(self):
        result = self.provider.generate(
            [{"role": "user", "content": "hi"}], stream=False,
        )
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_generate_streaming(self):
        tokens = []

        def on_token(t):
            tokens.append(t)

        result = self.provider.generate(
            [{"role": "user", "content": "hello"}],
            stream=True, on_token=on_token,
        )
        self.assertGreater(len(tokens), 0)
        self.assertEqual("".join(tokens), result)
        self.assertGreater(len(result), 0)

    def test_thinking_parameter(self):
        from core.provider import DeepSeekProvider
        cfg = __import__("config").load_config()
        p = DeepSeekProvider(
            endpoint=cfg.api_endpoint, api_key=cfg.api_key,
            model=cfg.api_model, thinking="enabled", timeout=cfg.api_timeout,
        )
        result = p.generate(
            [{"role": "user", "content": "say hi"}], stream=False,
        )
        self.assertGreater(len(result), 0)


if __name__ == "__main__":
    unittest.main()
