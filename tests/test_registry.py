import sys
import tempfile
import unittest
from pathlib import Path

from agaistock.reviewers import registry


class FakeReviewer:
    id = "fake"
    version = "0.0.1"

    def review(self, ctx):
        raise AssertionError("不应被调用")


def _write_module(directory: Path, name: str, source: str) -> None:
    """在临时目录里放一个可导入的模块。"""
    (directory / f"{name}.py").write_text(source, encoding="utf-8")


class RegistryTests(unittest.TestCase):
    def test_disabled_reviewers_are_skipped(self):
        specs = [
            {"id": "a", "enabled": True, "module": "x", "weight": 1.0},
            {"id": "b", "enabled": False, "module": "y", "weight": 1.0},
        ]
        loaded = registry.load_reviewers(specs)
        self.assertEqual([r["id"] for r in loaded], ["a"])

    def test_instantiate_imports_module_and_class(self):
        spec = {
            "id": "fake",
            "enabled": True,
            "module": "tests.test_registry",
            "weight": 1.0,
        }
        instance = registry.instantiate(spec)
        self.assertIsInstance(instance, FakeReviewer)

    def test_instantiate_raises_for_missing_module(self):
        with self.assertRaises(ImportError):
            registry.instantiate({"id": "x", "module": "no.such.module", "weight": 1.0})

    def test_load_reviewers_isolates_import_time_crash(self):
        """模块在 import 阶段抛 RuntimeError：不能拖垮整轮加载。"""
        module_name = "agaistock_test_broken_reviewer"
        spec = {"id": "broken", "enabled": True, "module": module_name, "weight": 1.0}
        with tempfile.TemporaryDirectory() as tmp:
            _write_module(Path(tmp), module_name, 'raise RuntimeError("导入期炸了")\n')
            sys.path.insert(0, tmp)
            try:
                # instantiate 自身保持抛错，隔离是 load_reviewers 的职责
                with self.assertRaises(RuntimeError):
                    registry.instantiate(spec)
                loaded = registry.load_reviewers([
                    spec,
                    {"id": "good", "enabled": True, "module": "tests.test_registry", "weight": 1.0},
                ])
            finally:
                sys.path.remove(tmp)
                sys.modules.pop(module_name, None)

        self.assertEqual([r["id"] for r in loaded], ["broken", "good"])
        broken, good = loaded
        self.assertIn("broken", broken["error"])
        self.assertIn(module_name, broken["error"])
        self.assertIn("RuntimeError", broken["error"])
        self.assertIn("导入期炸了", broken["error"])
        # 占位实例在 review 时抛错，由引擎转成 status='error' 的 verdict
        with self.assertRaises(RuntimeError):
            broken["instance"].review(None)
        # 同一批次里的其它点评师照常加载
        self.assertIsInstance(good["instance"], FakeReviewer)
        self.assertNotIn("error", good)

    def test_instantiate_rejects_ambiguous_reviewer_class(self):
        """多个 *Reviewer 候选且无精确 Reviewer：必须报错并列出候选名，不能猜。"""
        module_name = "agaistock_test_ambiguous_reviewer"
        source = (
            "class BaseReviewer:\n"
            "    id = 'base'\n"
            "\n"
            "class ChanlunReviewer:\n"
            "    id = 'chanlun'\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            _write_module(Path(tmp), module_name, source)
            sys.path.insert(0, tmp)
            try:
                with self.assertRaises(ImportError) as raised:
                    registry.instantiate(
                        {"id": "ambiguous", "module": module_name, "weight": 1.0}
                    )
            finally:
                sys.path.remove(tmp)
                sys.modules.pop(module_name, None)

        message = str(raised.exception)
        self.assertIn("BaseReviewer", message)
        self.assertIn("ChanlunReviewer", message)


if __name__ == "__main__":
    unittest.main()
