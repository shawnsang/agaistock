import unittest

from agaistock import config


class ConfigTests(unittest.TestCase):
    def test_load_scoring_returns_five_fixed_dimensions(self):
        scoring = config.load_scoring()
        names = [d["name"] for d in scoring["dimensions"]]
        self.assertEqual(
            names,
            ["事实锚定", "证伪条件", "逻辑链条", "位置与时机", "一致性"],
        )
        self.assertAlmostEqual(sum(d["weight"] for d in scoring["dimensions"]), 1.0)

    def test_load_reviewers_returns_registry(self):
        reviewers = config.load_reviewers()
        self.assertTrue(reviewers)
        for item in reviewers:
            self.assertIn("id", item)
            self.assertIn("module", item)
            self.assertIn("weight", item)

    def test_repo_root_contains_config_dir(self):
        self.assertTrue((config.repo_root() / "config" / "scoring.json").is_file())


if __name__ == "__main__":
    unittest.main()
