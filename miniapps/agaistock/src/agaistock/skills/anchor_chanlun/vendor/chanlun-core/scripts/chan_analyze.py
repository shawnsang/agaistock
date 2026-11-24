#!/usr/bin/env python3
"""
缠论结构识别引擎（纯标准库 · 多周期版）

处理链：K线 → 包含处理 → 分型 → 笔 → 段 → 中枢 → 背驰 → 结构上下文

用法：
  python3 chan_analyze.py [workdir] --level week
  python3 chan_analyze.py [workdir] --level day  --input kline_day.json
  python3 chan_analyze.py [workdir] --level m30  --output chan_analysis_m30.json

默认输入：kline_<level>.json（不存在则回退 kline_latest.json）
默认输出：chan_analysis_<level>.json（--level day 时额外写一份 chan_analysis.json 兼容旧流程）

统一输入 JSON 格式：
  { "data": { "klines": ["YYYY-MM-DD,o,c,h,l,v,a", ...] } }

级别标识：week（周线）/ day（日线）/ m30（30分钟）
"""
import argparse
import json
import os
import sys
from datetime import datetime, date

LEVEL_META = {
    "week": {"zh": "周线", "role": "长期战略", "rank": 1, "div_window": 12},
    "day": {"zh": "日线", "role": "中期战术", "rank": 2, "div_window": 15},
    "m30": {"zh": "30分钟", "role": "短期执行", "rank": 3, "div_window": 24},
}

# 背驰判定阈值：MACD 柱面积缩小到前次的 90% 以下才算背驰
DIVERGENCE_SHRINK = 0.9

# 背驰"仍然有效"的观察窗口（合并后 K 线根数）——按级别分别取值。
#
# 口径：窗口 ≈ 该级别 2-3 根笔的走势深度，而不是一个统一根数。
#   week 12 根 ≈ 3 个月  ≈ 2 根周线笔
#   day  15 根 ≈ 3 周    ≈ 2.5 根日线笔
#   m30  24 根 ≈ 3 个交易日 ≈ 3 根 30 分钟笔
# 统一用 15 根是错的：那等于让周线背驰"有效"15 周、30 分钟只"有效"3-4 天，
# 同一个背驰在不同级别得到完全不等的保鲜期，区间套的跨级别比较就失去意义。
DIVERGENCE_WINDOW_BY_LEVEL = {"week": 12, "day": 15, "m30": 24}
DIVERGENCE_WINDOW = 15  # 兜底值（级别未知时使用）

# 结构样本健康区间（窗口取舍的量化标尺，详见 SKILL.md「窗口取舍原则」）
PIVOT_COUNT_IDEAL = (4, 8)     # 每级别理想的中枢个数
KLINE_COUNT_IDEAL = (250, 600)  # 每级别理想的 K 线根数

# 距现价多少百分比以内的历史中枢要单独拎出来当「供给带 / 支撑带」候选
NEARBY_BAND_PCT = 10.0


def parse_args():
    p = argparse.ArgumentParser(description="缠论结构识别（多周期）")
    p.add_argument("workdir", nargs="?", default=None, help="工作目录，默认当前目录")
    p.add_argument("--level", default="day", choices=sorted(LEVEL_META), help="分析级别")
    p.add_argument("--input", default=None, help="输入 K 线文件名")
    p.add_argument("--output", default=None, help="输出 JSON 文件名")
    p.add_argument("--min-gap", type=int, default=4,
                   help="成笔所需的最小间隔（合并后 K 线根数，默认 4）")
    return p.parse_args()


# ========== 1. 读 K 线 ==========
def load_records(path):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    klines = raw.get("data", {}).get("klines", [])
    records = []
    for line in klines:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        records.append({
            "date": parts[0],
            "o": float(parts[1]),
            "c": float(parts[2]),
            "h": float(parts[3]),
            "l": float(parts[4]),
            "v": float(parts[5]),
            "a": float(parts[6]) if len(parts) > 6 else 0.0,
            "src_idx": len(records),
        })
    return records


