import sys
import unittest
from copy import deepcopy
from math import log
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from energy_model.accounting import CapacityProject, EnergyBalance, Storage, carbon_account
from energy_model.baselines import fit_baselines, predict_baselines
from build_foundation import derive_history, derive_power_history, table_records


class AccountingTests(unittest.TestCase):
    def test_unserved_demand_is_explicit(self):
        balance = EnergyBalance(
            production=80, opening_stock=10,
            requested_final_demand=100, unserved_final_demand=10,
        )
        balance.require_closed()
        with self.assertRaises(ValueError):
            EnergyBalance(production=80, requested_final_demand=100).require_closed()

    def test_invalid_supply_or_shortage_is_rejected(self):
        for fields in ({"production": -1}, {"production": float("nan")},
                       {"requested_final_demand": 2, "unserved_final_demand": 3}):
            with self.assertRaises(ValueError):
                EnergyBalance(**fields)

    def test_storage_round_trip_accounts_for_losses(self):
        initial = Storage(0, 100, 20, 20, 0.9, 0.8)
        charged = initial.step(20, 0, 5)
        self.assertAlmostEqual(charged.energy_mwh, 90)
        empty = charged.step(0, 14.4, 5)
        self.assertAlmostEqual(empty.energy_mwh, 0)
        self.assertAlmostEqual(14.4 * 5 / (20 * 5), 0.9 * 0.8)

    def test_storage_cannot_create_energy_or_break_limits(self):
        storage = Storage(5, 10, 2, 2, 0.9, 0.9)
        for action in ((1, 1, 1), (3, 0, 1), (0, 2, 5), (2, 0, 5), (0, 0, 0)):
            with self.assertRaises(ValueError):
                storage.step(*action)

    def test_capacity_respects_commissioning_and_retirement(self):
        project = CapacityProject(2, 2030, 2060)
        self.assertEqual([project.available_gw(y) for y in (2029, 2030, 2059, 2060)],
                         [0, 2, 2, 0])

    def test_capture_deducted_only_once(self):
        result = carbon_account(100, 10, 20, 30)
        self.assertEqual(result["positive_co2_after_capture"], 90)
        self.assertEqual(result["net_co2"], 60)
        self.assertAlmostEqual(result["neutralization_ratio"], 1 / 3)
        with self.assertRaises(ValueError):
            carbon_account(100, 0, 101, 0)
        self.assertIsNone(carbon_account(0, 0, 0, 0)["neutralization_ratio"])


class DataAndBaselineTests(unittest.TestCase):
    def test_missing_values_and_stock_sign_are_preserved(self):
        table = {
            "columns": ["year", "value", "inventory_delta"],
            "source_id": "S01", "locator": "row",
            "rows": [[2015, None, -2]],
        }
        result = table_records(table, {"S01"})
        self.assertIsNone(result[0]["value"])
        self.assertEqual(result[0]["inventory_delta"], -2)

    def test_unknown_sources_duplicate_years_and_bad_width_fail(self):
        table = {"columns": ["year", "value"], "source_id": "S01",
                 "locator": "row", "rows": [[2015, 1]]}
        for edited in (
            dict(table, source_id="unknown"),
            dict(table, rows=[[2015, 1], [2015, 2]]),
            dict(table, rows=[[2015]]),
            dict(table, rows=[[2015, float("inf")]]),
        ):
            with self.assertRaises(ValueError):
                table_records(edited, {"S01"})

    def test_gdp_chain_does_not_apply_base_year_growth(self):
        records = {
            "energy_consumption_2015_2024": [
                {"year": year, "total_energy_consumption": 10000, "source_id": "S01"}
                for year in range(2015, 2025)
            ],
            "macro_growth_2015_2024": [
                {"year": year, "real_gdp_growth_pct": 999 if year == 2015 else 10,
                 "source_id": "S02"} for year in range(2015, 2025)
            ],
        }
        anchors = {"observations": [
            {"indicator_id": "total_energy_consumption", "value": None}
        ]}
        history = derive_history(records, anchors)["rows"]
        self.assertEqual(history[0]["real_gdp_index_2015"], 100)
        self.assertAlmostEqual(history[1]["real_gdp_index_2015"], 110)
        self.assertAlmostEqual(history[-1]["energy_intensity_index_2015"], 100 / 1.1 ** 9)

    def test_holdout_energy_does_not_affect_training_or_predictions(self):
        records = [
            {"year": year, "energy_mtce": 100 * 1.03 ** (year - 2015),
             "real_gdp_index_2015": 100 * 1.05 ** (year - 2015)}
            for year in range(2015, 2026)
        ]
        changed = deepcopy(records)
        for row in changed:
            if row["year"] > 2021:
                row["energy_mtce"] *= 10
        fitted = fit_baselines(records)
        self.assertEqual(fitted, fit_baselines(changed))
        self.assertEqual(
            predict_baselines(fitted, 2025, 200),
            predict_baselines(fit_baselines(changed), 2025, 200),
        )
        self.assertAlmostEqual(fitted["gdp_elasticity"],
                               log(1.03) / log(1.05))

    def test_power_units_and_unallocated_generation(self):
        records = {
            "power_capacity_2015_2024": [{
                "year": 2015, "total": 100, "thermal": 60, "hydro": 20,
                "nuclear": 5, "wind": 5, "solar": 9, "other": 1, "source_id": "S01",
            }],
            "power_generation_2015_2024": [{
                "year": 2015, "total": 100, "thermal": 60, "hydro": 20,
                "nuclear": 5, "wind": 5, "solar": None, "source_id": "S02",
            }],
        }
        row = derive_power_history(records)["rows"][0]
        self.assertEqual(row["year_end_capacity_gw"]["total"], 1)
        self.assertEqual(row["generation_twh"]["total"], 10)
        self.assertIsNone(row["generation_twh"]["solar"])
        self.assertEqual(row["unallocated_generation_or_rounding_twh"], 1)


if __name__ == "__main__":
    unittest.main()
