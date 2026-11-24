import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from agaistock.reviewers.contract import Finding, ReviewContext
from agaistock.skills.anchor_chanlun import reviewer


def make_structure():
    return {
        "levels": {
            "week": {"bias": "down", "trend_direction": "down", "signal": "无明确买卖点",
                     "window_verdict": "结构充分", "nearby_pivots": [], "recent_divergence": None},
            "day": {"bias": "down", "trend_direction": "down", "signal": "中枢下方 · 底背驰预警",
                    "window_verdict": "结构充分", "nearby_pivots": [], "recent_divergence": None},
            "m30": {"bias": "range", "trend_direction": "range", "signal": "无明确买卖点",
                    "window_verdict": "结构充分", "nearby_pivots": [], "recent_divergence": None},
        },
        # 档位字母在 grade 上，level 是中文定性（见 Global Constraint 8）
        "resonance": {"grade": "C", "level": "级别交错"},
        "interval_nesting": {"verdict": "unconfirmed", "reason": "次级别尚无背驰"},
        "window_alignment": {"density_balance": "balanced", "over_wide_levels": []},
        "key_levels": {"bands": []},
        # 上游结构自己的限制声明不能是空的
        "caveats": ["上游结构识别基于固定窗口，样本偏薄时结论需降级使用"],
    }


class ReviewerTests(unittest.TestCase):
    def test_reviewer_id_and_version(self):
        r = reviewer.Reviewer()
        self.assertEqual(r.id, "anchor-chanlun")
        self.assertEqual(r.version, "0.1.0")

    def test_review_returns_valid_verdict(self):
        structure = make_structure()
        with TemporaryDirectory() as tmp:
            ctx = ReviewContext(
                observation={"symbol": "002378", "direction": "bullish", "thesis": "还能拿半年",
                             "timeframe": "半年", "trigger": ""},
                symbol="002378", name="章源钨业", now="2026-11-24T07:30:00Z",
                data_dir=Path(tmp), llm=None,
            )
            with mock.patch.object(reviewer, "build_structure", return_value=structure), \
                 mock.patch.object(reviewer, "fetch_last_close", return_value=15.54):
                verdict = reviewer.Reviewer().review(ctx)

        self.assertEqual(verdict.reviewer_id, "anchor-chanlun")
        self.assertEqual(verdict.status, "ok")
        self.assertTrue(verdict.findings)
        # 有发现就必须有限制声明：否则契约校验不通过，engine.run_one 会把整条结论丢掉
        self.assertTrue(verdict.caveats)
        self.assertIsNotNone(verdict.horizon_hint)
        self.assertTrue(verdict.data_refs)

    def test_review_folds_contract_validation_errors_into_caveats(self):
        bad_finding = Finding(
            code="CHAN_X", severity="medium", dimension="第六感", delta=-1,
            claim="c", why="w", evidence_ref=[], suggested_fix="",
        )
        with TemporaryDirectory() as tmp:
            ctx = ReviewContext(
                observation={"symbol": "002378", "direction": "bullish", "thesis": "还能拿半年",
                             "timeframe": "半年", "trigger": ""},
                symbol="002378", name="章源钨业", now="2026-11-24T07:30:00Z",
                data_dir=Path(tmp), llm=None,
            )
            with mock.patch.object(reviewer, "build_structure", return_value=make_structure()), \
                 mock.patch.object(reviewer, "fetch_last_close", return_value=15.54), \
                 mock.patch.object(reviewer.rules, "evaluate", return_value=([bad_finding], [])):
                verdict = reviewer.Reviewer().review(ctx)

        # 校验错误不吞结论，但要显式写进 caveats
        self.assertTrue(any("契约校验" in c for c in verdict.caveats))

    def test_review_skips_when_symbol_missing(self):
        ctx = ReviewContext(
            observation={"symbol": ""}, symbol="", name="", now="t",
            data_dir=Path("."), llm=None,
        )
        verdict = reviewer.Reviewer().review(ctx)
        self.assertEqual(verdict.status, "skipped")


if __name__ == "__main__":
    unittest.main()
