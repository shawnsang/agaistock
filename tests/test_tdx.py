import json
import unittest
from unittest import mock

from agaistock.providers import tdx


class TdxTests(unittest.TestCase):
    def test_setcode_for_shenzhen(self):
        self.assertEqual(tdx.setcode_for("002378"), "0")

    def test_setcode_for_shanghai(self):
        self.assertEqual(tdx.setcode_for("600519"), "1")

    def test_setcode_for_chinext(self):
        self.assertEqual(tdx.setcode_for("300750"), "0")

    def test_setcode_for_bse(self):
        self.assertEqual(tdx.setcode_for("430047"), "2")

    def test_setcode_for_bse_new_code_space(self):
        # 北交所 920xxx 是当前代码空间，连接器按 setcode=2 提供
        self.assertEqual(tdx.setcode_for("920001"), "2")

    def test_setcode_rejects_unknown_prefix(self):
        with self.assertRaises(ValueError):
            tdx.setcode_for("12345")

    @mock.patch("agaistock.providers.tdx.call_connector")
    def test_fetch_kline_requests_houfuquan(self, fake_call):
        fake_call.return_value = json.dumps({"Rows": []})
        tdx.fetch_kline("600519", "1", "4", want_num=3)
        tool, args = fake_call.call_args[0]
        self.assertEqual(tool, tdx.TDX_KLINE)
        # D6 口径：必须显式带 tqFlag=2，否则连接器默认返回前复权
        self.assertEqual(args["tqFlag"], "2")
        self.assertEqual(args["wantNum"], 3)

    @mock.patch("agaistock.providers.tdx.call_connector")
    def test_fetch_adjustment_factors_normalizes_rows(self, fake_call):
        fake_call.return_value = (
            "tdx_api_data 请求成功\n\n"
            + json.dumps(
                {
                    "response": {
                        "transformed": {
                            "tables": [
                                {
                                    "name": "capital_flow",
                                    "rows": [{"日期": "2026-11-24", "主力净额金额(元)": -1}],
                                },
                                {
                                    "name": "adjustment_factor",
                                    "rows": [
                                        {"日期": "2026-06-26", "精确复权因子": 2.6, "精确复权常数": 2.2552},
                                        {"日期": "2025-06-06", "精确复权因子": 2.6, "精确复权常数": 1.9432},
                                    ],
                                },
                            ]
                        }
                    }
                },
                ensure_ascii=False,
            )
        )
        factors = tdx.fetch_adjustment_factors("002378")
        self.assertEqual(
            factors,
            [
                {"ex_date": "2026-06-26", "factor": 2.6, "constant": 2.2552},
                {"ex_date": "2025-06-06", "factor": 2.6, "constant": 1.9432},
            ],
        )

    @mock.patch("agaistock.providers.tdx.call_connector")
    def test_fetch_adjustment_factors_empty_when_table_absent(self, fake_call):
        fake_call.return_value = (
            "tdx_api_data 请求成功\n\n"
            + json.dumps({"response": {"transformed": {"tables": []}}}, ensure_ascii=False)
        )
        self.assertEqual(tdx.fetch_adjustment_factors("002378"), [])

    def test_to_houfuquan_matches_measured_formula(self):
        # 600519 2026-06-26 的因子行：现价 1460.00 → 后复权 10014.70
        row = {"ex_date": "2026-06-26", "factor": 5.627766, "constant": 1798.159313}
        self.assertAlmostEqual(tdx.to_houfuquan(1460.0, row), 10014.70, places=2)

    def test_to_current_price_is_inverse_of_to_houfuquan(self):
        row = {"ex_date": "2026-06-26", "factor": 5.627766, "constant": 1798.159313}
        self.assertAlmostEqual(tdx.to_current_price(10014.70, row), 1460.0, places=2)
        self.assertAlmostEqual(
            tdx.to_current_price(tdx.to_houfuquan(15.54, row), row), 15.54, places=6
        )


if __name__ == "__main__":
    unittest.main()
