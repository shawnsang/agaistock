"""临时：Rows → 东财格式，并跑上游缠论脚本，验证 3.11 兼容性。"""
import json
import subprocess
import sys
from pathlib import Path

TMP = Path(r"D:\workroom\agaistock\.tmp")
VENDOR = Path(r"C:\Users\shawn\.workbuddy\plugins\marketplaces\my-experts\plugins\chanlun-analyst\skills\chanlun-core")


def parse_date(d: str) -> str:
    s = str(d).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def rows_to_em(payload: dict) -> dict:
    rows = payload.get("Rows") or []
    klines = []
    for row in rows:
        klines.append(
            f"{parse_date(row['Data'])},{float(row['Open']):.2f},{float(row['Close']):.2f},"
            f"{float(row['High']):.2f},{float(row['Low']):.2f},"
            f"{float(row['Volume']):.0f},{float(row['Amount']):.0f}"
        )
    return {"data": {"klines": klines}}


payload = json.loads((TMP / "tdx_day.json").read_text(encoding="utf-8"))
em = rows_to_em(payload)
(TMP / "kline_day.json").write_text(json.dumps(em, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"转换完成: {len(em['data']['klines'])} 根")
print("首:", em["data"]["klines"][0])
print("末:", em["data"]["klines"][-1])

result = subprocess.run(
    [sys.executable, str(VENDOR / "scripts" / "chan_analyze.py"), str(TMP), "--level", "day"],
    capture_output=True,
    text=True,
    encoding="utf-8",
    cwd=str(TMP),
)
print("\n=== chan_analyze.py stdout ===")
print(result.stdout[-3000:])
print("=== stderr ===")
print(result.stderr[-2000:])
print("returncode:", result.returncode)
