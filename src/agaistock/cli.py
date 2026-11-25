"""命令行入口：python -m agaistock.cli

子命令：
  review  记录一条观察 → 跑点评师 → 落库 → 评分 → 观察期
  list    列出观察
  delete  软删除一条观察

**观察续接**（Task 21）：同一标的的第二次输入**不新开一条记录** ——
它并进同一条观察线程（append-only 版本链），观点取新、依据与证伪条件取并集、
观察期锚定在线程起点（续接**绝不**顺延结算日）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import config, continuation, horizon as horizon_mod, scoring
from .llm import client as llm_client
from .reviewers import engine as engine_mod
from .reviewers import registry
from .storage import db

DEFAULT_DB = "data/agaistock.db"


def _default_db(db_arg: str | None) -> Path:
    if db_arg:
        return Path(db_arg)
    env_db = os.environ.get("AGAISTOCK_DB", "").strip()
    if env_db:
        return Path(env_db)
    return config.repo_root() / DEFAULT_DB


def _open(db_arg: str | None):
    path = _default_db(db_arg)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(path)
    db.migrate(conn)
    return conn


def _parse_observation(symbol: str, name: str, text: str) -> dict:
    """极简解析：方向与时限靠关键词；真实解析由 Mini App 的 LLM 层完成。"""
    lowered = text.lower()
    direction = "neutral"
    if any(word in text for word in ("看多", "看好", "拿", "涨", "买")):
        direction = "bullish"
    elif any(word in text for word in ("看空", "跌", "卖", "减仓")):
        direction = "bearish"
    timeframe = ""
    for window in ("半年", "一年", "三个月", "一个月", "两周"):
        if window in text:
            timeframe = window
            break
    return {
        "symbol": symbol,
        "name": name,
        "direction": direction,
        "thesis": text[:80],
        "confidence": 0.0,
        "timeframe": timeframe,
        "trigger": "",
        "position": {},
        "raw_text": text,
    }


def _observation_from_draft(draft: dict, symbol: str, name: str, text: str) -> dict:
    """把接入层（Mini App 的 LLM 层）解析出的结构化观察转成内核的观察行。

    **不盲信草稿**：每个字段都校验，不合法的退回关键词解析的结果。
    理由：草稿来自模型输出，可能缺字段、类型不对、信心越界；
    而观察记录是后面评分与校准的输入，不能带脏数据进去。
    """
    fallback = _parse_observation(symbol, name, text)
    direction = draft.get("direction")
    if direction not in ("bullish", "bearish", "neutral"):
        direction = fallback["direction"]
    raw_confidence = draft.get("confidence")
    confidence = (
        float(raw_confidence)
        if isinstance(raw_confidence, (int, float)) and not isinstance(raw_confidence, bool)
        else fallback["confidence"]
    )
    confidence = min(1.0, max(0.0, confidence))
    thesis = str(draft.get("thesis") or "").strip() or fallback["thesis"]
    evidence = []
    for item in draft.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        item_text = str(item.get("text") or "").strip()
        if not item_text:
            continue
        item_type = item.get("type")
        evidence.append({
            "text": item_text,
            "type": item_type if item_type in ("fact", "assumption") else "assumption",
        })
    invalidation = [
        str(item).strip()
        for item in (draft.get("invalidation") or [])
        if str(item or "").strip()
    ]
    position = draft.get("position")
    return {
        "symbol": symbol or fallback["symbol"],
        "name": name or str(draft.get("name") or "").strip() or fallback["name"],
        "direction": direction,
        "thesis": thesis[:200],
        "confidence": confidence,
        "timeframe": str(draft.get("timeframe") or "").strip() or fallback["timeframe"],
        "trigger": str(draft.get("trigger") or "").strip() or fallback["trigger"],
        "position": position if isinstance(position, dict) else {},
        "evidence": evidence,
        "invalidation": invalidation,
        "raw_text": text,
    }


def _load_structured_observation(path: str | None, symbol: str, name: str, text: str) -> dict:
    """有结构化观察文件就用它，没有就退回关键词解析。"""
    if not path:
        return _parse_observation(symbol, name, text)
    file_path = Path(path)
    if not file_path.is_file():
        raise FileNotFoundError(f"结构化观察文件不存在: {file_path}")
    draft = json.loads(file_path.read_text(encoding="utf-8"))
    if not isinstance(draft, dict):
        raise ValueError(f"结构化观察文件顶层必须是 JSON 对象: {file_path}")
    return _observation_from_draft(draft, symbol, name, text)


def run_reviewers(ctx, reviewers):  # pragma: no cover - 便于测试打桩
    return engine_mod.run_reviewers([r["instance"] for r in reviewers], ctx)


def _anchor_date(conn, thread_id: str) -> str:
    """观察期锚点：线程第一版的创建**日期**（YYYY-MM-DD）。

    `created_at` 存的是 UTC 时间戳 —— 直接取前 10 位会在跨时区的晚上差一天，
    所以先转成本地日期再取日期部分。

    锚在**线程起点**而不是「今天」：每次补充都从今天起算的话，
    用户可以靠反复补充**无限顺延**结算日，到期校准就废了。
    """
    started = db.thread_started_at(conn, thread_id)
    if not started:
        return date.today().isoformat()
    try:
        moment = datetime.fromisoformat(started)
    except ValueError:
        return started[:10]
    if moment.tzinfo is None:
        return moment.date().isoformat()
    return moment.astimezone().date().isoformat()


def _thread_history(conn, thread_id: str) -> list[dict]:
    """线程各版本的点评历史（按版本升序）。

    `reviews` 用 **verdict 字典**（与 `cmd_review` 的 `reviews` 同形），
    前端可以用同一个渲染函数画出每一轮。
    """
    entries = []
    for index, row in enumerate(db.thread_versions(conn, thread_id), start=1):
        entries.append({
            "observation_id": row["id"],
            "version": index,
            "created_at": row.get("created_at"),
            "reviews": [item["verdict"] for item in db.latest_reviews(conn, row["id"])],
        })
    return entries


def cmd_review(args) -> int:
    conn = _open(args.db)
    try:
        observation = _load_structured_observation(
            args.observation_file, args.symbol, args.name, args.text
        )
        # 续接：同一标的的**最新存活版本** —— 新输入并进同一条线程，
        # 而不是新开一条互不相干的记录。
        previous = (
            None
            if args.new_thread
            else db.find_thread_head(
                conn, observation.get("symbol", ""), observation.get("name", "")
            )
        )
        if previous:
            observation = continuation.merge_into_previous(previous, observation)
        thread_id = (previous.get("thread_id") or previous["id"]) if previous else None
        observation_id = db.insert_observation(
            conn,
            observation,
            supersedes_id=previous["id"] if previous else None,
            thread_id=thread_id,
        )
        thread_id = thread_id or observation_id

        reviewers = registry.load_reviewers()
        ctx = engine_mod.ReviewContext(
            observation=observation,
            symbol=args.symbol,
            name=args.name,
            now=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            data_dir=config.data_dir(),
            # 措辞层接线：环境变量没配全时 from_env() 返回 None → 点评保留规则层原文
            llm=llm_client.from_env(),
        )
        verdicts = run_reviewers(ctx, reviewers)
        saved = engine_mod.persist(conn, observation_id, verdicts)

        weights = {r["id"]: float(r.get("weight", 1.0)) for r in reviewers}
        score = scoring.aggregate(verdicts, reviewer_weights=weights)
        # 观察期锚定在线程起点 —— 续接**绝不**顺延结算日。
        start = (
            _anchor_date(conn, thread_id)
            if previous
            else date.today().isoformat()
        )
        plan = horizon_mod.plan(observation, verdicts, start=start)

        history = [
            entry
            for entry in _thread_history(conn, thread_id)
            if entry["observation_id"] != observation_id
        ]
        version_count = len(history) + 1
        payload = {
            "observation_id": observation_id,
            "thread_id": thread_id,
            "version": version_count,
            "version_count": version_count,
            "supersedes_id": previous["id"] if previous else None,
            "first_seen_at": db.thread_started_at(conn, thread_id),
            "reviews": saved,
            "history": history,
            "score": score,
            "horizon": plan,
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"观察 {observation_id}：{observation['name']} {observation['symbol']}")
            if previous:
                print(f"（续接第 {version_count} 版，取代 {previous['id']}）")
            print(
                f"评分 {score['total']:.1f} / 100"
                f"（被审维度：{'、'.join(score['scored_dimensions']) or '无'}，"
                f"分母 {score['score_denominator']:.2f}）"
            )
            print(f"观察期 {plan['review_at']}（档位 {plan['tier'] or '默认'}）")
            for verdict in saved:
                print(f"- {verdict['reviewer_id']} [{verdict['status']}] {len(verdict['findings'])} 条发现")
        return 0
    finally:
        # 显式关闭连接：Windows 上未关闭的 sqlite 句柄会锁住 .db 文件，
        # 临时目录清理与后续迁移都会失败（临时目录删除直接报 PermissionError）。
        # **必须放 finally** —— 命令中途抛异常（配置坏了、点评师炸了）时句柄同样会锁住文件。
        conn.close()


def cmd_list(args) -> int:
    conn = _open(args.db)
    try:
        if args.all_versions:
            rows = db.list_observations(conn, include_deleted=args.include_deleted)
        else:
            # 默认按**线程**返回：一个标的一条持续观察 = 一行。
            rows = db.list_threads(conn, include_deleted=args.include_deleted)
        if args.json:
            # 带 ok/items 外壳：Mini App 前端读的是 data.items（见 Task 14 / Task 15）
            print(json.dumps({"ok": True, "items": rows}, ensure_ascii=False, indent=2))
        else:
            for row in rows:
                marker = "（已删除）" if row.get("deleted_at") else ""
                version = row.get("version")
                version_text = f"第 {version} 版" if version else ""
                print(
                    f"{row['id']}  {row.get('created_at')}  "
                    f"{row.get('name')} {row.get('symbol')} {version_text}{marker}"
                )
        return 0
    finally:
        conn.close()


def cmd_reviews(args) -> int:
    conn = _open(args.db)
    try:
        thread_id = db.resolve_thread_id(conn, args.observation_id)
        if thread_id is None:
            payload = {
                "observation_id": args.observation_id,
                "thread_id": None,
                "items": [],
                "versions": [],
            }
            if args.json:
                print(json.dumps(payload, ensure_ascii=False, indent=2))
            else:
                print("未找到该观察。")
            return 0
        versions = _thread_history(conn, thread_id)
        # `items` = **被请求的那一版**的点评（保持 Task 21 之前的语义，且与
        # `observation_id` 一致）；**整条线程**的历史在 `versions` 里。
        # 复审 Minor-1：原先这里装的是「线程最后一版」的点评 —— 请求 v1 却拿到 v2 的点评，
        # 而没有任何测试钉住这个字段的语义。
        items = db.latest_reviews(conn, args.observation_id) if versions else []
        payload = {
            "observation_id": args.observation_id,
            "thread_id": thread_id,
            "items": items,
            "versions": versions,
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            for entry in versions:
                print(f"第 {entry['version']} 版 {entry['observation_id']} {entry['created_at']}")
                for item in entry["reviews"]:
                    print(f"- {item['reviewer_id']} [{item['status']}] {len(item.get('findings') or [])} 条发现")
        return 0
    finally:
        conn.close()


def cmd_delete(args) -> int:
    conn = _open(args.db)
    try:
        # 删**整条线程**：只删头的话，上一版会复活成新线程头 ——
        # 用户会看到一条「从没被删过」但内容变旧的记录。
        thread_id = db.resolve_thread_id(conn, args.observation_id)
        ok = db.soft_delete_thread(conn, args.observation_id)
        if not ok:
            if args.json:
                print(json.dumps({"ok": False, "id": args.observation_id}, ensure_ascii=False))
            else:
                print(f"未找到或已删除：{args.observation_id}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(
                {"ok": True, "id": args.observation_id, "thread_id": thread_id},
                ensure_ascii=False,
            ))
        else:
            print(f"已软删除 {args.observation_id} 及其所在观察线程的全部版本（不参与评分与校准统计）")
        return 0
    finally:
        conn.close()


def _force_utf8_stdio() -> None:
    """管道场景强制 UTF-8，终端场景只放宽 errors。

    Windows 中文机器上 Python 的 stdout 编码是 GBK（控制台代码页）。
    CLI 用 print() 输出 JSON 时，遇到一个 GBK 编不出来的字符（实测：连接器
    输出里的 U+FFFD）就会抛 UnicodeEncodeError —— 用户看到的是「点评失败」，
    整轮点评全废。

    - **管道**（stdout 不是 TTY）：JSON 是给 Node 侧解析的机器间通道，
      必须 UTF-8，不能受控制台代码页影响。
    - **终端**（是 TTY）：保留控制台编码（否则中文会变乱码），
      只把 errors 放宽成 replace —— 宁可显示一个替换字符，也不能崩。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            if stream.isatty():
                reconfigure(errors="replace")
            else:
                reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            # 流已关闭或不支持重配置：不能因此让命令失败
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agaistock")
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser("review", help="记录观察并跑点评")
    review.add_argument("--symbol", required=True)
    review.add_argument("--name", default="")
    review.add_argument("--text", required=True)
    review.add_argument("--observation-file", default=None,
                        help="接入层解析出的结构化观察（JSON 文件）")
    review.add_argument("--new-thread", action="store_true",
                        help="不续接已有观察，另开一条独立记录（默认续接）")
    review.add_argument("--db", default=None)
    review.add_argument("--json", action="store_true")
    review.set_defaults(func=cmd_review)

    listing = subparsers.add_parser("list", help="列出观察")
    listing.add_argument("--db", default=None)
    listing.add_argument("--include-deleted", action="store_true")
    listing.add_argument("--all-versions", action="store_true",
                         help="返回全部原始行（不按观察线程聚合）")
    listing.add_argument("--json", action="store_true")
    listing.set_defaults(func=cmd_list)

    reviews_cmd = subparsers.add_parser("reviews", help="列出某条观察的点评结论")
    reviews_cmd.add_argument("observation_id")
    reviews_cmd.add_argument("--db", default=None)
    reviews_cmd.add_argument("--json", action="store_true")
    reviews_cmd.set_defaults(func=cmd_reviews)

    delete = subparsers.add_parser("delete", help="软删除观察")
    delete.add_argument("observation_id")
    delete.add_argument("--db", default=None)
    delete.add_argument("--json", action="store_true")
    delete.set_defaults(func=cmd_delete)

    return parser


def main(argv: list[str] | None = None) -> int:
    _force_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
