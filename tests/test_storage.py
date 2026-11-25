import sqlite3
import tempfile
import unittest
from pathlib import Path

from agaistock.storage import db


def make_conn():
    conn = db.connect(":memory:")
    db.migrate(conn)
    return conn


OBSERVATION = {
    "symbol": "002378",
    "name": "章源钨业",
    "direction": "bullish",
    "thesis": "钨价上涨，还可拿半年",
    "confidence": 0.72,
    "timeframe": "半年",
    "trigger": "",
    "position_json": "{}",
    "raw_text": "章源钨业我看了三年了",
}


def verdict(reviewer_id="anchor-chanlun", ran_at="2026-11-24T07:30:00Z"):
    return {
        "reviewer_id": reviewer_id,
        "reviewer_version": "0.1.0",
        "ran_at": ran_at,
        "status": "ok",
        "duration_ms": 100,
        "data_refs": [],
        "findings": [],
        "proposed_invalidation": [],
        "horizon_hint": None,
        "caveats": [],
    }


class StorageTests(unittest.TestCase):
    def test_migrate_is_idempotent(self):
        conn = make_conn()
        db.migrate(conn)
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        self.assertIn("observations", tables)
        self.assertIn("reviews", tables)
        self.assertIn("adjustment_factors", tables)

    def test_insert_and_list_observation(self):
        conn = make_conn()
        obs_id = db.insert_observation(conn, OBSERVATION)
        rows = db.list_observations(conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], obs_id)
        self.assertIsNone(rows[0]["deleted_at"])

    def test_soft_delete_hides_observation_by_default(self):
        conn = make_conn()
        obs_id = db.insert_observation(conn, OBSERVATION)
        self.assertTrue(db.soft_delete_observation(conn, obs_id))
        self.assertEqual(db.list_observations(conn), [])
        self.assertEqual(len(db.list_observations(conn, include_deleted=True)), 1)

    def test_soft_delete_unknown_id_returns_false(self):
        conn = make_conn()
        self.assertFalse(db.soft_delete_observation(conn, "nope"))

    def test_insert_review_appends_every_run(self):
        conn = make_conn()
        obs_id = db.insert_observation(conn, OBSERVATION)
        db.insert_review(conn, obs_id, verdict(ran_at="2026-11-24T07:30:00Z"))
        db.insert_review(conn, obs_id, verdict(ran_at="2026-11-24T09:00:00Z"))
        rows = conn.execute("SELECT * FROM reviews").fetchall()
        self.assertEqual(len(rows), 2)

    def test_latest_reviews_returns_only_newest_per_reviewer(self):
        conn = make_conn()
        obs_id = db.insert_observation(conn, OBSERVATION)
        db.insert_review(conn, obs_id, verdict(reviewer_id="a", ran_at="2026-11-24T07:00:00Z"))
        db.insert_review(conn, obs_id, verdict(reviewer_id="a", ran_at="2026-11-24T09:00:00Z"))
        db.insert_review(conn, obs_id, verdict(reviewer_id="b", ran_at="2026-11-24T08:00:00Z"))
        latest = db.latest_reviews(conn, obs_id)
        self.assertEqual([r["reviewer_id"] for r in latest], ["b", "a"])
        a_rows = [r for r in latest if r["reviewer_id"] == "a"]
        self.assertEqual(a_rows[0]["ran_at"], "2026-11-24T09:00:00Z")

    def test_latest_reviews_returns_one_row_when_ran_at_ties(self):
        """同一 reviewer 两条 ran_at 相同的 review，只能返回一条。"""
        conn = make_conn()
        obs_id = db.insert_observation(conn, OBSERVATION)
        db.insert_review(conn, obs_id, verdict(reviewer_id="a", ran_at="2026-11-24T07:00:00Z"))
        db.insert_review(conn, obs_id, verdict(reviewer_id="a", ran_at="2026-11-24T07:00:00Z"))
        latest = db.latest_reviews(conn, obs_id)
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["reviewer_id"], "a")
        self.assertEqual(latest[0]["ran_at"], "2026-11-24T07:00:00Z")

    def test_insert_observation_keeps_position_json_verbatim(self):
        """position_json 已是序列化字符串，原样落库，不得被静默丢弃。"""
        conn = make_conn()
        observation = dict(OBSERVATION, position_json='{"shares": 1000}')
        obs_id = db.insert_observation(conn, observation)
        rows = db.list_observations(conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], obs_id)
        self.assertEqual(rows[0]["position_json"], '{"shares": 1000}')

    def test_insert_observation_serializes_position_dict(self):
        """position 传 dict 时，序列化后落库。"""
        conn = make_conn()
        observation = dict(OBSERVATION)
        observation.pop("position_json")
        observation["position"] = {"shares": 1000}
        db.insert_observation(conn, observation)
        rows = db.list_observations(conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["position_json"], '{"shares": 1000}')

    def test_soft_deleted_observation_keeps_its_reviews(self):
        """软删观察不隐藏其 reviews —— 全局约束：reviews 保留。"""
        conn = make_conn()
        obs_id = db.insert_observation(conn, OBSERVATION)
        db.insert_review(conn, obs_id, verdict())
        self.assertTrue(db.soft_delete_observation(conn, obs_id))
        self.assertEqual(db.list_observations(conn), [])
        self.assertEqual(len(db.list_observations(conn, include_deleted=True)), 1)
        latest = db.latest_reviews(conn, obs_id)
        self.assertEqual(len(latest), 1)
        self.assertEqual(latest[0]["reviewer_id"], "anchor-chanlun")

    def test_insert_and_list_adjustment_factors(self):
        conn = make_conn()
        written = db.insert_adjustment_factors(
            conn,
            "002378",
            [
                {"ex_date": "2025-06-06", "factor": 2.6, "constant": 1.9432},
                {"ex_date": "2026-06-26", "factor": 2.6, "constant": 2.2552},
            ],
        )
        self.assertEqual(written, 2)
        rows = db.list_adjustment_factors(conn, "002378")
        # 按 ex_date 降序：最近的除权事件排在最前
        self.assertEqual([r["ex_date"] for r in rows], ["2026-06-26", "2025-06-06"])
        self.assertEqual(rows[0]["factor"], 2.6)
        self.assertEqual(rows[0]["constant"], 2.2552)

    def test_insert_adjustment_factors_upserts_same_ex_date(self):
        conn = make_conn()
        db.insert_adjustment_factors(
            conn, "002378", [{"ex_date": "2026-06-26", "factor": 2.6, "constant": 2.2552}]
        )
        db.insert_adjustment_factors(
            conn, "002378", [{"ex_date": "2026-06-26", "factor": 2.6, "constant": 9.9999}]
        )
        rows = db.list_adjustment_factors(conn, "002378")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["constant"], 9.9999)

    def test_list_adjustment_factors_is_symbol_scoped(self):
        conn = make_conn()
        db.insert_adjustment_factors(
            conn, "002378", [{"ex_date": "2026-06-26", "factor": 2.6, "constant": 2.2552}]
        )
        db.insert_adjustment_factors(
            conn, "600519", [{"ex_date": "2026-06-26", "factor": 1.0, "constant": 1.0}]
        )
        rows = db.list_adjustment_factors(conn, "600519")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "600519")

    def test_adjustment_factor_write_rolls_back_on_failure(self):
        # 第二条因子缺 ex_date → 整体失败，第一条也不能留在事务里。
        conn = make_conn()
        with self.assertRaises(KeyError):
            db.insert_adjustment_factors(conn, "002378", [
                {"ex_date": "2026-01-01", "factor": 1.0, "constant": 0.0},
                {"factor": 1.0, "constant": 0.0},
            ])
        count = conn.execute("SELECT COUNT(*) FROM adjustment_factors").fetchone()[0]
        self.assertEqual(count, 0, "失败后必须回滚，不能留下半截数据")

    def test_insert_review_rejects_empty_reviewer_id(self):
        conn = make_conn()
        with self.assertRaises(ValueError):
            db.insert_review(conn, "obs_1", {
                "reviewer_id": "", "reviewer_version": "0.1.0", "status": "ok",
            })

    def test_insert_observation_stores_evidence_and_invalidation(self):
        conn = make_conn()
        db.insert_observation(conn, {
            "symbol": "002378", "name": "章源钨业", "direction": "bullish",
            "thesis": "钨价上涨", "confidence": 0.75,
            "evidence": [{"text": "钨价从去年就开始涨", "type": "fact"}],
            "invalidation": ["钨价跌回去年年底的水平"],
        })
        row = db.list_observations(conn)[0]
        self.assertEqual(row["confidence"], 0.75)
        self.assertEqual(row["invalidation"], ["钨价跌回去年年底的水平"])
        self.assertEqual(row["evidence"][0]["type"], "fact")

    def test_migration_adds_columns_to_existing_table(self):
        # 老库没有这两列：migrate() 必须补上。
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE observations (id TEXT PRIMARY KEY, symbol TEXT NOT NULL, "
            "created_at TEXT NOT NULL, deleted_at TEXT)"
        )
        conn.commit()
        db.migrate(conn)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(observations)")}
        self.assertIn("evidence_json", columns)
        self.assertIn("invalidation_json", columns)

    def test_list_observations_tiebreak_is_stable(self):
        # 两条 created_at 完全相同：顺序必须确定（后插入的在前）。
        conn = make_conn()
        for index in range(2):
            db.insert_observation(conn, {
                "id": f"obs_{index}", "symbol": "002378", "name": "x",
                "created_at": "2026-11-24T10:00:00+00:00", "direction": "bullish",
            })
        first = [row["id"] for row in db.list_observations(conn)]
        second = [row["id"] for row in db.list_observations(conn)]
        self.assertEqual(first, second)
        self.assertEqual(first, ["obs_1", "obs_0"])


