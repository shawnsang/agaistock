#!/usr/bin/env python3
"""
缠论三级别统合分析（周线 · 日线 · 30分钟）

定位：把三个连续级别的分析结果合成一份可执行结论。
  周线 = 长期战略 → 定方向（能不能做）
  日线 = 中期战术 → 看位置（什么性质的买卖点、几成仓）
  30分 = 短期执行 → 选进出（具体在哪进、在哪止损）

三条纪律（本脚本据此实现）：
  1. 时间周期只是级别的工程近似，不是缠论严格意义上的级别。
  2. 小级别服从大级别 —— 30 分钟只做「确认器」，不独立决策。
  3. 背驰必须同级别判断；跨级别只做「区间套确认」，不做数值直接比较。

前置：先对三个级别分别跑 chan_analyze.py
  python3 chan_analyze.py . --level week
  python3 chan_analyze.py . --level day
  python3 chan_analyze.py . --level m30

用法：
  python3 chan_multi_level.py [workdir]
  python3 chan_multi_level.py [workdir] --output chan_multi_level.json

输出：chan_multi_level.json + 控制台结论
"""
import argparse
import json
import os
import sys
from datetime import datetime

NEST_WINDOW_DAYS = 10      # 次级别背驰须落在本级别背驰之后的多少自然日内，才算确认
NEST_PRICE_TOL = 0.06      # 次级别背驰极值与本级别极值的最大允许偏离（6%）

LEVELS = ["week", "day", "m30"]
LEVEL_LABEL = {"week": "周线", "day": "日线", "m30": "30分钟"}
LEVEL_ROLE = {"week": "长期战略", "day": "中期战术", "m30": "短期执行"}
BIAS_ZH = {"up": "向上", "down": "向下", "range": "震荡", "unknown": "未知"}

# 共振矩阵：周线 × 日线 × 30分钟 → (定性, 等级, 操作基调)
GRADE_ACTION = {
    "A": "可正常建仓，用足仓位上限",
    "B": "分批建仓，等短期信号确认后再加仓",
    "C": "只做短线，轻仓，目标位降一档",
    "D": "空仓观望，等待大级别转折信号",
}


def parse_args():
    p = argparse.ArgumentParser(description="缠论三级别统合分析")
    p.add_argument("workdir", nargs="?", default=None, help="工作目录，默认当前目录")
    p.add_argument("--output", default="chan_multi_level.json", help="输出文件名")
    p.add_argument("--symbol", default="", help="股票代码（写入结果，供报告使用）")
    p.add_argument("--name", default="", help="股票名称（写入结果，供报告使用）")
    return p.parse_args()


def load_level(level):
    f = f"chan_analysis_{level}.json"
    if not os.path.exists(f):
        print(f"❌ 缺少 {f}，请先运行： python3 chan_analyze.py . --level {level}")
        sys.exit(1)
    with open(f, "r", encoding="utf-8") as fh:
        return json.load(fh)


def day_of(ts):
    return str(ts)[:10]


