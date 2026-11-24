"""通达信取数（经由 mcode-tools 连接器）。

复权口径（D6 / Global Constraint 16）：K 线固定取**后复权**（tqFlag="2"）。
口径在适配层收口，调用方不传、不切换。
"""
from __future__ import annotations

import json

from .mcode_cli import call_connector

TDX_KLINE = "connector__tdx-finance__tdx_kline"
TDX_QUOTES = "connector__tdx-finance__tdx_quotes"
TDX_API_DATA = "connector__tdx-finance__tdx_api_data"

# D6 口径：后复权序列。不传这个参数，连接器默认给的是前复权。
TQ_FLAG_HOUFUQUAN = "2"

# 复权因子所在的后端接口与子视图（主规格 §6.7.4）。
# 同一个 preset 还顺带返回 capital_flow 表；本任务只取复权因子。
_ADJ_ENTRY = "TdxSharePCCW.tdxf10_gg_jyds"
_ADJ_FIXED_TAG = "zjlx"


def setcode_for(symbol: str) -> str:
    """按代码前缀推断市场代码：沪=1 深=0 北=2。"""
    code = str(symbol).strip()
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"无法识别的证券代码: {symbol!r}")
    if code.startswith("6"):
        return "1"
    if code.startswith(("0", "3")):
        return "0"
    # 北交所：43xxxx / 83xxxx / 87xxxx 旧代码段 + 920xxx 当前代码段
    if code.startswith(("4", "8", "9")):
        return "2"
    raise ValueError(f"无法识别的证券代码前缀: {symbol!r}")


def _payload_from_text(text: str) -> dict:
    """从连接器返回文本中抽出 JSON 负载。

    返回文本形如：`<摘要>\n详细K线数据:\n{...}` —— 取第一个 `{` 起的内容。
    用 raw_decode 只解析第一个 JSON 值，容忍 JSON 之后还有尾随说明文字。
    """
    start = text.find("{")
    if start < 0:
        raise RuntimeError(f"连接器返回中找不到 JSON: {text[:200]}")
    try:
        payload, _ = json.JSONDecoder().raw_decode(text[start:])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"连接器返回的 JSON 解析失败: {text[start:][:200]}") from exc
    return payload


def fetch_kline(symbol: str, setcode: str, period: str, want_num: int = 500) -> dict:
    """拉取 K 线（后复权），返回原始 payload（含升序的 Rows）。"""
    text = call_connector(
        TDX_KLINE,
        {
            "code": str(symbol),
            "setcode": str(setcode),
            "period": str(period),
            "wantNum": int(want_num),
            "tqFlag": TQ_FLAG_HOUFUQUAN,
        },
    )
    return _payload_from_text(text)


def fetch_quotes(symbol: str, setcode: str) -> dict:
    """拉取实时行情快照。"""
    text = call_connector(TDX_QUOTES, {"code": str(symbol), "setcode": str(setcode)})
    return _payload_from_text(text)


def fetch_adjustment_factors(symbol: str) -> list[dict]:
    """拉取复权因子，归一化成 [{ex_date, factor, constant}]，按 ex_date 降序。

    数据来自 tdx_api_data 的 capital_flow preset —— 同一个 preset 返回两张表，
    复权因子那张叫 adjustment_factor，列名是中文：
    日期 / 精确复权因子 / 精确复权常数。
    """
    text = call_connector(
        TDX_API_DATA,
        {"entry": _ADJ_ENTRY, "fixedTag": _ADJ_FIXED_TAG, "code": str(symbol)},
    )
    payload = _payload_from_text(text)
    tables = (payload.get("response") or {}).get("transformed", {}).get("tables") or []
    for table in tables:
        if table.get("name") != "adjustment_factor":
            continue
        factors = []
        for row in table.get("rows") or []:
            factors.append(
                {
                    "ex_date": str(row.get("日期", "")),
                    "factor": float(row.get("精确复权因子", 0) or 0),
                    "constant": float(row.get("精确复权常数", 0) or 0),
                }
            )
        factors.sort(key=lambda item: item["ex_date"], reverse=True)
        return factors
    return []


def to_houfuquan(price: float, factor_row: dict) -> float:
    """现价 → 后复权。

    公式（已实测）：后复权价 = 现价 × 精确复权因子 + 精确复权常数。
    `factor_row` 必须是该价格所属日期对应的那一行（当前价位用最新一行）。
    """
    return float(price) * float(factor_row["factor"]) + float(factor_row["constant"])


def to_current_price(price: float, factor_row: dict) -> float:
    """后复权 → 现价（`to_houfuquan` 的逆变换）。"""
    return (float(price) - float(factor_row["constant"])) / float(factor_row["factor"])
