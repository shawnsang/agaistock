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


if __name__ == "__main__":
    unittest.main()
