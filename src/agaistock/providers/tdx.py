"""通达信取数（经由 mcode-tools 连接器）。"""
from __future__ import annotations

import json

from .mcode_cli import call_connector

TDX_KLINE = "connector__tdx-finance__tdx_kline"
TDX_QUOTES = "connector__tdx-finance__tdx_quotes"


def setcode_for(symbol: str) -> str:
    """按代码前缀推断市场代码：沪=1 深=0 北=2。"""
    code = str(symbol).strip()
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"无法识别的证券代码: {symbol!r}")
    if code.startswith("6"):
        return "1"
    if code.startswith(("0", "3")):
        return "0"
    if code.startswith(("4", "8")):
        return "2"
    raise ValueError(f"无法识别的证券代码前缀: {symbol!r}")


def _payload_from_text(text: str) -> dict:
    """从连接器返回文本中抽出 JSON 负载。

    返回文本形如：`<摘要>\n详细K线数据:\n{...}` —— 取第一个 `{` 起的内容。
    """
    start = text.find("{")
    if start < 0:
        raise RuntimeError(f"连接器返回中找不到 JSON: {text[:200]}")
    return json.loads(text[start:])


def fetch_kline(symbol: str, setcode: str, period: str, want_num: int = 500) -> dict:
    """拉取 K 线，返回原始 payload（含升序的 Rows）。"""
    text = call_connector(
        TDX_KLINE,
        {
            "code": str(symbol),
            "setcode": str(setcode),
            "period": str(period),
            "wantNum": int(want_num),
        },
    )
    return _payload_from_text(text)


def fetch_quotes(symbol: str, setcode: str) -> dict:
    """拉取实时行情快照。"""
    text = call_connector(TDX_QUOTES, {"code": str(symbol), "setcode": str(setcode)})
    return _payload_from_text(text)
