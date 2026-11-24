"""评分聚合：把多家点评师的 findings 按固定维度汇总。

规则（设计文档 §5.2）：
  - 同一维度多家点评师的 delta 直接相加
  - 没有点评师贡献的维度从加权平均的分子分母一并剔除，并标 no_reviewer
  - 「有人点评且结论中性」(delta=0) 与「无人点评」是不同的事，不可混淆
"""
from __future__ import annotations

from typing import Any

from .reviewers.contract import ReviewVerdict


def aggregate(
    verdicts: list[ReviewVerdict],
    reviewer_weights: dict[str, float] | None = None,
    dimensions: list[dict] | None = None,
) -> dict[str, Any]:
    if dimensions is None:
        from . import config

        dimensions = config.load_scoring()["dimensions"]

    weights = reviewer_weights or {}

    breakdown: list[dict[str, Any]] = []
    numerator = 0.0
    denominator = 0.0
    scored_dimensions: list[str] = []

    for dimension in dimensions:
        name = dimension["name"]
        weight = float(dimension["weight"])
        contributions: list[dict[str, Any]] = []
        total_delta = 0.0
        for verdict in verdicts:
            reviewer_weight = float(weights.get(verdict.reviewer_id, 1.0))
            matched = [f for f in verdict.findings if f.dimension == name]
            if not matched:
                continue
            delta = sum(f.delta for f in matched)
            total_delta += delta * reviewer_weight
            contributions.append({
                "reviewer_id": verdict.reviewer_id,
                "finding_codes": [f.code for f in matched],
                # delta 是这条 finding 自己的分值；applied_delta 是乘上点评师权重后
                # 真正计入 raw 的值。两者都要给：主规格 §5.3 要求「每一分必须可追溯到
                # 具体 Finding」，展示层若只用 delta 去解释 raw，weight != 1 时算不平。
                "delta": delta,
                "applied_delta": delta * reviewer_weight,
                "weight": reviewer_weight,
            })

        if not contributions:
            breakdown.append({
                "dimension": name,
                "weight": weight,
                "raw": None,
                "weighted": None,
                "completeness": "no_reviewer",
                "contributions": [],
            })
            continue

        raw = 100.0 + total_delta
        weighted = raw * weight
        numerator += weighted
        denominator += weight
        scored_dimensions.append(name)
        breakdown.append({
            "dimension": name,
            "weight": weight,
            "raw": raw,
            "weighted": weighted,
            "completeness": "ok",
            "contributions": contributions,
        })

    total = (numerator / denominator) if denominator > 0 else 0.0

    return {
        "total": total,
        "score_breakdown": breakdown,
        "scored_dimensions": scored_dimensions,
        "score_denominator": denominator,
    }