def judge_resonance(w, d, m):
    """共振判定：按「大级别许可 → 中期位置 → 短期时机」三层顺序推断。

    第一层：周线 bias 决定「能不能做多」
      周线向上 = 许可；周线向下 = 只允许短线或观望；周线震荡 = 谨慎
    第二层：日线 bias / 买卖点决定「中期位置是否合适」
    第三层：30 分钟 bias 决定「短期时机」
    """
    wb, db, mb = w["context"]["bias"], d["context"]["bias"], m["context"]["bias"]
    dsig = d["context"]["signal"]["type"]
    label = f"周线 {BIAS_ZH[wb]} / 日线 {BIAS_ZH[db]} / 30 分钟 {BIAS_ZH[mb]}"

    # 1. 三级别同向向上 —— 最强做多环境
    if wb == "up" and db == "up" and mb == "up":
        return {
            "grade": "A", "level": "三级别共振向上",
            "detail": f"{label}，三级别同处中枢上方，方向完全一致",
            "same_direction": True, "conflict_level": None,
        }

    # 2. 三级别同向向下 —— 最弱环境
    if wb == "down" and db == "down" and mb == "down":
        return {
            "grade": "D", "level": "三级别共振向下",
            "detail": f"{label}，三级别同时处于中枢下方，弱势共振",
            "same_direction": True, "conflict_level": None,
        }

    # 3. 周线向下 + 30 分钟走强 —— 只能定性为反弹
    if wb == "down" and mb == "up":
        return {
            "grade": "C", "level": "周线向下 · 小级别反弹",
            "detail": f"{label}，大级别方向未转，30 分钟走强只构成反弹",
            "same_direction": False, "conflict_level": "week_vs_m30",
        }

    # 4. 周线向上 + 30 分钟回调 —— 潜在加仓窗口
    if wb == "up" and mb == "down":
        return {
            "grade": "B", "level": "周线向上 · 小级别回调",
            "detail": f"{label}，大级别方向向上，30 分钟回撤是潜在加仓窗口",
            "same_direction": False, "conflict_level": "week_vs_m30",
        }

    # 5. 大级别许可 + 短期同向，但中期仍在中枢内震荡 —— 待突破
    if wb == "up" and mb == "up" and db == "range":
        return {
            "grade": "B", "level": "周线向上 · 中期震荡待突破",
            "detail": f"{label}，大级别已许可做多，但日线尚未脱离中枢，"
                      f"中期位置（{dsig}）不够清晰",
            "same_direction": False, "conflict_level": "day_undecided",
        }

    # 6. 大级别许可 + 中期向上，短期震荡 —— 等短期给信号
    if wb == "up" and db == "up" and mb == "range":
        return {
            "grade": "B", "level": "周线向上 · 中期向上 · 短期震荡",
            "detail": f"{label}，中长期方向一致，等待 30 分钟选出方向",
            "same_direction": False, "conflict_level": "m30_undecided",
        }

    # 7. 周线震荡 + 中短期向上 —— 中性偏多
    if wb == "range" and db == "up" and mb == "up":
        return {
            "grade": "B", "level": "周线震荡 · 中短期向上",
            "detail": f"{label}，大级别无明确方向，中短期走强但缺少大级别背书",
            "same_direction": False, "conflict_level": "week_undecided",
        }

    # 8. 周线向下 + 中期向上 —— 逆大级别的中期反弹，风险偏高
    if wb == "down" and db == "up":
        return {
            "grade": "C", "level": "周线向下 · 中期反弹",
            "detail": f"{label}，中期走强但大级别未转，反弹级别对待",
            "same_direction": False, "conflict_level": "week_vs_day",
        }

    return {
        "grade": "C", "level": "级别交错",
        "detail": f"{label}，三级别方向不一致，以日线（{dsig}）为决策基准",
        "same_direction": False, "conflict_level": "mixed",
    }


def _parse_date(ts):
    try:
        return datetime.strptime(day_of(ts), "%Y-%m-%d")
    except ValueError:
        return None


def _norm_date(ts):
    return str(ts)[:10]


