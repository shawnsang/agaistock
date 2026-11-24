"""内核随包走的漂移守卫。

宿主安装的是整个 Mini App 包目录，所以 `miniapps/agaistock/src/agaistock` 与
`miniapps/agaistock/config` 必须是仓库里 `src/agaistock`、`config` 的**逐字节副本**。
副本漂了就等于交付了一个和仓库不一致的内核 —— 开发机上 CLI 用新内核、
安装后的 Mini App 用旧内核，两边行为不一致。

修法：python tools/sync-kernel.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "miniapps" / "agaistock"
SYNC = ROOT / "tools" / "sync-kernel.py"


class KernelVendorTest(unittest.TestCase):
    def test_vendored_kernel_matches_source(self):
        result = subprocess.run(
            [sys.executable, str(SYNC), "--check"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(
            result.returncode,
            0,
            "内核副本与源不一致：\n" + result.stdout + result.stderr
            + "\n修复：python tools/sync-kernel.py",
        )

    def test_vendored_kernel_is_self_contained(self):
        """用插件根当 cwd、插件内 src 当 PYTHONPATH，必须能独立跑起来。

        这正是安装后的运行方式：PYTHONPATH 指向插件自己的 src，
        config 也从插件根读。不依赖 editable 安装。

        **必须带 `-S`**：editable 安装注册的是 meta-path finder，优先级高于
        PYTHONPATH —— 不带 `-S` 时这里会命中仓库里那份，测了个寂寞。
        """
        env = dict(os.environ)
        env["PYTHONPATH"] = str(PLUGIN_ROOT / "src")
        env.pop("AGAISTOCK_DB", None)
        result = subprocess.run(
            [
                sys.executable,
                "-S",
                "-c",
                "import agaistock, agaistock.config as c;"
                "print(agaistock.__file__);"
                "print(c.repo_root());"
                "print(len(c.load_scoring()['dimensions']))",
            ],
            cwd=PLUGIN_ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 3, result.stdout)
        # 必须导入的是插件里的那份副本，不是仓库里的 editable 安装
        self.assertIn("miniapps", lines[0], result.stdout)
        self.assertNotIn("site-packages", lines[0], result.stdout)
        # repo_root 必须落在插件根上，配置才能从插件内读到
        self.assertEqual(Path(lines[1]).resolve(), PLUGIN_ROOT.resolve(), result.stdout)
        # 五个评分维度必须读得到
        self.assertEqual(lines[2].strip(), "5", result.stdout)


if __name__ == "__main__":
    unittest.main()
