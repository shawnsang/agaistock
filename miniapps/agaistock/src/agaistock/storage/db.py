"""SQLite 存储层。

设计约束（主规格 §7）：
  - 观察记录只追加不修改；修订走新版本行
  - 删除是软删除（deleted_at），不物理删除
  - reviews 每次运行都追加一行，读取时取每位 reviewer 最新一版
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id            TEXT PRIMARY KEY,
    symbol        TEXT NOT NULL,
    name          TEXT,
    created_at    TEXT NOT NULL,
    direction     TEXT,
    thesis        TEXT,
    confidence    REAL DEFAULT 0,
    timeframe     TEXT,
    trigger       TEXT,
    position_json TEXT,
    evidence_json TEXT,
    invalidation_json TEXT,
    raw_text      TEXT,
    deleted_at    TEXT
);

CREATE TABLE IF NOT EXISTS reviews (
    id               TEXT PRIMARY KEY,
    observation_id   TEXT NOT NULL,
    reviewer_id      TEXT NOT NULL,
    reviewer_version TEXT NOT NULL,
    ran_at           TEXT NOT NULL,
    status           TEXT NOT NULL,
    duration_ms      INTEGER,
    verdict_json     TEXT NOT NULL,
    created_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reviews_obs
    ON reviews(observation_id, reviewer_id, ran_at);

CREATE TABLE IF NOT EXISTS adjustment_factors (
    symbol     TEXT NOT NULL,
    ex_date    TEXT NOT NULL,
    factor     REAL NOT NULL,
    constant   REAL NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (symbol, ex_date)
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    """生成带前缀的主键。

    秒级时间戳 + uuid 后缀：同一秒内重复落库（同一 reviewer 连续两次运行）
    也不会撞主键，符合"每次运行都追加一行"的约束。
    """
    return f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:8]}"


def connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    conn.commit()


# 新增列用 ALTER TABLE 补齐：CREATE TABLE IF NOT EXISTS 不会给已存在的表加列。
_MIGRATIONS = (
    ("observations", "evidence_json", "TEXT"),
    ("observations", "invalidation_json", "TEXT"),
)


def _migrate_columns(conn: sqlite3.Connection) -> None:
    """给已存在的表补上新增的列（幂等）。"""
    for table, column, declaration in _MIGRATIONS:
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _position_json(observation: dict[str, Any]) -> str:
    """把观察里的持仓信息落成 position_json 列的文本。

    同时接受两种键名：
      - ``position_json``：已序列化的字符串，原样存
      - ``position``：dict / list，序列化后存

    优先取 ``position_json``，缺失时回退到 ``position``，两者都缺时存 "{}"。
    """
    raw = observation.get("position_json")
    if raw is None:
        raw = observation.get("position", {})
    if isinstance(raw, str):
        return raw
    return json.dumps(raw, ensure_ascii=False)


def insert_observation(conn: sqlite3.Connection, observation: dict[str, Any]) -> str:
    obs_id = observation.get("id") or _new_id("obs")
    conn.execute(
        """INSERT INTO observations
           (id, symbol, name, created_at, direction, thesis, confidence,
            timeframe, trigger, position_json, evidence_json, invalidation_json,
            raw_text, deleted_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            obs_id,
            observation.get("symbol", ""),
            observation.get("name", ""),
            observation.get("created_at") or _now(),
            observation.get("direction", ""),
            observation.get("thesis", ""),
            float(observation.get("confidence") or 0),
            observation.get("timeframe", ""),
            observation.get("trigger", ""),
            _position_json(observation),
            json.dumps(observation.get("evidence") or [], ensure_ascii=False),
            json.dumps(observation.get("invalidation") or [], ensure_ascii=False),
            observation.get("raw_text", ""),
            None,
        ),
    )
    conn.commit()
    return obs_id


def _load_json_list(raw: str | None) -> list:
    """把 JSON 列读成列表；坏数据当成空列表，不能让整张表读不出来。"""
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return value if isinstance(value, list) else []


