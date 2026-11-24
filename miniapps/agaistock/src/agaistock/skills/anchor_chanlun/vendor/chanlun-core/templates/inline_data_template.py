#!/usr/bin/env python3
"""读取 kline JSON，生成 JS inline 数据，注入到 report.html"""
import json
import os

DIR = "/Users/shawnsang/WorkBuddy/2026-09-08-21-26-43/chan_600967"
data = json.load(open(os.path.join(DIR, "kline_latest.json")))
klines = data["data"]["klines"]
records = []
for line in klines:
    p = line.split(",")
    records.append({
        "date": p[0], "o": float(p[1]), "c": float(p[2]),
        "h": float(p[3]), "l": float(p[4]), "v": float(p[5])
    })
print(f"共 {len(records)} 根 K 线")
print(f"首: {records[0]['date']} 收 {records[0]['c']}")
print(f"末: {records[-1]['date']} 收 {records[-1]['c']}")

embed = (
    "const KLINE = ["
    + ",".join(
        f'{{d:"{r["date"]}",o:{r["o"]},c:{r["c"]},h:{r["h"]},l:{r["l"]},v:{r["v"]}}}'
        for r in records
    )
    + "];"
)
open(os.path.join(DIR, "kline_embed.txt"), "w").write(embed)
print(f"生成嵌入数据 {len(embed)} 字符")