"""观察期规划。

档位上限由点评师的 horizon_hint 决定，多家点评师取**最保守**。
具体 review_at 在允许档位内选取；本实现取档位内最小值（更早复校更安全）。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .reviewers.contract import ReviewVerdict

TIER_ALLOWED: dict[str, tuple[int, ...]] = {
    "short": (3, 5),
    "mid": (5, 10, 20),
    "long": (10, 20, 40),
    "event": (5, 10, 20),
}

# 保守程度排序（越靠前越保守，min() 取最保守的那个）。
# 按**允许窗口**排序，不按字母直觉：event 与 mid 的窗口完全相同 (5,10,20)，
# 都比 long 的 (10,20,40) 保守。若把 event 排到最后，就会出现
# 「有点评师说 event（最早 5 天复校）、另一个说 long（最早 10 天）」却选了 long 的怪事。
TIER_ORDER = ("short", "mid", "event", "long")


def _conservative(tier: str) -> int:
    return TIER_ORDER.index(tier) if tier in TIER_ORDER else 0


def resolve_tier(verdicts: list[ReviewVerdict]) -> tuple[str | None, list[str]]:
    """返回 (最保守档位, 各点评师给出的档位列表)。"""
    tiers: list[str] = []
    for verdict in verdicts:
        hint = verdict.horizon_hint
        if hint is None:
            continue
        tier = getattr(hint, "tier", None) or (hint.get("tier") if isinstance(hint, dict) else None)
        if tier in TIER_ALLOWED:
            tiers.append(tier)
    if not tiers:
        return None, []
    best = min(tiers, key=_conservative)
    return best, tiers


def _trading_days_later(start: date, offset: int) -> date:
    """按自然日推进后跳过周末（未处理节假日，仅作近似）。"""
    current = start
    remaining = offset
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _trading_days_between(start: date, end: date) -> int:
    """start 之后到 end（含）之间的交易日数，与 `_trading_days_later` 同口径。

    **必须与 `_trading_days_later` 同口径**：档位里的天数是**交易日偏移**，
    而 `(end - start).days` 是**日历日差**。两个口径混用时，
    自动推导出来的那个日期（`_trading_days_later(start, 10)`）会因为
    日历日差是 14 而不是 10，被误判成「不在允许档位内」。
    """
    if end <= start:
        return 0
    current = start
    count = 0
    while True:
        current += timedelta(days=1)
        if current > end:
            return count
        if current.weekday() < 5:
            count += 1


def _proposed_items(verdicts: list[ReviewVerdict]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for verdict in verdicts:
        for item in verdict.proposed_invalidation:
            if isinstance(item, dict):
                data = item
            else:
                data = item.to_dict()
            items.append(data)
    return items


def plan(
    observation: dict,
    verdicts: list[ReviewVerdict],
    start: str,
    review_at: str | None = None,
) -> dict[str, Any]:
    tier, source_tiers = resolve_tier(verdicts)
    allowed = TIER_ALLOWED.get(tier or "", ())

    start_date = date.fromisoformat(start)
    if review_at:
        chosen = date.fromisoformat(review_at)
        # 用**交易日**偏移校验，不要用日历日差 —— 档位里的天数是交易日偏移。
        offset = _trading_days_between(start_date, chosen)
        if allowed and offset not in allowed:
            # 用户指定的日期不在允许档位内 → 落到档位内最早的那个，
            # 并同步收窄窗口，保证 review_at 一定落在 allowed_window 之内。
            allowed = (min(allowed),)
            chosen = _trading_days_later(start_date, min(allowed))
    elif allowed:
        chosen = _trading_days_later(start_date, min(allowed))
    else:
        chosen = _trading_days_later(start_date, 5)

    window_start = start_date
    window_end = _trading_days_later(start_date, max(allowed)) if allowed else chosen

    proposed = _proposed_items(verdicts)
    checks = [
        {
            "id": f"c{index + 1}",
            "desc": item.get("desc", ""),
            "source": item.get("source", ""),
            "comparator": item.get("comparator", ""),
            "tolerance": item.get("tolerance"),
            # rationale 必须一起带下来：中枢在头顶时，「跌破下沿」的条件**已经成立**，
            # 只作结构参考、不作为本次的失效判定 —— 丢掉 rationale，下游（Task 15 的 UI）
            # 会把一条已成立的条件当成待触发条件展示。
            "rationale": item.get("rationale", ""),
        }
        for index, item in enumerate(proposed)
    ]

    rationales = []
    for verdict in verdicts:
        hint = verdict.horizon_hint
        if hint is None:
            continue
        rationale = getattr(hint, "rationale", None) or (
            hint.get("rationale") if isinstance(hint, dict) else ""
        )
        if rationale:
            rationales.append(f"{verdict.reviewer_id}: {rationale}")

    return {
        "tier": tier,
        "source_tiers": source_tiers,
        "review_at": chosen.isoformat(),
        "allowed_window": [window_start.isoformat(), window_end.isoformat()],
        "rationale": "；".join(rationales) if rationales else "无点评师给出档位建议，按默认短期档处理",
        "confidence": 0.5 if tier else 0.0,
        "checks": checks,
        "invalidation_triggers": [item.get("desc", "") for item in proposed],
    }