def judge_nesting(upper, sub, upper_label="日线", sub_label="30 分钟"):
    """区间套确认：本级别（upper）的背驰，是否得到次级别（sub）同向背驰的确认。

    确认成立需要同时满足五个条件：
      0. 本级别背驰锚点必须落在次级别的数据窗口之内（否则无从确认）
      1. 方向同向（同为顶背驰或同为底背驰）
      2. 次级别背驰发生在本级别背驰【之后】
      3. 时间邻近：落在 NEST_WINDOW_DAYS 个自然日内
      4. 价格邻近：极值偏离不超过 NEST_PRICE_TOL
    只有同向、同时、同位，才说明是同一个转折点的次级别确认；
    否则只是次级别一次独立的短期信号，不能用来确认本级别转折。

    注意：这是跨级别的「确认」关系，不是把两个级别的 MACD 数值拿来直接比大小。
    """
    dd = upper["context"]["recent_divergence"]
    md = sub["context"]["recent_divergence"]
    label = {"top": "顶背驰", "bottom": "底背驰"}
    ub = f"本级别（{upper_label}）"
    sb = f"次级别（{sub_label}）"

    if not dd or dd["kind"] not in ("top", "bottom"):
        extra = ""
        if md and md["active"]:
            extra = (f"；但{sb}当前存在有效{label[md['kind']]}"
                     f"（{md['date']} @ {md['price']}）—— 按纪律二，小级别只能确认、"
                     f"不能独立决策，该信号仅支持短线反弹，不足以定性为{upper_label}级别的转折")
        return {
            "verdict": "not_applicable",
            "text": f"{upper_label}级别当前没有可供确认的背驰信号" + extra,
            "upper": None, "sub": None,
        }

    payload_upper = {
        "kind": dd["kind"], "type": dd["type"], "date": dd["date"],
        "price": dd["price"], "active": dd["active"], "area_ratio": dd["area_ratio"],
    }

    # 条件 0：窗口前提。本级别背驰若早于次级别的数据起点，次级别根本"看不见"它，
    # 此时任何"已确认 / 未确认"的读数都是伪结论，必须显式区分出来。
    sub_start = _norm_date(sub["summary"]["data_range"][0])
    if _norm_date(dd["date"]) < sub_start:
        return {
            "verdict": "out_of_window",
            "text": f"{upper_label}的{label[dd['kind']]}发生在 {dd['date']}，"
                    f"早于{sub_label}数据的起点 {sub_start} —— "
                    f"该背驰落在次级别的窗口之外，{sub_label}无从确认。"
                    f"它只能作为背景结构，不得据此给出可执行的多级别结论"
                    f"（需要确认请拉长{sub_label}的数据窗口，或改用更小的级别）",
            "upper": payload_upper, "sub": None,
        }

    if not dd["active"]:
        extra = ""
        if md and md["kind"] == dd["kind"]:
            extra = f"（{sub_label}在 {md['date']} 另有同向背驰，但那是次级别独立信号，不能追溯确认本级别）"
        elif md and md["active"]:
            extra = (f"；但{sb}当前存在有效{label[md['kind']]}"
                     f"（{md['date']} @ {md['price']}），而本级别并无同向背驰可供确认 —— "
                     f"按纪律二，小级别只能确认、不能独立决策，该信号仅支持短线反弹，"
                     f"不足以定性为{upper_label}级别的转折")
        return {
            "verdict": "stale",
            "text": f"{upper_label}曾出现{label[dd['kind']]}（{dd['date']} @ {dd['price']}），"
                    f"但已超出观察窗口，当前不构成有效信号{extra}",
            "upper": payload_upper, "sub": None,
        }

    if not md or md["kind"] != dd["kind"]:
        return {
            "verdict": "unconfirmed",
            "text": f"{upper_label}出现{label[dd['kind']]}（{dd['date']} @ {dd['price']}），"
                    f"但{sub_label}尚未出现同向背驰 —— 信号未获次级别确认，建议等待",
            "upper": payload_upper, "sub": None,
        }

    payload_sub = {
        "kind": md["kind"], "type": md["type"], "date": md["date"],
        "price": md["price"], "active": md["active"], "area_ratio": md["area_ratio"],
    }

    d_upper, d_sub = _parse_date(dd["date"]), _parse_date(md["date"])
    gap = (d_sub - d_upper).days if (d_upper and d_sub) else None
    dev = abs(md["price"] - dd["price"]) / dd["price"] if dd["price"] else None

    if gap is not None and gap < 0:
        return {
            "verdict": "unconfirmed",
            "text": f"{sub_label}的{label[md['kind']]}（{md['date']}）发生在{upper_label}信号"
                    f"（{dd['date']}）之前，无法用于确认当前{upper_label}信号",
            "upper": payload_upper, "sub": payload_sub,
        }

    if gap is not None and gap > NEST_WINDOW_DAYS:
        return {
            "verdict": "unconfirmed",
            "text": f"{sub_label}的同向背驰出现在{upper_label}信号之后 {gap} 个自然日，"
                    f"超出 {NEST_WINDOW_DAYS} 日确认窗口，属于次级别独立信号，"
                    f"不能追溯确认本级别转折",
            "upper": payload_upper, "sub": payload_sub,
        }

    if dev is not None and dev > NEST_PRICE_TOL:
        return {
            "verdict": "unconfirmed",
            "text": f"{sub_label}背驰极值（{md['price']}）与{upper_label}极值（{dd['price']}）"
                    f"偏离 {dev * 100:.1f}%，超出 {NEST_PRICE_TOL * 100:.0f}% 容差，"
                    f"两者不是同一个转折点",
            "upper": payload_upper, "sub": payload_sub,
        }

    if not md["active"]:
        return {
            "verdict": "partial",
            "text": f"{sub_label}曾在 {md['date']}（@ {md['price']}）出现同向背驰，"
                    f"时间与价位均可对应{upper_label}信号，但已超出观察窗口，确认力度衰减",
            "upper": payload_upper, "sub": payload_sub,
        }

    return {
        "verdict": "confirmed",
        "text": f"{upper_label}{label[dd['kind']]}（{dd['date']} @ {dd['price']}）"
                f"已由{sub_label}同向背驰（{md['date']} @ {md['price']}，"
                f"间隔 {gap} 日、偏离 {dev * 100:.1f}%）确认，转折概率提升",
        "upper": payload_upper, "sub": payload_sub,
    }


