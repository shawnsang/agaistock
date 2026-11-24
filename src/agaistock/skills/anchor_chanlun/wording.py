"""LLM 措辞层：只改写 claim 的自然语言表述，不动任何判定字段。

若 LLM 输出篡改了受保护字段（code/severity/dimension/delta/evidence_ref），
**丢弃该条 LLM 输出，保留规则层原文**。
"""
from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any

from ...reviewers.contract import PROTECTED_FIELDS, Finding

# 受保护字段只有一个来源：契约层已经定义了 PROTECTED_FIELDS。
# 这里直接复用，不要各写一份 —— 两处分叉会让「哪些字段不许 LLM 改」变得不可控。
PROTECTED = PROTECTED_FIELDS

SYSTEM_PROMPT = (
    "你是股票复盘助手，负责把结构化发现改写成给投资者看的中文点评。"
    "只允许改写 claim 的表述，使其更口语化、更说明『这说明什么』。"
    "不得修改 code、severity、dimension、delta、evidence_ref，不得改变判定结论，"
    "不得给出投资建议，不得预测点位。只输出 JSON。"
)


def _extract_json(text: str) -> dict | None:
    source = str(text or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", source)
    body = fenced.group(1) if fenced else source
    start = body.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(body)):
        char = body[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(body[start:index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _matches_protected(original: Finding, item: dict[str, Any]) -> bool:
    """只校验 LLM **实际返回了**的受保护字段。

    字段缺失 = LLM 没有动这个字段（不算篡改）；字段存在但值与原值不同 = 篡改。
    要求五个字段全部出现是错的：正常的措辞回复只带 code + claim，
    会被误判成篡改而整条丢弃。
    """
    for field in PROTECTED:
        if field not in item:
            continue
        current = getattr(original, field)
        proposed = item[field]
        if isinstance(current, list):
            # LLM 返回的必须是列表：
            #   list(123) → TypeError（'int' object is not iterable），会穿透「任何异常都降级」的硬约束；
            #   list("a") → ['a']，与原文 ['a'] 相等 → 字符串会被误判成「没篡改」而放行。
            if not isinstance(proposed, list) or proposed != list(current):
                return False
        elif proposed != current:
            return False
    return True


def phrase(
    findings: list[Finding],
    observation: dict,
    llm=None,
    context: dict | None = None,
) -> list[Finding]:
    """用 LLM 改写 claim；任何异常或篡改都退回规则层原文。

    `context` 可携带缠论结构的整体语境（上游已生成的 narrative / resonance / 纪律），
    让点评有整体参照而不是逐条孤立改写。
    """
    if llm is None or not findings:
        return list(findings)

    prompt = json.dumps(
        {
            "observation": {
                "thesis": observation.get("thesis", ""),
                "direction": observation.get("direction", ""),
                "timeframe": observation.get("timeframe", ""),
            },
            "structure_context": context or {},
            "findings": [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "dimension": f.dimension,
                    "delta": f.delta,
                    "claim": f.claim,
                    "why": f.why,
                    "evidence_ref": list(f.evidence_ref),
                    "suggested_fix": f.suggested_fix,
                }
                for f in findings
            ],
        },
        ensure_ascii=False,
    )

    try:
        raw = llm.complete(prompt, system=SYSTEM_PROMPT)
    except Exception:  # noqa: BLE001 —— 措辞层失败必须降级，不能影响判定
        return list(findings)

    payload = _extract_json(raw)
    if not payload:
        return list(findings)

    items = payload.get("items")
    if not isinstance(items, list):
        return list(findings)

    by_code = {item.get("code"): item for item in items if isinstance(item, dict)}

    result = []
    for finding in findings:
        item = by_code.get(finding.code)
        if not isinstance(item, dict) or not _matches_protected(finding, item):
            result.append(finding)
            continue
        new_claim = str(item.get("claim") or "").strip()
        if not new_claim:
            result.append(finding)
            continue
        result.append(replace(finding, claim=new_claim))
    return result
