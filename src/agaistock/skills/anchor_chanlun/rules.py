"""缠论纪律 → findings / caveats。

纯函数：输入观察卡与缠论结构，输出结构化发现与限制声明。不触网、不读盘。
纪律来源：上游 chanlun-core/SKILL.md 的 25 条判读纪律。
"""
from __future__ import annotations

from typing import Any

from ...reviewers.contract import Finding

DIMENSION_POSITION = "位置与时机"
DIMENSION_FALSIFICATION = "证伪条件"

RULE_DELTAS: dict[str, int] = {
    "CHAN_HIGHER_LEVEL_DENIES": -15,
    "CHAN_POSITION_SIZE_CAP": -5,
    "CHAN_TOP_DIVERGENCE_OVERRIDES": -12,
    "CHAN_DIRECTION_CONFLICT": -18,
    "CHAN_POSITION_VS_TREND": 0,
    "CHAN_PIVOT_FAR_FROM_PRICE": -3,
    "CHAN_NEARBY_SUPPLY_BAND": -4,
    "CHAN_NESTING_UNCONFIRMED": -6,
    "CHAN_WINDOW_THIN": -2,
    "CHAN_PRICE_INSIDE_PIVOT": -5,
    "CHAN_SECOND_BUY_NO_BACKING": -6,
}

FAR_FROM_PRICE_PCT = 15.0
NEAR_BAND_PCT = 10.0

LEVEL_LABELS = {"week": "周线", "day": "日线", "m30": "30 分钟"}

# 常驻限制声明：只要给出了发现，就必须同时给出限制。
# 契约（Task 3 的 validate_verdict）把「有发现却没有限制声明」判为非法结论，
# engine.run_one 会把这类结论整条丢弃 —— 所以这里必须自己保证不为空。
STANDING_CAVEAT = (
    "本结论基于缠论结构识别：中枢、分笔与背驰窗口由上游脚本按固定规则判定，"
    "只对本次取数窗口内的结构负责；结构识别本身有窗口与样本限制，不构成投资建议。"
)


def _level(structure: dict[str, Any], name: str) -> dict[str, Any]:
    return (structure.get("levels") or {}).get(name) or {}


def _finding(code: str, severity: str, claim: str, why: str,
             evidence_ref: list[str], suggested_fix: str) -> Finding:
    return Finding(
        code=code,
        severity=severity,
        dimension=DIMENSION_POSITION,
        delta=RULE_DELTAS.get(code, 0),
        claim=claim,
        why=why,
        evidence_ref=evidence_ref,
        suggested_fix=suggested_fix,
    )


