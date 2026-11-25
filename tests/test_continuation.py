"""观察续接的合并语义（Task 21）。

合并是**纯函数** —— 不碰数据库、不碰时钟，所以规则可以被逐条钉住。
"""
import unittest

from agaistock.continuation import merge_into_previous


PREVIOUS = {
    "id": "obs_old",
    "thread_id": "obs_old",
    "supersedes_id": None,
    "symbol": "002378",
    "name": "章源钨业",
    "direction": "bullish",
    "thesis": "钨价上涨，还可拿半年",
    "confidence": 0.72,
    "timeframe": "半年",
    "trigger": "明年上半年产量翻倍",
    "position_json": '{"entry": "回踩 22 买", "size": "三成"}',
    "evidence": [{"text": "钨价从去年就开始涨", "type": "fact"}],
    "invalidation": ["钨价跌回去年年底的水平"],
    "raw_text": "章源钨业我看了三年了",
    "created_at": "2026-11-24T07:00:00+00:00",
    "deleted_at": None,
}

INCOMING = {
    "symbol": "002378",
    "name": "章源钨业",
    "direction": "bullish",
    "thesis": "产量翻倍确认",
    "confidence": 0.8,
    "timeframe": "半年",
    "trigger": "",
    "position": {"entry": "站上 25 加仓", "size": ""},
    "evidence": [{"text": "明年上半年产量翻倍", "type": "assumption"}],
    "invalidation": ["产量不及预期"],
    "raw_text": "产量翻倍确认",
}


class MergeViewFieldTests(unittest.TestCase):
    def test_new_thesis_wins(self):
        merged = merge_into_previous(PREVIOUS, INCOMING)
        self.assertEqual(merged["thesis"], "产量翻倍确认")

    def test_empty_new_timeframe_falls_back_to_old(self):
        merged = merge_into_previous(PREVIOUS, dict(INCOMING, timeframe=""))
        self.assertEqual(merged["timeframe"], "半年")

    def test_empty_new_trigger_falls_back_to_old(self):
        merged = merge_into_previous(PREVIOUS, dict(INCOMING, trigger="  "))
        self.assertEqual(merged["trigger"], "明年上半年产量翻倍")

    def test_new_trigger_wins_when_present(self):
        merged = merge_into_previous(PREVIOUS, dict(INCOMING, trigger="季报超预期"))
        self.assertEqual(merged["trigger"], "季报超预期")

    def test_position_is_merged_key_by_key(self):
        merged = merge_into_previous(PREVIOUS, INCOMING)
        # entry 用新的；size 新的为空 ⇒ 沿用旧的
        self.assertEqual(merged["position"]["entry"], "站上 25 加仓")
        self.assertEqual(merged["position"]["size"], "三成")

    def test_position_previous_is_read_from_position_json(self):
        merged = merge_into_previous(PREVIOUS, dict(INCOMING, position={}))
        self.assertEqual(merged["position"]["entry"], "回踩 22 买")
        self.assertEqual(merged["position"]["size"], "三成")


class MergeDirectionTests(unittest.TestCase):
    def test_new_direction_wins_when_it_is_a_stance(self):
        merged = merge_into_previous(PREVIOUS, dict(INCOMING, direction="bearish"))
        self.assertEqual(merged["direction"], "bearish")

    def test_neutral_incoming_keeps_previous_direction(self):
        """neutral 在本代码库里是「没有表态」—— 纯补充不能把方向抹成中性。"""
        merged = merge_into_previous(PREVIOUS, dict(INCOMING, direction="neutral"))
        self.assertEqual(merged["direction"], "bullish")

    def test_empty_incoming_direction_falls_back(self):
        merged = merge_into_previous(PREVIOUS, dict(INCOMING, direction=""))
        self.assertEqual(merged["direction"], "bullish")

    def test_neutral_on_both_sides_stays_neutral(self):
        merged = merge_into_previous(
            dict(PREVIOUS, direction="neutral"), dict(INCOMING, direction="neutral")
        )
        self.assertEqual(merged["direction"], "neutral")


