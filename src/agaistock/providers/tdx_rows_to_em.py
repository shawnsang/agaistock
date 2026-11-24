"""TDX `Rows` → 东财格式。

上游 chanlun-core 的 tdx_to_em_format.py 针对旧结构（ListHead 数组 + AttachInfo 数组的数组）
编写，当前 tdx_kline 返回 `Rows` 对象数组（英文字段、升序），故重写。

关键点：
  - 字段序 东财 = date,o,c,h,l,v,a；TDX Rows 的键顺序是 o,h,l,c → 必须按名取，不可按位取
  - Rows 已是升序，**不要 reverse**
"""
from __future__ import annotations

from typing import Any

REQUIRED_KEYS = ("Data", "Open", "High", "Low", "Close")


def parse_tdx_date(value: str) -> str:
    """统一为 YYYY-MM-DD。"""
    text = str(value).strip()
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) == 10 and "-" in text:
        return text
    if "/" in text:
        return text.replace("/", "-")
    raise ValueError(f"无法识别的日期格式: {value!r}")


def rows_to_em_format(payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("Rows")
    if not isinstance(rows, list) or not rows:
        raise ValueError("payload 中没有 Rows 数据")
    klines: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        missing = [k for k in REQUIRED_KEYS if k not in row]
        if missing:
            raise ValueError(f"K 线行缺少字段 {missing}：{row}")
        try:
            date = parse_tdx_date(row["Data"])
            o = float(row["Open"])
            h = float(row["High"])
            l = float(row["Low"])
            c = float(row["Close"])
            v = float(row.get("Volume") or 0)
            a = float(row.get("Amount") or 0)
        except (TypeError, ValueError):
            continue
        klines.append(f"{date},{o:.2f},{c:.2f},{h:.2f},{l:.2f},{v:.0f},{a:.0f}")
    if not klines:
        raise ValueError("所有 K 线行都无法解析")
    return {"data": {"klines": klines, "count": len(klines)}}
