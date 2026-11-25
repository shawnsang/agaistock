"""SQLite 存储层。

设计约束（主规格 §7）：
  - 观察记录只追加不修改；修订走新版本行
  - 删除是软删除（deleted_at），不物理删除
  - reviews 每次运行都追加一行，读取时取每位 reviewer 最新一版

**观察版本链**（Task 21）：同一标的的持续观察由多个版本行组成，
用 `supersedes_id`（本版本取代谁）+ `thread_id`（线程根行 id）串起来。
旧行永不改写 —— 合并的结果写在**新版本行**里。
"""
from __future__ import annotations

import contextlib
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
    deleted_at    TEXT,
    supersedes_id TEXT,
    thread_id     TEXT
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
    # ⚠️ `timeout=30`：写锁竞争时最多等 30 秒。默认 5 秒太短 ——
    # 两个进程同时点评同一只标的时，第二个会等第一个的写事务结束；
    # 5 秒一过就抛 `database is locked`，用户看到的是「保存失败」。
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextlib.contextmanager
def write_transaction(conn: sqlite3.Connection):
    """SQLite **写事务**：在第一句 SELECT 之前就拿到写锁。

    「查续接 + 落库」必须整体串行化：两个进程各自读到同一个 head，
    各自以为自己是下一版 ⇒ 同名不同代码的观察被并进同一条线程，
    版本链还会分叉（Task 21 fix round 2）。

    ⚠️ 必须是 `BEGIN IMMEDIATE`（**立即**拿写锁）：延迟事务（`BEGIN`）
    要到第一次写才拿锁 ⇒ 两个进程仍然能各自读到同一个 head。
    """
    if conn.in_transaction:
        # 已经在事务里（调用方自己开的）⇒ 不重复 begin，直接用外层那个。
        yield conn
        return
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        if conn.in_transaction:
            conn.commit()


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    conn.commit()


