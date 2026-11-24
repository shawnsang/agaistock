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
    def test_fetch_kline_requests_raw_series_and_rebuilds_houfuquan(self, fake_call):
        # 连接器的 tqFlag="2" 对 30 分钟级别不生效，所以本层取不复权原始序列自己重建
        def fake(tool, args):
            if tool == tdx.TDX_KLINE:
                self.assertEqual(args["tqFlag"], "0")
                return json.dumps(
                    {
                        "Rows": [
                            {
                                "Data": "20261124",
                                "Open": "1460.00", "High": "1470.00",
                                "Low": "1450.00", "Close": "1460.00",
                                "Volume": 100.0, "Amount": 146000.0,
                            }
                        ]
                    }
                )
            return json.dumps(
                {
                    "response": {
                        "transformed": {
                            "tables": [
                                {
                                    "name": "adjustment_factor",
                                    "rows": [
                                        {
                                            "日期": "2026-06-26",
                                            "精确复权因子": 5.627766,
                                            "精确复权常数": 1798.159313,
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                },
                ensure_ascii=False,
            )

        fake_call.side_effect = fake
        payload = tdx.fetch_kline("600519", "1", "4", want_num=1)
        row = payload["Rows"][0]
        # 1460.00 × 5.627766 + 1798.159313 = 10014.70（实测的日线后复权值）
        self.assertAlmostEqual(float(row["Close"]), 10014.70, places=2)
        self.assertAlmostEqual(float(row["Open"]), 10014.70, places=2)
        # 量额保持原值
        self.assertEqual(row["Amount"], 146000.0)
        self.assertEqual(row["Volume"], 100.0)

    @mock.patch("agaistock.providers.tdx.call_connector")
    def test_fetch_kline_uses_provided_factors_without_extra_call(self, fake_call):
        fake_call.side_effect = lambda tool, args: json.dumps(
            {
                "Rows": [
                    {
                        "Data": "20261124", "Open": "1460.00", "High": "1470.00",
                        "Low": "1450.00", "Close": "1460.00",
                        "Volume": 100.0, "Amount": 146000.0,
                    }
                ]
            }
        )
        factors = [{"ex_date": "2026-06-26", "factor": 5.627766, "constant": 1798.159313}]
        payload = tdx.fetch_kline("600519", "1", "4", want_num=1, factors=factors)
        self.assertAlmostEqual(float(payload["Rows"][0]["Close"]), 10014.70, places=2)
        # 只调了一次连接器（K 线），因子表是调用方给的
        self.assertEqual(fake_call.call_count, 1)

    def test_factor_row_for_picks_the_latest_row_not_after_the_date(self):
        factors = [
            {"ex_date": "2026-06-26", "factor": 5.627766, "constant": 1798.159313},
            {"ex_date": "2025-12-19", "factor": 5.627766, "constant": 1640.4455},
            {"ex_date": "2024-12-20", "factor": 5.627766, "constant": 1349.883934},
        ]
        # 因子表日期带连字符、K 线日期不带，比较必须归一化
        self.assertEqual(tdx.factor_row_for(factors, "20260626")["ex_date"], "2026-06-26")
        self.assertEqual(tdx.factor_row_for(factors, "20250108")["ex_date"], "2024-12-20")
        # 早于最早一行因子 → 恒等变换
        early = tdx.factor_row_for(factors, "20240102")
        self.assertEqual(early["ex_date"], "")
        self.assertEqual(early["factor"], 1.0)
        self.assertEqual(early["constant"], 0.0)

    def test_factor_row_for_before_first_ex_date_is_identity(self):
        factors = [{"ex_date": "2026-06-26", "factor": 5.627766, "constant": 1798.159313}]
        row = tdx.factor_row_for(factors, "20240102")
        self.assertEqual(row["factor"], 1.0)
        self.assertEqual(row["constant"], 0.0)

    def test_apply_houfuquan_leaves_volume_and_amount_untouched(self):
        payload = {
            "Rows": [
                {
                    "Data": "20261124", "Open": "1460.00", "High": "1470.00",
                    "Low": "1450.00", "Close": "1460.00",
                    "Volume": 100.0, "Amount": 146000.0,
                }
            ]
        }
        factors = [{"ex_date": "2026-06-26", "factor": 5.627766, "constant": 1798.159313}]
        converted = tdx.apply_houfuquan(payload, factors)
        self.assertAlmostEqual(float(converted["Rows"][0]["Close"]), 10014.70, places=2)
        self.assertEqual(converted["Rows"][0]["Volume"], 100.0)
        self.assertEqual(converted["Rows"][0]["Amount"], 146000.0)
        # 原 payload 不被就地修改
        self.assertEqual(payload["Rows"][0]["Close"], "1460.00")

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
    def test_fetch_adjustment_factors_empty_when_table_has_no_rows(self, fake_call):
        fake_call.return_value = (
            "tdx_api_data 请求成功\n\n"
            + json.dumps(
                {
                    "response": {
                        "transformed": {"tables": [{"name": "adjustment_factor", "rows": []}]}
                    }
                },
                ensure_ascii=False,
            )
        )
        self.assertEqual(tdx.fetch_adjustment_factors("002378"), [])

    @mock.patch("agaistock.providers.tdx.call_connector")
    def test_fetch_adjustment_factors_raises_when_table_missing(self, fake_call):
        # 连接器返回形态不稳定：找不到因子表 != 该标的没有除权记录。
        # 必须重试一次，仍失败就抛错，不能静默返回空表。
        fake_call.return_value = (
            "tdx_api_data 请求成功\n\n"
            + json.dumps({"response": {"data": {"anything": 1}}}, ensure_ascii=False)
        )
        with self.assertRaises(RuntimeError):
            tdx.fetch_adjustment_factors("002378")
        self.assertEqual(fake_call.call_count, 2)

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