# ========== 2. 包含处理 ==========
def merge_inclusion(records):
    """标准 K 线包含处理。

    方向判定：把当前 K 线与上一根【合并后】K 线比较，高点抬升记为向上。
    合并规则：
      向上 → 取「高高、高低」（max high, max low）
      向下 → 取「低高、低低」（min high, min low）
    合并后 K 线保留决定极值那一根的日期与 src_idx，便于后续回溯 MACD。
    """
    if len(records) < 2:
        return [dict(r) for r in records]

    out = [dict(records[0])]
    direction = 1
    if records[1]["h"] < records[0]["h"]:
        direction = -1
    elif records[1]["h"] == records[0]["h"] and records[1]["l"] < records[0]["l"]:
        direction = -1

    for i in range(1, len(records)):
        cur = records[i]
        prev = out[-1]

        is_included = (cur["h"] <= prev["h"] and cur["l"] >= prev["l"]) or \
                      (cur["h"] >= prev["h"] and cur["l"] <= prev["l"])

        if is_included:
            if direction == 1:
                nh, nl = max(prev["h"], cur["h"]), max(prev["l"], cur["l"])
                extreme_is_cur = cur["h"] >= prev["h"]
            else:
                nh, nl = min(prev["h"], cur["h"]), min(prev["l"], cur["l"])
                extreme_is_cur = cur["l"] <= prev["l"]

            pick = cur if extreme_is_cur else prev
            merged = dict(prev)
            merged["h"], merged["l"] = nh, nl
            merged["date"] = pick["date"]
            merged["src_idx"] = pick["src_idx"]
            out[-1] = merged
        else:
            if cur["h"] > prev["h"]:
                direction = 1
            elif cur["h"] < prev["h"]:
                direction = -1
            out.append(dict(cur))

    return out


# ========== 3. 顶/底分型 ==========
def find_fractals(bars):
    """在包含处理后的序列上找分型。"""
    tops, bots = [], []
    for i in range(1, len(bars) - 1):
        if bars[i]["h"] > bars[i - 1]["h"] and bars[i]["h"] > bars[i + 1]["h"]:
            tops.append(i)
        if bars[i]["l"] < bars[i - 1]["l"] and bars[i]["l"] < bars[i + 1]["l"]:
            bots.append(i)
    return tops, bots


# ========== 4. 笔 ==========
def build_strokes(tops, bots, bars, min_gap=4):
    """顶底分型交替连线成笔；顶底之间至少间隔 min_gap 根合并 K 线。"""
    cands = sorted([(i, "T") for i in tops] + [(i, "B") for i in bots])
    strokes = []
    for idx, typ in cands:
        price = bars[idx]["h"] if typ == "T" else bars[idx]["l"]
        if not strokes:
            strokes.append({"idx": idx, "type": typ, "price": price})
            continue
        last = strokes[-1]
        if typ == last["type"]:
            if (typ == "T" and price > last["price"]) or (typ == "B" and price < last["price"]):
                strokes[-1] = {"idx": idx, "type": typ, "price": price}
        else:
            if idx - last["idx"] < min_gap:
                continue
            strokes.append({"idx": idx, "type": typ, "price": price})
    return strokes


# ========== 5. MACD ==========
def ema(values, span):
    k = 2 / (span + 1)
    out = [values[0]]
    for v in values[1:]:
        out.append(out[-1] + k * (v - out[-1]))
    return out


def compute_macd(records):
    """在【原始】收盘价序列上计算 MACD，返回 hist 数组。"""
    closes = [r["c"] for r in records]
    ema12, ema26 = ema(closes, 12), ema(closes, 26)
    dif = [a - b for a, b in zip(ema12, ema26)]
    dea = ema(dif, 9)
    hist = [(d - e) * 2 for d, e in zip(dif, dea)]
    for i, r in enumerate(records):
        r["dif"], r["dea"], r["hist"] = dif[i], dea[i], hist[i]
    return hist


def attach_stroke_area(strokes, bars, hist):
    """为每一笔计算 MACD 柱面积（该笔区间内 |hist| 之和），用于背驰比较。"""
    for k, s in enumerate(strokes):
        left = strokes[k - 1]["idx"] if k > 0 else 0
        area = 0.0
        for bar in bars[left:s["idx"] + 1]:
            si = bar["src_idx"]
            if 0 <= si < len(hist):
                area += abs(hist[si])
        s["area"] = round(area, 4)
    return strokes


