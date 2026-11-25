"""同一标的的观察**续接**：新输入如何并进上一版。

规则（见计划 Task 21 §2）：
  - **观点**（方向 / 主张 / 时限 / 触发 / 仓位）取新的；
  - **积累项**（依据 / 证伪条件）取并集；
  - 证伪条件的并集**只并用户自己前后两次说的话** ——
    点评师仍然不自动写 observation（设计 §2.2 硬约束）。

纯函数、无 I/O ⇒ 可直接单测。
"""
from __future__ import annotations

import json
from typing import Any

# 「当前观点」字段：新的优先，新的为空才回退旧的。
VIEW_FIELDS = ("thesis", "timeframe", "trigger")


def _text(value: Any) -> str:
    """去空白的字符串；None / 非字符串统一成 ''。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _confidence(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _position_dict(value: Any) -> dict[str, Any]:
    """持仓信息统一成 dict。

    上一版来自数据库（`position_json`，**字符串**），
    新输入来自接入层的结构化草稿（`position`，**dict**）—— 两种形态都要吃。
    """
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return {}
        return dict(parsed) if isinstance(parsed, dict) else {}
    return {}


def _merge_position(previous: Any, incoming: Any) -> dict[str, Any]:
    """逐键合并：新的非空值覆盖旧的，旧的独有键保留。"""
    old = _position_dict(previous)
    new = _position_dict(incoming)
    merged = dict(old)
    for key, value in new.items():
        if _text(value):
            merged[key] = value
    return merged


def _merge_evidence(previous: Any, incoming: Any) -> list[dict[str, Any]]:
    """依据取并集：按 text 去重，旧的在前、新的在后。"""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(previous or []) + list(incoming or []):
        if isinstance(item, dict):
            text = _text(item.get("text"))
            item_type = item.get("type")
            item_type = item_type if item_type in ("fact", "assumption") else "assumption"
        else:
            text = _text(item)
            item_type = "assumption"
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append({"text": text, "type": item_type})
    return merged


def _merge_invalidation(previous: Any, incoming: Any) -> list[str]:
    """证伪条件取并集：按文本去重，旧的在前、新的在后。"""
    merged: list[str] = []
    seen: set[str] = set()
    for item in list(previous or []) + list(incoming or []):
        text = _text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        merged.append(text)
    return merged


def merge_into_previous(previous: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """把新输入并进上一版，返回**待落库的新版本行**。

    返回值**不含**上一版的 `id` / `thread_id` / `supersedes_id` / `deleted_at` ——
    `id` 会被 `insert_observation` 当主键用（撞主键），
    版本链的三列由调用方决定。
    """
    merged: dict[str, Any] = {
        "symbol": _text(incoming.get("symbol")) or _text(previous.get("symbol")),
        "name": _text(incoming.get("name")) or _text(previous.get("name")),
    }
    # created_at 只在**新输入**自己带了的时候才继承；否则落库时用当前时间。
    if incoming.get("created_at"):
        merged["created_at"] = incoming["created_at"]

    for field in VIEW_FIELDS:
        merged[field] = _text(incoming.get(field)) or _text(previous.get(field))

    # direction：新的优先，但新的为 neutral 时**保留旧的**。
    # neutral 在本代码库里表示「没有表态」—— 关键词解析在文本无方向词时给 neutral，
    # 接入层的模型在用户没表态时也给 neutral。若「新的非空就取新的」，
    # 一次纯补充（"产量翻倍确认了"）会把方向悄悄抹成中性。
    new_direction = _text(incoming.get("direction"))
    old_direction = _text(previous.get("direction"))
    if not new_direction or (new_direction == "neutral" and old_direction and old_direction != "neutral"):
        new_direction = old_direction
    merged["direction"] = new_direction

    # confidence：0.0 表示「未提供」，此时沿用旧的。
    new_confidence = _confidence(incoming.get("confidence"))
    if new_confidence <= 0:
        new_confidence = _confidence(previous.get("confidence"))
    merged["confidence"] = new_confidence

    merged["position"] = _merge_position(
        previous.get("position") if previous.get("position") is not None else previous.get("position_json"),
        incoming.get("position") if incoming.get("position") is not None else incoming.get("position_json"),
    )
    merged["evidence"] = _merge_evidence(previous.get("evidence"), incoming.get("evidence"))
    merged["invalidation"] = _merge_invalidation(previous.get("invalidation"), incoming.get("invalidation"))
    merged["raw_text"] = incoming.get("raw_text") or previous.get("raw_text") or ""
    return merged