def judge_window_alignment(levels):
    """窗口对齐体检：三个级别的数据窗口是否落在可比的「结构密度」上。

    窗口取舍原则（详见 SKILL.md）：
      识别规则（包含处理/分型/笔/段）是尺度不变的，识别出一个中枢所需的
      K 线根数在各级别基本相同（约 45-75 根）。因此要让三个级别"看到可比数量的
      结构"，三级别的窗口根数就该落在同一量级（250-600 根），而不是让自然时间
      跨度随便拉开。跨度失衡的真实代价有两个：
        (a) 结构密度失衡 —— 某级别中枢数是别的级别的两倍以上，买卖点会泛滥，
            区间套的"确认"门槛被拉低；
        (b) 区间套锚点越界 —— 上游级别的背驰若早于下游级别窗口的起点，
            下游根本无从确认，任何 confirmed/unconfirmed 都是伪结论。
    """
    meta, starts, ends = {}, [], []
    for lv in LEVELS:
        s = levels[lv]["summary"]
        rng_ = s["data_range"]
        meta[lv] = {
            "label": LEVEL_LABEL[lv],
            "role": LEVEL_ROLE[lv],
            "data_range": rng_,
            "span_days": s.get("data_span_days"),
            "kline_count": s.get("kline_count"),
            "pivots_total": levels[lv]["pivots_total"],
            "strokes_total": levels[lv]["strokes_total"],
            "divergence_window_bars": s.get("divergence_window_bars"),
            "window_verdict": s.get("window_verdict"),
            "window_note": s.get("window_note"),
        }
        starts.append(_norm_date(rng_[0]))
        ends.append(_norm_date(rng_[1]))

    common_from, common_to = max(starts), min(ends)
    span = None
    try:
        span = (datetime.strptime(common_to, "%Y-%m-%d")
                - datetime.strptime(common_from, "%Y-%m-%d")).days
    except ValueError:
        pass

    # 结构密度均衡度：中枢个数之比 —— 识别规则尺度不变，理想情况下三级别应接近
    piv = {lv: meta[lv]["pivots_total"] for lv in LEVELS}
    lo_lv = min(piv, key=lambda k: piv[k])
    hi_lv = max(piv, key=lambda k: piv[k])
    ratio = (piv[hi_lv] / piv[lo_lv]) if piv[lo_lv] else None
    if ratio is None:
        balance, balance_note = "unknown", "中枢样本不足，无法评估密度均衡度"
    elif ratio <= 1.6:
        balance = "balanced"
        balance_note = (f"三级别中枢数量接近（{piv['week']} / {piv['day']} / {piv['m30']}），"
                        f"结构密度可比，区间套的跨级别比较成立")
    elif ratio <= 2.5:
        balance = "slightly_off"
        balance_note = (f"三级别中枢数量为 {piv['week']} / {piv['day']} / {piv['m30']}，"
                        f"{LEVEL_LABEL[hi_lv]}偏密（为 {LEVEL_LABEL[lo_lv]}的 {ratio:.1f} 倍），"
                        f"读{LEVEL_LABEL[hi_lv]}的买卖点时需更严格地要求"
                        f"「锚定中枢贴近现价」")
    else:
        balance = "off"
        balance_note = (f"三级别中枢数量为 {piv['week']} / {piv['day']} / {piv['m30']}，"
                        f"{LEVEL_LABEL[hi_lv]}的结构密度约为 {LEVEL_LABEL[lo_lv]} 的 "
                        f"{ratio:.1f} 倍，跨级别结构不可比 —— 建议收窄"
                        f"{LEVEL_LABEL[hi_lv]}的窗口根数，使之与其他级别落在同一量级")

    over = [LEVEL_LABEL[lv] for lv in LEVELS if meta[lv]["window_verdict"] == "窗口偏长"]
    thin = [LEVEL_LABEL[lv] for lv in LEVELS if meta[lv]["window_verdict"] in ("样本偏薄", "窗口偏短")]

    return {
        "common_window": {"from": common_from, "to": common_to, "span_days": span},
        "levels": meta,
        "density_balance": balance,
        "density_ratio": round(ratio, 2) if ratio else None,
        "density_note": balance_note,
        "over_wide_levels": over,
        "thin_levels": thin,
        "principle": ("取舍单位是「中枢个数」而非自然时间跨度：每级别理想 4-8 个中枢，"
                      "约合 250-600 根 K 线。窗口下界＝当前未完成走势的起点＋至少 2 个"
                      "完整中枢＋1 个前中枢（供背驰比较）；上界＝再多也只是压扁图表、"
                      "稀释最近中枢的参照权重，边际收益为零。"),
        "rule": ("区间套只在三级别共同覆盖的区间内成立；"
                 "落在共同区间之外的背驰只能定性为背景结构，不得作为可执行结论的依据。"),
    }


