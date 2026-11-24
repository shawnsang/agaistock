#!/usr/bin/env python3
"""
三级别报告数据内联工具

把三个级别的 K 线 + 结构结果打包成 JS 对象，注入 report.html，避免 CORS 问题。

用法：
  python3 inline_multi_data.py [workdir]
  python3 inline_multi_data.py [workdir] --html report.html
  python3 inline_multi_data.py [workdir] --out multi_data.js --ma 20

输入：
  kline_week.json / kline_day.json / kline_m30.json
  chan_analysis_week.json / chan_analysis_day.json / chan_analysis_m30.json

输出：
  multi_data.js          —— const MULTI = {...}; 片段
  （若指定 --html）同时把 report.html 里的 const MULTI 行替换掉
"""
import argparse
import json
import os
import re
import sys

LEVELS = ["week", "day", "m30"]
LEVEL_LABEL = {"week": "周线", "day": "日线", "m30": "30分钟"}
BIAS_ZH = {"up": "向上", "down": "向下", "range": "震荡", "unknown": "未知"}
UP_RED = "#d63333"      # 中国市场惯例：涨红
DOWN_GREEN = "#2a7f3f"


def parse_args():
    p = argparse.ArgumentParser(description="三级别报告数据内联工具")
    p.add_argument("workdir", nargs="?", default=None, help="工作目录，默认当前目录")
    p.add_argument("--html", default=None, help="要注入的 report.html")
    p.add_argument("--out", default="multi_data.js", help="输出的 JS 片段文件名")
    p.add_argument("--ma", type=int, default=20, help="均线周期（按 K 线根数）")
    p.add_argument("--max-pivots", type=int, default=3, help="每个级别最多标注的中枢数")
    return p.parse_args()


def load_kline(level):
    f = f"kline_{level}.json"
    if not os.path.exists(f):
        print(f"❌ 缺少 {f}")
        sys.exit(1)
    raw = json.load(open(f, encoding="utf-8"))
    out = []
    for line in raw.get("data", {}).get("klines", []):
        p = line.split(",")
        if len(p) < 6:
            continue
        out.append({"d": p[0], "o": float(p[1]), "c": float(p[2]),
                    "h": float(p[3]), "l": float(p[4]), "v": float(p[5])})
    return out


def load_analysis(level):
    f = f"chan_analysis_{level}.json"
    if not os.path.exists(f):
        print(f"❌ 缺少 {f}，请先运行 chan_analyze.py --level {level}")
        sys.exit(1)
    return json.load(open(f, encoding="utf-8"))


def build_marks(level, analysis):
    """标注：最近背驰点 + 最近的关键极值。"""
    marks = []
    seen = set()

    def push(date, price, color, label):
        key = (date, price)
        if key in seen:
            return
        seen.add(key)
        marks.append({"d": date, "p": price, "c": color, "l": label})

    ctx = analysis.get("context", {})
    div = ctx.get("recent_divergence")
    if div:
        color = UP_RED if div["kind"] == "top" else DOWN_GREEN
        tag = "顶背驰" if div["kind"] == "top" else "底背驰"
        push(div["date"], div["price"], color, f"{div['date']} {tag} {div['price']}")

    for d in analysis.get("top_divergences", [])[-2:]:
        if d.get("verdict") == "顶背驰":
            push(d["date"], d["price"], UP_RED, f"{d['date']} 顶背驰 {d['price']}")

    for d in analysis.get("bottom_divergences", [])[-2:]:
        if d.get("verdict") == "底背驰":
            push(d["date"], d["price"], DOWN_GREEN, f"{d['date']} 底背驰 {d['price']}")

    return marks


def main():
    args = parse_args()
    workdir = args.workdir or os.getcwd()
    os.chdir(workdir)

    meta = {}
    if os.path.exists("chan_multi_level.json"):
        meta = json.load(open("chan_multi_level.json", encoding="utf-8"))

    levels = {}
    for lv in LEVELS:
        kline = load_kline(lv)
        ana = load_analysis(lv)
        pivots = [{"from": p["from"], "to": p["to"], "ZG": p["ZG"], "ZD": p["ZD"]}
                  for p in ana.get("recent_pivots", [])[-args.max_pivots:]]
        levels[lv] = {
            "label": LEVEL_LABEL[lv],
            "ma": args.ma,
            "kline": kline,
            "pivots": pivots,
            "marks": build_marks(lv, ana),
        }
        print(f"{LEVEL_LABEL[lv]:<8} K线 {len(kline):>5} 根 · "
              f"中枢标注 {len(pivots)} 个 · 标记点 {len(levels[lv]['marks'])} 个")

    symbol = meta.get("symbol") or "—"
    name = meta.get("name") or ""
    obj = {"symbol": symbol, "name": name, "levels": levels}

    js = "const MULTI = " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + ";"
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(js)
    print(f"\n✅ 已生成 {args.out}（{len(js)} 字符）")

    if args.html:
        if not os.path.exists(args.html):
            print(f"❌ 未找到 {args.html}")
            sys.exit(1)
        lines = open(args.html, encoding="utf-8").read().split("\n")
        hit = False
        for i, ln in enumerate(lines):
            if ln.strip().startswith("const MULTI"):
                lines[i] = js
                hit = True
                break
        if not hit:
            print(f"❌ {args.html} 中没有找到 const MULTI 行，未注入")
            sys.exit(1)
        open(args.html, "w", encoding="utf-8").write("\n".join(lines))
        print(f"✅ 已注入 {args.html}")


if __name__ == "__main__":
    main()