# ========== 6. 线段 ==========
def build_segments(strokes):
    """简化段：连续三笔且末笔极值越过首笔极值即成一段。"""
    segs = []
    i = 0
    while i < len(strokes) - 2:
        a, b, c = strokes[i], strokes[i + 1], strokes[i + 2]
        if a["type"] == "B" and b["type"] == "T" and c["type"] == "B" and c["price"] > a["price"]:
            segs.append({
                "dir": "up",
                "start_idx": a["idx"], "mid_idx": b["idx"], "end_idx": c["idx"],
                "start_price": a["price"], "mid_price": b["price"], "end_price": c["price"],
                "hi": max(a["price"], b["price"], c["price"]),
                "lo": min(a["price"], b["price"], c["price"]),
            })
            i += 2
            continue
        if a["type"] == "T" and b["type"] == "B" and c["type"] == "T" and c["price"] < a["price"]:
            segs.append({
                "dir": "down",
                "start_idx": a["idx"], "mid_idx": b["idx"], "end_idx": c["idx"],
                "start_price": a["price"], "mid_price": b["price"], "end_price": c["price"],
                "hi": max(a["price"], b["price"], c["price"]),
                "lo": min(a["price"], b["price"], c["price"]),
            })
            i += 2
            continue
        i += 1
    return segs


# ========== 7. 中枢 ==========
def find_pivots(segs, min_overlap_ratio=0.003):
    """中枢 = 连续三段重叠区间；后续段仍与区间重叠则延伸（中枢延伸）。"""
    pivs = []
    i, n = 0, len(segs)
    while i + 2 < n:
        s1, s2, s3 = segs[i], segs[i + 1], segs[i + 2]
        hi = min(s1["hi"], s2["hi"], s3["hi"])   # ZG：三段中最低的高点
        lo = max(s1["lo"], s2["lo"], s3["lo"])   # ZD：三段中最高的低点
        if hi > lo and (hi - lo) / lo >= min_overlap_ratio:
            start, end = i, i + 2
            j = i + 3
            while j < n:
                s = segs[j]
                # 段末端重新回到中枢区间内 → 中枢延伸；否则中枢被离开，就此结束
                if lo <= s["end_price"] <= hi:
                    end, j = j, j + 1
                else:
                    break
            pivs.append({
                "start_idx": segs[start]["start_idx"],
                "end_idx": segs[end]["end_idx"],
                "seg_start": start, "seg_end": end,
                "ZG": hi, "ZD": lo,
                "first_dir": segs[start]["dir"], "last_dir": segs[end]["dir"],
                "extend": end - start - 2,
                "amp_pct": round((hi - lo) / lo * 100, 2),
            })
            i = end + 1
        else:
            i += 1
    return pivs


# ========== 8. 背驰 ==========
def check_divs(strokes, kind):
    """相邻同向极值比较：价格创新极值但 MACD 柱面积萎缩 → 背驰。"""
    pts = [s for s in strokes if s["type"] == ("T" if kind == "top" else "B")]
    res = []
    for i in range(1, len(pts)):
        prev, cur = pts[i - 1], pts[i]
        if kind == "top":
            if cur["price"] <= prev["price"]:
                continue
        else:
            if cur["price"] >= prev["price"]:
                continue

        if cur["area"] < prev["area"] * DIVERGENCE_SHRINK:
            verdict = "顶背驰" if kind == "top" else "底背驰"
        elif cur["area"] >= prev["area"]:
            verdict = "无背驰"
        else:
            verdict = "背驰迹象"

        res.append({
            "idx": cur["idx"], "prev_idx": prev["idx"],
            "price": cur["price"], "prev_price": prev["price"],
            "area": cur["area"], "prev_area": prev["area"],
            "type": verdict,
            "kind": kind,
        })
    return res


