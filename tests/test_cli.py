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

    def test_review_data_dir_comes_from_the_host_env_var(self):
        # 缠论分析工作目录必须落宿主给的目录（AGAISTOCK_DATA_DIR → context.dataDir），
        # 不是插件包自己的 data/ —— 包目录是安装产物，可能只读。
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            captured = {}

            def fake_run_reviewers(ctx, reviewers):
                captured["ctx"] = ctx
                return []

            with mock.patch.object(cli, "run_reviewers", side_effect=fake_run_reviewers), \
                 mock.patch.dict(os.environ, {"AGAISTOCK_DATA_DIR": tmp}):
                code = cli.main([
                    "review", "--symbol", "002378", "--name", "章源钨业",
                    "--text", "还能拿半年", "--db", str(db_path), "--json",
                ])
            self.assertEqual(code, 0)
            self.assertEqual(captured["ctx"].data_dir, Path(tmp))

    def test_review_closes_the_db_connection_even_when_the_command_fails(self):
        # Windows 上未关闭的 sqlite 句柄会锁住 .db 文件（临时目录删除直接 PermissionError）。
        # 连接必须在 finally 里关 —— 命令中途抛异常时同样要关。
        conn = mock.MagicMock()
        with mock.patch.object(cli, "_open", return_value=conn), \
             mock.patch.object(cli.db, "find_thread_head", return_value=None), \
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
             mock.patch.object(cli.db, "list_threads", side_effect=RuntimeError("boom")):
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