def judge_action(res, nesting, w, d, m):
    """综合共振档位与区间套结论，给出操作定性与失效条件。"""
    grade = res["grade"]
    day_sig = d["context"]["signal"]
    m30_sig = m["context"]["signal"]
    action = {
        "grade": grade,
        "tone": GRADE_ACTION[grade],
        "day_signal": day_sig["type"],
        "m30_signal": m30_sig["type"],
        "notes": [],
        "invalidation": [],
    }

    if grade == "A":
        action["notes"].append("三级别同向，是本框架里确定性最高的做多环境")
        if day_sig["type"] == "3买" and m30_sig["type"] == "3买":
            action["notes"].append("日线与 30 分钟同时给出 3 买，回抽不破中枢上沿，"
                                   "属于缠论中风险收益比较好的介入点")
    elif grade == "B":
        action["notes"].append(f"大级别方向已许可做多（{res['level']}），"
                               f"限制项在中等或较小级别，尚不构成趋势反转")
        action["notes"].append("等 30 分钟出现底背驰或 3 买再介入，不要在下跌途中接")
        if res["conflict_level"] == "day_undecided":
            action["notes"].append("日线仍在最近中枢内震荡，中期位置不清晰，"
                                   "建议只做试探仓，等日线脱离中枢再加")
    elif grade == "C":
        action["notes"].append("大级别方向未转，任何买点都只能按反弹对待")
        action["notes"].append("严格轻仓、快进快出，不设长期持有预期")
    else:
        action["notes"].append("三级别同向向下，此时任何买点胜率都偏低")
        action["notes"].append("等待周线级别出现底背驰（大级别转折预警）再评估")

    if nesting["verdict"] == "unconfirmed":
        action["notes"].append("区间套未确认：本级别信号缺少次级别同向背驰的支撑")
        action["invalidation"].append("本级别信号在次级别未确认前，不构成可执行信号")
    elif nesting["verdict"] == "confirmed":
        action["notes"].append("区间套已确认：本级别与次级别同向、同时、同位背驰，可提高信号权重")
    elif nesting["verdict"] == "partial":
        action["notes"].append("区间套部分确认：次级别背驰已超出观察窗口，"
                               "信号权重不宜放大")
    elif nesting["verdict"] == "out_of_window":
        action["notes"].append("区间套锚点落在次级别数据窗口之外，本级别背驰无法被"
                               "次级别印证 —— 该背驰只能作背景，不得据以给出多级别结论")
        action["invalidation"].append("本级别背驰在次级别窗口之外，未获确认，不构成可执行信号")
    elif nesting["verdict"] == "stale":
        action["notes"].append("此前本级别出现过的背驰信号已超出观察窗口，"
                               "当前应以最新结构（中枢位置与买卖点）为准，不要沿用旧信号")

    if day_sig.get("invalidation") and day_sig["invalidation"] != "—":
        action["invalidation"].append(f"日线信号失效条件：{day_sig['invalidation']}")
    if m30_sig.get("invalidation") and m30_sig["invalidation"] != "—":
        action["invalidation"].append(f"30 分钟信号失效条件：{m30_sig['invalidation']}")

    return action