# ========== 9. 结构上下文（供多级别统合使用）==========
def build_pivot_bands(bars, pivs, last_close):
    """中枢分层：把每一个中枢相对现价归位，标出它在当下扮演什么角色。

    这一步是「细节不被淹没」的关键。脚本原先只把 *最近* 中枢写进结论，
    但更早的中枢常常与现价构成关键供给带或支撑带——只标注最近中枢会漏掉
    最重要的阻力 / 支撑判断。

    方位规则（以现价为基准）：
      现价 > ZG  → 该中枢在脚下，是【支撑带】
      现价 < ZD  → 该中枢在头顶，是【供给带】
      ZD ≤ 现价 ≤ ZG → 现价正在其中，是【当前中枢】

    枢纽注：缠论里中枢的价值不在"新旧"，而在"是否与当前走势发生重叠"。
    一个三年前的中枢，只要其上沿压在现价上方 3%，它对当下的约束力就和
    上周的中枢一样真实。
    """
    bands = []
    for i, p in enumerate(pivs):
        if last_close > p["ZG"]:
            side, role, dist = "below", "支撑带", (p["ZG"] - last_close) / last_close * 100
        elif last_close < p["ZD"]:
            side, role, dist = "above", "供给带", (p["ZD"] - last_close) / last_close * 100
        else:
            side, role, dist = "inside", "当前中枢", 0.0
        if i == len(pivs) - 1:
            role = "最近中枢"
        bands.append({
            "is_last": i == len(pivs) - 1,
            "side": side,
            "from": bars[p["start_idx"]]["date"],
            "to": bars[p["end_idx"]]["date"],
            "ZD": round(p["ZD"], 2),
            "ZG": round(p["ZG"], 2),
            "amp_pct": p["amp_pct"],
            "extend": p["extend"],
            "role": role,
            "dist_pct": round(dist, 2),
        })
    return bands


def pick_nearby_bands(bands, tol_pct=NEARBY_BAND_PCT):
    """挑出「与现价有关」的中枢：绝对距离在容差内的全部，外加最近的上方供给带
    与最近的下方支撑带各一个（保底，避免关键价位表为空）。

    缠论里中枢的价值不在"新旧"，而在"是否与当前走势发生重叠"：一个三年前的
    中枢，只要其上沿压在现价上方 3%，它对当下的约束力就和上周的中枢一样真实。
    因此不能只标注最近中枢。

    dist_pct 的符号约定：正数 = 该中枢在现价上方（供给带），负数 = 在现价下方（支撑带）。
    """
    picked = {i for i, b in enumerate(bands) if abs(b["dist_pct"]) <= tol_pct}
    above = [(i, b) for i, b in enumerate(bands) if b["side"] == "above"]
    below = [(i, b) for i, b in enumerate(bands) if b["side"] == "below"]
    if above:
        picked.add(min(above, key=lambda t: t[1]["dist_pct"])[0])   # 最近的上方供给带
    if below:
        picked.add(max(below, key=lambda t: t[1]["dist_pct"])[0])   # 最近的下方支撑带
    return [b for i, b in enumerate(bands) if i in picked]


