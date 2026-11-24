import unittest

from agaistock.horizon import resolve_tier, plan
from agaistock.reviewers.contract import HorizonHint, ProposedInvalidation, ReviewVerdict


def verdict_with_tier(reviewer_id, tier):
    return ReviewVerdict(
        reviewer_id=reviewer_id, reviewer_version="0.1.0", ran_at="2026-11-24T07:00:00Z",
        status="ok", duration_ms=0, data_refs=[], findings=[], proposed_invalidation=[],
        horizon_hint=HorizonHint(tier=tier, rationale="r", checks=[]), caveats=[],
    )


class HorizonTests(unittest.TestCase):
    def test_resolve_tier_takes_the_most_conservative(self):
        tier, sources = resolve_tier([verdict_with_tier("a", "long"), verdict_with_tier("b", "short")])
        self.assertEqual(tier, "short")
        self.assertEqual(len(sources), 2)

    def test_resolve_tier_returns_none_without_hints(self):
        tier, sources = resolve_tier([verdict_with_tier("a", "long")])
        self.assertEqual(tier, "long")
        tier, sources = resolve_tier([])
        self.assertIsNone(tier)

    def test_plan_review_at_falls_inside_allowed_window(self):
        plan_result = plan(
            {"symbol": "002378", "thesis": "t"},
            [verdict_with_tier("a", "short")],
            start="2026-11-24",
        )
        self.assertIn(plan_result["review_at"], ("2026-11-27", "2026-12-01"))
        self.assertTrue(plan_result["allowed_window"])

    def test_plan_uses_proposed_invalidation_as_checks(self):
        verdict = ReviewVerdict(
            reviewer_id="a", reviewer_version="0.1.0", ran_at="t", status="ok", duration_ms=0,
            data_refs=[], findings=[],
            proposed_invalidation=[
                ProposedInvalidation(
                    desc="跌破 22.39", source="chan.pivot.ZD",
                    comparator="below", tolerance=0.5, rationale="结构失效位",
                )
            ],
            horizon_hint=None, caveats=[],
        )
        plan_result = plan({"symbol": "002378"}, [verdict], start="2026-11-24")
        self.assertEqual(len(plan_result["checks"]), 1)
        self.assertEqual(plan_result["checks"][0]["desc"], "跌破 22.39")
        self.assertEqual(plan_result["invalidation_triggers"], ["跌破 22.39"])

    def test_plan_checks_keep_the_rationale(self):
        # rationale 必须跟着 check 一起传到 UI：中枢在头顶时「跌破下沿」的条件已经成立，
        # 只作结构参考 —— 丢掉 rationale 就会被展示成待触发的失效条件。
        verdict = ReviewVerdict(
            reviewer_id="a", reviewer_version="0.1.0", ran_at="t", status="ok", duration_ms=0,
            data_refs=[], findings=[],
            proposed_invalidation=[
                ProposedInvalidation(
                    desc="跌破 22.39", source="chan.pivot.ZD",
                    comparator="below", tolerance=0.5, rationale="中枢位于现价上方，只作结构参考",
                )
            ],
            horizon_hint=None, caveats=[],
        )
        plan_result = plan({"symbol": "002378"}, [verdict], start="2026-11-24")
        self.assertEqual(plan_result["checks"][0]["rationale"], "中枢位于现价上方，只作结构参考")

    def test_resolve_tier_prefers_event_over_long(self):
        # event 的窗口 (5,10,20) 比 long 的 (10,20,40) 更保守，必须取 event。
        tier, sources = resolve_tier([
            verdict_with_tier("a", "event"), verdict_with_tier("b", "long"),
        ])
        self.assertEqual(tier, "event")
        self.assertEqual(len(sources), 2)

    def test_plan_without_any_hint_still_returns_structure(self):
        plan_result = plan({"symbol": "002378"}, [], start="2026-11-24")
        self.assertIn("tier", plan_result)
        self.assertIn("checks", plan_result)

    def test_explicit_review_at_on_an_allowed_offset_keeps_the_full_window(self):
        # 档位里的天数是**交易日**偏移。显式传入的日期如果正好是
        # `_trading_days_later(start, 10)` 的结果，就不该被误判成「不在档位内」
        # 而把 40 天的窗口塌缩成 10 天。
        result = plan(
            {"symbol": "002378"},
            [verdict_with_tier("a", "long")],
            start="2026-11-24",
            review_at="2026-12-08",  # 2026-11-24 起第 10 个交易日
        )
        self.assertEqual(result["review_at"], "2026-12-08")
        # 窗口没被塌缩：末位不是 review_at 本身
        self.assertNotEqual(result["allowed_window"][1], "2026-12-08")
        self.assertEqual(result["allowed_window"][0], "2026-11-24")

    def test_review_at_outside_the_allowed_offsets_falls_back_to_the_earliest(self):
        # 越界的日期必须被拉回档位内最早的那个，而且 review_at 一定要落在
        # allowed_window 之内（不能出现「返回的日期在自己的窗口之外」）。
        result = plan(
            {"symbol": "002378"},
            [verdict_with_tier("a", "long")],
            start="2026-11-24",
            review_at="2027-02-01",
        )
        self.assertEqual(result["review_at"], "2026-12-08")
        self.assertIn(result["review_at"], (
            result["allowed_window"][0],
            result["allowed_window"][1],
        ))
        self.assertEqual(result["allowed_window"][1], "2026-12-08")

    def test_explicit_review_at_on_weekend_lands_on_trading_day(self):
        # 2026-11-29 是周日：结算日不能落在非交易日。
        # 推进到交易日后偏移可能冲出 allowed —— 回退分支必须把它收回来，
        # 保证 review_at 既是非交易日、也落在 allowed_window 之内。
        from datetime import date
        plan_result = plan(
            {"symbol": "002378", "thesis": "t"},
            [verdict_with_tier("a", "short")],
            start="2026-11-20",
            review_at="2026-11-29",
        )
        chosen = date.fromisoformat(plan_result["review_at"])
        self.assertLess(chosen.weekday(), 5, "review_at 不能落在周末")
        start, end = plan_result["allowed_window"]
        self.assertGreaterEqual(chosen, date.fromisoformat(start))
        self.assertLessEqual(chosen, date.fromisoformat(end))


if __name__ == "__main__":
    unittest.main()
