import unittest

from agaistock.providers import tdx_rows_to_em


def row(date="20241104", o="7.38", h="7.40", l="6.82", c="6.98", v="897053.84", a="644506752"):
    return {
        "Data": date, "Second": "0", "Open": o, "High": h, "Low": l, "Close": c,
        "Amount": float(a), "Volume": float(v),
    }


class RowsToEmTests(unittest.TestCase):
    def test_maps_columns_to_eastmoney_field_order(self):
        result = tdx_rows_to_em.rows_to_em_format({"Rows": [row()]})
        self.assertEqual(
            result["data"]["klines"],
            ["2024-11-04,7.38,6.98,7.40,6.82,897054,644506752"],
        )

    def test_preserves_ascending_order_without_reversing(self):
        payload = {"Rows": [row(date="20241104"), row(date="20241105"), row(date="20241106")]}
        result = tdx_rows_to_em.rows_to_em_format(payload)
        dates = [k.split(",")[0] for k in result["data"]["klines"]]
        self.assertEqual(dates, ["2024-11-04", "2024-11-05", "2024-11-06"])

    def test_parse_date_accepts_compact_and_iso(self):
        self.assertEqual(tdx_rows_to_em.parse_tdx_date("20241104"), "2024-11-04")
        self.assertEqual(tdx_rows_to_em.parse_tdx_date("2024-11-04"), "2024-11-04")

    def test_raises_on_empty_rows(self):
        with self.assertRaises(ValueError):
            tdx_rows_to_em.rows_to_em_format({"Rows": []})

    def test_raises_when_row_lacks_close(self):
        broken = row()
        del broken["Close"]
        with self.assertRaises(ValueError):
            tdx_rows_to_em.rows_to_em_format({"Rows": [broken]})

    def test_skips_rows_with_unparsable_numbers(self):
        broken = row()
        broken["Close"] = "not-a-number"
        result = tdx_rows_to_em.rows_to_em_format({"Rows": [broken, row(date="20241105")]})
        self.assertEqual(result["data"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
