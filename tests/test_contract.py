import unittest

from agaistock.reviewers import contract


def make_finding(**overrides):
    base = dict(
        code="CHAN_DAY_TOP_DIVERGENCE",
        severity="critical",
        dimension="位置与时机",
        delta=-12,
        claim="日线顶背驰成立",
        why="与大级别动能背离",
        evidence_ref=["chan.levels.day.recent_divergence"],
        suggested_fix="降级为反弹参与",
    )
    base.update(overrides)
    return contract.Finding(**base)


class ContractTests(unittest.TestCase):
    def test_finding_to_dict_keeps_all_fields(self):
        data = make_finding().to_dict()
        self.assertEqual(data["code"], "CHAN_DAY_TOP_DIVERGENCE")
        self.assertEqual(data["dimension"], "位置与时机")
        self.assertEqual(data["delta"], -12)
        self.assertIn("evidence_ref", data)

    def test_verdict_round_trips_through_dict(self):
        verdict = contract.ReviewVerdict(
            reviewer_id="anchor-chanlun",
            reviewer_version="0.1.0",
            ran_at="2026-11-24T07:30:00Z",
            status="ok",
            duration_ms=1234,
            data_refs=[{"source": "tdx_kline"}],
            findings=[make_finding()],
            proposed_invalidation=[
                contract.ProposedInvalidation(
                    desc="跌破日线中枢下沿 22.39",
                    source="chan.levels.day.nearby_pivots[].ZD",
                    comparator="below",
                    tolerance=0.5,
                    rationale="中枢下沿是结构失效位",
                )
            ],
            horizon_hint=contract.HorizonHint(tier="short", rationale="顶背驰", checks=[]),
            caveats=["背驰 active 不代表仍成立"],
        )
        restored = contract.ReviewVerdict.from_dict(verdict.to_dict())
        self.assertEqual(restored.findings[0].code, "CHAN_DAY_TOP_DIVERGENCE")
        self.assertEqual(restored.proposed_invalidation[0].comparator, "below")
        self.assertEqual(restored.horizon_hint.tier, "short")
        self.assertEqual(restored.caveats, ["背驰 active 不代表仍成立"])

    def test_validate_rejects_unknown_severity(self):
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="ok",
            duration_ms=0, data_refs=[], findings=[make_finding(severity="致命")],
            proposed_invalidation=[], horizon_hint=None, caveats=[],
        )
        errors = contract.validate_verdict(verdict, ["位置与时机"])
        self.assertTrue(any("severity" in e for e in errors))

    def test_validate_rejects_unknown_dimension(self):
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="ok",
            duration_ms=0, data_refs=[], findings=[make_finding(dimension="第六感")],
            proposed_invalidation=[], horizon_hint=None, caveats=[],
        )
        errors = contract.validate_verdict(verdict, ["位置与时机"])
        self.assertTrue(any("dimension" in e for e in errors))

    def test_validate_rejects_missing_dimension(self):
        finding = make_finding()
        object.__setattr__(finding, "dimension", "")
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="ok",
            duration_ms=0, data_refs=[], findings=[finding],
            proposed_invalidation=[], horizon_hint=None, caveats=[],
        )
        errors = contract.validate_verdict(verdict, ["位置与时机"])
        self.assertTrue(any("dimension" in e for e in errors))

    def test_validate_rejects_missing_delta(self):
        finding = make_finding()
        object.__setattr__(finding, "delta", None)
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="ok",
            duration_ms=0, data_refs=[], findings=[finding],
            proposed_invalidation=[], horizon_hint=None, caveats=[],
        )
        errors = contract.validate_verdict(verdict, ["位置与时机"])
        self.assertTrue(any("delta" in e for e in errors))

    def test_validate_rejects_unknown_status(self):
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="也许",
            duration_ms=0, data_refs=[], findings=[], proposed_invalidation=[],
            horizon_hint=None, caveats=[],
        )
        errors = contract.validate_verdict(verdict, ["位置与时机"])
        self.assertTrue(any("status" in e for e in errors))

    def test_validate_accepts_a_well_formed_verdict(self):
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="ok",
            duration_ms=0, data_refs=[], findings=[make_finding()],
            proposed_invalidation=[], horizon_hint=None, caveats=["c"],
        )
        self.assertEqual(contract.validate_verdict(verdict, ["位置与时机"]), [])

    def test_validate_rejects_missing_caveats_when_findings_present(self):
        """有发现却没有任何限制声明 —— 把机械结论当结论，必须判为非法。"""
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="ok",
            duration_ms=0, data_refs=[], findings=[make_finding()],
            proposed_invalidation=[], horizon_hint=None, caveats=[],
        )
        errors = contract.validate_verdict(verdict, ["位置与时机"])
        self.assertTrue(errors)
        self.assertTrue(any("caveats" in e for e in errors))
        # 错误信息要指明是哪些 finding 缺少限制声明
        self.assertTrue(any("CHAN_DAY_TOP_DIVERGENCE" in e for e in errors))

    def test_validate_allows_empty_caveats_without_findings(self):
        """没有发现的点评师（如 skipped）不需要限制声明，不得因此判为非法。"""
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="skipped",
            duration_ms=0, data_refs=[], findings=[], proposed_invalidation=[],
            horizon_hint=None, caveats=[],
        )
        self.assertEqual(contract.validate_verdict(verdict, ["位置与时机"]), [])

    def test_validate_accepts_findings_with_caveats(self):
        verdict = contract.ReviewVerdict(
            reviewer_id="x", reviewer_version="0.1.0", ran_at="t", status="ok",
            duration_ms=0, data_refs=[], findings=[make_finding()],
            proposed_invalidation=[], horizon_hint=None,
            caveats=["背驰 active 不代表仍成立"],
        )
        self.assertEqual(contract.validate_verdict(verdict, ["位置与时机"]), [])

    def test_empty_reviewer_version_is_rejected(self):
        verdict = contract.ReviewVerdict(
            reviewer_id="anchor-chanlun",
            reviewer_version="",
            ran_at="2026-11-24T07:30:00Z",
            status="ok",
            duration_ms=0,
            data_refs=[],
            findings=[],
            proposed_invalidation=[],
            horizon_hint=None,
            caveats=[],
        )
        errors = contract.validate_verdict(verdict, ["位置与时机"])
        self.assertTrue(any("reviewer_version" in err for err in errors))


if __name__ == "__main__":
    unittest.main()
