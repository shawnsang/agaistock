"""点评师统一契约。

设计依据：docs/superpowers/specs/2026-11-24-reviewer-layer-and-chanlun-reviewer-design.md §2
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

SEVERITIES = ("critical", "high", "medium", "low", "info")
STATUSES = ("ok", "partial", "skipped", "error")
HORIZON_TIERS = ("short", "mid", "long", "event")
PROTECTED_FIELDS = ("code", "severity", "dimension", "delta", "evidence_ref")


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    dimension: str
    delta: int
    claim: str
    why: str
    evidence_ref: list[str] = field(default_factory=list)
    suggested_fix: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "dimension": self.dimension,
            "delta": self.delta,
            "claim": self.claim,
            "why": self.why,
            "evidence_ref": list(self.evidence_ref),
            "suggested_fix": self.suggested_fix,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Finding":
        return cls(
            code=data.get("code", ""),
            severity=data.get("severity", ""),
            dimension=data.get("dimension", ""),
            delta=data.get("delta"),
            claim=data.get("claim", ""),
            why=data.get("why", ""),
            evidence_ref=list(data.get("evidence_ref") or []),
            suggested_fix=data.get("suggested_fix", ""),
        )


@dataclass(frozen=True)
class ProposedInvalidation:
    desc: str
    source: str
    comparator: str
    tolerance: float | None = None
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "desc": self.desc,
            "source": self.source,
            "comparator": self.comparator,
            "tolerance": self.tolerance,
            "rationale": self.rationale,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ProposedInvalidation":
        return cls(
            desc=data.get("desc", ""),
            source=data.get("source", ""),
            comparator=data.get("comparator", ""),
            tolerance=data.get("tolerance"),
            rationale=data.get("rationale", ""),
        )


@dataclass(frozen=True)
class HorizonHint:
    tier: str
    rationale: str
    checks: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"tier": self.tier, "rationale": self.rationale, "checks": list(self.checks)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HorizonHint":
        return cls(
            tier=data.get("tier", ""),
            rationale=data.get("rationale", ""),
            checks=list(data.get("checks") or []),
        )


@dataclass(frozen=True)
class ReviewVerdict:
    reviewer_id: str
    reviewer_version: str
    ran_at: str
    status: str
    duration_ms: int = 0
    data_refs: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    proposed_invalidation: list[ProposedInvalidation] = field(default_factory=list)
    horizon_hint: HorizonHint | None = None
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "reviewer_id": self.reviewer_id,
            "reviewer_version": self.reviewer_version,
            "ran_at": self.ran_at,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "data_refs": list(self.data_refs),
            "findings": [f.to_dict() for f in self.findings],
            "proposed_invalidation": [p.to_dict() for p in self.proposed_invalidation],
            "horizon_hint": self.horizon_hint.to_dict() if self.horizon_hint else None,
            "caveats": list(self.caveats),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewVerdict":
        hint = data.get("horizon_hint")
        return cls(
            reviewer_id=data.get("reviewer_id", ""),
            reviewer_version=data.get("reviewer_version", ""),
            ran_at=data.get("ran_at", ""),
            status=data.get("status", ""),
            duration_ms=int(data.get("duration_ms") or 0),
            data_refs=list(data.get("data_refs") or []),
            findings=[Finding.from_dict(f) for f in (data.get("findings") or [])],
            proposed_invalidation=[
                ProposedInvalidation.from_dict(p) for p in (data.get("proposed_invalidation") or [])
            ],
            horizon_hint=HorizonHint.from_dict(hint) if hint else None,
            caveats=list(data.get("caveats") or []),
        )


@dataclass
class ReviewContext:
    observation: dict
    symbol: str
    name: str
    now: str
    data_dir: Path
    llm: Any = None
    prior_reviews: list[ReviewVerdict] = field(default_factory=list)


class Reviewer(Protocol):
    id: str
    version: str

    def review(self, ctx: ReviewContext) -> ReviewVerdict: ...


def validate_verdict(verdict: ReviewVerdict, dimensions: list[str]) -> list[str]:
    """返回错误信息列表；空列表表示合法。"""
    errors: list[str] = []
    if verdict.status not in STATUSES:
        errors.append(f"status 非法: {verdict.status!r}，允许 {STATUSES}")
    if not verdict.reviewer_id:
        errors.append("reviewer_id 为空")
    if not verdict.reviewer_version:
        errors.append("reviewer_version 为空")
    for index, finding in enumerate(verdict.findings):
        if finding.severity not in SEVERITIES:
            errors.append(f"findings[{index}].severity 非法: {finding.severity!r}")
        if not finding.dimension:
            errors.append(f"findings[{index}].dimension 为空")
        elif finding.dimension not in dimensions:
            errors.append(
                f"findings[{index}].dimension 未定义: {finding.dimension!r}，允许 {dimensions}"
            )
        if finding.delta is None or not isinstance(finding.delta, int):
            errors.append(f"findings[{index}].delta 必须为整数")
    if verdict.horizon_hint is not None and verdict.horizon_hint.tier not in HORIZON_TIERS:
        errors.append(f"horizon_hint.tier 非法: {verdict.horizon_hint.tier!r}")
    # 硬约束：有发现就必须随结论一起给出限制声明（设计文档 §2.2）。
    # 没有发现的点评师（如 skipped）不需要限制声明，不在此处报错。
    if verdict.findings and not verdict.caveats:
        missing = ", ".join(f"[{i}]{f.code}" for i, f in enumerate(verdict.findings))
        errors.append(
            f"caveats 为空：以下 finding 缺少限制声明（{missing}）；"
            "限制声明缺失等于把机械结论当结论"
        )
    return errors