def list_observations(conn: sqlite3.Connection, include_deleted: bool = False) -> list[dict]:
    sql = "SELECT * FROM observations"
    if not include_deleted:
        sql += " WHERE deleted_at IS NULL"
    sql += " ORDER BY created_at DESC, rowid DESC"
    rows = []
    for row in conn.execute(sql):
        item = dict(row)
        item["evidence"] = _load_json_list(item.pop("evidence_json", None))
        item["invalidation"] = _load_json_list(item.pop("invalidation_json", None))
        rows.append(item)
    return rows


def soft_delete_observation(conn: sqlite3.Connection, observation_id: str) -> bool:
    cursor = conn.execute(
        "UPDATE observations SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
        (_now(), observation_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def insert_review(conn: sqlite3.Connection, observation_id: str, verdict: dict[str, Any]) -> str:
    """落一条点评结论。

    reviewer_id / reviewer_version / status 是**必填**的：它们不是「有则存之」的可选列 ——
    latest_reviews 靠 reviewer_id 分组取最新一版，空的 reviewer_id 会分出一个
    伪分组；空的 status 会让「这条点评成功还是失败」无从判断。
    """
    for field in ("reviewer_id", "reviewer_version", "status"):
        if not str(verdict.get(field, "") or "").strip():
            raise ValueError(f"点评结论缺少必填字段 {field}: {verdict.get('reviewer_id', '')}")
    review_id = _new_id("rev")
    conn.execute(
        """INSERT INTO reviews
           (id, observation_id, reviewer_id, reviewer_version, ran_at, status,
            duration_ms, verdict_json, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            review_id,
            observation_id,
            verdict["reviewer_id"],
            verdict["reviewer_version"],
            verdict.get("ran_at", ""),
            verdict["status"],
            int(verdict.get("duration_ms") or 0),
            json.dumps(verdict, ensure_ascii=False),
            _now(),
        ),
    )
    conn.commit()
    return review_id


def latest_reviews(conn: sqlite3.Connection, observation_id: str) -> list[dict]:
    """每位 reviewer 只返回 ran_at 最新的一条，按 ran_at 升序返回。

    ran_at 精度只到秒，同一 reviewer 同一秒内的两次运行会并列；
    依次用 created_at、rowid（插入顺序）兜底排序，保证每位 reviewer
    恰好一行，且并列时取后插入的那次运行。
    """
    rows = conn.execute(
        """SELECT * FROM (
               SELECT r.*,
                      ROW_NUMBER() OVER (
                          PARTITION BY r.reviewer_id
                          ORDER BY r.ran_at DESC, r.created_at DESC, r.rowid DESC
                      ) AS rn
               FROM reviews r
               WHERE r.observation_id = ?
           )
           WHERE rn = 1
           ORDER BY ran_at ASC, created_at ASC, id ASC""",
        (observation_id,),
    )
    result = []
    for row in rows:
        item = dict(row)
        item.pop("rn", None)
        item["verdict"] = json.loads(item.pop("verdict_json"))
        result.append(item)
    return result


def insert_adjustment_factors(
    conn: sqlite3.Connection, symbol: str, factors: list[dict[str, Any]]
) -> int:
    """写入复权因子；同一 (symbol, ex_date) 重复写入覆盖。

    任何一条失败都必须回滚：否则已写入的部分会留在事务里，
    被之后无关的 commit 一起提交 —— 复权因子表变成半截数据，
    而复权价是后复权口径的地基。
    """
    fetched_at = _now()
    try:
        for item in factors:
            conn.execute(
                """INSERT INTO adjustment_factors
                   (symbol, ex_date, factor, constant, fetched_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(symbol, ex_date) DO UPDATE SET
                       factor = excluded.factor,
                       constant = excluded.constant,
                       fetched_at = excluded.fetched_at""",
                (
                    str(symbol),
                    str(item["ex_date"]),
                    float(item["factor"]),
                    float(item["constant"]),
                    fetched_at,
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(factors)


def list_adjustment_factors(conn: sqlite3.Connection, symbol: str) -> list[dict[str, Any]]:
    """按 ex_date 降序返回该标的的复权因子。"""
    rows = conn.execute(
        """SELECT symbol, ex_date, factor, constant, fetched_at
           FROM adjustment_factors WHERE symbol = ?
           ORDER BY ex_date DESC""",
        (str(symbol),),
    )
    return [dict(row) for row in rows]