class ContinuationCliTests(unittest.TestCase):
    """观察续接（Task 21）：同一标的的第二次输入不新开一条记录。"""

    def _run(self, argv, db_path):
        """跑一条 CLI 命令，返回解析后的 JSON。"""
        import io
        from contextlib import redirect_stdout

        buffer = io.StringIO()
        with mock.patch.object(cli.registry, "load_reviewers", return_value=[]), \
             redirect_stdout(buffer):
            code = cli.main(argv)
        self.assertEqual(code, 0)
        return json.loads(buffer.getvalue())

    def _draft(self, tmp, payload, name="draft"):
        path = Path(tmp) / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def _review(self, tmp, db_path, draft, extra=()):
        return self._run([
            "review", "--symbol", "002378", "--name", "章源钨业",
            "--text", "补充一句", "--observation-file", draft,
            "--db", str(db_path), "--json", *extra,
        ], db_path)

    def test_second_review_continues_the_same_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.7, "thesis": "钨价上涨", "timeframe": "半年",
                "evidence": [{"text": "钨价从去年就开始涨", "type": "fact"}],
                "invalidation": ["钨价跌回去年年底的水平"],
            })
            first = self._review(tmp, db_path, draft)
            second = self._review(tmp, db_path, draft)
            self.assertNotEqual(first["observation_id"], second["observation_id"])
            self.assertEqual(first["thread_id"], second["thread_id"])
            self.assertEqual(second["supersedes_id"], first["observation_id"])
            self.assertEqual(second["version"], 2)
            self.assertIsNone(first["supersedes_id"])
            self.assertEqual(first["version"], 1)

    def test_continuation_keeps_the_observation_list_at_one_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.7, "thesis": "钨价上涨",
            })
            self._review(tmp, db_path, draft)
            self._review(tmp, db_path, draft)
            listing = self._run(["list", "--db", str(db_path), "--json"], db_path)
            self.assertEqual(len(listing["items"]), 1)
            self.assertEqual(listing["items"][0]["version"], 2)

    def test_list_all_versions_returns_the_raw_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.7, "thesis": "钨价上涨",
            })
            self._review(tmp, db_path, draft)
            self._review(tmp, db_path, draft)
            listing = self._run(["list", "--all-versions", "--db", str(db_path), "--json"], db_path)
            self.assertEqual(len(listing["items"]), 2)

    def test_continuation_merges_evidence_and_invalidation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            first_draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.7, "thesis": "钨价上涨",
                "evidence": [{"text": "钨价从去年就开始涨", "type": "fact"}],
                "invalidation": ["钨价跌回去年年底的水平"],
            }, name="first")
            second_draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.8, "thesis": "产量翻倍确认",
                "evidence": [{"text": "明年上半年产量翻倍", "type": "assumption"}],
                "invalidation": ["产量不及预期"],
            }, name="second")
            self._review(tmp, db_path, first_draft)
            self._review(tmp, db_path, second_draft)
            listing = self._run(["list", "--db", str(db_path), "--json"], db_path)
            head = listing["items"][0]
            self.assertEqual(
                [item["text"] for item in head["evidence"]],
                ["钨价从去年就开始涨", "明年上半年产量翻倍"],
            )
            self.assertEqual(
                head["invalidation"],
                ["钨价跌回去年年底的水平", "产量不及预期"],
            )
            self.assertEqual(head["thesis"], "产量翻倍确认")
            self.assertEqual(head["confidence"], 0.8)

    def test_continuation_keeps_the_old_direction_when_the_new_one_is_neutral(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            first_draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.7, "thesis": "钨价上涨",
            }, name="first")
            second_draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "neutral",
                "confidence": 0.0, "thesis": "产量翻倍确认",
            }, name="second")
            self._review(tmp, db_path, first_draft)
            self._review(tmp, db_path, second_draft)
            listing = self._run(["list", "--db", str(db_path), "--json"], db_path)
            head = listing["items"][0]
            self.assertEqual(head["direction"], "bullish")
            self.assertEqual(head["confidence"], 0.7)

    def test_continuation_never_pushes_the_review_date_forward(self):
        """观察期锚定在线程起点 —— 反复补充不能无限顺延结算日。"""
        from datetime import date

        from agaistock import horizon as horizon_mod
        from agaistock.storage import db

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            # 第一版是 20 天前记的：直接落库，好把线程起点固定住。
            conn = db.connect(db_path)
            db.migrate(conn)
            db.insert_observation(conn, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "thesis": "钨价上涨", "confidence": 0.7,
                "created_at": "2026-11-01T09:00:00+00:00",
            })
            conn.close()

            draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.8, "thesis": "产量翻倍确认",
            })
            payload = self._review(tmp, db_path, draft)

            anchored = horizon_mod.plan({}, [], start="2026-11-01")["review_at"]
            naive = horizon_mod.plan({}, [], start=date.today().isoformat())["review_at"]
            self.assertEqual(payload["horizon"]["review_at"], anchored)
            self.assertLess(anchored, naive, "续接后的结算日必须早于「从今天起算」")

    def test_new_thread_starts_an_independent_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.7, "thesis": "钨价上涨",
            })
            first = self._review(tmp, db_path, draft)
            second = self._review(tmp, db_path, draft, extra=["--new-thread"])
            self.assertNotEqual(first["thread_id"], second["thread_id"])
            self.assertIsNone(second["supersedes_id"])
            listing = self._run(["list", "--db", str(db_path), "--json"], db_path)
            self.assertEqual(len(listing["items"]), 2)

    def test_delete_removes_the_whole_thread(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.7, "thesis": "钨价上涨",
            })
            first = self._review(tmp, db_path, draft)
            second = self._review(tmp, db_path, draft)
            self._run(["delete", second["observation_id"], "--db", str(db_path), "--json"], db_path)
            listing = self._run(["list", "--db", str(db_path), "--json"], db_path)
            self.assertEqual(listing["items"], [])
            raw = self._run(
                ["list", "--all-versions", "--include-deleted", "--db", str(db_path), "--json"],
                db_path,
            )
            self.assertEqual(len(raw["items"]), 2, "软删的版本行必须保留")

    def test_reviews_returns_the_whole_thread_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.7, "thesis": "钨价上涨",
            })
            first = self._review(tmp, db_path, draft)
            second = self._review(tmp, db_path, draft)
            payload = self._run(
                ["reviews", second["observation_id"], "--db", str(db_path), "--json"], db_path
            )
            self.assertEqual(payload["thread_id"], first["thread_id"])
            self.assertEqual([entry["version"] for entry in payload["versions"]], [1, 2])
            self.assertEqual(
                [entry["observation_id"] for entry in payload["versions"]],
                [first["observation_id"], second["observation_id"]],
            )

    def test_reviews_items_belong_to_the_requested_version(self):
        """`items` = **被请求的那一版**的点评（与 `observation_id` 一致）。

        Task 21 复审 Minor-1：`items` 曾装「线程最后一版」的点评 ——
        请求 v1 却拿到 v2 的点评，而 `payload.observation_id` 回显的是 v1 ⇒ 语义漂移。
        整条线程的历史在 `versions` 里，那才是「线程历史」的位置。
        """
        from agaistock.storage import db

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.7, "thesis": "钨价上涨",
            })
            first = self._review(tmp, db_path, draft)
            second = self._review(tmp, db_path, draft)

            # 给两版各落一条**可区分**的点评。
            conn = db.connect(db_path)
            db.insert_review(conn, first["observation_id"], {
                "reviewer_id": "anchor-chanlun", "reviewer_version": "0.1.0",
                "status": "ok", "ran_at": "2026-11-01T10:00:00+00:00",
                "summary": "第一版点评",
            })
            db.insert_review(conn, second["observation_id"], {
                "reviewer_id": "anchor-chanlun", "reviewer_version": "0.1.0",
                "status": "ok", "ran_at": "2026-11-02T10:00:00+00:00",
                "summary": "第二版点评",
            })
            conn.close()

            payload = self._run(
                ["reviews", first["observation_id"], "--db", str(db_path), "--json"], db_path
            )
            self.assertEqual(payload["observation_id"], first["observation_id"])
            self.assertEqual(len(payload["items"]), 1)
            self.assertEqual(payload["items"][0]["ran_at"], "2026-11-01T10:00:00+00:00")
            self.assertEqual(payload["items"][0]["verdict"]["summary"], "第一版点评")
            # 线程历史仍然完整：两版都在 `versions` 里。
            self.assertEqual(len(payload["versions"]), 2)

    def test_continuation_matches_by_name_when_the_symbol_appears_later(self):
        """先按简称记、后来解析出代码 ⇒ 仍是**同一条线程**（Task 21 复审 Minor-2）。

        真实场景：模型这次没解析出代码、下次解析出来了 —— 不能因此裂成两条记录。
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.7, "thesis": "钨价上涨",
            })
            # 第一次：只有简称，没有代码。
            first = self._run([
                "review", "--symbol", "", "--name", "章源钨业",
                "--text", "补充一句", "--observation-file", draft,
                "--db", str(db_path), "--json",
            ], db_path)
            # 第二次：模型解析出了代码。
            second = self._review(tmp, db_path, draft)
            self.assertEqual(first["thread_id"], second["thread_id"])
            self.assertEqual(second["version"], 2)
            listing = self._run(["list", "--db", str(db_path), "--json"], db_path)
            self.assertEqual(len(listing["items"]), 1, "同一条线程只能占一行")

    def test_review_payload_carries_the_previous_rounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.7, "thesis": "钨价上涨",
            })
            first = self._review(tmp, db_path, draft)
            second = self._review(tmp, db_path, draft)
            self.assertEqual(second["version"], 2)
            self.assertEqual(len(second["history"]), 1)
            self.assertEqual(second["history"][0]["observation_id"], first["observation_id"])
            self.assertEqual(second["history"][0]["version"], 1)

    def test_continuation_matches_by_name_when_symbol_is_missing(self):
        """模型没解析出代码时，按股票简称唯一匹配已有线程。"""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            draft = self._draft(tmp, {
                "symbol": "002378", "name": "章源钨业", "direction": "bullish",
                "confidence": 0.7, "thesis": "钨价上涨",
            })
            first = self._review(tmp, db_path, draft)
            # 第二次只给了简称：--symbol 为空。
            second = self._run([
                "review", "--symbol", "", "--name", "章源钨业",
                "--text", "补充一句", "--observation-file", draft,
                "--db", str(db_path), "--json",
            ], db_path)
            self.assertEqual(first["thread_id"], second["thread_id"])
            self.assertEqual(second["version"], 2)


if __name__ == "__main__":
    unittest.main()
