"""anchor-chanlun 点评师：缠论三级别结构 → 与用户观察对照 → findings / 证伪位 / 观察期档位。"""
from __future__ import annotations

import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from ...providers import tdx
from ...reviewers.contract import ReviewContext, ReviewVerdict, validate_verdict
from . import rules, signals, wording
from .engine import build_structure


def _dimension_names() -> list[str]:
    """评分维度名列表，来自 config/scoring.json。"""
    from ...config import load_scoring

    return [item["name"] for item in load_scoring()["dimensions"]]


def _validation_errors(verdict: ReviewVerdict) -> list[str]:
    """契约校验错误列表；配置读不到时也降级成一条错误，不向上抛。"""
    try:
        dimensions = _dimension_names()
    except Exception as exc:  # noqa: BLE001 —— 配置问题也要隔离
        return [f"无法读取评分维度配置: {type(exc).__name__}: {exc}"]
    return validate_verdict(verdict, dimensions)


def _latest_factor_row(symbol: str) -> dict | None:
    """取该标的最新的复权因子行（现价 → 后复权换算用）。

    点评师拿不到数据库连接（`ReviewContext` 只有 `data_dir`），所以这里直接取一次
    连接器；`fetch_adjustment_factors` 已按 ex_date 降序，第一行就是最新一行。
    取不到时返回 None —— 调用方按「无法换算」处理，不要静默当成现价。
    """
    try:
        factors = tdx.fetch_adjustment_factors(symbol)
    except Exception:  # noqa: BLE001 —— 换算失败不该让整轮点评挂掉
        return None
    return factors[0] if factors else None


def _quote_price(payload: dict) -> float:
    """从行情载荷里取现价（**不复权**口径）。

    实测（2026-11-24，`tdx_quotes` 返回 002378）：
      - 顶层键是 BaseInfo / ExtInfo / **HQInfo** / CalcInfo / ProInfo / ...
      - `HQInfo.Now` = 15.54（现价）、`HQInfo.Close` = 15.59（收盘价）
      - **没有 `AttachInfo`** —— 那是 K 线载荷 `tdx_kline` 的元数据，不是行情载荷的。
        读错字段会让回退路径永远静默返回「现价未知」。
    两个容器都试一遍，兼容两种载荷形态。
    """
    for container in ("HQInfo", "AttachInfo"):
        info = payload.get(container)
        if not isinstance(info, dict):
            continue
        for key in ("Now", "Close"):
            value = info.get(key)
            if isinstance(value, (int, float)) and value:
                return float(value)
    return 0.0


def fetch_last_close(symbol: str, setcode: str, structure: dict | None = None) -> float:
    """取现价（**后复权空间**）。

    优先用缠论结构里的 `levels.day.last_close`（上游已算好，省一次连接器调用）；
    结构里没有时才退回实时行情。

    **空间一致性（Global Constraint 16/18）**：结构里的 `last_close` 来自后复权 K 线，
    已经是后复权空间；实时行情返回的是**现价**（不复权空间），必须用复权因子换算成
    后复权再返回，否则会拿 10014 去和 1460 比。
    """
    if structure:
        for level_name in ("day", "m30", "week"):
            level = (structure.get("levels") or {}).get(level_name) or {}
            value = level.get("last_close")
            if isinstance(value, (int, float)) and value:
                return float(value)
    try:
        payload = tdx.fetch_quotes(symbol, setcode)
    except Exception:  # noqa: BLE001
        return 0.0
    price = _quote_price(payload)
    if not price:
        return 0.0
    row = _latest_factor_row(symbol)
    # 换不到因子行就**不能**返回现价 —— 它不在后复权空间，
    # 拿它去和后复权的中枢上下沿比会得出错误结论。返回 0.0 表示「未知」。
    return 0.0 if row is None else tdx.to_houfuquan(price, row)


class Reviewer:
    """缠论点评师。"""

    id = "anchor-chanlun"
    version = "0.1.0"

    def review(self, ctx: ReviewContext) -> ReviewVerdict:
        started = time.monotonic()
        symbol = ctx.symbol or (ctx.observation.get("symbol") or "")
        if not symbol:
            return ReviewVerdict(
                reviewer_id=self.id, reviewer_version=self.version,
                ran_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                status="skipped", duration_ms=0, data_refs=[], findings=[],
                proposed_invalidation=[], horizon_hint=None,
                caveats=["观察未包含证券代码，缠论点评跳过"],
            )

        try:
            setcode = tdx.setcode_for(symbol)
        except ValueError as exc:
            return ReviewVerdict(
                reviewer_id=self.id, reviewer_version=self.version,
                ran_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                status="skipped", duration_ms=0, data_refs=[], findings=[],
                proposed_invalidation=[], horizon_hint=None,
                caveats=[f"无法识别市场：{exc}"],
            )

        work_dir = Path(ctx.data_dir) / "chanlun" / symbol
        work_dir.mkdir(parents=True, exist_ok=True)

        structure = build_structure(symbol, ctx.name or symbol, setcode, work_dir)
        last_close = fetch_last_close(symbol, setcode, structure)

        findings, caveats = rules.evaluate(ctx.observation, structure, last_close)
        if ctx.llm is None:
            # 措辞层降级必须留痕，否则用户以为看到的是 LLM 改写过的表述
            caveats.append(
                "LLM 措辞层不可用（未配置 AGAISTOCK_LLM_BASE_URL / API_KEY / MODEL），"
                "点评保留规则层原文"
            )
        findings = wording.phrase(
            findings,
            ctx.observation,
            llm=ctx.llm,
            context={
                "narrative": structure.get("narrative"),
                "resonance": structure.get("resonance"),
                "discipline": (structure.get("framework") or {}).get("discipline"),
                "day_signal_detail": (structure.get("levels") or {}).get("day", {}).get("signal_detail"),
            },
        )

        invalidation = signals.build_invalidation(structure, last_close)
        hint = signals.build_horizon_hint(ctx.observation, structure, findings, last_close=last_close)

        caveats = list(caveats) + list(structure.get("caveats") or [])

        data_refs = [
            {
                "source": "tdx_kline",
                "params": {"code": symbol, "setcode": setcode, "want_num": 500},
                "window": "week/day/m30 各 500 根",
                "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
        ]

        verdict = ReviewVerdict(
            reviewer_id=self.id,
            reviewer_version=self.version,
            ran_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            status="ok",
            duration_ms=int((time.monotonic() - started) * 1000),
            data_refs=data_refs,
            findings=findings,
            proposed_invalidation=invalidation,
            horizon_hint=hint,
            caveats=caveats,
        )

        # 与 engine.run_one 保持一致地做一次契约校验，但**不丢结论**：
        # 错误写进 caveats，让「有发现却无限制声明」这类问题可见、可追。
        errors = _validation_errors(verdict)
        if errors:
            verdict = replace(
                verdict,
                caveats=list(verdict.caveats)
                + [f"点评结论未通过契约校验: {err}" for err in errors],
            )
        return verdict
