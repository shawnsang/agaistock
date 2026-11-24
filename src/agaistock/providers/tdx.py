"""通达信取数（经由 mcode-tools 连接器）。

复权口径（D6 / Global Constraint 16）：K 线一律取**后复权**。

关键事实（实测 2026-11-24）：
  - 连接器的 `tqFlag="2"`（后复权）**只在日线/周线生效，30 分钟级别不生效**：
    600519 的 m30 给 1563.54，同一天的日线给 10014.70；002378 m30 给 15.73、日线给 42.66。
    直接用连接器的后复权，三个级别会落在两个价格空间。
  - 所以本层取 `tqFlag="0"`（不复权）原始序列 + 复权因子表，**自己重建**后复权。
    重建规则与连接器自身的后复权一致（600519 700 根日线中位相对误差 0.00003%）。
  - `Volume` / `Amount` 保持原值（与连接器后复权行为一致）。

口径在适配层收口，调用方不传、不切换。
"""
from __future__ import annotations

import json

from .mcode_cli import call_connector

TDX_KLINE = "connector__tdx-finance__tdx_kline"
TDX_QUOTES = "connector__tdx-finance__tdx_quotes"
TDX_API_DATA = "connector__tdx-finance__tdx_api_data"

# 请求连接器时固定要**不复权**原始序列，后复权由本层重建。
TQ_FLAG_RAW = "0"

# 复权因子所在的后端接口与子视图（主规格 §6.7.4）。
_ADJ_ENTRY = "TdxSharePCCW.tdxf10_gg_jyds"
_ADJ_FIXED_TAG = "zjlx"

# 需要做后复权换算的价格字段。
_PRICE_KEYS = ("Open", "High", "Low", "Close")


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


def _normalize_factor_rows(table: dict) -> list[dict]:
    """把 adjustment_factor 表归一化成 [{ex_date, factor, constant}]，按 ex_date 降序。"""
    factors = []
    for row in table.get("rows") or []:
        try:
            factor = float(row["精确复权因子"])
            constant = float(row["精确复权常数"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"复权因子表缺少预期列：{row}") from exc
        factors.append(
            {
                "ex_date": str(row.get("日期", "")).strip(),
                "factor": factor,
                "constant": constant,
            }
        )
    factors.sort(key=lambda item: item["ex_date"], reverse=True)
    return factors


def _find_factor_table(payload: dict) -> dict | None:
    tables = (payload.get("response") or {}).get("transformed", {}).get("tables") or []
    for table in tables:
        if table.get("name") == "adjustment_factor":
            return table
    return None


def fetch_adjustment_factors(symbol: str) -> list[dict]:
    """拉取复权因子，归一化成 [{ex_date, factor, constant}]，按 ex_date 降序。

    数据来自 tdx_api_data 的 capital_flow preset —— 同一个 preset 返回两张表，
    复权因子那张叫 adjustment_factor，列名是中文：
    日期 / 精确复权因子 / 精确复权常数。

    连接器返回形态不稳定（Global Constraint 19）：偶尔给 `response.data` 而不是
    `response.transformed.tables`。所以「找不到因子表」**不等于**「该标的没有除权记录」，
    先重试一次，仍失败就抛错 —— 静默返回空表会让后复权重建悄悄退化成不复权。
    """
    for attempt in range(2):
        text = call_connector(
            TDX_API_DATA,
            {"entry": _ADJ_ENTRY, "fixedTag": _ADJ_FIXED_TAG, "code": str(symbol)},
        )
        payload = _payload_from_text(text)
        table = _find_factor_table(payload)
        if table is not None:
            return _normalize_factor_rows(table)
    raise RuntimeError(f"拉取 {symbol} 的复权因子失败：未找到 adjustment_factor 表")


def factor_row_for(factors: list[dict], date: str) -> dict:
    """取某日期生效的因子行：ex_date ≤ date 的最新一行。

    因子表的日期带连字符（2026-06-26），K 线日期不带（20261124）——
    比较前统一成 YYYYMMDD，否则字符串比较会挑错行。
    早于首个 ex_date 的日期返回恒等变换（factor=1, constant=0）。

    **与入参顺序无关**：`fetch_adjustment_factors` 返回的是 ex_date 降序，
    这里必须自己取「匹配行里 ex_date 最大的那个」，不能靠遍历顺序碰运气。
    """
    key = str(date).replace("-", "")
    best = None
    best_key = ""
    for row in factors or []:
        row_key = str(row.get("ex_date", "")).replace("-", "")
        if not row_key or row_key > key:
            continue
        if row_key >= best_key:
            best = row
            best_key = row_key
    return best or {"ex_date": "", "factor": 1.0, "constant": 0.0}


def apply_houfuquan(payload: dict, factors: list[dict]) -> dict:
    """把 payload 里 Rows 的价格字段换算成后复权，返回新 payload（原 payload 不改）。

    后复权价(d) = 不复权价(d) × 精确复权因子 + 精确复权常数
    `Volume` / `Amount` 保持原值（与连接器后复权行为一致）。
    """
    rows = payload.get("Rows") or []
    converted = []
    for row in rows:
        if not isinstance(row, dict):
            converted.append(row)
            continue
        frow = factor_row_for(factors, row.get("Data", ""))
        factor = float(frow.get("factor", 1.0))
        constant = float(frow.get("constant", 0.0))
        new_row = dict(row)
        for key in _PRICE_KEYS:
            value = row.get(key)
            if value is None:
                continue
            try:
                new_row[key] = f"{float(value) * factor + constant:.6f}"
            except (TypeError, ValueError):
                continue
        converted.append(new_row)
    new_payload = dict(payload)
    new_payload["Rows"] = converted
    return new_payload


def fetch_raw_kline(symbol: str, setcode: str, period: str, want_num: int = 500) -> dict:
    """拉取不复权原始序列，返回原始 payload（含升序的 Rows）。"""
    text = call_connector(
        TDX_KLINE,
        {
            "code": str(symbol),
            "setcode": str(setcode),
            "period": str(period),
            "wantNum": int(want_num),
            "tqFlag": TQ_FLAG_RAW,
        },
    )
    return _payload_from_text(text)


def fetch_kline(
    symbol: str,
    setcode: str,
    period: str,
    want_num: int = 500,
    factors: list[dict] | None = None,
) -> dict:
    """拉取后复权序列（口径在适配层收口，调用方不切换）。

    `factors` 可传入已取好的因子表以避免重复调用；不给则内部自己取。
    """
    payload = fetch_raw_kline(symbol, setcode, period, want_num)
    if not (payload.get("Rows") or []):
        return payload
    factor_rows = factors if factors is not None else fetch_adjustment_factors(symbol)
    return apply_houfuquan(payload, factor_rows)


def fetch_quotes(symbol: str, setcode: str) -> dict:
    """拉取实时行情快照（现价口径，不复权）。"""
    text = call_connector(TDX_QUOTES, {"code": str(symbol), "setcode": str(setcode)})
    return _payload_from_text(text)


def to_houfuquan(price: float, factor_row: dict) -> float:
    """现价 → 后复权。

    公式（已实测）：后复权价 = 现价 × 精确复权因子 + 精确复权常数。
    `factor_row` 必须是该价格所属日期对应的那一行（当前价位用最新一行）。
    """
    return float(price) * float(factor_row["factor"]) + float(factor_row["constant"])


def to_current_price(price: float, factor_row: dict) -> float:
    """后复权 → 现价（`to_houfuquan` 的逆变换）。"""
    return (float(price) - float(factor_row["constant"])) / float(factor_row["factor"])
