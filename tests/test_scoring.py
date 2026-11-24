import unittest

from agaistock.reviewers.contract import Finding, ReviewVerdict
from agaistock import scoring


def verdict(reviewer_id, dimension, delta, code="X"):
    return ReviewVerdict(
        reviewer_id=reviewer_id, reviewer_version="0.1.0", ran_at="2026-11-24T07:00:00Z",
        status="ok", duration_ms=0, data_refs=[],
        findings=[Finding(code=code, severity="medium", dimension=dimension, delta=delta,
                          claim="c", why="w", evidence_ref=[], suggested_fix="")],
        proposed_invalidation=[], horizon_hint=None, caveats=[],
    )


DIMENSIONS = [
    {"name": "事实锚定", "weight": 0.25},
    {"name": "证伪条件", "weight": 0.25},
    {"name": "逻辑链条", "weight": 0.20},
    {"name": "位置与时机", "weight": 0.15},
    {"name": "一致性", "weight": 0.15},
]


class ScoringTests(unittest.TestCase):
    def test_no_reviewer_dimension_is_excluded_not_zeroed(self):
        result = scoring.aggregate([], dimensions=DIMENSIONS)
        entry = next(e for e in result["score_breakdown"] if e["dimension"] == "事实锚定")
        self.assertEqual(entry["completeness"], "no_reviewer")
        self.assertIsNone(entry["raw"])
        self.assertIsNone(entry["weighted"])
        self.assertEqual(result["score_denominator"], 0.0)

    def test_dimensions_with_findings_are_summed_across_reviewers(self):
        verdicts = [
            verdict("a", "位置与时机", -12, "A1"),
            verdict("b", "位置与时机", -8, "B1"),
        ]
        result = scoring.aggregate(verdicts, dimensions=DIMENSIONS)
        entry = next(e for e in result["score_breakdown"] if e["dimension"] == "位置与时机")
        self.assertEqual(entry["raw"], 80)  # 100 - 12 - 8
        self.assertEqual(entry["completeness"], "ok")
        self.assertEqual(len(entry["contributions"]), 2)

    def test_total_is_weighted_average_over_scored_dimensions_only(self):
        verdicts = [verdict("a", "位置与时机", -12)]
        result = scoring.aggregate(verdicts, dimensions=DIMENSIONS)
        self.assertAlmostEqual(result["total"], 88.0)
        self.assertAlmostEqual(result["score_denominator"], 0.15)
        self.assertEqual(result["scored_dimensions"], ["位置与时机"])

    def test_neutral_finding_scores_full_marks_and_is_marked_ok(self):
        verdicts = [verdict("a", "位置与时机", 0)]
        result = scoring.aggregate(verdicts, dimensions=DIMENSIONS)
        entry = next(e for e in result["score_breakdown"] if e["dimension"] == "位置与时机")
        self.assertEqual(entry["raw"], 100)
        self.assertEqual(entry["completeness"], "ok")

    def test_reviewer_weight_scales_delta(self):
        verdicts = [verdict("a", "位置与时机", -12)]
        result = scoring.aggregate(verdicts, reviewer_weights={"a": 0.5}, dimensions=DIMENSIONS)
        entry = next(e for e in result["score_breakdown"] if e["dimension"] == "位置与时机")
        self.assertEqual(entry["raw"], 94)  # 100 - 12*0.5

    def test_contributions_reference_finding_codes(self):
        verdicts = [verdict("a", "位置与时机", -12, "CHAN_X")]
        result = scoring.aggregate(verdicts, dimensions=DIMENSIONS)
        entry = next(e for e in result["score_breakdown"] if e["dimension"] == "位置与时机")
        self.assertEqual(entry["contributions"][0]["finding_codes"], ["CHAN_X"])

    def test_contribution_exposes_the_applied_delta_so_raw_can_be_reconciled(self):
        # 主规格 §5.3：每一分必须可追溯到具体 Finding。
        # 只给未缩放的 delta 时，weight != 1 的情况下展示层算不平 raw。
        verdicts = [verdict("a", "位置与时机", -12)]
        result = scoring.aggregate(verdicts, reviewer_weights={"a": 0.5}, dimensions=DIMENSIONS)
        entry = next(e for e in result["score_breakdown"] if e["dimension"] == "位置与时机")
        contribution = entry["contributions"][0]
        self.assertEqual(contribution["delta"], -12)
        self.assertEqual(contribution["applied_delta"], -6)
        # raw 必须等于 100 + 各 contribution 的 applied_delta 之和
        self.assertEqual(
            entry["raw"],
            100 + sum(c["applied_delta"] for c in entry["contributions"]),
        )


if __name__ == "__main__":
    unittest.main()
