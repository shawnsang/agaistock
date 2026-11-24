import unittest

from agaistock.llm import client


class LlmClientTests(unittest.TestCase):
    def test_from_env_returns_none_when_incomplete(self):
        self.assertIsNone(client.from_env(base_url="", api_key="", model=""))

    def test_extracts_text_from_openai_shape(self):
        payload = {"choices": [{"message": {"content": "你好"}}]}
        self.assertEqual(client.extract_text(payload), "你好")


if __name__ == "__main__":
    unittest.main()
