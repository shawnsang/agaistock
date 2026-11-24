"""从缠论结构生成建议的证伪条件与观察期档位提示。"""
from __future__ import annotations

from typing import Any

from ...reviewers.contract import Finding, HorizonHint, ProposedInvalidation

TOLERANCE_PCT = 0.5

# 档位的保守程度：允许的观察窗口越短 = 越保守。
# （Task 12 的 resolve_tier 用同一套语义做跨点评师取最保守）
TIER_RANK = {"short": 0, "mid": 1, "event": 1, "long": 2}

# 点评师**自己的发现**对观察期档位构成上限。
# 依据是 rules.py 每条规则的 suggested_fix 里已经写明的处置：
#   「把观察期放在短线档」/「按减仓、观望处理」/「重新检查主张是否已被否定」→ 短线
#   「按单级别处理」/「降级使用」/「不依赖中枢的读面」→ 不超过中期
# 没有这张表时，build_horizon_hint 收了 findings 参数却不用，会出现
# 「finding 说『把观察期放在短线档』，horizon_hint 却给 long」这种自相矛盾的结论。
FINDING_TIER_CAPS = {
    "CHAN_HIGHER_LEVEL_DENIES": "short",
    "CHAN_POSITION_SIZE_CAP": "short",
    "CHAN_TOP_DIVERGENCE_OVERRIDES": "short",
    "CHAN_DIRECTION_CONFLICT": "short",
    "CHAN_SECOND_BUY_NO_BACKING": "short",
    "CHAN_NESTING_UNCONFIRMED": "mid",
    "CHAN_WINDOW_THIN": "mid",
    "CHAN_PIVOT_FAR_FROM_PRICE": "mid",
}


def _cap_from_findings(findings: list[Finding]) -> str | None:
    """由发现推出档位上限（多条发现取最保守的那个）。"""
    cap: str | None = None
    for finding in findings or []:
        limit = FINDING_TIER_CAPS.get(finding.code)
        if limit is None:
            continue
        if cap is None or TIER_RANK[limit] < TIER_RANK[cap]:
            cap = limit
    return cap


def _levels(structure: dict[str, Any]) -> dict[str, Any]:
    return structure.get("levels") or {}


def _position(last_close: float, zd: float, zg: float) -> str:
    """现价相对中枢的位置：above / inside / below / unknown。

    `last_close <= 0` 表示**现价未知**（取不到可比的现价，例如复权因子缺失导致
    无法把实时行情换算到后复权空间）。这时不能假装现价在中枢下方 ——
    那会让文案说出「跌破下沿属于已发生的事实」这种假话。
    """
    if last_close <= 0:
        return "unknown"
    if last_close > zg:
        return "above"
    if last_close >= zd:
        return "inside"
    return "below"


def _below_rationale(level_name: str, position: str, zd: float, zg: float) -> str:
    """跌破中枢下沿的含义随现价位置而变，写清楚才不会被误读。"""
    if position == "unknown":
        return (
            f"现价未知（取不到可比的现价），跌破 {level_name} 中枢下沿 {zd} "
            f"（中枢区间 {zd}~{zg}）即视为判断错误"
        )
    if position == "inside":
        return f"价格跌出 {level_name} 中枢下沿 {zd} 即视为判断错误"
    if position == "above":
        return (
            f"价格已站在 {level_name} 中枢上方，跌破该支撑带下沿 {zd} 即视为判断错误"
            f"（中枢区间 {zd}~{zg}）"
        )
    return (
        f"{level_name} 中枢位于现价上方（{zd}~{zg}），跌破下沿 {zd} 属于已发生的事实，"
        "此处只作结构失效参考，不作为本次的失效判定"
    )


