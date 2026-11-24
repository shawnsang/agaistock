"""点评师调度：逐个执行、失败隔离、结果落库。"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from .contract import ReviewContext, ReviewVerdict, validate_verdict


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dimension_names() -> list[str]:
    """评分维度名列表，来自 config/scoring.json。"""
    from .. import config

    return [item["name"] for item in config.load_scoring()["dimensions"]]


def _reviewer_version(reviewer) -> str:
    """点评师版本号；空值用默认版本。

    空版本号会被 db.insert_review 拒绝落库（reviewer_version 是必填），
    而落库在异常隔离之外 —— 不能让「一个点评师定义有问题」变成「整轮崩掉」。
    """
    version = getattr(reviewer, "version", "")
    return str(version).strip() or "0.0.0"


def _error_verdict(
    reviewer_id: str,
    reviewer_version: str,
    duration_ms: int,
    caveats: list[str],
) -> ReviewVerdict:
    return ReviewVerdict(
        reviewer_id=reviewer_id,
        reviewer_version=reviewer_version,
        ran_at=_now_iso(),
        status="error",
        duration_ms=duration_ms,
        data_refs=[],
        findings=[],
        proposed_invalidation=[],
        horizon_hint=None,
        caveats=list(caveats),
    )


def _validation_errors(verdict: ReviewVerdict) -> list[str]:
    """契约校验错误列表；配置读不到时也降级成一条错误，不向上抛。"""
    try:
        dimensions = _dimension_names()
    except Exception as exc:  # noqa: BLE001 —— 配置问题也要隔离
        return [f"无法读取评分维度配置: {type(exc).__name__}: {exc}"]
    return validate_verdict(verdict, dimensions)


def run_one(reviewer, ctx: ReviewContext) -> ReviewVerdict:
    """执行单个点评师；异常或契约校验失败都转为 status='error' 的 verdict，绝不向上抛。

    校验不通过的结论不落成有效结论：findings 被丢弃，只在 caveats 里留下错误。
    """
    started = time.monotonic()
    try:
        raw = reviewer.review(ctx)
    except Exception as exc:  # noqa: BLE001 —— 点评师故障必须被隔离
        return _error_verdict(
            getattr(reviewer, "id", "unknown"),
            _reviewer_version(reviewer),
            int((time.monotonic() - started) * 1000),
            [f"点评师执行失败: {type(exc).__name__}: {exc}"],
        )
    duration = int((time.monotonic() - started) * 1000)
    try:
        verdict = ReviewVerdict(
            reviewer_id=raw.reviewer_id,
            reviewer_version=raw.reviewer_version,
            ran_at=raw.ran_at or _now_iso(),
            status=raw.status,
            duration_ms=duration,
            data_refs=raw.data_refs,
            findings=raw.findings,
            proposed_invalidation=raw.proposed_invalidation,
            horizon_hint=raw.horizon_hint,
            caveats=raw.caveats,
        )
    except Exception as exc:  # noqa: BLE001 —— 点评师返回了非契约对象
        return _error_verdict(
            getattr(reviewer, "id", "unknown"),
            _reviewer_version(reviewer),
            duration,
            [f"点评师结果无法解析: {type(exc).__name__}: {exc}"],
        )
    errors = _validation_errors(verdict)
    if errors:
        return _error_verdict(
            verdict.reviewer_id or getattr(reviewer, "id", "unknown"),
            verdict.reviewer_version or _reviewer_version(reviewer),
            duration,
            [f"点评师结果未通过契约校验: {err}" for err in errors],
        )
    return verdict


def run_reviewers(reviewers: list, ctx: ReviewContext) -> list[ReviewVerdict]:
    """依次执行所有点评师，返回全部结果（含失败项）。"""
    return [run_one(reviewer, ctx) for reviewer in reviewers]


def persist(conn, observation_id: str, verdicts: list[ReviewVerdict]) -> list[dict]:
    """把 verdict 落库，返回落库后的字典列表。"""
    from ..storage import db

    saved = []
    for verdict in verdicts:
        db.insert_review(conn, observation_id, verdict.to_dict())
        saved.append(verdict.to_dict())
    return saved
