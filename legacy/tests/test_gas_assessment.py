import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_gas_assessment import calculate
from workflow_status import read_json


class GasAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.report = read_json(ROOT / "data/observations/gas_official_report_2024.json")
        self.quick = read_json(ROOT / "data/observations/gas_apparent_consumption_2024.json")

    def edit(self, key, field, value):
        next(row for row in self.report["observations"] if row["indicator_id"] == key)[field] = value

    def test_no_cross_scope_sector_volumes_or_stock_imputation(self):
        result = calculate(self.report, self.quick)
        self.assertEqual(result["fuel_ledger"]["status"], "incomplete")
        self.assertIn("domestic_use_excluding_losses", result["fuel_ledger"]["missing_terms"])
        for key in ("sector_absolute_volume_100m_m3", "total_storage_capacity_100m_m3",
                    "storage_cover_days", "country_hhi", "net_import_dependency_pct"):
            self.assertIsNone(result[key])
        self.assertEqual(result["cross_release_arithmetic_gap"]["value_100m_m3"], 21.5)
        self.assertIsNone(result["fuel_ledger"]["residual"])

    def test_consumption_growth_scopes_remain_distinct(self):
        result = calculate(self.report, self.quick)
        self.assertEqual(result["gas_consumption_growth_report_pct"], 7.3)
        self.assertEqual(result["gas_apparent_consumption_growth_quick_pct"], 8)
        self.assertAlmostEqual(result["growth_scope_gap_percentage_points"], 0.7)

    def test_lng_spot_uses_lng_denominator(self):
        result = calculate(self.report, self.quick)
        self.assertAlmostEqual(result["lng_spot_share_derived_pct"], 133 / 1057 * 100)
        self.assertAlmostEqual(result["pipeline_import_share_pct"], 760 / 1817 * 100)
        self.assertEqual(result["import_split_residual_100m_m3"], 0)

    def test_mass_cannot_silently_replace_volume(self):
        self.edit("gas_imports", "unit", "万吨")
        with self.assertRaises(ValueError):
            calculate(self.report, self.quick)

    def test_impossible_import_subsets_and_shares_rejected(self):
        original = deepcopy(self.report)
        for key, value in (("lng_spot_imports", 2000), ("five_main_origins_imports", 2000),
                           ("pipeline_imports", 1), ("power_consumption_share_pct", 101)):
            self.report = deepcopy(original)
            self.edit(key, "value", value)
            with self.subTest(indicator=key), self.assertRaises(ValueError):
                calculate(self.report, self.quick)
