import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agaistock import config


def with_config(filename, content, func):
    """把 config 的仓库根临时指向一个只含指定配置文件的临时目录。"""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "config").mkdir()
        (root / "config" / filename).write_text(content, encoding="utf-8")
        original = config.repo_root
        config.repo_root = lambda: root
        try:
            return func()
        finally:
            config.repo_root = original


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

    def test_non_dict_top_level_raises_value_error(self):
        # 顶层是数组时不能抛 AttributeError，要给可读的 ValueError。
        with self.assertRaises(ValueError):
            with_config("scoring.json", "[1, 2, 3]", config.load_scoring)

    def test_scoring_missing_dimensions_raises(self):
        with self.assertRaises(ValueError):
            with_config("scoring.json", '{"other": 1}', config.load_scoring)

    def test_scoring_dimension_missing_field_raises(self):
        payload = json.dumps({"dimensions": [{"name": "事实锚定"}]})
        with self.assertRaises(ValueError):
            with_config("scoring.json", payload, config.load_scoring)

    def test_reviewers_missing_registry_raises(self):
        with self.assertRaises(ValueError):
            with_config("reviewers.json", '{"other": 1}', config.load_reviewers)

    def test_reviewer_missing_field_raises(self):
        payload = json.dumps({"reviewers": [{"id": "anchor-chanlun"}]})
        with self.assertRaises(ValueError):
            with_config("reviewers.json", payload, config.load_reviewers)

    def test_empty_reviewer_registry_fails_fast(self):
        # 空注册表 = 产品核心功能整体失效，必须报错而不是静默返回 []。
        with self.assertRaises(ValueError):
            with_config("reviewers.json", '{"reviewers": []}', config.load_reviewers)


class DataDirTest(unittest.TestCase):
    """运行期数据目录（数据库之外的可写工作区）由宿主给。

    插件目录是**安装产物**：可能被重装覆盖，也可能只读安装 ——
    运行产物不能写在那里。
    """

    def test_env_var_wins(self):
        with mock.patch.dict(os.environ, {"AGAISTOCK_DATA_DIR": "/tmp/host-data"}):
            self.assertEqual(config.data_dir(), Path("/tmp/host-data"))

    def test_falls_back_to_repo_data_dir(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(config.data_dir(), config.repo_root() / "data")

    def test_blank_env_var_is_treated_as_unset(self):
        with mock.patch.dict(os.environ, {"AGAISTOCK_DATA_DIR": "   "}):
            self.assertEqual(config.data_dir(), config.repo_root() / "data")


if __name__ == "__main__":
    unittest.main()