def judge_context(records, bars, strokes, segs, pivs, top_divs, bot_divs,
                  div_window=DIVERGENCE_WINDOW):
    last_close = records[-1]["c"]
    last_date = records[-1]["date"]

    last_pivot = pivs[-1] if pivs else None
    if last_pivot:
        if last_close > last_pivot["ZG"]:
            pos = "above"
        elif last_close < last_pivot["ZD"]:
            pos = "below"
        else:
            pos = "inside"
    else:
        pos = "unknown"

    # 走势类型：优先看中枢迁移，其次看最近一段方向
    if len(pivs) >= 2:
        p1, p2 = pivs[-2], pivs[-1]
        if p2["ZG"] > p1["ZG"] and p2["ZD"] > p1["ZD"]:
            direction = "up"
        elif p2["ZG"] < p1["ZG"] and p2["ZD"] < p1["ZD"]:
            direction = "down"
        else:
            direction = "range"
    elif len(pivs) == 1:
        if pos == "inside":
            direction = "range"
        else:
            direction = "up" if last_close > pivs[-1]["ZG"] else "down"
    elif segs:
        direction = "up" if segs[-1]["dir"] == "up" else "down"
    else:
        direction = "unknown"

    # 最近的背驰信号，并判断是否仍在观察窗口内
    all_divs = sorted(top_divs + bot_divs, key=lambda d: d["idx"])
    recent_div, div_state = None, "none"
    for d in reversed(all_divs):
        if d["type"] in ("顶背驰", "底背驰"):
            recent_div = d
            if len(bars) - 1 - d["idx"] <= div_window:
                div_state = "top" if d["kind"] == "top" else "bottom"
            break

    # 最近的「背驰迹象」（面积比在阈值附近但未达成立标准）——属动能衰减线索，
    # 不能作为买点依据，但不应在统合与报告中丢失，故单独记录、不参与信号判定。
    recent_hint = next((d for d in reversed(all_divs) if d["type"] == "背驰迹象"), None)

    signal = judge_signal(last_close, last_pivot, pos, div_state, strokes)

    # 当前强弱：直接由「价格相对最近中枢的位置」决定，比中枢迁移更贴近当下
    if pos == "above":
        bias = "up"
    elif pos == "below":
        bias = "down"
    else:
        bias = "range"

    current_leg = segs[-1]["dir"] if segs else "unknown"

    pivot_bands = build_pivot_bands(bars, pivs, last_close)

    return {
        "last_close": round(last_close, 2),
        "last_bar_date": last_date,
        "direction": direction,
        "bias": bias,
        "current_leg": current_leg,
        "pivot_position": pos,
        "last_pivot": None if not last_pivot else {
            "from": bars[last_pivot["start_idx"]]["date"],
            "to": bars[last_pivot["end_idx"]]["date"],
            "ZG": round(last_pivot["ZG"], 2),
            "ZD": round(last_pivot["ZD"], 2),
            "extend": last_pivot["extend"],
        },
        "recent_divergence": None if not recent_div else {
            "kind": recent_div["kind"],
            "type": recent_div["type"],
            "date": bars[recent_div["idx"]]["date"],
            "price": round(recent_div["price"], 2),
            "prev_date": bars[recent_div["prev_idx"]]["date"],
            "prev_price": round(recent_div["prev_price"], 2),
            "area_ratio": round(recent_div["area"] / recent_div["prev_area"], 3)
            if recent_div["prev_area"] else None,
            "active": div_state != "none",
        },
        "signal": signal,
        "bars_after_last_divergence": None if not recent_div else len(bars) - 1 - recent_div["idx"],
        "recent_divergence_hint": None if not recent_hint else {
            "kind": recent_hint["kind"],
            "date": bars[recent_hint["idx"]]["date"],
            "price": round(recent_hint["price"], 2),
            "prev_date": bars[recent_hint["prev_idx"]]["date"],
            "prev_price": round(recent_hint["prev_price"], 2),
            "area_ratio": round(recent_hint["area"] / recent_hint["prev_area"], 3)
            if recent_hint["prev_area"] else None,
            "bars_after": len(bars) - 1 - recent_hint["idx"],
            "in_window": len(bars) - 1 - recent_hint["idx"] <= div_window,
        },
        "divergence_window_bars": div_window,
        "pivot_bands": pivot_bands,
        "nearby_pivots": pick_nearby_bands(pivot_bands),
    }


