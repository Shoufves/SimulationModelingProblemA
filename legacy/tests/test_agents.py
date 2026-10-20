import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from energy_model.agents import simulate, validate


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT / "examples/synthetic_agents.json").read_text(encoding="utf-8"))

    def test_energy_fuel_network_and_service_constraints(self):
        run = simulate(self.config)
        for row in run["rows"]:
            for residual in row["balance_residuals"].values():
                self.assertAlmostEqual(residual, 0, places=8)
            self.assertLessEqual(sum(row["generation"].values()), row["grid_transfer_limit"] + 1e-8)
            for fuel, flow in row["fuel_flows"].items():
                self.assertLessEqual(flow["total_burned"], flow["supply_limit"] + 1e-8)
                self.assertLessEqual(flow["imports"], self.config["fuels"][fuel]["import_limit"] + 1e-8)
            for name, service in row["services"].items():
                self.assertLessEqual(service["service_served"], service["service"] + 1e-8)
                self.assertGreaterEqual(service["service_served"], 0)
                expected = (service["electricity_served"] * self.config["demand"][name]["electric_efficiency"]
                            + service["direct_fuel_served"] * self.config["demand"][name]["fuel_efficiency"])
                self.assertAlmostEqual(service["service_served"], expected)

    def test_construction_lag_and_retirement(self):
        run = simulate(self.config)
        for row in run["rows"]:
            for tech, capacity in row["capacity_at_start"].items():
                p = self.config["generation"][tech]
                expected = p["initial_capacity"] if row["step"] < p["initial_retirement_step"] else 0
                for prior in run["rows"][:row["step"] - 1]:
                    for decision in prior["decisions"]:
                        if decision["kind"] == "generation_investment" and decision["actor"] == tech:
                            online = decision["online_step"]
                            if online is not None and online <= row["step"] < online + p["life_steps"]:
                                expected += decision["capacity_ordered"]
                self.assertAlmostEqual(capacity, expected)
        self.assertGreater(run["rows"][1]["decisions"][-1]["capacity_ordered"], 0)
        self.assertEqual(run["rows"][2]["capacity_at_start"]["renewable"], 14)
        self.assertEqual(run["rows"][3]["capacity_at_start"]["renewable"], 19)
        self.assertEqual(run["rows"][6]["capacity_at_start"]["coal"], 0)

    def test_equipment_changes_next_step_with_budget_and_replacement_limits(self):
        run = simulate(self.config)
        for i, row in enumerate(run["rows"]):
            for d in row["decisions"]:
                self.assertLessEqual(d["information_cutoff_step"], row["step"])
                if d["kind"] not in {"equipment_substitution", "generation_investment"}:
                    continue
                self.assertLessEqual(d["investment"], d["budget"] + 1e-8)
                if d["kind"] == "equipment_substitution":
                    self.assertLessEqual(abs(d["share_change"]),
                                         self.config["demand"][d["actor"]]["replacement_limit"] + 1e-8)
                    self.assertGreaterEqual(d["electric_share_next"], 0)
                    self.assertLessEqual(d["electric_share_next"], 1)
                    self.assertEqual(row["services"][d["actor"]]["electric_share"],
                                     d["electric_share_before"])
                    if i + 1 < len(run["rows"]):
                        self.assertEqual(run["rows"][i + 1]["services"][d["actor"]]["electric_share"],
                                         d["electric_share_next"])

    def test_future_policy_and_event_cannot_change_past(self):
        reference = simulate(self.config)
        self.config["policy"]["carbon_price_by_step"][5:] = [999, 999, 999]
        self.config["events_by_step"] = {"7": {"fuel_capacity_multiplier": {"gas": 0}}}
        altered = simulate(self.config)
        self.assertEqual(reference["rows"][:5], altered["rows"][:5])
        self.assertNotEqual(reference["rows"][5:], altered["rows"][5:])

    def test_reproducibility_and_input_immutability(self):
        snapshot = deepcopy(self.config)
        run = simulate(self.config)
        self.assertEqual(self.config, snapshot)
        self.assertEqual(run, simulate(self.config))
        self.assertIsNone(run["national_forecast"])

    def test_freezing_mechanisms_changes_system_path(self):
        full = simulate(self.config)
        frozen_demand = simulate(self.config, substitution=False)
        frozen_investment = simulate(self.config, investment=False)
        self.assertNotEqual(full["rows"][-1]["services"]["transport"]["electric_share"],
                            frozen_demand["rows"][-1]["services"]["transport"]["electric_share"])
        self.assertNotEqual(full["rows"][-1]["capacity_at_start"],
                            frozen_investment["rows"][-1]["capacity_at_start"])
        self.assertGreater(sum(s["unserved_service"] for row in frozen_investment["rows"]
                               for s in row["services"].values()),
                           sum(s["unserved_service"] for row in full["rows"]
                               for s in row["services"].values()))
        self.assertTrue(all(d["investment"] == 0 for row in frozen_investment["rows"]
                            for d in row["decisions"] if d["kind"] == "generation_investment"))

    def test_supplier_prices_respond_to_observed_use(self):
        run = simulate(self.config)
        fuel = "oil"
        previous = run["rows"][0]["fuel_flows"][fuel]
        p = self.config["fuels"][fuel]
        expected = p["base_price"] * (1 + p["scarcity_markup"] * previous["total_burned"] / previous["supply_limit"])
        self.assertAlmostEqual(run["rows"][1]["fuel_prices_before_carbon"][fuel], expected)

    def test_carbon_cost_changes_merit_order(self):
        self.config["demand"]["industry"]["electric_share"] = 0.5
        low = simulate(self.config, substitution=False, investment=False)["rows"][0]
        self.config["policy"]["carbon_price_by_step"] = [10] * self.config["run"]["steps"]
        high = simulate(self.config, substitution=False, investment=False)["rows"][0]
        self.assertGreater(low["generation"]["coal"], high["generation"]["coal"])
        self.assertGreater(high["generation"]["gas"], low["generation"]["gas"])
        self.assertAlmostEqual(sum(low["generation"].values()), sum(high["generation"].values()))

    def test_supply_shutdown_records_shortage_and_no_fictitious_imports(self):
        self.config["events_by_step"] = {"1": {
            "fuel_capacity_multiplier": {"coal": 0, "oil": 0, "gas": 0},
            "grid_capacity_multiplier": 0}}
        row = simulate(self.config)["rows"][0]
        self.assertEqual(row["electricity_served"], 0)
        self.assertEqual(row["energy_related_synthetic_emissions"], 0)
        self.assertTrue(all(flow["imports"] == 0 for flow in row["fuel_flows"].values()))
        self.assertAlmostEqual(sum(s["unserved_service"] for s in row["services"].values()),
                               sum(s["service"] for s in row["services"].values()))

    def test_burned_fuel_emissions_counted_once(self):
        run = simulate(self.config)
        for row in run["rows"]:
            expected = sum((flow["direct_served"] + flow["generation_input"]) *
                           self.config["fuels"][fuel]["emission_factor"]
                           for fuel, flow in row["fuel_flows"].items())
            self.assertAlmostEqual(row["energy_related_synthetic_emissions"], expected)

    def test_invalid_or_unlabelled_parameters_are_rejected(self):
        for mutate in (
            lambda c: c.update(mode="national"),
            lambda c: c["parameter_groups"]["demand"].update(basis="unknown"),
            lambda c: c["generation"]["gas"].update(lead_steps=0),
            lambda c: c["grid"].update(delivery_efficiency=1.1),
            lambda c: c["demand"]["transport"].update(electric_efficiency=0),
            lambda c: c["fuels"]["oil"].update(base_price=float("nan")),
            lambda c: c["generation"]["coal"].update(budget=-1),
        ):
            case = deepcopy(self.config)
            mutate(case)
            with self.assertRaises(ValueError):
                validate(case)
