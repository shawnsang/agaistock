#!/usr/bin/env python3
"""
三级别缠论报告渲染器

把 chan_multi_level.json 的结果自动填进三级别报告模板，产出可直接预览的 report.html。
机械性字段（数据卡、表格、价位、图示标注）全部自动填充；叙述性文字优先使用
chan_multi_level.json 里已经算好的结论，Agent 可在此基础上再润色。

用法：
  python3 render_multi_report.py [workdir]
  python3 render_multi_report.py [workdir] --out report.html --title "内蒙一机 · 缠论三级别分析"

前置：
  chan_analyze.py --level week / day / m30
  chan_multi_level.py

输出：report.html（含内联数据，可直接本地打开或经 server.js 预览）
"""
import argparse
import json
import os
import re
import sys

LEVELS = ["week", "day", "m30"]
LEVEL_LABEL = {"week": "周线", "day": "日线", "m30": "30分钟"}
LEVEL_ROLE = {"week": "长期战略", "day": "中期战术", "m30": "短期执行"}
BIAS_ZH = {"up": "向上", "down": "向下", "range": "震荡", "unknown": "未知"}

CARD_CLASS = {"up": "up", "down": "down", "range": "amber", "unknown": "gray"}
GRADE_CLASS = {"A": "up", "B": "amber", "C": "amber", "D": "down"}
POS_ZH = {"above": "中枢之上", "inside": "中枢之内", "below": "中枢之下", "unknown": "位置不明"}
NEST_ZH = {"confirmed": "已确认", "unconfirmed": "未确认",
           "partial": "部分确认", "not_applicable": "不适用", "stale": "已过期",
           "out_of_window": "锚点越界", "invalidated": "已作废"}
MARK_ZH = {"top": "顶背驰", "bottom": "底背驰"}
WINDOW_ZH = {"结构充分": "结构充分", "窗口偏长": "窗口偏长",
             "窗口偏短": "窗口偏短", "样本偏薄": "样本偏薄", "样本过密": "样本过密"}
BALANCE_ZH = {"balanced": "均衡", "slightly_off": "略有偏差",
              "off": "失衡", "unknown": "无法评估"}
SIDE_CLS = {"above": "up", "below": "down", "inside": "amber"}


def div_state(rd, active_word="有效"):
    """背驰状态：已作废 > 有效/已过期。

    `active` 只表示「锚点落在背驰窗口内」，不等于背驰仍然成立。
    手工复核（见 SKILL.md 纪律第 12 条）确认被破坏的，写 `invalidated: true`，
    此时必须显示「已作废」，不得沿用「有效」。
    """
    if rd.get("invalidated"):
        return "已作废"
    return active_word if rd.get("active") else "已过期"


def parse_args():
    p = argparse.ArgumentParser(description="三级别缠论报告渲染器")
    p.add_argument("workdir", nargs="?", default=None, help="工作目录，默认当前目录")
    p.add_argument("--template", default=None, help="模板路径（默认取同目录 ../templates/）")
    p.add_argument("--out", default="report.html", help="输出文件名")
    p.add_argument("--title", default=None, help="报告标题（默认 代码 名称 · 缠论三级别分析报告）")
    p.add_argument("--ma", type=int, default=20, help="均线周期")
    return p.parse_args()


def card_class(bias):
    return CARD_CLASS.get(bias, "gray")


def li_list(items):
    return "\n      ".join(f"<li>{x}</li>" for x in items) if items else "<li>—</li>"


def level_summary(lv, meta):
    """级别数据卡副文本。"""
    pos = POS_ZH.get(meta["pivot_position"], "位置不明")
    sig = meta["signal"]
    bits = [f"位置：{pos}", f"买卖点：{sig}"]
    lp = meta.get("last_pivot")
    if lp:
        bits.append(f"最近中枢 {lp['ZD']}~{lp['ZG']}")
    return " · ".join(bits)


def chart_sub(lv, meta):
    bits = [f"{meta['kline_count']} 根 K 线"]
    rd = meta.get("recent_divergence")
    if rd:
        bits.append(f"最近背驰 {rd['date']} {MARK_ZH.get(rd['kind'], '')} {rd['price']}")
    return " · ".join(bits)