def judge_signal(last_close, last_pivot, pos, div_state, strokes):
    """买卖点启发式判定。返回 dict(type/confidence/basis/invalidation)。"""
    last_stroke = strokes[-1] if strokes else None

    if last_pivot and last_stroke:
        ZG, ZD = last_pivot["ZG"], last_pivot["ZD"]
        if (last_stroke["type"] == "B" and last_stroke["price"] > ZG
                and last_close > ZG):
            return {
                "type": "3买",
                "confidence": "中",
                "basis": f"回抽低点 {last_stroke['price']:.2f} 未回到中枢上沿 ZG={ZG:.2f}",
                "invalidation": f"跌回中枢（收盘价低于 {ZG:.2f}）则 3 买失效",
            }
        if (last_stroke["type"] == "T" and last_stroke["price"] < ZD
                and last_close < ZD):
            return {
                "type": "3卖",
                "confidence": "中",
                "basis": f"反抽高点 {last_stroke['price']:.2f} 未回到中枢下沿 ZD={ZD:.2f}",
                "invalidation": f"重回中枢（收盘价高于 {ZD:.2f}）则 3 卖失效",
            }

    if div_state == "bottom" and pos == "below":
        return {
            "type": "中枢下方 · 底背驰预警",
            "confidence": "中",
            "basis": "价格仍在中枢之下（偏弱），但已出现底背驰，下跌动能衰减；"
                     "需次级别同向背驰确认后才可视为转折",
            "invalidation": "创新低且 MACD 柱面积同步放大则背驰被破坏",
        }
    if div_state == "top" and pos == "above":
        warn = (f"跌破中枢上沿 {last_pivot['ZG']:.2f} 则转为震荡"
                if last_pivot else "跌破中枢后转为震荡")
        return {
            "type": "中枢上方 · 顶背驰预警",
            "confidence": "中",
            "basis": "价格仍在中枢之上（偏强），但已出现顶背驰，上涨动能衰减；"
                     "属持仓者的减仓预警，而非立即做空信号",
            "invalidation": "创新高且 MACD 柱面积同步放大则背驰失效；" + warn,
        }

    if div_state == "bottom":
        return {
            "type": "1买区域",
            "confidence": "中",
            "basis": "出现底背驰，下跌动能衰减；需次级别同向背驰确认",
            "invalidation": "创新低且 MACD 柱面积同步放大则背驰被破坏",
        }
    if div_state == "top":
        return {
            "type": "1卖区域",
            "confidence": "中",
            "basis": "出现顶背驰，上涨动能衰减；需次级别同向背驰确认",
            "invalidation": "创新高且 MACD 柱面积同步放大则背驰被破坏",
        }

    if pos == "inside":
        return {
            "type": "无明确买卖点",
            "confidence": "—",
            "basis": "价格运行于中枢区间内部，属中枢震荡",
            "invalidation": "等待脱离中枢（突破 ZG 或跌破 ZD）后再判断",
        }
    if pos == "above":
        return {
            "type": "中枢上方运行",
            "confidence": "—",
            "basis": "价格位于中枢之上但尚未出现回抽买点",
            "invalidation": "回落进入中枢则转为震荡",
        }
    if pos == "below":
        return {
            "type": "中枢下方运行",
            "confidence": "—",
            "basis": "价格位于中枢之下，属弱势区域",
            "invalidation": "重新站上中枢下沿则弱势缓解",
        }
    return {"type": "结构不足", "confidence": "—",
            "basis": "K 线根数不足，未能形成有效中枢与笔段结构",
            "invalidation": "—"}


def _span_days(d1, d2):
    """两个时间戳之间的自然日跨度（供窗口对齐使用）。"""
    try:
        a = datetime.strptime(str(d1)[:10], "%Y-%m-%d").date()
        b = datetime.strptime(str(d2)[:10], "%Y-%m-%d").date()
        return (b - a).days
    except ValueError:
        return None


