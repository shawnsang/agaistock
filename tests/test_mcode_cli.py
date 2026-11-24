import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agaistock.providers import mcode_cli


class McodeCliTests(unittest.TestCase):
    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_unwraps_text_field(self, fake_run):
        # capture_output 不带 text=True 时拿到的是**字节**（实现已改成按字节解码）
        fake_run.return_value = mock.Mock(
            returncode=0,
            stdout=json.dumps([{"type": "text", "text": "hello"}]).encode("utf-8"),
            stderr=b"",
        )
        result = mcode_cli.call_connector("some__tool", {"a": 1})
        self.assertEqual(result, "hello")

    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_raises_on_non_zero_exit(self, fake_run):
        fake_run.return_value = mock.Mock(returncode=1, stdout=b"", stderr=b"boom")
        with self.assertRaises(RuntimeError) as ctx:
            mcode_cli.call_connector("some__tool", {})
        # MCodedToolsMissing 是 RuntimeError 的子类，只断言 RuntimeError 分辨不出来：
        # 连接器自身报错必须不能被误判成「CLI 不在 PATH」。
        self.assertNotIsInstance(ctx.exception, mcode_cli.MCodedToolsMissing)

    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_uses_args_file_not_inline_json(self, fake_run):
        fake_run.return_value = mock.Mock(
            returncode=0,
            stdout=json.dumps([{"type": "text", "text": "ok"}]).encode("utf-8"),
            stderr=b"",
        )
        mcode_cli.call_connector("some__tool", {"code": "002378"})
        command = fake_run.call_args[0][0]
        self.assertIn("--args-file", command)
        self.assertNotIn("--args ", command)

    @mock.patch("agaistock.providers.mcode_cli.subprocess.run")
    def test_call_connector_escapes_paths_with_spaces(self, fake_run):
        fake_run.return_value = mock.Mock(
            returncode=0,
            stdout=json.dumps([{"type": "text", "text": "ok"}]).encode("utf-8"),
            stderr=b"",
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
            stdout=b"",
            stderr=b"'mcode-tools' is not recognized as an internal or external command",
        )
        with self.assertRaises(mcode_cli.MCodedToolsMissing):
            mcode_cli.call_connector("some__tool", {})


class DecodeOutputTest(unittest.TestCase):
    def test_prefers_utf8(self):
        from agaistock.providers.mcode_cli import _decode_output
        self.assertEqual(_decode_output("章源钨业".encode("utf-8")), "章源钨业")

    def test_falls_back_to_gbk_instead_of_replacement_char(self):
        from agaistock.providers.mcode_cli import _decode_output
        # GBK 字节：非法 UTF-8，但合法 GBK。
        # 老实现 errors="replace" 会把它变成 U+FFFD —— 那正是崩掉整轮点评的元凶。
        # （brief 原文写的 b"\xd5\xc5" 在 GBK 里其实是「张」，「章」是 b"\xd5\xc2"；
        #   两个字节序列都断言一遍 —— 行为是「按 GBK 解出来」，不是「猜对某个字」。）
        decoded = _decode_output(b"\xd5\xc2")
        self.assertEqual(decoded, "章")
        self.assertNotIn("\ufffd", decoded)
        brief_bytes = _decode_output(b"\xd5\xc5")
        self.assertEqual(brief_bytes, "张")
        self.assertNotIn("\ufffd", brief_bytes)

    def test_replacement_char_only_as_last_resort(self):
        from agaistock.providers.mcode_cli import _decode_output
        # 既不是合法 UTF-8 也不是合法 GBK 的字节：只能替换，但不能抛。
        self.assertIsInstance(_decode_output(b"\x80"), str)


if __name__ == "__main__":
    unittest.main()