def collect_key_levels(levels):
    """三级别关键价位：中枢上下沿 + 最近背驰极值 + 供给/支撑带。"""
    out = []
    for lv in LEVELS:
        data = levels[lv]
        ctx = data["context"]
        lp = ctx.get("last_pivot")
        div = ctx.get("recent_divergence")
        entry = {
            "level": lv,
            "level_label": LEVEL_LABEL[lv],
            "role": LEVEL_ROLE[lv],
            "last_close": ctx["last_close"],
            "position": ctx["pivot_position"],
            "bias": ctx["bias"],
            "pivot": None,
            "divergence_extreme": None,
            "bands": ctx.get("nearby_pivots", []),
        }
        if lp:
            entry["pivot"] = {
                "from": lp["from"], "to": lp["to"],
                "ZG": lp["ZG"], "ZD": lp["ZD"],
                "extend": lp["extend"],
            }
        if div:
            entry["divergence_extreme"] = {
                "kind": div["kind"], "date": div["date"], "price": div["price"],
                "active": div["active"],
            }
        out.append(entry)
    return out


def build_narrative(res, nesting, action, levels, w, d, m):
    """一句话统合结论。"""
    sym = "该标的"
    end = levels["m30"]["context"]["last_close"]
    parts = [
        f"{sym}当前收盘 {end}。",
        f"长期看，周线处于{BIAS_ZH[w['context']['bias']]}状态（{w['context']['signal']['type']}）；",
        f"中期看，日线处于{BIAS_ZH[d['context']['bias']]}状态，"
        f"买卖点判定为「{d['context']['signal']['type']}」；",
        f"短期看，30 分钟处于{BIAS_ZH[m['context']['bias']]}状态。",
        f"三级别合成为「{res['level']}」，{action['tone']}。",
    ]
    return "".join(parts)