def may_be_partial(level, last_date):
    """最后一根 K 线是否可能尚未收盘。

    盘中运行时，三个级别的最新一根都可能仍在形成：
      - 周线：最后一根落在本周内（含今天）即未收盘
      - 日线 / 30 分钟：最后一根落在今天即未收盘
    （30 分钟的时间戳形如 "2026-09-14 10:00"，取前 10 位做日期比较）
    """
    try:
        d = datetime.strptime(str(last_date)[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    today = date.today()
    if level == "week":
        return (today - d).days <= 4
    if level in ("day", "m30"):
        return d == today
    return False


# ========== 10. 主流程 ==========
def main():
    args = parse_args()
    workdir = args.workdir or os.getcwd()
    os.chdir(workdir)
    level = args.level
    meta = LEVEL_META[level]

    in_file = args.input or (f"kline_{level}.json" if os.path.exists(f"kline_{level}.json")
                             else "kline_latest.json")
    out_file = args.output or f"chan_analysis_{level}.json"

    if not os.path.exists(in_file):
        print(f"❌ 未找到 K 线文件: {in_file}")
        sys.exit(1)

    print(f"级别: {meta['zh']} ({level})")
    print(f"数据源: {in_file}")

    records = load_records(in_file)
    if len(records) < 20:
        print(f"❌ K 线仅 {len(records)} 根，不足以进行结构识别（至少 20 根）")
        sys.exit(1)
    print(f"原始 K 线: {len(records)} 根  {records[0]['date']} → {records[-1]['date']}")

    div_window = LEVEL_META[level].get("div_window", DIVERGENCE_WINDOW)
    print(f"背驰有效期口径: {div_window} 根合并 K 线（该级别专属）")

    hist = compute_macd(records)

    bars = merge_inclusion(records)
    print(f"包含处理后: {len(bars)} 根（合并掉 {len(records) - len(bars)} 根）")

    tops, bots = find_fractals(bars)
    strokes = build_strokes(tops, bots, bars, min_gap=args.min_gap)
    attach_stroke_area(strokes, bars, hist)
    segs = build_segments(strokes)
    pivs = find_pivots(segs)
    top_divs = check_divs(strokes, "top")
    bot_divs = check_divs(strokes, "bottom")
    ctx = judge_context(records, bars, strokes, segs, pivs, top_divs, bot_divs,
                        div_window=div_window)

    # ---------- 窗口体检（窗口取舍原则的量化落地）----------
    def assess_window(n_kline, n_pivot):
        lo_p, hi_p = PIVOT_COUNT_IDEAL
        lo_k, hi_k = KLINE_COUNT_IDEAL
        if n_pivot < 3:
            return "样本偏薄", (f"仅 {n_pivot} 个中枢，不足以构成「至少 2 个完整中枢 + "
                              f"1 个前中枢」的最小分析窗口，位置判断的可靠性下降")
        if n_pivot > 12:
            return "样本过密", (f"共 {n_pivot} 个中枢，远超「最近中枢」的有效参照范围"
                              f"（理想 {lo_p}-{hi_p} 个）；更早的中枢对当下走势已无约束力，"
                              f"其作用只剩供给/支撑带，应在报告中单独列出而非纳入级别定性")
        if n_kline < lo_k:
            return "窗口偏短", (f"{n_kline} 根 K 线低于理想下限 {lo_k} 根，"
                              f"结构可能尚未展开完整")
        if n_kline > hi_k:
            return "窗口偏长", (f"{n_kline} 根 K 线高于理想上限 {hi_k} 根，"
                              f"图表渲染会被压扁、远期结构会稀释最近中枢的参照权重；"
                              f"建议按「结构密度对齐」收窄窗口")
        return "结构充分", (f"{n_kline} 根 K 线 / {n_pivot} 个中枢，落在理想区间内")

    win_verdict, win_note = assess_window(len(records), len(pivs))

    # ---------- 控制台摘要 ----------
    print(f"\n=== {meta['zh']}缠论结构 ===")
    print(f"最新收盘: {ctx['last_close']}（{ctx['last_bar_date']}）")
    print(f"分型: 顶 {len(tops)} / 底 {len(bots)}   笔: {len(strokes)}   段: {len(segs)}   中枢: {len(pivs)}")
    print(f"走势类型: {ctx['direction']}   当前强弱: {ctx['bias']}"
          f"   位置: {ctx['pivot_position']}   最近一段: {ctx['current_leg']}")
    if ctx["last_pivot"]:
        lp = ctx["last_pivot"]
        print(f"最近中枢: {lp['from']} → {lp['to']}  ZD={lp['ZD']} ZG={lp['ZG']} 延伸{lp['extend']}段")
    print(f"买卖点判定: {ctx['signal']['type']}（{ctx['signal']['basis']}）")
    if ctx["recent_divergence"]:
        rd = ctx["recent_divergence"]
        print(f"最近背驰: {rd['date']} {rd['type']} @ {rd['price']}"
              f"（面积比 {rd['area_ratio']}，{'有效' if rd['active'] else '已过期'}）")

    print("\n最近 8 笔:")
    for s in strokes[-8:]:
        print(f"   {bars[s['idx']]['date']}  {s['type']}  {s['price']:.2f}  area={s.get('area', 0):.2f}")
    print("\n最近 3 个中枢:")
    for p in pivs[-3:]:
        print(f"   {bars[p['start_idx']]['date']} → {bars[p['end_idx']]['date']}"
              f"  ZD={p['ZD']:.2f} ZG={p['ZG']:.2f} ({p['amp_pct']}%)")

    nearby = ctx["nearby_pivots"]
    if nearby:
        print(f"\n与现价相关的中枢带（{NEARBY_BAND_PCT:.0f}% 内，含最近中枢之外的旧中枢）:")
        for b in nearby:
            print(f"   [{b['role']}] {b['from']} → {b['to']}  "
                  f"ZD={b['ZD']} ZG={b['ZG']}  距现价 {b['dist_pct']:+.2f}%")

    print(f"\n窗口体检: {win_verdict}")
    print(f"   {win_note}")

    # ---------- 导出 JSON ----------
    out = {
        "level": level,
        "level_label": meta["zh"],
        "level_role": meta["role"],
        "summary": {
            "symbol": "current stock",
            "last_close": ctx["last_close"],
            "last_bar_date": ctx["last_bar_date"],
            "data_range": [records[0]["date"], records[-1]["date"]],
            "kline_count": len(records),
            "merged_count": len(bars),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "may_be_partial": may_be_partial(level, ctx["last_bar_date"]),
            "data_span_days": _span_days(records[0]["date"], records[-1]["date"]),
            "divergence_window_bars": div_window,
            "pivots_total": len(pivs),
            "pivots_ideal": list(PIVOT_COUNT_IDEAL),
            "kline_ideal": list(KLINE_COUNT_IDEAL),
            "window_verdict": win_verdict,
            "window_note": win_note,
        },
        "fractals": {"tops": len(tops), "bots": len(bots)},
        "strokes_total": len(strokes),
        "segments_total": len(segs),
        "pivots_total": len(pivs),
        "context": ctx,
        "recent_strokes": [
            {"date": bars[s["idx"]]["date"], "type": s["type"],
             "price": round(s["price"], 2), "area": s.get("area")}
            for s in strokes[-15:]
        ],
        "recent_segments": [
            {
                "from": bars[s["start_idx"]]["date"],
                "to": bars[s["end_idx"]]["date"],
                "dir": s["dir"],
                "low": round(s["lo"], 2),
                "high": round(s["hi"], 2),
                "amp_pct": round((s["hi"] - s["lo"]) / s["lo"] * 100, 2),
            } for s in segs[-8:]
        ],
        "recent_pivots": [
            {
                "from": bars[p["start_idx"]]["date"],
                "to": bars[p["end_idx"]]["date"],
                "ZD": round(p["ZD"], 2),
                "ZG": round(p["ZG"], 2),
                "range_pct": p["amp_pct"],
                "extend": p["extend"],
                "next_dir": p["last_dir"],
            } for p in pivs[-5:]
        ],
        "all_pivots": [
            {
                "from": bars[p["start_idx"]]["date"],
                "to": bars[p["end_idx"]]["date"],
                "ZD": round(p["ZD"], 2),
                "ZG": round(p["ZG"], 2),
            } for p in pivs
        ],
        "top_divergences": [
            {
                "date": bars[d["idx"]]["date"], "price": round(d["price"], 2),
                "prev_date": bars[d["prev_idx"]]["date"], "prev_price": round(d["prev_price"], 2),
                "area": d["area"], "prev_area": d["prev_area"], "verdict": d["type"],
            } for d in top_divs[-5:]
        ],
        "bottom_divergences": [
            {
                "date": bars[d["idx"]]["date"], "price": round(d["price"], 2),
                "prev_date": bars[d["prev_idx"]]["date"], "prev_price": round(d["prev_price"], 2),
                "area": d["area"], "prev_area": d["prev_area"], "verdict": d["type"],
            } for d in bot_divs[-5:]
        ],
    }

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 已保存 {out_file}")

    if level == "day":
        with open("chan_analysis.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("✅ 已保存 chan_analysis.json（兼容旧流程）")


if __name__ == "__main__":
    main()