def build_invalidation(structure: dict, last_close: float) -> list[ProposedInvalidation]:
    """从中枢上下沿生成建议的证伪条件与确认位。

    证伪位取中枢下沿 ZD，**不按距现价的远近过滤**：一个远在 +44% 的中枢下沿
    仍然是有效的失效位（跌回去说明结构被证伪）。若用 dist_pct 当门槛，证伪位
    会被全部过滤掉，「建议的证伪条件」与观察期 checks 就永远是空的。
    「邻近带」只用于 rules.py 的 CHAN_NEARBY_SUPPLY_BAND 规则。

    跌破 ZD 在三种位置下都要给出（现价在带下 / 带内 / 带上）：
      - 带内：跌出中枢 → 结构走坏
      - 带上（支撑带在脚下）：跌破支撑带下沿 → 支撑失效
      - 带下（供给带在头顶）：条件已成立，只作结构参考
    """
    result: list[ProposedInvalidation] = []
    for level_name in ("day", "week", "m30"):
        level = _levels(structure).get(level_name) or {}
        for pivot in level.get("nearby_pivots") or []:
            zd = pivot.get("ZD")
            zg = pivot.get("ZG")
            if not isinstance(zd, (int, float)) or not isinstance(zg, (int, float)):
                continue
            if zd <= 0 or zg <= zd:
                continue
            position = _position(last_close, zd, zg)
            result.append(ProposedInvalidation(
                desc=f"跌破 {level_name} 中枢下沿 {zd}",
                source=f"chan.levels.{level_name}.nearby_pivots[].ZD",
                comparator="below",
                tolerance=TOLERANCE_PCT,
                rationale=_below_rationale(level_name, position, zd, zg),
            ))
            if position != "above":
                # 现价已经在上沿之上时，「站上 ZG」已经成立，不再作为待确认条件给出。
                result.append(ProposedInvalidation(
                    desc=f"站上 {level_name} 中枢上沿 {zg}",
                    source=f"chan.levels.{level_name}.nearby_pivots[].ZG",
                    comparator="above",
                    tolerance=TOLERANCE_PCT,
                    rationale=f"价格站上 {level_name} 中枢上沿 {zg} 视为主张被强化",
                ))
    return result


def build_horizon_hint(
    observation: dict,
    structure: dict,
    findings: list[Finding],
    last_close: float = 0.0,
) -> HorizonHint:
    """给出观察期档位上限建议（多家点评师取最保守时由上游聚合）。"""
    day = _levels(structure).get("day") or {}
    week = _levels(structure).get("week") or {}
    day_signal = day.get("signal") or ""
    week_bias = week.get("bias")

    tier = "mid"
    rationale = "结构未给出明确的强弱许可，按中期档处理"

    if week_bias == "up" and ("底背驰" in day_signal or "买点" in day_signal):
        tier = "long"
        rationale = "周线许可向上且日线给出同向信号，支持较长观察期"
    elif "顶背驰" in day_signal or "卖点" in day_signal:
        tier = "short"
        rationale = "日线给出顶背驰/卖点信号，只支持短线验证"
    elif week_bias == "down":
        tier = "short"
        rationale = "周线未许可向上，只支持短线验证"

    if observation.get("trigger"):
        tier = "event"
        rationale = f"存在明确催化剂（{observation.get('trigger')}），按事件驱动锚定"

    # 档位上限：点评师自己的发现不能被自己的观察期建议推翻。
    # （rules.py 的 suggested_fix 常写着「把观察期放在短线档」；若这里仍给 long，
    #   同一份结论里就会自相矛盾。）
    cap = _cap_from_findings(findings)
    if cap is not None and TIER_RANK.get(cap, 99) < TIER_RANK.get(tier, 0):
        rationale = f"{rationale}；受本次发现约束，观察期档位降为 {cap}"
        tier = cap

    # 必须传真实的 last_close —— 用 0.0 会让「现价是否落在中枢内部」的判断失效
    checks = [
        {
            "id": f"c{index + 1}",
            "desc": item.desc,
            "source": item.source,
            "comparator": item.comparator,
            "tolerance": item.tolerance,
        }
        for index, item in enumerate(build_invalidation(structure, last_close))
    ]

    return HorizonHint(tier=tier, rationale=rationale, checks=checks)