def main():
    args = parse_args()
    workdir = args.workdir or os.getcwd()
    os.chdir(workdir)

    levels = {lv: load_level(lv) for lv in LEVELS}
    w, d, m = levels["week"], levels["day"], levels["m30"]

    res = judge_resonance(w, d, m)
    nesting = judge_nesting(d, m, "日线", "30 分钟")
    nesting_wd = judge_nesting(w, d, "周线", "日线")
    window = judge_window_alignment(levels)
    action = judge_action(res, nesting, w, d, m)
    key_levels = collect_key_levels(levels)
    narrative = build_narrative(res, nesting, action, levels, w, d, m)

    caveats = []
    for lv in LEVELS:
        s = levels[lv]["summary"]
        if s.get("may_be_partial"):
            caveats.append(
                f"{LEVEL_LABEL[lv]}最后一根 K 线（{s['last_bar_date']}）可能尚未收盘，"
                f"该级别结构存在变动可能")
    for lv in LEVELS:
        if levels[lv]["pivots_total"] < 2:
            caveats.append(
                f"{LEVEL_LABEL[lv]}仅识别出 {levels[lv]['pivots_total']} 个中枢，"
                f"结构样本偏少，位置判断的可靠性下降")
    # 窗口与结构密度体检
    if window["over_wide_levels"]:
        caveats.append(
            f"窗口偏长：{'、'.join(window['over_wide_levels'])}的数据根数超出理想区间"
            f"（250-600 根），图表会被压扁、远期结构会稀释最近中枢的参照权重；"
            f"该类级别的早期中枢只应作背景，不参与级别定性")
    if window["thin_levels"]:
        caveats.append(
            f"窗口偏薄：{'、'.join(window['thin_levels'])}的结构样本不足，"
            f"位置判断可靠性下降")
    if window["density_balance"] in ("off", "slightly_off"):
        caveats.append(f"结构密度{'失衡' if window['density_balance'] == 'off' else '略有偏差'}："
                       f"{window['density_note']}")
    if nesting["verdict"] == "out_of_window":
        caveats.append(
            f"区间套锚点越界：{nesting['text']}")
    if nesting_wd["verdict"] == "out_of_window":
        caveats.append(
            f"周线→日线区间套锚点越界：{nesting_wd['text']}")
    for lv in LEVELS:
        hint = levels[lv]["context"].get("recent_divergence_hint")
        if hint and hint.get("in_window"):
            kind_zh = "底" if hint["kind"] == "bottom" else "顶"
            caveats.append(
                f"{LEVEL_LABEL[lv]}在 {hint['date']} @ {hint['price']} 出现{kind_zh}背驰的"
                f"「迹象」（面积比 {hint['area_ratio']}，位于阈值附近但未达成立标准），"
                f"属动能衰减线索、不足以单独构成买卖点依据，应结合次级别同向信号判断")
    # 顶背驰（减仓预警）方向偏空，可能与共振等级的默认操作表述冲突，须显式提示
    for lv in LEVELS:
        stype = levels[lv]["context"]["signal"].get("type", "")
        if "顶背驰" in stype:
            caveats.append(
                f"{LEVEL_LABEL[lv]}的买卖点为「{stype}」——顶背驰是上涨动能衰减的"
                f"减仓预警，方向偏空，与本级别「当前强弱 / 位置」的读数方向相反；"
                f"若共振等级给出的操作表述偏多（如「分批建仓」），须先辨析这一冲突，"
                f"按纪律二不得由更小级别的买点推翻大级别预警")
    caveats.append("三个级别的 K 线更新时点不同，跨级别比较时以日线收盘为基准时点最稳妥")

    out = {
        "symbol": args.symbol,
        "name": args.name,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "framework": {
            "week": "长期战略 · 定方向",
            "day": "中期战术 · 看位置",
            "m30": "短期执行 · 选进出",
            "discipline": [
                "时间周期是级别的工程近似，不等同于缠论严格的递归级别",
                "小级别服从大级别，30 分钟只做确认器，不独立决策",
                "背驰必须同级别判断，跨级别只做区间套确认",
                "窗口取舍以「中枢个数」为单位（每级别 4-8 个），不以自然时间跨度为单位",
                "区间套只在三级别共同覆盖的区间内成立",
            ],
        },
        "levels": {
            lv: {
                "label": LEVEL_LABEL[lv],
                "role": LEVEL_ROLE[lv],
                "last_close": levels[lv]["context"]["last_close"],
                "last_bar_date": levels[lv]["summary"]["last_bar_date"],
                "data_range": levels[lv]["summary"]["data_range"],
                "kline_count": levels[lv]["summary"]["kline_count"],
                "bias": levels[lv]["context"]["bias"],
                "bias_zh": BIAS_ZH[levels[lv]["context"]["bias"]],
                "trend_direction": levels[lv]["context"]["direction"],
                "pivot_position": levels[lv]["context"]["pivot_position"],
                "current_leg": levels[lv]["context"]["current_leg"],
                "signal": levels[lv]["context"]["signal"]["type"],
                "signal_detail": levels[lv]["context"]["signal"],
                "pivots_total": levels[lv]["pivots_total"],
                "strokes_total": levels[lv]["strokes_total"],
                "segments_total": levels[lv]["segments_total"],
                "recent_divergence": levels[lv]["context"]["recent_divergence"],
                "divergence_hint": levels[lv]["context"].get("recent_divergence_hint"),
                "divergence_window_bars": levels[lv]["context"].get("divergence_window_bars"),
                "last_pivot": levels[lv]["context"]["last_pivot"],
                "nearby_pivots": levels[lv]["context"].get("nearby_pivots", []),
                "may_be_partial": levels[lv]["summary"].get("may_be_partial", False),
                "span_days": levels[lv]["summary"].get("data_span_days"),
                "window_verdict": levels[lv]["summary"].get("window_verdict"),
                "window_note": levels[lv]["summary"].get("window_note"),
            } for lv in LEVELS
        },
        "resonance": res,
        "interval_nesting": nesting,
        "interval_nesting_week_day": nesting_wd,
        "window_alignment": window,
        "action": action,
        "key_levels": key_levels,
        "narrative": narrative,
        "caveats": caveats,
    }

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    # ---------- 控制台结论 ----------
    print("=" * 62)
    print("缠论三级别统合分析")
    print("=" * 62)
    print(f"{'级别':<8}{'角色':<12}{'当前强弱':<10}{'走势类型':<10}{'买卖点'}")
    print("-" * 62)
    for lv in LEVELS:
        c = levels[lv]["context"]
        print(f"{LEVEL_LABEL[lv]:<8}{LEVEL_ROLE[lv]:<12}"
              f"{BIAS_ZH[c['bias']]:<10}{c['direction']:<10}{c['signal']['type']}")
    print("-" * 62)
    print(f"\n【共振判定】{res['level']}   等级 {res['grade']}")
    print(f"  {res['detail']}")
    print(f"\n【区间套确认】{nesting['verdict']}")
    print(f"  {nesting['text']}")
    print(f"\n【区间套（周线→日线）】{nesting_wd['verdict']}")
    print(f"  {nesting_wd['text']}")
    print("\n【窗口与结构密度】")
    for lv in LEVELS:
        m = window["levels"][lv]
        print(f"  {m['label']:<8}{m['data_range'][0]} → {m['data_range'][1]}"
              f"  {m['kline_count']} 根 / {m['pivots_total']} 个中枢"
              f"  背驰窗口 {m['divergence_window_bars']} 根"
              f"  [{m['window_verdict']}]")
    cw = window["common_window"]
    print(f"  共同覆盖区间: {cw['from']} → {cw['to']}"
          f"（{cw['span_days']} 个自然日）")
    print(f"  密度均衡度: {window['density_balance']}（比值 {window['density_ratio']}）")
    print(f"  {window['density_note']}")
    print(f"\n【操作定性】{action['tone']}")
    for n in action["notes"]:
        print(f"  · {n}")
    if action["invalidation"]:
        print("\n【失效条件】")
        for n in action["invalidation"]:
            print(f"  · {n}")
    print(f"\n【一句话结论】\n  {narrative}")
    print("\n【关键价位】")
    for k in key_levels:
        p = k["pivot"]
        seg = f"中枢 {p['ZD']} ~ {p['ZG']}" if p else "无有效中枢"
        dv = k["divergence_extreme"]
        dseg = f"  最近背驰极值 {dv['price']}（{dv['date']}）" if dv else ""
        print(f"  {k['level_label']:<8}{seg}{dseg}")
        for b in k.get("bands", []):
            print(f"      · [{b['role']}] {b['from']} → {b['to']}"
                  f"  {b['ZD']} ~ {b['ZG']}  距现价 {b['dist_pct']:+.2f}%")
    print("\n【注意事项】")
    for c in caveats:
        print(f"  ⚠️ {c}")

    print(f"\n✅ 已保存 {args.output}")


if __name__ == "__main__":
    main()
