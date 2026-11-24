#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
腾讯前复权 K 线 → 东方财富统一格式（东财限流时的降级通道）

用法:
    python3 tx_to_em_format.py <腾讯.json> <输出.json> [key]

先抓数据:
    curl -s -A "Mozilla/5.0" \
      "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh601208,week,,,520,qfq" -o tx_week.json
    curl -s -A "Mozilla/5.0" \
      "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh601208,day,,,520,qfq"  -o tx_day.json

再转换:
    python3 tx_to_em_format.py tx_week.json kline_week.json qfqweek
    python3 tx_to_em_format.py tx_day.json  kline_day.json  qfqday

腾讯字段序: [date, open, close, high, low, volume, ...]
东方财富目标格式: {"data": {"klines": ["date,open,close,high,low,volume,amount", ...]}}
两者字段序一致，amount 腾讯不提供，补 0（chan_analyze.py 不使用该字段）。

注意: 腾讯是前复权、新浪 30 分钟是未复权。转换后务必核对
      三级别最新收盘价差异在 0.5% 以内，否则不可跨级别比较价位。
"""
import json
import sys

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(1)

src, dst = sys.argv[1], sys.argv[2]
key = sys.argv[3] if len(sys.argv) > 3 else None

raw = json.load(open(src, encoding="utf-8"))
if raw.get("code") != 0:
    print(f"❌ 腾讯接口返回异常: code={raw.get('code')} msg={raw.get('msg')}")
    sys.exit(1)

data = raw.get("data") or {}
if not data:
    print("❌ 腾讯返回 data 为空，检查股票代码（需带 sh/sz 前缀）")
    sys.exit(1)

sym = list(data.keys())[0]
block = data[sym]

if key is None:
    cands = [k for k in block.keys() if k.startswith("qfq")]
    if not cands:
        print(f"❌ 未找到前复权数据，可用键: {list(block.keys())}")
        sys.exit(1)
    key = cands[0]

rows = block.get(key) or []
if not rows:
    print(f"❌ {sym}.{key} 为空（停牌或代码错误）")
    sys.exit(1)

klines = []
for r in rows:
    d = str(r[0])
    o, c, h, l = float(r[1]), float(r[2]), float(r[3]), float(r[4])
    v = float(r[5]) if len(r) > 5 else 0.0
    klines.append(f"{d},{o:.2f},{c:.2f},{h:.2f},{l:.2f},{v:.0f},0")

json.dump({"data": {"klines": klines, "_source": "tencent", "_key": key, "_symbol": sym}},
          open(dst, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

print(f"✅ {src} [{key}] → {dst}")
print(f"   {len(klines)} 根  {klines[0].split(',')[0]} → {klines[-1].split(',')[0]}  末收 {klines[-1].split(',')[2]}")