def build_level_rows(levels):
    rows = []
    for lv in LEVELS:
        m = levels[lv]
        lp = m.get("last_pivot")
        pivot_txt = f"{lp['ZD']} ~ {lp['ZG']}" if lp else "—"
        rd = m.get("recent_divergence")
        if rd:
            state = div_state(rd)
            div_txt = (f"{rd['date']}<br>{MARK_ZH.get(rd['kind'], '')} @ {rd['price']}"
                       f"<br><span class=\"muted\">{state}</span>")
        else:
            div_txt = "—"
        bias_cls = {"up": "up", "down": "down", "range": "amber"}.get(m["bias"], "gray")
        rows.append(
            f'<tr><td><strong>{LEVEL_LABEL[lv]}</strong></td>'
            f'<td>{LEVEL_ROLE[lv]}</td>'
            f'<td><span class="tag {bias_cls}">{m["bias_zh"]}</span></td>'
            f'<td>{m["trend_direction"]}</td>'
            f'<td>{m["signal"]}</td>'
            f'<td>{pivot_txt}</td>'
            f'<td>{div_txt}</td></tr>'
        )
    return "\n      ".join(rows)


def build_key_level_blocks(key_levels):
    blocks = []
    for k in key_levels:
        lv = k["level"]
        p = k.get("pivot")
        lines = []
        if p:
            lines.append(f"中枢区间 ZD={p['ZD']} ～ ZG={p['ZG']}"
                         f"（{p['from']} 起，延伸 {p.get('extend', 0)} 段）")
        else:
            lines.append("该级别尚无有效中枢")
        lines.append(f"当前收盘 {k['last_close']} · 位于{POS_ZH.get(k['position'], '位置不明')}")
        dv = k.get("divergence_extreme")
        if dv:
            state = div_state(dv, active_word="仍有效")
            lines.append(f"最近{MARK_ZH.get(dv['kind'], '')}极值 {dv['price']}"
                         f"（{dv['date']}，{state}）")
        desc = " · ".join(lines[1:])
        head = lines[0]
        blocks.append(
            f'<div class="key-price {lv}">'
            f'<div class="name">{k["level_label"]} · {k["role"]} —— {head}</div>'
            f'<div class="desc">{desc}</div></div>'
        )
    return "\n  ".join(blocks)


def build_band_blocks(key_levels):
    """供给带 / 支撑带：最近中枢之外、但与现价发生重叠的历史中枢。"""
    blocks = []
    for k in key_levels:
        bands = k.get("bands") or []
        if not bands:
            continue
        lv = k["level"]
        items = []
        for b in bands:
            cls = SIDE_CLS.get(b.get("side"), "gray")
            dist = f"{b['dist_pct']:+.2f}%"
            items.append(
                f'<div class="desc" style="padding:4px 0">'
                f'<span class="tag {cls}">{b["role"]}</span> '
                f'<strong>{b["ZD"]} ~ {b["ZG"]}</strong>'
                f'（{b["from"]} → {b["to"]}，距现价 {dist}，'
                f'振幅 {b.get("amp_pct", "—")}%）</div>'
            )
        blocks.append(
            f'<div class="key-price {lv}">'
            f'<div class="name">{k["level_label"]} · {k["role"]}</div>'
            + "".join(items) +
            f'</div>'
        )
    return "\n  ".join(blocks) if blocks else '<p class="muted">该标的各级别中枢均无与现价发生重叠的历史带。</p>'


def build_window_rows(window):
    rows = []
    for lv in LEVELS:
        m = window["levels"][lv]
        v = m.get("window_verdict") or "—"
        cls = {"结构充分": "down", "窗口偏长": "amber",
               "窗口偏短": "amber", "样本偏薄": "amber",
               "样本过密": "amber"}.get(v, "gray")
        rows.append(
            f'<tr><td><strong>{m["label"]}</strong></td>'
            f'<td>{m["role"]}</td>'
            f'<td>{m["data_range"][0]} → {m["data_range"][1]}'
            f'<br><span class="muted">{m.get("span_days")} 个自然日</span></td>'
            f'<td>{m["kline_count"]}</td>'
            f'<td>{m["pivots_total"]}</td>'
            f'<td>{m["divergence_window_bars"]} 根</td>'
            f'<td><span class="tag {cls}">{WINDOW_ZH.get(v, v)}</span></td></tr>'
        )
    return "\n      ".join(rows)


