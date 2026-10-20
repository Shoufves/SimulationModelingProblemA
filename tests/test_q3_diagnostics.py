"""Counterexamples for the explanatory audit, not new policy acceptance tests."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from diagnose_q3_mechanisms import (
    carbon_components, combine_prefix, compare_services, probe_operation,
    service_metrics, suffix_operation,
)
from energy_model.q2_national import operate_national, EF
from energy_model.q3_events import run_event
from review_q3_diagnostics import verify_probe_inputs
from test_q2_operations import dispatch_case
from test_q3 import event_fixture


class MechanismDiagnosticTests(unittest.TestCase):
    def test_review_rejects_unregistered_price_or_demand_changes(self):
        baseline = dispatch_case()
        numeric_zero = deepcopy(baseline)
        numeric_zero["plants"]["coal"]["capacity_mw"] = 0
        verify_probe_inputs(numeric_zero, probe_operation(numeric_zero, "generation_power", .01), "generation_power", .01)
        changed = probe_operation(baseline, "storage_power", .01)
        verify_probe_inputs(baseline, changed, "storage_power", .01)
        for field in ("service_mwh", "efficiency"):
            invalid = deepcopy(changed)
            if field == "service_mwh":
                invalid["demands"]["load"][field][0] *= .5
            else:
                invalid["demands"]["load"][field] *= .5
            with self.assertRaises(ValueError):
                verify_probe_inputs(baseline, invalid, "storage_power", .01)
        invalid = deepcopy(changed)
        invalid["fuels"]["coal"]["domestic_cost_per_mwh"] *= 2
        with self.assertRaises(ValueError):
            verify_probe_inputs(baseline, invalid, "storage_power", .01)

    def test_saved_prefix_suffix_replays_without_resetting_stocks(self):
        snapshot, event = event_fixture()
        run = run_event(snapshot, event, "SGW", .3)
        before = deepcopy(run)
        suffix, count = suffix_operation(run)
        result = operate_national(suffix)
        compare_services(run["result"], combine_prefix(run, result, count), "counterexample replay")
        self.assertEqual(run, before)
        self.assertEqual(suffix["storage"]["initial_mwh"], run["result"]["storage"][count - 1]["closing_mwh"])
        self.assertEqual(suffix["storage"]["terminal_mwh"], run["operation"]["storage"]["terminal_mwh"])

    def test_import_closure_detects_an_actually_import_dependent_case(self):
        op = dispatch_case()
        op["fuels"] = {"gas": {**deepcopy(op["fuels"]["coal"]), "domestic_mw": [0, 0], "import_mw": [10, 10]}}
        op["plants"] = {"gas": {**deepcopy(op["plants"]["coal"]), "input": "gas"}}
        op["storage"]["power_mw"] = 0
        baseline = operate_national(op)
        closed = operate_national(probe_operation(op, "no_gas_imports", .01))
        self.assertAlmostEqual(service_metrics(baseline)["building"]["unmet_service_mwh"], 0)
        self.assertGreater(service_metrics(closed)["building"]["unmet_service_mwh"], 9)
        with self.assertRaises(ValueError):
            compare_services(baseline, closed, "real import dependence must not pass")

    def test_protecting_one_service_transfers_shortage_to_another(self):
        op = dispatch_case()
        op["plants"] = {"coal": {**op["plants"]["coal"], "capacity_mw": 5, "window_energy_budget_mwh": 10}}
        op["storage"]["power_mw"] = 0
        op["demands"]["transport"] = {**deepcopy(op["demands"]["load"]), "sector": "transport_proxy", "efficiency": .5}
        original = deepcopy(op)
        normal = service_metrics(operate_national(op))
        protected = service_metrics(operate_national(probe_operation(op, "transport_priority", .01)))
        self.assertLess(protected["transport_proxy"]["unmet_service_mwh"], normal["transport_proxy"]["unmet_service_mwh"])
        self.assertGreater(protected["building"]["unmet_service_mwh"], normal["building"]["unmet_service_mwh"])
        self.assertEqual(op, original)
        for key in normal:
            self.assertEqual(normal[key]["requested_service_mwh"], protected[key]["requested_service_mwh"])

    def test_carbon_does_not_burn_material_or_trust_an_exported_total(self):
        result = {"fuel": [dict(fuel="gas", direct_mwh=100., conversion_mwh=50., combustion_co2_t=-999.)],
                  "demand": [dict(sector="nonenergy_feedstock", carrier="gas", input_mwh=25.)]}
        gas = next(r for r in carbon_components(result, 365) if r["fuel"] == "gas")
        self.assertAlmostEqual(gas["direct_co2_t"], 75 * EF["gas"] * 365)
        self.assertAlmostEqual(gas["conversion_co2_t"], 50 * EF["gas"] * 365)


if __name__ == "__main__":
    unittest.main()
