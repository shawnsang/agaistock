import unittest

from agaistock.reviewers import contract, engine


class BoomReviewer:
    id = "boom"
    version = "0.1.0"

    def review(self, ctx):
        raise RuntimeError("炸了")


class OkReviewer:
    id = "ok"
    version = "0.1.0"

    def review(self, ctx):
        return contract.ReviewVerdict(
            reviewer_id="ok", reviewer_version="0.1.0", ran_at="2026-11-24T07:00:00Z",
            status="ok", duration_ms=5, data_refs=[], findings=[], proposed_invalidation=[],
            horizon_hint=None, caveats=["c"],
        )


class UnknownDimensionReviewer:
    """返回的 finding 用了未定义的维度，应被引擎拦成 error verdict。"""

    id = "unknown-dimension"
    version = "0.1.0"

    def review(self, ctx):
        return contract.ReviewVerdict(
            reviewer_id="unknown-dimension", reviewer_version="0.1.0",
            ran_at="2026-11-24T07:00:00Z", status="ok", duration_ms=5, data_refs=[],
            findings=[
                contract.Finding(
                    code="X1", severity="high", dimension="不存在的维度", delta=-1,
                    claim="结论", why="理由",
                )
            ],
            proposed_invalidation=[], horizon_hint=None, caveats=["c"],
        )


class EngineTests(unittest.TestCase):
    def test_run_one_wraps_exception_into_error_verdict(self):
        ctx = contract.ReviewContext(
            observation={}, symbol="002378", name="章源钨业", now="t",
            data_dir=".", llm=None,
        )
        verdict = engine.run_one(BoomReviewer(), ctx)
        self.assertEqual(verdict.status, "error")
        self.assertIn("炸了", verdict.caveats[0])

    def test_run_reviews_isolates_failures_and_keeps_both(self):
        ctx = contract.ReviewContext(
            observation={}, symbol="002378", name="章源钨业", now="t",
            data_dir=".", llm=None,
        )
        results = engine.run_reviewers([BoomReviewer(), OkReviewer()], ctx)
        statuses = sorted(r.status for r in results)
        self.assertEqual(statuses, ["error", "ok"])

    def test_run_one_rejects_verdict_with_unknown_dimension(self):
        ctx = contract.ReviewContext(
            observation={}, symbol="002378", name="章源钨业", now="t",
            data_dir=".", llm=None,
        )
        verdict = engine.run_one(UnknownDimensionReviewer(), ctx)
        self.assertEqual(verdict.status, "error")
        self.assertEqual(verdict.findings, [])
        self.assertIn("不存在的维度", " ".join(verdict.caveats))


if __name__ == "__main__":
    unittest.main()