def build_strategy_blocks(ml):
    action = ml["action"]
    res = ml["resonance"]
    nesting = ml["interval_nesting"]
    levels = ml["levels"]

    day = levels["day"]
    m30 = levels["m30"]

    entry_bits = []
    if m30.get("last_pivot"):
        entry_bits.append(f"30 分钟中枢上沿 {m30['last_pivot']['ZG']} 附近回抽不破可作参考入场区")
    if day.get("last_pivot"):
        entry_bits.append(f"日线中枢 {day['last_pivot']['ZD']}~{day['last_pivot']['ZG']} 是中期多空分界")
    entry_txt = "；".join(entry_bits) if entry_bits else "等待结构明确后再评估入场位"

    pos_map = {"A": "可用足仓位上限", "B": "建议先建试探仓（约三成），确认后再加",
               "C": "轻仓（不超过两成），短线思路", "D": "空仓"}
    position_txt = pos_map.get(action["grade"], "轻仓试探")

    blocks = [
        f'<div class="strategy"><strong>总体定性</strong> —— {action["tone"]}。'
        f'共振结论为「{res["level"]}」，等级 {res["grade"]}。</div>',

        f'<div class="strategy"><strong>入场参考</strong> —— {entry_txt}。'
        f'当前日线买卖点为「{action["day_signal"]}」，'
        f'30 分钟为「{action["m30_signal"]}」。</div>',

        f'<div class="strategy"><strong>区间套</strong> —— {nesting["text"]}</div>',

        f'<div class="strategy"><strong>仓位建议</strong> —— {position_txt}。'
        f'大级别方向为「{BIAS_ZH.get(levels["week"]["bias"], "未知")}」，'
        f'仓位上限应与大级别方向匹配。</div>',

        f'<div class="strategy"><strong>止损与失效</strong> —— '
        f'{"；".join(action["invalidation"]) if action["invalidation"] else "见各级别失效条件"}</div>',
    ]
    return "\n  ".join(blocks)


