import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agaistock import cli


class CliTests(unittest.TestCase):
    def test_list_on_empty_db_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            code = cli.main(["list", "--db", str(db_path), "--json"])
            self.assertEqual(code, 0)

    def test_delete_unknown_id_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            code = cli.main(["delete", "nope", "--db", str(db_path)])
            self.assertEqual(code, 1)

    def test_reviews_on_unknown_observation_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            code = cli.main(["reviews", "obs_nope", "--db", str(db_path), "--json"])
            self.assertEqual(code, 0)

    def test_db_path_env_var_is_used_when_flag_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "env.db"
            with mock.patch.dict(os.environ, {"AGAISTOCK_DB": str(db_path)}):
                cli.main(["list", "--json"])
            self.assertTrue(db_path.is_file())

    def test_review_persists_observation_and_returns_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            fake_verdict = {
                "reviewer_id": "anchor-chanlun", "reviewer_version": "0.1.0",
                "ran_at": "2026-11-24T07:00:00Z", "status": "ok", "duration_ms": 1,
                "data_refs": [], "findings": [], "proposed_invalidation": [],
                "horizon_hint": None, "caveats": [],
            }
            with mock.patch.object(cli, "run_reviewers", return_value=[]) as runner:
                code = cli.main([
                    "review", "--symbol", "002378", "--name", "章源钨业",
                    "--text", "还能拿半年", "--db", str(db_path), "--json",
                ])
            self.assertEqual(code, 0)

    def test_review_wires_llm_client_into_review_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            sentinel = object()
            captured = {}

            def fake_run_reviewers(ctx, reviewers):
                captured["ctx"] = ctx
                return []

            with mock.patch.object(cli, "run_reviewers", side_effect=fake_run_reviewers), \
                 mock.patch.object(cli.llm_client, "from_env", return_value=sentinel):
                code = cli.main([
                    "review", "--symbol", "002378", "--name", "章源钨业",
                    "--text", "还能拿半年", "--db", str(db_path), "--json",
                ])
            self.assertEqual(code, 0)
            # 措辞层必须真的接上：ctx.llm 拿到 from_env() 的返回值
            self.assertIs(captured["ctx"].llm, sentinel)

    def test_review_closes_the_db_connection_even_when_the_command_fails(self):
        # Windows 上未关闭的 sqlite 句柄会锁住 .db 文件（临时目录删除直接 PermissionError）。
        # 连接必须在 finally 里关 —— 命令中途抛异常时同样要关。
        conn = mock.MagicMock()
        with mock.patch.object(cli, "_open", return_value=conn), \
             mock.patch.object(cli.registry, "load_reviewers",
                               side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                cli.main([
                    "review", "--symbol", "002378", "--name", "章源钨业",
                    "--text", "还能拿半年", "--db", "unused.db", "--json",
                ])
        conn.close.assert_called_once_with()

    def test_list_closes_the_db_connection_even_when_it_fails(self):
        conn = mock.MagicMock()
        with mock.patch.object(cli, "_open", return_value=conn), \
             mock.patch.object(cli.db, "list_observations", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                cli.main(["list", "--db", "unused.db", "--json"])
        conn.close.assert_called_once_with()

    def test_review_accepts_structured_observation(self):
        # 接入层的结构化草稿要能落库：信心/依据/证伪条件不能丢。
        from agaistock.storage import db

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft_path = Path(tmp) / "draft.json"
            draft_path.write_text(json.dumps({
                "symbol": "002378", "name": "章源钨业",
                "thesis": "钨价上涨叠加产量翻倍",
                "direction": "bullish", "confidence": 0.75,
                "evidence": [{"text": "钨价从去年就开始涨", "type": "fact"}],
                "invalidation": ["钨价跌回去年年底的水平"],
                "timeframe": "半年", "trigger": "明年上半年产量翻倍",
            }, ensure_ascii=False), encoding="utf-8")
            # 本文件**没有** review 的既有用例（review 会连真实行情源、很慢），
            # 这里把点评师列表 mock 成空 —— 只验「草稿被内核接收并落库」。
            with mock.patch.object(cli.registry, "load_reviewers", return_value=[]):
                code = cli.main([
                    "review", "--symbol", "002378", "--name", "章源钨业",
                    "--text", "还能拿半年", "--observation-file", str(draft_path),
                    "--db", str(db_path), "--json",
                ])
            self.assertEqual(code, 0)
            conn = db.connect(db_path)
            rows = db.list_observations(conn)
            conn.close()
            self.assertEqual(rows[0]["confidence"], 0.75)
            self.assertEqual(rows[0]["invalidation"], ["钨价跌回去年年底的水平"])
            self.assertEqual(rows[0]["thesis"], "钨价上涨叠加产量翻倍")
            self.assertEqual(rows[0]["evidence"][0]["type"], "fact")

    def test_structured_observation_clamps_confidence(self):
        # 草稿里的信心越界要被夹住，不能直接进库。
        from agaistock.storage import db

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft_path = Path(tmp) / "draft.json"
            draft_path.write_text(
                json.dumps({"confidence": 3.5, "direction": "看多"}), encoding="utf-8"
            )
            with mock.patch.object(cli.registry, "load_reviewers", return_value=[]):
                code = cli.main([
                    "review", "--symbol", "002378", "--text", "还能拿半年",
                    "--observation-file", str(draft_path),
                    "--db", str(db_path), "--json",
                ])
            self.assertEqual(code, 0)
            conn = db.connect(db_path)
            rows = db.list_observations(conn)
            conn.close()
            self.assertEqual(rows[0]["confidence"], 1.0)
            # direction 非法（"看多" 不是 bullish/bearish/neutral）→ 退回关键词解析
            self.assertIn(rows[0]["direction"], ("bullish", "bearish", "neutral"))

    def test_json_output_survives_unencodable_char(self):
        """Windows 中文机器上 stdout 是 GBK：输出里有一个 GBK 编不出来的字符时，
        整条命令不能崩。"""
        import subprocess
        import sys
        from agaistock.storage import db

        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "t.db"
            conn = db.connect(db_path)
            db.migrate(conn)
            db.insert_observation(conn, {
                "symbol": "002378",
                "name": "章\ufffd源钨业",
                "direction": "bullish",
                "thesis": "含替换字符的主张\ufffd",
                "raw_text": "原始文本",
            })
            conn.close()
            env = dict(os.environ)
            env["PYTHONPATH"] = str(repo_root / "src")
            env["PYTHONIOENCODING"] = ""  # 故意清掉，逼 CLI 自己处理
            result = subprocess.run(
                [sys.executable, "-m", "agaistock.cli", "list", "--db", str(db_path), "--json"],
                cwd=repo_root, env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(len(payload["items"]), 1)
            self.assertIn("\ufffd", payload["items"][0]["name"])


if __name__ == "__main__":
    unittest.main()
