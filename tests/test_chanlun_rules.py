import unittest

from agaistock.skills.anchor_chanlun import rules, signals


def structure(**overrides):
    base = {
        "levels": {
            "week": {"bias": "up", "trend_direction": "up", "signal": "无明确买卖点",
                     "bias_zh": "偏强", "signal_detail": {"type": "无明确买卖点", "basis": "结构不明确"},
                     "window_verdict": "结构充分", "nearby_pivots": [],
                     "recent_divergence": None, "divergence_hint": None,
                     "may_be_partial": False, "last_close": 15.54},
            "day": {"bias": "down", "trend_direction": "down", "signal": "中枢下方 · 底背驰预警",
                    "bias_zh": "偏弱", "signal_detail": {"type": "中枢下方 · 底背驰预警", "basis": "价格仍在中枢之下"},
                    "window_verdict": "结构充分", "nearby_pivots": [],
                    "recent_divergence": None, "divergence_hint": None,
                    "may_be_partial": False, "last_close": 15.54},
            "m30": {"bias": "range", "trend_direction": "range", "signal": "无明确买卖点",
                    "bias_zh": "震荡", "signal_detail": {"type": "无明确买卖点", "basis": "结构不明确"},
                    "window_verdict": "结构充分", "nearby_pivots": [],
                    "recent_divergence": None, "divergence_hint": None,
                    "may_be_partial": False, "last_close": 15.54},
        },
        "resonance": {"grade": "C", "level": "级别交错", "detail": "…",
                       "same_direction": False, "conflict_level": "mixed"},
        "interval_nesting": {"verdict": "unconfirmed", "reason": "次级别尚无背驰"},
        "window_alignment": {"density_balance": "balanced", "over_wide_levels": []},
        "key_levels": {"bands": []},
        "caveats": [],
    }
    base.update(overrides)
    return base


BULLISH = {"direction": "bullish", "thesis": "还能拿半年", "confidence": 0.72}


class RulesTests(unittest.TestCase):
    def test_higher_level_denial_when_week_is_down_and_user_is_bullish(self):
        st = structure()
        st["levels"]["week"]["bias"] = "down"
        findings, _ = rules.evaluate(BULLISH, st, 15.54)
        codes = [f.code for f in findings]
        self.assertIn("CHAN_HIGHER_LEVEL_DENIES", codes)

    def test_no_higher_level_denial_when_week_is_up(self):
        findings, _ = rules.evaluate(BULLISH, structure(), 15.54)
        self.assertNotIn("CHAN_HIGHER_LEVEL_DENIES", [f.code for f in findings])

    def test_direction_conflict_against_day_signal(self):
        st = structure()
        st["levels"]["day"]["signal"] = "中枢上方 · 顶背驰预警"
        findings, _ = rules.evaluate(BULLISH, st, 15.54)
        codes = [f.code for f in findings]
        self.assertIn("CHAN_DIRECTION_CONFLICT", codes)

    def test_position_vs_trend_mismatch_is_info_only(self):
        st = structure()
        st["levels"]["week"]["bias"] = "up"
        st["levels"]["week"]["trend_direction"] = "down"
        findings, caveats = rules.evaluate(BULLISH, st, 15.54)
        matching = [f for f in findings if f.code == "CHAN_POSITION_VS_TREND"]
        self.assertTrue(matching)
        self.assertEqual(matching[0].delta, 0)
        self.assertTrue(any("位置" in c for c in caveats))

    def test_position_vs_trend_mismatch_is_detected_on_m30_level(self):
        st = structure()
        st["levels"]["m30"]["bias"] = "up"
        st["levels"]["m30"]["trend_direction"] = "down"
        findings, _ = rules.evaluate(BULLISH, st, 15.54)
        matching = [f for f in findings if f.code == "CHAN_POSITION_VS_TREND"]
        self.assertTrue(matching)
        self.assertEqual(matching[0].delta, 0)
        self.assertTrue(any("chan.levels.m30.bias" in f.evidence_ref for f in matching))

    def test_evaluate_always_returns_a_caveat_when_there_are_findings(self):
        findings, caveats = rules.evaluate(BULLISH, structure(), 15.54)
        self.assertTrue(findings)
        self.assertTrue(caveats)

    def test_every_finding_has_dimension_and_nonzero_or_zero_delta(self):
        st = structure()
        st["levels"]["week"]["bias"] = "down"
        findings, _ = rules.evaluate(BULLISH, st, 15.54)
        self.assertTrue(findings)
        for f in findings:
            self.assertIn(f.dimension, ("事实锚定", "证伪条件", "逻辑链条", "位置与时机", "一致性"))
            self.assertIsInstance(f.delta, int)

    def test_caveats_mention_divergence_must_be_rechecked(self):
        st = structure()
        st["levels"]["day"]["recent_divergence"] = {"active": True, "kind": "bottom"}
        _, caveats = rules.evaluate(BULLISH, st, 15.54)
        self.assertTrue(any("active" in c for c in caveats))

    def test_nesting_unconfirmed_produces_finding(self):
        findings, _ = rules.evaluate(BULLISH, structure(), 15.54)
        self.assertIn("CHAN_NESTING_UNCONFIRMED", [f.code for f in findings])

    def test_no_partial_caveat_when_all_levels_closed(self):
        _, caveats = rules.evaluate(BULLISH, structure(), 15.54)
        self.assertFalse(any("未收盘" in c for c in caveats))

    def test_partial_caveat_when_a_level_is_still_open(self):
        st = structure()
        st["levels"]["day"]["may_be_partial"] = True
        _, caveats = rules.evaluate(BULLISH, st, 15.54)
        self.assertTrue(any("未收盘" in c for c in caveats))


