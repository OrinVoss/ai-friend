"""Tests for LLMProvider abstract base class (#23)."""
import unittest
from unittest.mock import MagicMock

from core.provider import LLMProvider, DeepSeekProvider


class TestLLMProviderABC(unittest.TestCase):
    def test_cannot_instantiate_abstract_class(self):
        with self.assertRaises(TypeError):
            LLMProvider()

    def test_deepseek_provider_is_instance_of_abc(self):
        p = DeepSeekProvider(
            endpoint="https://api.example.com",
            api_key="test-key",
            model="test-model",
        )
        self.assertIsInstance(p, LLMProvider)

    def test_concrete_provider_must_implement_generate(self):
        class BrokenProvider(LLMProvider):
            pass

        with self.assertRaises(TypeError):
            BrokenProvider()

    def test_custom_provider_implements_generate(self):
        class MockProvider(LLMProvider):
            def generate(self, messages, stream=True, on_token=None,
                         max_tokens=None, response_format=None):
                return "mocked"

        p = MockProvider()
        self.assertEqual(p.generate([]), "mocked")


if __name__ == "__main__":
    unittest.main()
