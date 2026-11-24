import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from agaistock.skills.anchor_chanlun import engine


def fake_kline(symbol, setcode, period, want_num=500):
    """造一段可识别的合成 K 线（升序）。"""
    rows = []
    for i in range(120):
        day = 1 + (i % 28)
        month = 1 + (i // 28) % 12
        base = 10 + (i % 10) * 0.3
        rows.append({
            "Data": f"2025{month:02d}{day:02d}",
            "Open": f"{base:.2f}", "High": f"{base + 0.5:.2f}",
            "Low": f"{base - 0.5:.2f}", "Close": f"{base + 0.1:.2f}",
            "Volume": 100000.0, "Amount": 1000000.0,
        })
    return {"Rows": rows, "ListHead": {"ItemHead": []}}


class ChanlunEngineTests(unittest.TestCase):
    def test_vendor_scripts_are_present(self):
        scripts = engine.vendor_root() / "scripts"
        self.assertTrue((scripts / "chan_analyze.py").is_file())
        self.assertTrue((scripts / "chan_multi_level.py").is_file())

    def test_levels_map_to_tdx_periods(self):
        self.assertEqual(engine.LEVELS["week"], "5")
        self.assertEqual(engine.LEVELS["day"], "4")
        self.assertEqual(engine.LEVELS["m30"], "2")

    def test_build_structure_produces_multi_level_payload(self):
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            structure = engine.build_structure(
                "002378", "章源钨业", "0", work, kline_fetcher=fake_kline
            )
            self.assertIn("levels", structure)
            self.assertIn("resonance", structure)
            self.assertIn("caveats", structure)
            self.assertIn("day", structure["levels"])

    def test_build_structure_writes_analysis_files(self):
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            engine.build_structure("002378", "章源钨业", "0", work, kline_fetcher=fake_kline)
            self.assertTrue((work / "chan_multi_level.json").is_file())
            self.assertTrue((work / "chan_analysis_day.json").is_file())

    def test_load_analysis_reads_the_level_analysis_file(self):
        with TemporaryDirectory() as tmp:
            work = Path(tmp)
            engine.build_structure("002378", "章源钨业", "0", work, kline_fetcher=fake_kline)
            analysis = engine.load_analysis(work, "day")
            self.assertEqual(analysis["level"], "day")
            self.assertIn("summary", analysis)

    def test_load_analysis_raises_when_file_missing(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                engine.load_analysis(Path(tmp), "day")


if __name__ == "__main__":
    unittest.main()
