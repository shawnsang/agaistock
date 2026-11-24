import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agaistock.providers import mcode_cli


class McodeCliTests(unittest.TestCase):
    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_unwraps_text_field(self, fake_run):
        fake_run.return_value = mock.Mock(
            returncode=0,
            stdout=json.dumps([{"type": "text", "text": "hello"}]),
            stderr="",
        )
        result = mcode_cli.call_connector("some__tool", {"a": 1})
        self.assertEqual(result, "hello")

    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_raises_on_non_zero_exit(self, fake_run):
        fake_run.return_value = mock.Mock(returncode=1, stdout="", stderr="boom")
        with self.assertRaises(RuntimeError):
            mcode_cli.call_connector("some__tool", {})

    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_uses_args_file_not_inline_json(self, fake_run):
        fake_run.return_value = mock.Mock(
            returncode=0, stdout=json.dumps([{"type": "text", "text": "ok"}]), stderr=""
        )
        mcode_cli.call_connector("some__tool", {"code": "002378"})
        command = fake_run.call_args[0][0]
        self.assertIn("--args-file", command)
        self.assertNotIn("--args ", command)

    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_escapes_paths_with_spaces(self, fake_run):
        fake_run.return_value = mock.Mock(
            returncode=0, stdout=json.dumps([{"type": "text", "text": "ok"}]), stderr=""
        )
        # 目录必须真实存在：实现要把 args.json 写进去，把目录存在性一起 mock 掉会写崩。
        with tempfile.TemporaryDirectory() as root:
            spaced = Path(root) / "a b" / "tmp"
            spaced.mkdir(parents=True)
            with mock.patch("agaistock.providers.mcode_cli.tempfile.TemporaryDirectory") as tmp_dir:
                tmp_dir.return_value.__enter__.return_value = str(spaced)
                mcode_cli.call_connector("some__tool", {})
            args_file = spaced / "args.json"
            # args 文件确实写进了这个带空格的目录
            self.assertTrue(args_file.is_file())
        command = fake_run.call_args[0][0]
        # 含空格的路径在命令行里必须被引号包住，否则 cmd.exe 会把它拆成两个参数
        self.assertIn(f'"{args_file}"', command)

    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_raises_missing_cli_when_command_not_found(self, fake_run):
        fake_run.return_value = mock.Mock(
            returncode=1,
            stdout="",
            stderr="'mcode-tools' is not recognized as an internal or external command",
        )
        with self.assertRaises(mcode_cli.MCodedToolsMissing):
            mcode_cli.call_connector("some__tool", {})


if __name__ == "__main__":
    unittest.main()