def evaluate(observation: dict, structure: dict, last_close: float) -> tuple[list[Finding], list[str]]:
    """返回 (findings, caveats)。"""
    findings: list[Finding] = []
    caveats: list[str] = []
    direction = (observation.get("direction") or "").lower()

    week = _level(structure, "week")
    day = _level(structure, "day")
    m30 = _level(structure, "m30")

    week_bias = week.get("bias")
    day_signal = day.get("signal") or ""

    # 纪律二：小级别服从大级别
    if week_bias == "down" and direction == "bullish":
        findings.append(_finding(
            "CHAN_HIGHER_LEVEL_DENIES", "high",
            f"周线当前强弱为 down，而你的主张是看多",
            "按纪律二，小级别服从大级别；周线未给出向上许可时，日线级别的看多只能定性为反弹。",
            ["chan.levels.week.bias"],
            "把主张降级为『反弹参与』，或等待周线底背驰背书后再提高仓位",
        ))
        findings.append(_finding(
            "CHAN_POSITION_SIZE_CAP", "info",
            "周线未许可向上，仓位应受限",
            "按纪律二：周线向下时只做短线轻仓或空仓。",
            ["chan.levels.week.bias"],
            "若仍要参与，按轻仓处理，并把观察期放在短线档",
        ))

    # 纪律四/八：顶背驰优先
    if "顶背驰" in day_signal:
        findings.append(_finding(
            "CHAN_TOP_DIVERGENCE_OVERRIDES", "critical",
            f"日线出现顶背驰预警（{day_signal}）",
            "顶背驰是大级别预警，不得被更小级别的买点推翻。",
            ["chan.levels.day.signal"],
            "先按减仓/观望处理，等日线级别的新结构确认",
        ))

    # 纪律二/二十一：方向冲突
    if direction == "bullish" and ("顶背驰" in day_signal or "卖点" in day_signal):
        findings.append(_finding(
            "CHAN_DIRECTION_CONFLICT", "critical",
            f"你的方向是看多，但日线买卖点判定为「{day_signal}」",
            "结构判定与主张方向相反，这是位置与时机维度上最直接的冲突。",
            ["chan.levels.day.signal"],
            "重新检查主张所依赖的依据是否已被价格结构否定",
        ))
    if direction == "bearish" and "底背驰" in day_signal:
        findings.append(_finding(
            "CHAN_DIRECTION_CONFLICT", "critical",
            f"你的方向是看空，但日线买卖点判定为「{day_signal}」",
            "结构判定与主张方向相反。",
            ["chan.levels.day.signal"],
            "重新检查主张所依赖的依据是否已被价格结构否定",
        ))

    # 纪律二十一：位置读数 ≠ 趋势性质
    # 三个级别都要看：位置/趋势背离在任何级别上都成立，只看日线会漏掉周线与 30 分钟的背离。
    for level_name, level in (("week", week), ("day", day), ("m30", m30)):
        bias = level.get("bias")
        trend = level.get("trend_direction")
        if not bias or not trend or bias == trend:
            continue
        label = LEVEL_LABELS[level_name]
        caveats.append(
            f"{label}位置读数为 {bias}，但趋势性质为 {trend}；"
            "位置读数只代表价格相对最近中枢的位置，不代表趋势已经改变"
        )
        findings.append(_finding(
            "CHAN_POSITION_VS_TREND", "info",
            f"{label}位置 {bias} 与趋势性质 {trend} 不一致",
            "价格刚站上或跌破中枢沿会翻转位置读数，但趋势性质往往未变。",
            [f"chan.levels.{level_name}.bias", f"chan.levels.{level_name}.trend_direction"],
            "读结论时以趋势性质为准，位置读数仅作参考",
        ))

    # 纪律二十二：中枢不贴近现价 → 中枢类判据降权
    for level_name, level in (("week", week), ("day", day), ("m30", m30)):
        for pivot in level.get("nearby_pivots") or []:
            dist = pivot.get("dist_pct")
            if isinstance(dist, (int, float)) and abs(dist) > FAR_FROM_PRICE_PCT:
                findings.append(_finding(
                    "CHAN_PIVOT_FAR_FROM_PRICE", "medium",
                    f"{level_name} 最近中枢距现价 {dist:.1f}%，超出 {FAR_FROM_PRICE_PCT}% 阈值",
                    "中枢不贴近现价时，「中枢上方/下方运行」这个标签对当期决策几乎没有参考价值。",
                    [f"chan.levels.{level_name}.nearby_pivots"],
                    "把判断重心转向双底/双顶结构、动能收缩或放大、MACD 交叉与成交量等不依赖中枢的读面",
                ))
                break

    # 纪律二十二 / 十一：旧中枢供给带
    supply_bands = []
    for level_name, level in (("week", week), ("day", day), ("m30", m30)):
        for pivot in level.get("nearby_pivots") or []:
            dist = pivot.get("dist_pct")
            if isinstance(dist, (int, float)) and 0 < dist <= NEAR_BAND_PCT:
                supply_bands.append((level_name, pivot))
    if supply_bands:
        level_name, pivot = supply_bands[0]
        findings.append(_finding(
            "CHAN_NEARBY_SUPPLY_BAND", "medium",
            f"{level_name} 头顶存在距现价 {pivot.get('dist_pct'):.1f}% 的供给带"
            f"（{pivot.get('ZD')} ~ {pivot.get('ZG')}）",
            "脚本只标注最近中枢，更早但仍在起作用的旧中枢常构成关键阻力。",
            [f"chan.levels.{level_name}.nearby_pivots"],
            "把该区间当作上方压力带纳入操作定性",
        ))

    # 纪律十三：区间套未确认
    nesting = structure.get("interval_nesting") or {}
    if nesting.get("verdict") == "unconfirmed":
        findings.append(_finding(
            "CHAN_NESTING_UNCONFIRMED", "medium",
            f"日线→30 分钟区间套未确认（{nesting.get('reason', '未说明')}）",
            "未确认的信号不构成可执行信号，需要追问未确认的具体成因。",
            ["chan.interval_nesting"],
            "确认次级别是否已出现同向背驰，否则把该信号按单级别处理",
        ))

    # 纪律九：区间套方向必须写明
    if nesting.get("verdict") in ("partial", "confirmed"):
        caveats.append(
            f"区间套为 {nesting.get('verdict')}；该结论只描述次级别是否同向印证，"
            "若印证的是顶背驰，含义是向下动能衰减得到印证，不是买入理由"
        )

    # 纪律十二：背驰失效复核
    for level_name, level in (("week", week), ("day", day), ("m30", m30)):
        divergence = level.get("recent_divergence")
        if divergence and divergence.get("active"):
            caveats.append(
                f"{level_name} 的背驰 active 标签仅表示锚点落在背驰窗口内，"
                "不代表背驰仍然成立；须复核价格是否已突破锚点、新一笔动能是否同步放大"
            )
        hint = level.get("divergence_hint")
        if hint:
            caveats.append(
                f"{level_name} 存在背驰迹象（面积比 {hint.get('area_ratio')}），"
                "迹象不能单独作为买卖点依据，但也不能漏掉"
            )

    # 纪律二十四：窗口偏薄
    for level_name, level in (("week", week), ("day", day), ("m30", m30)):
        verdict = level.get("window_verdict")
        if verdict in ("样本偏薄", "窗口偏短", "窗口偏长", "样本过密"):
            findings.append(_finding(
                "CHAN_WINDOW_THIN", "medium",
                f"{level_name} 窗口体检结论为「{verdict}」",
                "窗口结构不充分，依赖该级别中枢的关键价位置信度下降。",
                [f"chan.levels.{level_name}.window_verdict"],
                "该级别的关键价位降级使用，不要作为唯一依据",
            ))

    # 纪律十七：现价落在中枢内部
    for level_name, level in (("day", day), ("m30", m30)):
        for pivot in level.get("nearby_pivots") or []:
            zd = pivot.get("ZD")
            zg = pivot.get("ZG")
            if isinstance(zd, (int, float)) and isinstance(zg, (int, float)) and zd <= last_close <= zg:
                findings.append(_finding(
                    "CHAN_PRICE_INSIDE_PIVOT", "medium",
                    f"现价 {last_close} 落在 {level_name} 中枢 {zd}~{zg} 内部",
                    "现价在中枢内部时，该中枢上下沿就是天然决胜位。",
                    [f"chan.levels.{level_name}.nearby_pivots"],
                    f"以 {zg} 作确认线、{zd} 作失效线",
                ))
                break

    # 纪律二十三：回调不创新低 + 大级别无背书
    if "底背驰" in day_signal and not (week.get("recent_divergence") or {}).get("kind"):
        findings.append(_finding(
            "CHAN_SECOND_BUY_NO_BACKING", "medium",
            "日线出现底背驰迹象，但周线未给出同向背驰背书",
            "按纪律二，没有大级别背书的日线结构只能支撑试探仓。",
            ["chan.levels.day.signal", "chan.levels.week.recent_divergence"],
            "按试探仓对待（不超过三成），并把观察期放在短线档",
        ))

    # 纪律二十五：盘中未收盘 —— 用上游的 may_be_partial 标志，不无条件报警
    # （实测：may_be_partial=false 表示该级别最后一根已收盘；true 才是未收盘）
    partial_levels = [
        name for name, lvl in (("week", week), ("day", day), ("m30", m30))
        if (lvl or {}).get("may_be_partial") is True
    ]
    if partial_levels:
        caveats.append(
            f"{'、'.join(partial_levels)} 的最后一根 K 线尚未收盘，"
            "MACD 柱与 DIF 都会在收盘后变化，结论需收盘后复校"
        )

    # 有发现就必须有限制声明（见 STANDING_CAVEAT 的说明）。
    if findings:
        caveats.append(STANDING_CAVEAT)

    return findings, caveats