class MergeConfidenceTests(unittest.TestCase):
    def test_positive_new_confidence_wins(self):
        merged = merge_into_previous(PREVIOUS, dict(INCOMING, confidence=0.9))
        self.assertEqual(merged["confidence"], 0.9)

    def test_zero_means_not_provided_and_old_is_kept(self):
        merged = merge_into_previous(PREVIOUS, dict(INCOMING, confidence=0.0))
        self.assertEqual(merged["confidence"], 0.72)

    def test_missing_confidence_keeps_old(self):
        incoming = dict(INCOMING)
        incoming.pop("confidence")
        merged = merge_into_previous(PREVIOUS, incoming)
        self.assertEqual(merged["confidence"], 0.72)


class MergeAccumulationTests(unittest.TestCase):
    def test_evidence_is_the_union_with_old_first(self):
        merged = merge_into_previous(PREVIOUS, INCOMING)
        self.assertEqual(
            [item["text"] for item in merged["evidence"]],
            ["钨价从去年就开始涨", "明年上半年产量翻倍"],
        )

    def test_evidence_deduplicates_by_text(self):
        merged = merge_into_previous(PREVIOUS, dict(INCOMING, evidence=[
            {"text": "钨价从去年就开始涨", "type": "fact"},
        ]))
        self.assertEqual(len(merged["evidence"]), 1)

    def test_invalidation_is_the_union_with_old_first(self):
        merged = merge_into_previous(PREVIOUS, INCOMING)
        self.assertEqual(
            merged["invalidation"],
            ["钨价跌回去年年底的水平", "产量不及预期"],
        )

    def test_invalidation_deduplicates_by_text(self):
        merged = merge_into_previous(PREVIOUS, dict(INCOMING, invalidation=[
            "钨价跌回去年年底的水平",
        ]))
        self.assertEqual(merged["invalidation"], ["钨价跌回去年年底的水平"])

    def test_evidence_keeps_the_declared_type(self):
        merged = merge_into_previous(PREVIOUS, dict(INCOMING, evidence=[
            {"text": "钨精矿报价单", "type": "fact"},
        ]))
        types = {item["text"]: item["type"] for item in merged["evidence"]}
        self.assertEqual(types["钨精矿报价单"], "fact")
        self.assertEqual(types["钨价从去年就开始涨"], "fact")


class MergeSafetyTests(unittest.TestCase):
    def test_previous_id_is_not_carried_over(self):
        """id 会被 insert_observation 当主键用 —— 带过去就是撞主键。"""
        merged = merge_into_previous(PREVIOUS, INCOMING)
        self.assertNotIn("id", merged)

    def test_version_chain_columns_are_not_carried_over(self):
        merged = merge_into_previous(PREVIOUS, INCOMING)
        self.assertNotIn("thread_id", merged)
        self.assertNotIn("supersedes_id", merged)
        self.assertNotIn("deleted_at", merged)

    def test_previous_created_at_is_not_inherited(self):
        """新版本的时间戳必须是「现在」—— 继承旧的会让列表顺序错乱。"""
        merged = merge_into_previous(PREVIOUS, INCOMING)
        self.assertNotIn("created_at", merged)

    def test_explicit_created_at_on_incoming_is_kept(self):
        merged = merge_into_previous(
            PREVIOUS, dict(INCOMING, created_at="2026-11-25T09:00:00+00:00")
        )
        self.assertEqual(merged["created_at"], "2026-11-25T09:00:00+00:00")

    def test_raw_text_is_the_new_one(self):
        merged = merge_into_previous(PREVIOUS, INCOMING)
        self.assertEqual(merged["raw_text"], "产量翻倍确认")

    def test_symbol_and_name_fall_back_to_old(self):
        merged = merge_into_previous(PREVIOUS, dict(INCOMING, symbol="", name=""))
        self.assertEqual(merged["symbol"], "002378")
        self.assertEqual(merged["name"], "章源钨业")

    def test_merged_result_does_not_mutate_the_inputs(self):
        before_previous = dict(PREVIOUS)
        before_incoming = dict(INCOMING)
        merge_into_previous(PREVIOUS, INCOMING)
        self.assertEqual(PREVIOUS, before_previous)
        self.assertEqual(INCOMING, before_incoming)


if __name__ == "__main__":
    unittest.main()
