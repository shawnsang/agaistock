import unittest

from agaistock.reviewers.contract import Finding
from agaistock.skills.anchor_chanlun import wording


def finding(**overrides):
    base = dict(
        code="CHAN_DAY_TOP_DIVERGENCE", severity="critical", dimension="位置与时机",
        delta=-12, claim="原始表述", why="原始理由",
        evidence_ref=["chan.levels.day.signal"], suggested_fix="原始建议",
    )
    base.update(overrides)
    return Finding(**base)


class FakeLlm:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def complete(self, prompt, system=""):
        self.calls.append(prompt)
        return self.response


class WordingTests(unittest.TestCase):
    def test_returns_original_when_llm_missing(self):
        original = [finding()]
        result = wording.phrase(original, {"thesis": "t"}, llm=None)
        self.assertEqual(result[0].claim, "原始表述")

    def test_applies_wording_to_claim_only(self):
        llm = FakeLlm('{"items":[{"code":"CHAN_DAY_TOP_DIVERGENCE","claim":"更口语化的表述"}]}')
        result = wording.phrase([finding()], {"thesis": "t"}, llm=llm)
        self.assertEqual(result[0].claim, "更口语化的表述")
        self.assertEqual(result[0].delta, -12)
        self.assertEqual(result[0].severity, "critical")
        self.assertEqual(result[0].dimension, "位置与时机")
        self.assertEqual(result[0].code, "CHAN_DAY_TOP_DIVERGENCE")

    def test_discards_llm_output_that_tampered_protected_fields(self):
        # 同一个 code，但 severity / dimension / delta 被改了 → 整条丢弃，保留规则层原文
        llm = FakeLlm(
            '{"items":[{"code":"CHAN_DAY_TOP_DIVERGENCE","severity":"info",'
            '"dimension":"一致性","delta":99,"claim":"篡改"}]}'
        )
        result = wording.phrase([finding()], {"thesis": "t"}, llm=llm)
        self.assertEqual(result[0].claim, "原始表述")
        self.assertEqual(result[0].delta, -12)
        self.assertEqual(result[0].severity, "critical")
        self.assertEqual(result[0].dimension, "位置与时机")

    def test_survives_llm_exception(self):
        class Boom:
            def complete(self, prompt, system=""):
                raise RuntimeError("挂了")
        result = wording.phrase([finding()], {"thesis": "t"}, llm=Boom())
        self.assertEqual(result[0].claim, "原始表述")

    def test_non_list_evidence_ref_is_treated_as_tampering_not_a_crash(self):
        # LLM 输出是不可信输入：evidence_ref 给成数字时 list(123) 会抛 TypeError，
        # 穿透「任何异常都必须降级」的硬约束 —— 整轮点评会因此变成 status=error，
        # 连规则层的 findings 一起丢掉。必须判为篡改并退回原文。
        llm = FakeLlm(
            '{"items":[{"code":"CHAN_DAY_TOP_DIVERGENCE","evidence_ref":123,"claim":"改写"}]}'
        )
        result = wording.phrase([finding()], {"thesis": "t"}, llm=llm)
        self.assertEqual(result[0].claim, "原始表述")
        self.assertEqual(result[0].evidence_ref, ["chan.levels.day.signal"])

    def test_string_evidence_ref_is_treated_as_tampering(self):
        # list("a") → ['a']。原文的 evidence_ref 必须**恰好是** ['a']，
        # 旧实现才会把字符串误判成「没篡改」而放行 —— 用别的原文（如
        # ["chan.levels.day.signal"]）时 list("a") 跟它本来就不相等，
        # 这条测试在旧实现下也会通过，等于没卡住任何东西。
        llm = FakeLlm(
            '{"items":[{"code":"CHAN_DAY_TOP_DIVERGENCE","evidence_ref":"a","claim":"改写"}]}'
        )
        original = finding(evidence_ref=["a"])
        result = wording.phrase([original], {"thesis": "t"}, llm=llm)
        self.assertEqual(result[0].claim, "原始表述")

    def test_unexpected_shape_in_the_llm_payload_degrades_to_the_original(self):
        # LLM 返回的 items 里混进一个非 dict 的元素时，整个解析段都不能抛异常 ——
        # 措辞层失败必须降级，不能影响判定。
        llm = FakeLlm('{"items":[123, null, "oops"]}')
        result = wording.phrase([finding()], {"thesis": "t"}, llm=llm)
        self.assertEqual(result[0].claim, "原始表述")
        self.assertEqual(result[0].delta, -12)

    def test_unhashable_code_in_the_llm_payload_degrades_to_the_original(self):
        # 解析段真正会崩的输入：item.get("code") 拿到一个 list 时，
        # 拿它当 dict 的键 → TypeError: unhashable type: 'list'。
        # 这一步处理的是不可信外部输入，异常一旦穿透到点评师，
        # 整轮点评会变成 status="error"，连规则层已经算好的 findings 一起丢掉。
        llm = FakeLlm('{"items":[{"code":[],"claim":"改写"}]}')
        result = wording.phrase([finding()], {"thesis": "t"}, llm=llm)
        self.assertEqual(result[0].claim, "原始表述")
        self.assertEqual(result[0].delta, -12)

    def test_protected_fields_come_from_the_contract(self):
        # 受保护字段只能有一个来源，否则两处分叉就没人说得清「哪些字段不许 LLM 改」。
        from agaistock.reviewers import contract
        self.assertEqual(tuple(wording.PROTECTED), tuple(contract.PROTECTED_FIELDS))


if __name__ == "__main__":
    unittest.main()