def main():
    args = parse_args()
    workdir = args.workdir or os.getcwd()
    os.chdir(workdir)

    if not os.path.exists("chan_multi_level.json"):
        print("❌ 缺少 chan_multi_level.json，请先运行 chan_multi_level.py")
        sys.exit(1)
    ml = json.load(open("chan_multi_level.json", encoding="utf-8"))

    script_dir = os.path.dirname(os.path.abspath(__file__))
    tpl = args.template or os.path.join(script_dir, "..", "templates", "report_multi_template.html")
    if not os.path.exists(tpl):
        print(f"❌ 未找到模板: {tpl}")
        sys.exit(1)
    html = open(tpl, encoding="utf-8").read()

    levels = ml["levels"]
    res, nesting, action = ml["resonance"], ml["interval_nesting"], ml["action"]
    nesting_wd = ml.get("interval_nesting_week_day") or {}
    window = ml.get("window_alignment") or {}

    def nest_pair(n, lbl_upper, lbl_sub):
        up = (f"{n['upper']['type']} {n['upper']['date']} @ {n['upper']['price']}"
              if n.get("upper") else "无信号")
        sb = (f"{n['sub']['type']} {n['sub']['date']} @ {n['sub']['price']}"
              if n.get("sub") else "未出现同向背驰")
        return up, sb

    wd_up, wd_sub = nest_pair(nesting_wd, "周线", "日线") if nesting_wd else ("—", "—")

    symbol = ml.get("symbol") or "—"
    name = ml.get("name") or ""
    title = args.title or f"{symbol} {name} · 缠论三级别分析报告".strip()

    def rng(lv):
        d = levels[lv]["data_range"]
        return f"{d[0]} → {d[1]}"

    cw = window.get("common_window", {}) if window else {}
    repl = {
        "SYMBOL": symbol,
        "NAME": name,
        "DATA_UNTIL": levels["day"]["last_bar_date"],
        "WEEK_RANGE": rng("week"),
        "DAY_RANGE": rng("day"),
        "M30_RANGE": rng("m30"),
        "NARRATIVE": ml["narrative"],
        "RES_LEVEL": res["level"],
        "RES_GRADE": res["grade"],
        "RES_TONE": action["tone"],
        "RES_DETAIL": res["detail"],
        "RES_CARD_CLASS": GRADE_CLASS.get(res["grade"], "gray"),
        "LEVEL_ROWS": build_level_rows(levels),
        "KEY_LEVEL_BLOCKS": build_key_level_blocks(ml["key_levels"]),
        "BAND_BLOCKS": build_band_blocks(ml["key_levels"]),
        "STRATEGY_BLOCKS": build_strategy_blocks(ml),
        "WINDOW_PRINCIPLE": window.get("principle", ""),
        "WINDOW_ROWS": build_window_rows(window) if window else "",
        "WINDOW_COMMON": (
            f"{cw.get('from', '—')} → {cw.get('to', '—')}"
            f"（{cw.get('span_days', '—')} 个自然日）。"
            f"三级别在共同覆盖区间之外的结论只能作背景结构，不得作为可执行依据。"
            if cw else "—"),
        "WINDOW_DENSITY": (
            f"<strong>{BALANCE_ZH.get(window.get('density_balance'), '—')}</strong>"
            f"（中枢数比值 {window.get('density_ratio', '—')}）—— "
            f"{window.get('density_note', '')}"
            if window else "—"),
        "WINDOW_RULE": window.get("rule", ""),
        "CAVEAT_ITEMS": li_list(ml["caveats"]),
        "INVALIDATION_ITEMS": li_list(action["invalidation"]),
        "ACTION_SUMMARY": "；".join(action["notes"]),
        "NEST_TEXT": nesting["text"],
        "NEST_VERDICT": NEST_ZH.get(nesting["verdict"], nesting["verdict"]),
        "NEST_WD_TEXT": nesting_wd.get("text", "—"),
        "NEST_WD_VERDICT": NEST_ZH.get(nesting_wd.get("verdict"), nesting_wd.get("verdict", "—")),
        "NEST_WD_UPPER": wd_up,
        "NEST_WD_SUB": wd_sub,
        "NEST_DAY": (f"{nesting['upper']['type']} {nesting['upper']['date']} @ {nesting['upper']['price']}"
                     if nesting.get("upper") else "无信号"),
        "NEST_M30": (f"{nesting['sub']['type']} {nesting['sub']['date']} @ {nesting['sub']['price']}"
                     if nesting.get("sub") else "未出现同向背驰"),
    }
    for lv in LEVELS:
        m = levels[lv]
        key = lv.upper()
        repl[f"{key}_BIAS_ZH"] = m["bias_zh"]
        repl[f"{key}_CARD_CLASS"] = card_class(m["bias"])
        repl[f"{key}_SUMMARY"] = level_summary(lv, m)
        repl[f"{key}_CHART_SUB"] = chart_sub(lv, m)

    for k, v in repl.items():
        html = html.replace("{{" + k + "}}", str(v))

    # 标题（模板里标题同时出现在 <title> 和 <h1>）
    html = html.replace(f"<title>{symbol} {name} · 缠论三级别分析报告</title>",
                        f"<title>{title}</title>")
    html = html.replace(f"<h1>{symbol} {name} · 缠论三级别分析报告</h1>",
                        f"<h1>{title}</h1>")

    rest = sorted(set(re.findall(r"\{\{[A-Z0-9_]+\}\}", html)))
    if rest:
        print(f"⚠️  仍有未替换的占位符: {rest}")

    out = args.out
    open(out, "w", encoding="utf-8").write(html)
    print(f"✅ 已生成 {out}")

    # 注入内联行情数据
    os.system(f'python3 "{os.path.join(script_dir, "..", "templates", "inline_multi_data.py")}" '
              f'. --html {out} --ma {args.ma}')

    print("\n下一步：node ../templates/server.js 启动本地预览")


if __name__ == "__main__":
    main()
