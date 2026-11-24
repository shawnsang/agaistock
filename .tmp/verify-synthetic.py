"""验证：合成锯齿 K 线能否让上游 chan_multi_level.py 正常跑通。"""
import json
import subprocess
import sys
from pathlib import Path

VENDOR = Path(r"C:\Users\shawn\.workbuddy\plugins\marketplaces\my-experts\plugins\chanlun-analyst\skills\chanlun-core")
OUT = Path(r"D:\workroom\agaistock\.tmp\synthetic")
OUT.mkdir(parents=True, exist_ok=True)

rows = []
for i in range(120):
    day = 1 + (i % 28)
    month = 1 + (i // 28) % 12
    base = 10 + (i % 10) * 0.3
    rows.append({
        "Data": f"2025{month:02d}{day:02d}",
        "Open": f"{base:.2f}", "High": f"{base + 0.5:.2f}",
        "Low": f"{base - 0.5:.2f}", "Close": f"{base + 0.1:.2f}",
        "Volume": 100000.0, "Amount": 1000000.0,
    })

klines = []
for r in rows:
    klines.append(
        f"{r['Data'][:4]}-{r['Data'][4:6]}-{r['Data'][6:]},"
        f"{r['Open']},{r['Close']},{r['High']},{r['Low']},100000,1000000"
    )
(OUT / "kline_day.json").write_text(
    json.dumps({"data": {"klines": klines, "count": len(klines)}}, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print(f"合成 K 线: {len(klines)} 根")

r1 = subprocess.run(
    [sys.executable, str(VENDOR / "scripts" / "chan_analyze.py"), str(OUT), "--level", "day"],
    capture_output=True, text=True, encoding="utf-8", cwd=str(OUT),
)
print("chan_analyze exit:", r1.returncode)
print((r1.stdout or "")[-900:])
if r1.returncode != 0:
    print("STDERR:", (r1.stderr or "")[-900:])

r2 = subprocess.run(
    [sys.executable, str(VENDOR / "scripts" / "chan_multi_level.py"), str(OUT),
     "--symbol", "002378", "--name", "章源钨业"],
    capture_output=True, text=True, encoding="utf-8", cwd=str(OUT),
)
print("chan_multi_level exit:", r2.returncode)
print((r2.stdout or "")[-900:])
if r2.returncode != 0:
    print("STDERR:", (r2.stderr or "")[-900:])

multi = OUT / "chan_multi_level.json"
print("chan_multi_level.json 存在:", multi.is_file())
if multi.is_file():
    data = json.loads(multi.read_text(encoding="utf-8"))
    print("顶层键:", sorted(data.keys()))
    print("levels 键:", sorted((data.get("levels") or {}).keys()))
