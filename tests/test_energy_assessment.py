import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_energy_assessment import calculate
from workflow_status import read_json


class EnergyAssessmentTests(unittest.TestCase):
    def setUp(self):
        self.data = read_json(ROOT / "data/observations/energy_official_communique_2024.json")

    def edit(self, indicator, field, value):
        row = next(r for r in self.data["observations"] if r["indicator_id"] == indicator)
        row[field] = value

    def test_no_invented_dependency_nonfossil_or_emissions(self):
        result = calculate(self.data)
        self.assertIsNone(result["net_import_dependency_pct"])
        self.assertIsNone(result["nonfossil_primary_energy_share_pct"])
        self.assertIsNone(result["national_co2_total"])
        self.assertEqual(result["clean_energy_consumption_share_including_gas_pct"], 28.6)

    def test_mass_volume_and_money_scales_are_not_interchangeable(self):
        result = calculate(self.data)
        crude = next(r for r in result["imports"] if r["commodity"] == "crude_oil")
        self.assertAlmostEqual(crude["import_unit_value_yuan_per_t"], 23108 / 55342 * 10000)
        self.edit("natural_gas_import_quantity", "unit", "亿立方米")
        with self.assertRaises(ValueError):
            calculate(self.data)

    def test_intensity_scopes_remain_distinct(self):
        result = calculate(self.data)
        self.assertAlmostEqual(result["illustrative_total_energy_per_real_gdp_growth_pct"], -2 / 3)
        self.assertEqual(result["reported_adjusted_energy_intensity_growth_pct"], -3.8)
        self.assertNotEqual(result["illustrative_total_energy_per_real_gdp_growth_pct"],
                            result["reported_adjusted_energy_intensity_growth_pct"])

    def test_no_renormalization_of_generation_residual(self):
        result = calculate(self.data)
        self.assertAlmostEqual(result["generation_rounding_residual_100m_kwh"], 0.1)
        self.assertAlmostEqual(result["generation_share_pct"]["wind"], 9970.4 / 100868.8 * 100)
        self.assertLess(sum(result["generation_share_pct"].values()), 100)

    def test_invalid_observations_rejected(self):
        original = deepcopy(self.data)
        for indicator, field, value in (
            ("generation_total", "value", 0),
            ("carbon_allowance_turnover_volume", "value", 0),
            ("coal_consumption_share_pct", "value", 101),
            ("coal_lignite_import_quantity", "value", -1),
            ("generation_wind", "value", float("nan")),
        ):
            self.data = deepcopy(original)
            self.edit(indicator, field, value)
            with self.subTest(indicator=indicator), self.assertRaises(ValueError):
                calculate(self.data)

    def test_duplicate_indicators_rejected(self):
        self.data["observations"].append(deepcopy(self.data["observations"][0]))
        with self.assertRaises(ValueError):
            calculate(self.data)


if __name__ == "__main__":
    unittest.main()