class SignalsTests(unittest.TestCase):
    def test_build_invalidation_uses_pivot_zd(self):
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2026-02-05", "to": "2026-09-22", "ZD": 22.39, "ZG": 29.04,
             "role": "recent", "dist_pct": 44.08}
        ]
        result = signals.build_invalidation(st, 15.54)
        descs = [p.desc for p in result]
        self.assertTrue(any("22.39" in d for d in descs))

    def test_build_invalidation_uses_support_band_below_price(self):
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2025-08-04", "to": "2026-02-05", "ZD": 11.84, "ZG": 14.05,
             "role": "support", "dist_pct": -9.59}
        ]
        result = signals.build_invalidation(st, 15.54)
        self.assertTrue(any(p.comparator == "below" for p in result))

    def test_build_invalidation_emits_below_level_when_price_is_inside_band(self):
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2025-08-04", "to": "2026-02-05", "ZD": 11.84, "ZG": 14.05,
             "role": "current", "dist_pct": -9.59}
        ]
        result = signals.build_invalidation(st, 13.0)
        below = [p for p in result if p.comparator == "below"]
        self.assertTrue(below)
        self.assertTrue(any("11.84" in p.desc for p in below))

    def test_build_invalidation_keeps_levels_far_below_price(self):
        # 证伪位不按「距现价远近」过滤：远在脚下的中枢下沿同样是有效的失效位。
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2023-01-04", "to": "2023-05-04", "ZD": 8.0, "ZG": 9.0,
             "role": "support", "dist_pct": -42.0}
        ]
        result = signals.build_invalidation(st, 15.54)
        self.assertTrue(any("8.0" in p.desc for p in result))

    def test_build_horizon_hint_takes_most_conservative(self):
        st = structure()
        st["levels"]["day"]["signal"] = "中枢上方 · 顶背驰预警"
        hint = signals.build_horizon_hint(BULLISH, st, [], last_close=15.54)
        self.assertEqual(hint.tier, "short")

    def test_build_horizon_hint_is_event_when_trigger_present(self):
        obs = dict(BULLISH)
        obs["trigger"] = "2026-12-01 产量公告"
        hint = signals.build_horizon_hint(obs, structure(), [], last_close=15.54)
        self.assertIn(hint.tier, ("event", "short"))

    def test_build_horizon_hint_checks_use_real_last_close(self):
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2026-02-05", "to": "2026-09-22", "ZD": 22.39, "ZG": 29.04,
             "role": "recent", "dist_pct": 44.08}
        ]
        hint = signals.build_horizon_hint(BULLISH, st, [], last_close=15.54)
        self.assertTrue(hint.checks)

    def test_build_invalidation_with_unknown_last_close_does_not_claim_it_already_broke(self):
        # last_close <= 0 = 现价未知。此时不能说「跌破下沿属于已发生的事实」。
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2026-02-05", "to": "2026-09-22", "ZD": 22.39, "ZG": 29.04,
             "role": "recent", "dist_pct": 44.08}
        ]
        items = signals.build_invalidation(st, 0.0)
        self.assertTrue(items)
        for item in items:
            self.assertNotIn("已发生的事实", item.rationale)
            if item.comparator == "below":
                self.assertIn("现价未知", item.rationale)

    def test_structural_falsification_findings_land_on_the_falsification_dimension(self):
        # 设计文档 §5.1 / 主规格 §5.3：anchor-chanlun 要同时贡献「证伪条件」与
        # 「位置与时机」两个维度。若全部发现都落在位置与时机，证伪条件（权重 25%）
        # 会恒为 no_reviewer 被剔除，总分实际只除以 15% 的权重。
        st = structure()
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2026-02-05", "to": "2026-09-22", "ZD": 22.39, "ZG": 29.04,
             "role": "recent", "dist_pct": 44.08}
        ]
        findings, _ = rules.evaluate(BULLISH, st, 15.54)
        by_code = {f.code: f for f in findings}
        # 中枢距现价远 → 结构位证伪条件不可靠 → 归「证伪条件」
        self.assertEqual(by_code["CHAN_PIVOT_FAR_FROM_PRICE"].dimension, "证伪条件")
        # 现价在中枢内部 → 说清了失效线在哪 → 也归「证伪条件」
        st2 = structure()
        st2["levels"]["day"]["nearby_pivots"] = [
            {"from": "2025-08-04", "to": "2026-02-05", "ZD": 11.84, "ZG": 14.05,
             "role": "current", "dist_pct": -9.59}
        ]
        findings2, _ = rules.evaluate(BULLISH, st2, 13.0)
        by_code2 = {f.code: f for f in findings2}
        self.assertEqual(by_code2["CHAN_PRICE_INSIDE_PIVOT"].dimension, "证伪条件")

    def test_position_findings_stay_on_the_position_dimension(self):
        # 「位置与时机」维度的贡献不能被上面那条改动挤掉。
        # 这里逐条核对**所有会被观察到的规则码**：把一条位置类规则挪到证伪维度，
        # 会把 15% 的位置维度悄悄挪进 25% 的证伪维度（finding A 的反向风险），
        # 而 delta 最大的 CHAN_DIRECTION_CONFLICT（−18）最容易被误改。
        falsification_codes = {"CHAN_PRICE_INSIDE_PIVOT", "CHAN_PIVOT_FAR_FROM_PRICE"}
        seen: dict[str, str] = {}

        def collect(observation, st, last_close):
            findings, _ = rules.evaluate(observation, st, last_close)
            for f in findings:
                seen.setdefault(f.code, f.dimension)

        # 场景 1：看多 + 周线向下 + 日线顶背驰
        # → 高一级否决 / 仓位上限 / 顶背驰优先 / 方向冲突 / 中枢离现价远
        st = structure()
        st["levels"]["week"]["bias"] = "down"
        st["levels"]["day"]["signal"] = "中枢上方 · 顶背驰预警"
        st["levels"]["day"]["nearby_pivots"] = [
            {"from": "2023-01-04", "to": "2023-05-04", "ZD": 8.0, "ZG": 9.0,
             "role": "support", "dist_pct": -42.0},
            {"from": "2026-02-05", "to": "2026-09-22", "ZD": 22.39, "ZG": 29.04,
             "role": "recent", "dist_pct": 5.0},
        ]
        collect(BULLISH, st, 13.0)

        # 场景 2：看空 + 日线底背驰 + 周线无背书 + 窗口偏薄 + 现价在中枢内部
        # → 次买点无背书 / 窗口偏薄 / 位置≠趋势 / 现价在中枢内部
        st2 = structure()
        st2["levels"]["day"]["signal"] = "中枢下方 · 底背驰预警"
        st2["levels"]["week"]["recent_divergence"] = None
        st2["levels"]["day"]["window_verdict"] = "样本偏薄"
        st2["levels"]["m30"]["nearby_pivots"] = [
            {"from": "2025-08-04", "to": "2026-02-05", "ZD": 11.84, "ZG": 14.05,
             "role": "current", "dist_pct": -9.59},
        ]
        collect({"direction": "bearish", "thesis": "要跌", "confidence": 0.6}, st2, 13.0)

        # 证伪维度上只允许出现那两条
        for code, dimension in seen.items():
            if dimension == "证伪条件":
                self.assertIn(code, falsification_codes)
        # 其余规则码一律落在位置维度
        for code, dimension in seen.items():
            if code not in falsification_codes:
                self.assertEqual(dimension, "位置与时机")
        # 两条证伪类规则确实都被观察到了 —— 否则上面的循环是空的，等于没测
        self.assertTrue(falsification_codes.issubset(set(seen)))
        # 至少要覆盖到 delta 最重的那几条位置类规则，否则这个测试保护不到重点
        self.assertIn("CHAN_DIRECTION_CONFLICT", seen)
        self.assertIn("CHAN_HIGHER_LEVEL_DENIES", seen)
        self.assertIn("CHAN_TOP_DIVERGENCE_OVERRIDES", seen)

    def test_horizon_hint_is_capped_by_its_own_findings(self):
        # 同一份结论不能自相矛盾：finding 说「把观察期放在短线档」，
        # horizon_hint 就不能给 long。
        st = structure()
        st["levels"]["week"]["bias"] = "up"
        st["levels"]["week"]["recent_divergence"] = None
        st["levels"]["day"]["signal"] = "中枢上方 · 底背驰预警"
        findings, _ = rules.evaluate(BULLISH, st, 15.54)
        codes = [f.code for f in findings]
        self.assertIn("CHAN_SECOND_BUY_NO_BACKING", codes)
        hint = signals.build_horizon_hint(BULLISH, st, findings, last_close=15.54)
        self.assertEqual(hint.tier, "short")
        self.assertIn("降为 short", hint.rationale)

    def test_horizon_hint_keeps_long_tier_when_no_cap_applies(self):
        # 没有降档约束时，档位逻辑保持原样
        st = structure()
        st["levels"]["week"]["bias"] = "up"
        st["levels"]["week"]["recent_divergence"] = {"active": True, "kind": "bottom"}
        st["levels"]["day"]["signal"] = "中枢上方 · 底背驰预警"
        hint = signals.build_horizon_hint(BULLISH, st, [], last_close=15.54)
        self.assertEqual(hint.tier, "long")

    def test_horizon_hint_cap_survives_the_trigger_override(self):
        # 顺序要求：档位上限必须在 trigger 覆盖**之后**应用。
        # 否则「有催化剂 + 有短线级发现」会被 event 静默盖掉 ——
        # finding 说「把观察期放在短线档」，horizon_hint 却给 event。
        st = structure()
        st["levels"]["week"]["bias"] = "up"
        st["levels"]["week"]["recent_divergence"] = None
        st["levels"]["day"]["signal"] = "中枢下方 · 底背驰预警"
        obs = dict(BULLISH)
        obs["trigger"] = "2026-12-01 产量公告"
        findings, _ = rules.evaluate(obs, st, 15.54)
        self.assertIn("CHAN_SECOND_BUY_NO_BACKING", [f.code for f in findings])
        hint = signals.build_horizon_hint(obs, st, findings, last_close=15.54)
        self.assertEqual(hint.tier, "short")
        self.assertIn("降为 short", hint.rationale)


if __name__ == "__main__":
    unittest.main()
