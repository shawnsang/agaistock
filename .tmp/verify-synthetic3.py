"""验证：三个级别的合成数据齐全时，chan_multi_level.py 能否跑通。"""
import json
import subprocess
import sys
from pathlib import Path

VENDOR = Path(r"C:\Users\shawn\.workbuddy\plugins\marketplaces\my-experts\plugins\chanlun-analyst\skills\chanlun-core")
OUT = Path(r"D:\workroom\agaistock\.tmp\synthetic3")
OUT.mkdir(parents=True, exist_ok=True)


def make_klines(count, step):
    klines = []
    for i in range(count):
        day = 1 + (i % 28)
        month = 1 + (i // 28) % 12
        base = 10 + ((i // step) % 10) * 0.6
        klines.append(
            f"2025{month:02d}{day:02d},"
            f"{base:.2f},{base + 0.1:.2f},{base + 0.5:.2f},{base - 0.5:.2f},100000,1000000"
        )
    return klines


for level, count in (("week", 120), ("day", 120), ("m30", 120)):
    klines = make_klines(count, 3)
    (OUT / f"kline_{level}.json").write_text(
        json.dumps({"data": {"klines": klines, "count": len(klines)}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    r = subprocess.run(
        [sys.executable, str(VENDOR / "scripts" / "chan_analyze.py"), str(OUT), "--level", level],
        capture_output=True, text=True, encoding="utf-8", cwd=str(OUT),
    )
    print(f"chan_analyze --level {level} exit={r.returncode}")

r2 = subprocess.run(
    [sys.executable, str(VENDOR / "scripts" / "chan_multi_level.py"), str(OUT),
     "--symbol", "002378", "--name", "章源钨业"],
    capture_output=True, text=True, encoding="utf-8", cwd=str(OUT),
)
print("chan_multi_level exit:", r2.returncode)
print((r2.stdout or "")[-1200:])
if r2.returncode != 0:
    print("STDERR:", (r2.stderr or "")[-900:])

multi = OUT / "chan_multi_level.json"
print("json 存在:", multi.is_file())
if multi.is_file():
    data = json.loads(multi.read_text(encoding="utf-8"))
    print("顶层键:", sorted(data.keys()))
    print("levels 键:", sorted((data.get("levels") or {}).keys()))
    print("day keys:", sorted((data.get("levels") or {}).get("day", {}).keys()))
