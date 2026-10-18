import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from energy_model.operations import (
    simulate_operation_window, summarize_operation_window, validate_operation_config,
)


class OperationWindowTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads(
            (ROOT / "examples/synthetic_operation_windows.json").read_text(encoding="utf-8")
        )

    def run_window(self, name="normal_variability", **kwargs):
        return simulate_operation_window(self.config, name, **kwargs)

    def test_balances_and_physical_constraints_in_every_control(self):
        p = self.config["storage"]
        for name in self.config["windows"]:
            for enabled in (True, False):
                run = self.run_window(name, storage_enabled=enabled)
                for row in run["rows"]:
                    hours = row["duration_hours"]
                    storage = row["storage"]
                    for residual in row["balance_residuals_mwh"].values():
                        self.assertAlmostEqual(residual, 0, places=8)
                    self.assertLessEqual(row["grid_input_mwh"], row["grid_limit_mw"] * hours + 1e-8)
                    self.assertGreaterEqual(storage["closing_energy_mwh"], 0)
                    self.assertLessEqual(storage["closing_energy_mwh"], p["capacity_mwh"] + 1e-8)
                    self.assertFalse(storage["charge_input_mwh"] > 0 and storage["discharge_output_mwh"] > 0)
                    self.assertLessEqual(storage["charge_input_mwh"], p["charge_limit_mw"] * hours + 1e-8)
                    self.assertLessEqual(storage["discharge_output_mwh"], p["discharge_limit_mw"] * hours + 1e-8)
                    for tech, amount in row["generation_mwh"].items():
                        self.assertGreaterEqual(amount, 0)
                        self.assertLessEqual(amount, row["available_generation_mwh"][tech] + 1e-8)
                    for fuel, amount in row["fuel_input_mwh_lhv"].items():
                        self.assertLessEqual(amount, row["fuel_supply_limit_mwh_lhv"][fuel] + 1e-8)

    def test_two_hour_charge_and_efficiency_losses_by_hand(self):
        self.config["windows"]["hand"] = {
            "description": "手算：40MWh充电输入，36MWh库存",
            "steps": [{
                "duration_hours": 2, "demand_mw": 0,
                "availability": {tech: float(tech == "solar") for tech in self.config["generation"]},
            }, {
                "duration_hours": 2, "demand_mw": 20,
                "availability": {tech: 0 for tech in self.config["generation"]},
            }],
        }
        run = self.run_window("hand")
        first, second = run["rows"]
        self.assertAlmostEqual(first["storage"]["charge_input_mwh"], 40)
        self.assertAlmostEqual(first["storage"]["closing_energy_mwh"], 36)
        self.assertAlmostEqual(first["storage"]["charge_loss_mwh"], 4)
        self.assertAlmostEqual(second["storage"]["discharge_output_mwh"], 24)
        self.assertAlmostEqual(second["storage"]["closing_energy_mwh"], 36 - 24 / 0.9)
        self.assertAlmostEqual(second["electricity_served_mwh"], 24 * 0.95)
        self.assertAlmostEqual(second["storage"]["discharge_loss_mwh"], 24 / 0.9 - 24)

    def test_fractional_hour_limits_not_treated_as_energy_capacity(self):
        self.config["storage"]["initial_energy_mwh"] = 40
        self.config["windows"]["half"] = {
            "description": "半小时限功率",
            "steps": [{"duration_hours": 0.5, "demand_mw": 100,
                       "availability": {name: 0 for name in self.config["generation"]}}],
        }
        row = self.run_window("half")["rows"][0]
        self.assertAlmostEqual(row["storage"]["discharge_output_mwh"], 6)
        self.assertAlmostEqual(row["electricity_served_mwh"], 5.7)
        self.assertAlmostEqual(row["electricity_requested_mwh"], 50)

    def test_soc_continues_and_window_ending_inventory_is_reported(self):
        run = self.run_window()
        for previous, current in zip(run["rows"], run["rows"][1:]):
            self.assertEqual(previous["storage"]["closing_energy_mwh"],
                             current["storage"]["opening_energy_mwh"])
        self.assertEqual(run["closing_storage_mwh"], run["rows"][-1]["storage"]["closing_energy_mwh"])
        constrained = self.run_window("grid_bottleneck")
        self.assertGreater(constrained["closing_storage_mwh"], 0)
        self.assertEqual(summarize_operation_window(constrained)["closing_storage_mwh"],
                         constrained["closing_storage_mwh"])

    def test_storage_reduces_shortage_in_normal_window(self):
        with_store = summarize_operation_window(self.run_window())
        without = summarize_operation_window(self.run_window(storage_enabled=False))
        self.assertGreater(with_store["storage_charge_mwh"], 0)
        self.assertGreater(with_store["storage_discharge_mwh"], 0)
        self.assertLess(with_store["unserved_mwh"], without["unserved_mwh"])
        self.assertEqual(without["storage_charge_mwh"], 0)
        self.assertEqual(without["storage_discharge_mwh"], 0)

    def test_empty_storage_cannot_help_without_surplus(self):
        with_store = self.run_window("persistent_low_wind_solar")
        without = self.run_window("persistent_low_wind_solar", storage_enabled=False)
        self.assertEqual(with_store["rows"], without["rows"])
        self.assertGreater(summarize_operation_window(with_store)["unserved_mwh"], 0)
        self.assertEqual(with_store["closing_storage_mwh"], 0)

    def test_generation_side_storage_cannot_bypass_grid_limit(self):
        with_store = self.run_window("grid_bottleneck")
        without = self.run_window("grid_bottleneck", storage_enabled=False)
        for index in (1, 2):
            row = with_store["rows"][index]
            self.assertAlmostEqual(row["electricity_served_mwh"],
                                   row["grid_limit_mw"] * row["duration_hours"] * 0.95)
            self.assertAlmostEqual(row["unserved_electricity_mwh"],
                                   without["rows"][index]["unserved_electricity_mwh"])

    def test_shutdown_preserves_inventory_and_records_shortage(self):
        self.config["storage"]["initial_energy_mwh"] = 20
        period = self.config["windows"]["normal_variability"]["steps"][0]
        period["grid_capacity_multiplier"] = 0
        period["availability"] = {name: 0 for name in self.config["generation"]}
        row = self.run_window()["rows"][0]
        self.assertEqual(row["storage"]["closing_energy_mwh"], 20)
        self.assertEqual(row["electricity_served_mwh"], 0)
        self.assertEqual(row["unserved_electricity_mwh"], row["electricity_requested_mwh"])
        self.assertEqual(row["energy_related_synthetic_emissions"], 0)

    def test_future_demand_availability_and_policy_cannot_change_past(self):
        reference = self.run_window()
        self.config["windows"]["normal_variability"]["steps"][2].update(
            demand_mw=999, carbon_price=1000, grid_capacity_multiplier=0,
            availability={name: 0 for name in self.config["generation"]},
        )
        altered = self.run_window()
        self.assertEqual(reference["rows"][:2], altered["rows"][:2])
        self.assertNotEqual(reference["rows"][2], altered["rows"][2])
        for row in altered["rows"]:
            self.assertEqual(row["information_cutoff_period"], row["period"])

    def test_combustion_emissions_and_variable_costs_counted_once(self):
        for row in self.run_window()["rows"]:
            expected = sum(
                amount * self.config["fuels"][fuel]["emission_factor"]
                for fuel, amount in row["fuel_input_mwh_lhv"].items()
            )
            self.assertAlmostEqual(row["energy_related_synthetic_emissions"], expected)
            self.assertAlmostEqual(row["costs_cu"]["carbon_payment"], expected * row["carbon_price"])
            self.assertAlmostEqual(
                row["costs_cu"]["resource_variable_total"],
                row["costs_cu"]["fuel"] + row["costs_cu"]["generation_variable_om"]
                + row["costs_cu"]["storage_variable"],
            )
            self.assertAlmostEqual(row["thermal_conversion_loss_mwh"],
                                   sum(row["fuel_input_mwh_lhv"].values())
                                   - row["generation_mwh"]["coal"] - row["generation_mwh"]["gas"])

    def test_carbon_cost_changes_coal_gas_dispatch_order(self):
        # Large unmet load ensures both technologies are useful and the marginal order is visible.
        window = self.config["windows"]["normal_variability"]
        window["steps"][0]["availability"] = {
            name: float(name in {"coal", "gas"}) for name in self.config["generation"]
        }
        window["steps"][0]["demand_mw"] = 8
        window["steps"][0]["carbon_price"] = 0
        low = self.run_window(storage_enabled=False)["rows"][0]
        window["steps"][0]["carbon_price"] = 10
        high = self.run_window(storage_enabled=False)["rows"][0]
        self.assertGreater(low["generation_mwh"]["coal"], high["generation_mwh"]["coal"])
        self.assertGreater(high["generation_mwh"]["gas"], low["generation_mwh"]["gas"])
        self.assertAlmostEqual(low["electricity_served_mwh"], high["electricity_served_mwh"])

    def test_input_unchanged_reproducible_and_boundaries_explicit(self):
        snapshot = deepcopy(self.config)
        first = self.run_window()
        self.assertEqual(self.config, snapshot)
        self.assertEqual(first, self.run_window())
        self.assertIsNone(first["annual_reliability"])
        self.assertIsNone(first["national_forecast"])
        self.assertFalse(first["storage_capital_and_fixed_costs_included"])
        self.assertFalse(first["initial_stock_upstream_cost_and_emissions_included"])

    def test_invalid_units_boundaries_and_parameters_rejected(self):
        for mutate in (
            lambda c: c.update(mode="national"),
            lambda c: c["parameter_groups"]["storage"].update(basis="unlabelled"),
            lambda c: c["storage"].update(charge_efficiency=0),
            lambda c: c["storage"].update(initial_energy_mwh=41),
            lambda c: c["generation"]["nuclear"].update(fuel="coal"),
            lambda c: c["generation"]["solar"].update(efficiency=0.5),
            lambda c: c["windows"]["normal_variability"]["steps"][0].update(duration_hours=0),
            lambda c: c["windows"]["normal_variability"]["steps"][0]["availability"].update(solar=1.1),
            lambda c: c["fuels"]["coal"].update(price=float("nan")),
        ):
            case = deepcopy(self.config)
            mutate(case)
            with self.assertRaises(ValueError):
                validate_operation_config(case)


if __name__ == "__main__":
    unittest.main()