class WriteTransactionTests(unittest.TestCase):
    """写事务（Task 21 fix round 2）：「查续接 + 落库」必须整体串行化。"""

    def test_write_transaction_excludes_a_second_writer(self):
        # 写锁的**可观测**判据：持锁期间，另一个连接拿不到写锁。
        # 没有这条，「查续接 + 落库」就没有任何串行化保证 ——
        # 两个进程各自读到同一个 head ⇒ 同名不同代码被并进同一条线程。
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            conn = db.connect(db_path)
            db.migrate(conn)
            # 竞争者用**短超时**：拿不到锁就立刻报错，不要把测试拖成 30 秒。
            other = sqlite3.connect(str(db_path), timeout=0.2)
            try:
                with db.write_transaction(conn):
                    self.assertTrue(conn.in_transaction, "写事务必须真的开起来了")
                    with self.assertRaises(sqlite3.OperationalError):
                        other.execute("BEGIN IMMEDIATE")
                # 事务正常退出 ⇒ 锁已释放 ⇒ 另一个连接能拿到。
                other.execute("BEGIN IMMEDIATE")
                other.rollback()
            finally:
                other.close()
                conn.close()

    def test_write_transaction_rolls_back_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "a.db"
            conn = db.connect(db_path)
            db.migrate(conn)
            try:
                with self.assertRaises(RuntimeError):
                    with db.write_transaction(conn):
                        conn.execute(
                            "INSERT INTO observations (id, symbol, created_at) "
                            "VALUES ('obs_x', '002378', '2026-11-25T00:00:00+00:00')"
                        )
                        raise RuntimeError("boom")
                rows = conn.execute(
                    "SELECT * FROM observations WHERE id = 'obs_x'"
                ).fetchall()
                self.assertEqual(len(rows), 0, "写事务里出错必须回滚")
            finally:
                conn.close()


