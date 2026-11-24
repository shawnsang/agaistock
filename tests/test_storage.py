import sqlite3
import unittest

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


if __name__ == "__main__":
    unittest.main()