# 新增列用 ALTER TABLE 补齐：CREATE TABLE IF NOT EXISTS 不会给已存在的表加列。
_MIGRATIONS = (
    ("observations", "evidence_json", "TEXT"),
    ("observations", "invalidation_json", "TEXT"),
    ("observations", "supersedes_id", "TEXT"),
    ("observations", "thread_id", "TEXT"),
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


def insert_observation(
    conn: sqlite3.Connection,
    observation: dict[str, Any],
    *,
    supersedes_id: str | None = None,
    thread_id: str | None = None,
) -> str:
    """落一条观察行。

    `thread_id` 缺省时取本行 id —— 自己就是线程根；
    `supersedes_id` 是本版本取代的那一行（第一版为 NULL）。
    """
    obs_id = observation.get("id") or _new_id("obs")
    thread = str(thread_id) if thread_id else obs_id
    conn.execute(
        """INSERT INTO observations
           (id, symbol, name, created_at, direction, thesis, confidence,
            timeframe, trigger, position_json, evidence_json, invalidation_json,
            raw_text, deleted_at, supersedes_id, thread_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
            supersedes_id,
            thread,
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


# ------------------------------------------------------------------
# 观察版本链（Task 21）
#
# 一条「线程」= 一个标的一条持续观察，由若干版本行组成：
#   第一版：supersedes_id IS NULL，thread_id = 自己的 id
#   后续版：supersedes_id = 上一版的 id，thread_id = 线程根 id
#
# 旧行永不改写（append-only 不变量），合并结果写在**新版本行**里。
# ------------------------------------------------------------------


def _row_to_item(row: sqlite3.Row, keep_rowid: bool = False) -> dict[str, Any]:
    """内核行 → 观察字典（JSON 列还原成列表）。"""
    item = dict(row)
    if not keep_rowid:
        item.pop("_rowid", None)
    item["evidence"] = _load_json_list(item.pop("evidence_json", None))
    item["invalidation"] = _load_json_list(item.pop("invalidation_json", None))
    return item


def _all_rows_with_rowid(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """全部观察行（含软删），带内部 `_rowid` 用于确定插入顺序。

    `created_at` 只到秒 —— 同一秒内连续落两行是常态，
    所以「最新一版」必须靠 `rowid` 兜底排序，不能只看时间戳。
    """
    rows = conn.execute(
        "SELECT rowid AS _rowid, * FROM observations ORDER BY created_at DESC, rowid DESC"
    )
    return [_row_to_item(row, keep_rowid=True) for row in rows]


def _thread_head_by_name(
    conn: sqlite3.Connection, name: str
) -> tuple[dict[str, Any] | None, str]:
    """按 `name` 找线程头 + 线程根 id。

    必须**唯一命中一条线程** —— 命中多条说明认不准，宁可不续接（宁可新开一条，
    也别把新输入接到错的标的上）。唯一性按**线程**算：一条线程本来就有多个同名版本行。
    """
    rows = conn.execute(
        """SELECT * FROM observations
           WHERE name = ? AND deleted_at IS NULL
           ORDER BY created_at DESC, rowid DESC""",
        (name,),
    ).fetchall()
    if not rows:
        return None, ""
    threads = {row["thread_id"] or row["id"] for row in rows}
    if len(threads) != 1:
        return None, ""
    thread_id = rows[0]["thread_id"] or rows[0]["id"]
    return _row_to_item(rows[0]), thread_id


def _thread_has_coded_version(conn: sqlite3.Connection, thread_id: str) -> bool:
    """这条线程里有没有**带代码**的存活版本行。"""
    row = conn.execute(
        """SELECT 1 FROM observations
           WHERE (thread_id = ? OR id = ?) AND deleted_at IS NULL
             AND symbol IS NOT NULL AND TRIM(symbol) <> ''
           LIMIT 1""",
        (thread_id, thread_id),
    ).fetchone()
    return row is not None


def find_thread_head(
    conn: sqlite3.Connection, symbol: str, name: str = ""
) -> dict[str, Any] | None:
    """该标的的**最新存活版本**行；没有则 None。

    `symbol` 为空时退回按 `name` 匹配（用户只说股票简称、模型没解析出代码），
    且**必须唯一命中一条线程** —— 命中多条线程说明认不准，宁可不续接（宁可新开一条，
    也别把新输入接到错的标的上）。唯一性按**线程**算：一条线程本来就有多个同名版本行。

    `symbol` **有值但查不到**时同样退回按 `name` 匹配：这条观察当初可能是**只说简称**
    记的（symbol 为空），后来模型才解析出代码 —— 不回落的话，同一只股票会裂成两条
    线程（Task 21 复审 Minor-2；真实场景：「模型这次没解析出代码、下次解析出来了」）。

    回落**只对「当初没记代码」的线程开放**：候选线程里只要有**带代码**的存活版本行，
    就说明它是另一只标的（同名不同代码）—— 宁可不续接。
    """
    symbol = str(symbol or "").strip()
    name = str(name or "").strip()
    if symbol:
        row = conn.execute(
            """SELECT * FROM observations
               WHERE symbol = ? AND deleted_at IS NULL
               ORDER BY created_at DESC, rowid DESC LIMIT 1""",
            (symbol,),
        ).fetchone()
        if row is not None:
            return _row_to_item(row)
        # symbol 分支落空：这条观察当初可能是**只说简称**记的（symbol 为空）。
        # 不回落的话，「第一次没解析出代码、第二次解析出来了」会裂成两条线程
        # （Task 21 复审 Minor-2）。name 为空则没有第二条路。
        if not name:
            return None
        head, thread_id = _thread_head_by_name(conn, name)
        if head is None:
            return None
        if _thread_has_coded_version(conn, thread_id):
            # 同名但带代码 ⇒ 另一只标的。宁可新开一条，也别接错标的。
            return None
        return head

    if not name:
        return None
    head, _ = _thread_head_by_name(conn, name)
    return head


def resolve_thread_id(conn: sqlite3.Connection, observation_id: str) -> str | None:
    """任意一行的 id → 它的线程根 id。

    迁移前的老行 `thread_id` 是 NULL —— 那条行自己就是线程根。
    """
    row = conn.execute(
        "SELECT id, thread_id FROM observations WHERE id = ?", (str(observation_id),)
    ).fetchone()
    if row is None:
        return None
    return row["thread_id"] or row["id"]


def thread_versions(conn: sqlite3.Connection, thread_id: str) -> list[dict[str, Any]]:
    """线程的全部版本行，按时间升序（第一版在前）。"""
    rows = conn.execute(
        """SELECT * FROM observations
           WHERE thread_id = ? OR id = ?
           ORDER BY created_at ASC, rowid ASC""",
        (str(thread_id), str(thread_id)),
    )
    return [_row_to_item(row) for row in rows]


def thread_started_at(conn: sqlite3.Connection, thread_id: str) -> str:
    """线程第一版的 created_at —— 观察期的锚点。

    锚在**线程起点**而不是「今天」：否则用户可以靠反复补充无限顺延结算日。
    """
    row = conn.execute(
        """SELECT MIN(created_at) AS started FROM observations
           WHERE thread_id = ? OR id = ?""",
        (str(thread_id), str(thread_id)),
    ).fetchone()
    if row is None or not row["started"]:
        return ""
    return str(row["started"])


def list_threads(conn: sqlite3.Connection, include_deleted: bool = False) -> list[dict]:
    """每个线程一行（存活线程的头），带版本计数与首见时间。

    常态下一个 symbol 一条线程 ⇒ 列表一个 symbol 一行；
    只有显式开了第二条线程（`--new-thread`）时，同一 symbol 才会出现两行。
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in _all_rows_with_rowid(conn):
        key = item.get("thread_id") or item["id"]
        groups.setdefault(key, []).append(item)

    heads: list[dict[str, Any]] = []
    for key, versions in groups.items():
        versions.sort(key=lambda r: (r.get("created_at") or "", r["_rowid"]))
        head = dict(versions[-1])
        if not include_deleted and head.get("deleted_at"):
            continue
        head["thread_id"] = key
        head["version"] = len(versions)
        head["version_count"] = len(versions)
        head["first_seen_at"] = versions[0].get("created_at")
        heads.append(head)

    heads.sort(key=lambda r: (r.get("created_at") or "", r["_rowid"]), reverse=True)
    for item in heads:
        item.pop("_rowid", None)
    return heads


def soft_delete_observation(conn: sqlite3.Connection, observation_id: str) -> bool:
    cursor = conn.execute(
        "UPDATE observations SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
        (_now(), observation_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def soft_delete_thread(conn: sqlite3.Connection, observation_id: str) -> bool:
    """软删**整条线程**的所有版本。

    只删头是不够的：列表只显示存活线程头，上一版会「复活」成新线程头 ——
    用户会看到一条「从没被删过」但内容变旧的记录。
    `reviews` 记录**保留**（§7.1 的审计要求）。
    """
    thread_id = resolve_thread_id(conn, observation_id)
    if thread_id is None:
        return False
    cursor = conn.execute(
        """UPDATE observations SET deleted_at = ?
           WHERE deleted_at IS NULL AND (thread_id = ? OR id = ?)""",
        (_now(), thread_id, thread_id),
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