class ObservationThreadTests(unittest.TestCase):
    """观察版本链（Task 21）：同一标的一条持续观察 = 一个线程。"""

    def _thread(self, conn, symbol="002378", name="章源钨业"):
        first = db.insert_observation(conn, dict(OBSERVATION, symbol=symbol, name=name))
        second = db.insert_observation(
            conn,
            dict(OBSERVATION, symbol=symbol, name=name),
            supersedes_id=first,
            thread_id=first,
        )
        return first, second

    def test_first_version_is_its_own_thread_root(self):
        conn = make_conn()
        obs_id = db.insert_observation(conn, OBSERVATION)
        row = conn.execute(
            "SELECT thread_id, supersedes_id FROM observations WHERE id = ?", (obs_id,)
        ).fetchone()
        self.assertEqual(row["thread_id"], obs_id)
        self.assertIsNone(row["supersedes_id"])

    def test_insert_observation_accepts_version_chain_columns(self):
        conn = make_conn()
        first = db.insert_observation(conn, OBSERVATION)
        second = db.insert_observation(
            conn, OBSERVATION, supersedes_id=first, thread_id=first
        )
        row = conn.execute(
            "SELECT thread_id, supersedes_id FROM observations WHERE id = ?", (second,)
        ).fetchone()
        self.assertEqual(row["thread_id"], first)
        self.assertEqual(row["supersedes_id"], first)

    def test_migration_adds_version_chain_columns_to_existing_table(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE observations (id TEXT PRIMARY KEY, symbol TEXT NOT NULL, "
            "created_at TEXT NOT NULL, deleted_at TEXT)"
        )
        conn.commit()
        db.migrate(conn)
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(observations)")}
        self.assertIn("supersedes_id", columns)
        self.assertIn("thread_id", columns)

    def test_migration_keeps_existing_rows(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE observations (id TEXT PRIMARY KEY, symbol TEXT NOT NULL, "
            "created_at TEXT NOT NULL, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO observations (id, symbol, created_at) VALUES ('obs_old', '002378', '2026-11-01')"
        )
        conn.commit()
        db.migrate(conn)
        rows = conn.execute("SELECT id FROM observations").fetchall()
        self.assertEqual([row["id"] for row in rows], ["obs_old"])

    def test_legacy_row_without_thread_id_resolves_to_itself(self):
        """迁移前的行 thread_id 是 NULL —— 它自己就是线程根。"""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            "CREATE TABLE observations (id TEXT PRIMARY KEY, symbol TEXT NOT NULL, "
            "created_at TEXT NOT NULL, deleted_at TEXT)"
        )
        conn.execute(
            "INSERT INTO observations (id, symbol, created_at) VALUES ('obs_old', '002378', '2026-11-01')"
        )
        conn.commit()
        db.migrate(conn)
        self.assertEqual(db.resolve_thread_id(conn, "obs_old"), "obs_old")
        self.assertEqual(db.thread_started_at(conn, "obs_old"), "2026-11-01")

    def test_find_thread_head_returns_the_newest_surviving_version(self):
        conn = make_conn()
        first, second = self._thread(conn)
        head = db.find_thread_head(conn, "002378")
        self.assertEqual(head["id"], second)
        self.assertEqual(head["thread_id"], first)

    def test_find_thread_head_falls_back_to_name_when_symbol_is_empty(self):
        conn = make_conn()
        self._thread(conn)
        head = db.find_thread_head(conn, "", "章源钨业")
        self.assertIsNotNone(head)
        self.assertEqual(head["symbol"], "002378")

    def test_find_thread_head_falls_back_to_name_when_the_symbol_branch_misses(self):
        """symbol 分支落空时**回落 name 分支**（Task 21 复审 Minor-2）。

        真实场景：「模型这次没解析出代码、下次解析出来了」——
        先按简称记（symbol 为空）、后来解析出代码 ⇒ 仍应是**同一条线程**。
        """
        conn = make_conn()
        db.insert_observation(conn, dict(OBSERVATION, symbol="", name="章源钨业"))
        head = db.find_thread_head(conn, "002378", "章源钨业")
        self.assertIsNotNone(head, "symbol 分支落空时必须回落 name 分支")
        self.assertEqual(head["name"], "章源钨业")

    def test_find_thread_head_refuses_to_fall_back_onto_a_coded_thread(self):
        """同名但**另一个代码**的线程 ⇒ 不续接。

        回落 name 分支只对「当初没记代码」的线程开放：候选线程里只要有**带代码**
        的存活版本行，就说明它是另一只标的 —— 同名不同代码，宁可不续接
        （宁可新开一条，也别把新输入接到错的标的上）。
        """
        conn = make_conn()
        db.insert_observation(conn, dict(OBSERVATION, symbol="600519", name="同名"))
        self.assertIsNone(db.find_thread_head(conn, "002378", "同名"))

    def test_find_thread_head_refuses_ambiguous_name_match(self):
        """同名命中多条 ⇒ 认不准，宁可不续接。"""
        conn = make_conn()
        db.insert_observation(conn, dict(OBSERVATION, symbol="002378", name="同名"))
        db.insert_observation(conn, dict(OBSERVATION, symbol="600519", name="同名"))
        self.assertIsNone(db.find_thread_head(conn, "", "同名"))

    def test_find_thread_head_returns_none_for_unknown_symbol(self):
        conn = make_conn()
        self.assertIsNone(db.find_thread_head(conn, "600519"))

    def test_find_thread_head_ignores_deleted_threads(self):
        conn = make_conn()
        first, _ = self._thread(conn)
        db.soft_delete_thread(conn, first)
        self.assertIsNone(db.find_thread_head(conn, "002378"))

    def test_thread_started_at_is_the_first_version_timestamp(self):
        conn = make_conn()
        first = db.insert_observation(conn, dict(OBSERVATION, created_at="2026-11-01T09:00:00+00:00"))
        db.insert_observation(
            conn,
            dict(OBSERVATION, created_at="2026-11-20T09:00:00+00:00"),
            supersedes_id=first,
            thread_id=first,
        )
        self.assertEqual(db.thread_started_at(conn, first), "2026-11-01T09:00:00+00:00")

    def test_thread_versions_are_ordered_oldest_first(self):
        conn = make_conn()
        first = db.insert_observation(conn, dict(OBSERVATION, created_at="2026-11-01T09:00:00+00:00"))
        second = db.insert_observation(
            conn,
            dict(OBSERVATION, created_at="2026-11-20T09:00:00+00:00"),
            supersedes_id=first,
            thread_id=first,
        )
        versions = db.thread_versions(conn, first)
        self.assertEqual([row["id"] for row in versions], [first, second])

    def test_resolve_thread_id_maps_any_version_to_the_root(self):
        conn = make_conn()
        first, second = self._thread(conn)
        self.assertEqual(db.resolve_thread_id(conn, first), first)
        self.assertEqual(db.resolve_thread_id(conn, second), first)
        self.assertIsNone(db.resolve_thread_id(conn, "nope"))

    def test_list_threads_returns_one_row_per_thread(self):
        conn = make_conn()
        self._thread(conn)
        db.insert_observation(conn, dict(OBSERVATION, symbol="600519", name="贵州茅台"))
        rows = db.list_threads(conn)
        self.assertEqual(len(rows), 2)
        target = [row for row in rows if row["symbol"] == "002378"][0]
        self.assertEqual(target["version"], 2)
        self.assertEqual(target["version_count"], 2)
        self.assertIsNotNone(target["first_seen_at"])
        # 线程根是第一版；列表返回的是最新一版（头）。
        self.assertEqual(target["thread_id"], target["supersedes_id"])

    def test_list_threads_hides_deleted_threads(self):
        conn = make_conn()
        first, _ = self._thread(conn)
        db.soft_delete_thread(conn, first)
        self.assertEqual(db.list_threads(conn), [])
        self.assertEqual(len(db.list_threads(conn, include_deleted=True)), 1)

    def test_list_threads_keeps_two_threads_of_the_same_symbol_apart(self):
        conn = make_conn()
        self._thread(conn)
        db.insert_observation(conn, dict(OBSERVATION, symbol="002378", name="章源钨业"))
        rows = db.list_threads(conn)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(row["version"] for row in rows), [1, 2])

    def test_soft_delete_thread_deletes_every_version(self):
        conn = make_conn()
        first, second = self._thread(conn)
        self.assertTrue(db.soft_delete_thread(conn, first))
        rows = db.list_observations(conn)
        self.assertEqual(rows, [])
        deleted = db.list_observations(conn, include_deleted=True)
        self.assertEqual(len(deleted), 2)
        self.assertTrue(all(row["deleted_at"] for row in deleted))

    def test_soft_delete_thread_works_from_any_version_id(self):
        conn = make_conn()
        first, second = self._thread(conn)
        self.assertTrue(db.soft_delete_thread(conn, second))
        self.assertEqual(db.list_observations(conn), [])

    def test_soft_delete_thread_returns_false_for_unknown_id(self):
        conn = make_conn()
        self.assertFalse(db.soft_delete_thread(conn, "nope"))

    def test_soft_delete_thread_keeps_the_reviews(self):
        """reviews 保留是审计硬要求（设计 §7.1）。"""
        conn = make_conn()
        first, second = self._thread(conn)
        db.insert_review(conn, first, verdict())
        db.insert_review(conn, second, verdict())
        db.soft_delete_thread(conn, first)
        self.assertEqual(len(db.latest_reviews(conn, first)), 1)
        self.assertEqual(len(db.latest_reviews(conn, second)), 1)


if __name__ == "__main__":
    unittest.main()
