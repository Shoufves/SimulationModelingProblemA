import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_history_readiness import classify
from workflow_status import read_json


class HistoryReadinessTests(unittest.TestCase):
    def test_complete_single_vintage_is_pending_evidence_not_missing_history(self):
        for name in ("energy_consumption_2015_2024", "macro_growth_2015_2024",
                     "power_capacity_2015_2024"):
            data = read_json(ROOT / f"data/observations/{name}.json")
            result = classify(data)
            self.assertTrue(result["all_ten_year_rows_present"])
            self.assertEqual(result["missing_cells"], [])
            self.assertEqual(result["issues"], ["evidence_review_pending"])
            self.assertFalse(result["continuous_calibration_ready"])
            self.assertFalse(classify(data, admitted=True)["continuous_calibration_ready"],
                             "Formal admission alone does not approve historical calibration use")

    def test_mixed_generation_keeps_missing_solar_and_does_not_infer_it(self):
        data = read_json(ROOT / "data/observations/power_generation_2015_2024.json")
        result = classify(data)
        self.assertEqual(result["missing_years"], [])
        self.assertEqual(len(result["missing_cells"]), 9)
        self.assertEqual({r["column"] for r in result["missing_cells"]}, {"solar"})
        self.assertIn("mixed_sources_need_scope_revision_bridge", result["issues"])

    def test_coal_washing_blanks_and_petroleum_years_remain_missing(self):
        coal = classify(read_json(ROOT / "data/observations/coal_balance_2015_2023.json"))
        oil = classify(read_json(ROOT / "data/observations/petroleum_balance_selected_years.json"))
        self.assertEqual(coal["missing_years"], [2024])
        self.assertEqual([cell["year"] for cell in coal["missing_cells"]], [2020, 2022, 2023])
        self.assertEqual(oil["missing_years"], [2016, 2017, 2018, 2019, 2024])

    def test_malformed_and_duplicate_year_rows_rejected(self):
        for rows in ([[2024, 1], [2024, 2]], [[2024]], [[2024.5, 1]]):
            with self.assertRaises(ValueError):
                classify({"columns": ["year", "x"], "source_id": "S01", "rows": rows})
