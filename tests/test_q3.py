"""Q3 boundary counterexamples; numerical dependencies are mandatory here."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(ROOT/"scripts"))
from energy_model.q2_operations import operate, Q2Error
from energy_model.q3_events import event_calendar, make_event_operation, run_event, safety_metrics, interaction
from test_q2_operations import dispatch_case
import run_q3


def event_fixture():
    op = dispatch_case()
    op["periods"] = [dict(hours=6)]*4
    op["annual_repeats"] = 365
    for fuel in op["fuels"].values():
        fuel.update(domestic_mw=[20]*4, import_mw=[4]*4, tank_mwh=20,
                    initial_mwh=10, injection_mw=5, withdrawal_mw=5)
    op["fuels"]["gas"] = deepcopy(op["fuels"]["coal"])
    for plant in op["plants"].values():
        plant.update(availability=[1]*4, window_energy_budget_mwh=480)
    op["plants"]["wind"] = {**deepcopy(op["plants"]["coal"]), "input":None}
    op["plants"]["hydro"] = {**deepcopy(op["plants"]["wind"]), "window_energy_budget_mwh":100}
    op["demands"]["load"]["service_mwh"] = [25]*4
    op["storage"]["initial_mwh"] = 4
    event = dict(start_hour=6, duration_hours=12, recovery_hours=6,
                 window_days=2, gas_channel_loss=.8, renewable_loss=.5)
    return op, event


class FiniteEventTests(unittest.TestCase):
    def test_default_q2_dispatch_unchanged_without_options(self):
        case = dispatch_case()
        expected = operate(case)
        case["storage"]["discharge_limit_mwh"] = [case["storage"]["power_mw"]]*2
        self.assertEqual(expected, operate(case))

    def test_noncyclic_fuel_replenishment_prevents_free_initial_stock(self):
        case = dispatch_case()
        case["cyclic"] = False
        case["storage"]["terminal_mwh"] = 0
        case["fuels"]["coal"].update(tank_mwh=10, initial_mwh=10, injection_mw=10, withdrawal_mw=10)
        free = operate(case)
        case["fuels"]["coal"]["terminal_mwh"] = 10
        restored = operate(case)
        self.assertAlmostEqual(sum(r["domestic_mwh"] for r in free["fuel"] if r["fuel"]=="coal"), 0)
        self.assertAlmostEqual(sum(r["domestic_mwh"] for r in restored["fuel"] if r["fuel"]=="coal"), 10)
        self.assertAlmostEqual([r for r in restored["fuel"] if r["fuel"]=="coal"][-1]["closing_mwh"], 10)

    def test_frozen_discharge_changes_action_without_changing_assets(self):
        case = dispatch_case()
        case["plants"] = {"coal":case["plants"]["coal"]}
        case["plants"]["coal"]["availability"] = [1,0]
        case["demands"]["load"]["service_mwh"] = [0,5]
        case["storage"].update(charge_efficiency=1, discharge_efficiency=1)
        normal = operate(case)
        frozen = deepcopy(case)
        frozen["storage"]["discharge_limit_mwh"] = [0,0]
        result = operate(frozen)
        self.assertAlmostEqual(sum(r["unmet_service_mwh"] for r in normal["demand"]), 0)
        self.assertAlmostEqual(sum(r["unmet_service_mwh"] for r in result["demand"]), 5)
        self.assertEqual(case["storage"]["power_mw"], frozen["storage"]["power_mw"])

    def test_bad_response_caps_are_rejected(self):
        for cap in ([0], [-1,0], "zero"):
            case = dispatch_case(); case["storage"]["discharge_limit_mwh"] = cap
            with self.assertRaises(Q2Error):
                operate(case)

    def test_impossible_terminal_stock_is_infeasible(self):
        case = dispatch_case(); case["cyclic"] = False
        case["storage"]["terminal_mwh"] = 0
        for f in case["fuels"].values():
            f.update(domestic_mw=[0,0], import_mw=[0,0])
        case["fuels"]["coal"].update(tank_mwh=10, initial_mwh=0, terminal_mwh=10, injection_mw=10)
        with self.assertRaises(Q2Error) as caught:
            operate(case)
        self.assertEqual(caught.exception.status, "infeasible")

    def test_dispatch_carries_ramp_limit_across_window_boundary(self):
        case=dispatch_case();case["cyclic"]=False;case["storage"].update(power_mw=0,terminal_mwh=0)
        case["plants"]={"coal":case["plants"]["coal"]}
        case["plants"]["coal"].update(initial_power_mw=0,initial_period_hours=1,ramp_mw_per_hour=.1)
        result=operate(case)
        output=[r["output_mwh"] for r in result["generation"]]
        self.assertLessEqual(output[0],.100001)
        self.assertLessEqual(output[1],.200001)

    def test_calendar_integrates_recovery_and_elapsed_hours(self):
        _, event = event_fixture()
        rows = event_calendar(event, [6]*8)
        self.assertEqual([r["exposure"] for r in rows], [0,1,1,.5,0,0,0,0])
        self.assertEqual(rows[-1]["end_hour"], 48)
        self.assertAlmostEqual(sum(r["exposure"]*6 for r in rows), 15)

    def test_event_start_is_retained_when_not_on_period_boundary(self):
        _, event=event_fixture();event["start_hour"]=2
        rows=event_calendar(event,[6]*8)
        self.assertEqual(rows[0]["event_start_hour"],2)
        self.assertAlmostEqual(rows[0]["exposure"],4/6)

    def test_event_does_not_mutate_snapshot_or_scale_stocks_by_days(self):
        snapshot, event = event_fixture(); old = deepcopy(snapshot)
        op, _, _ = make_event_operation(snapshot,event,"SGW",.3)
        self.assertEqual(snapshot, old)
        self.assertFalse(op["cyclic"]); self.assertEqual(op["annual_repeats"],1)
        self.assertEqual(op["storage"]["initial_mwh"], snapshot["storage"]["initial_mwh"])
        self.assertEqual(op["fuels"]["gas"]["initial_mwh"], 10)
        self.assertEqual(len(op["periods"]),8)

    def test_sg_keeps_domestic_supply_other_sources_and_weather(self):
        s,e=event_fixture()
        base,_,_=make_event_operation(s,e,"S0",.3)
        sg,_,sources=make_event_operation(s,e,"SG",.3)
        self.assertEqual(sg["plants"],base["plants"])
        self.assertEqual(sg["demands"],base["demands"])
        self.assertEqual(sg["fuels"]["gas"]["domestic_mw"],base["fuels"]["gas"]["domestic_mw"])
        self.assertAlmostEqual(sources[1]["other_import_capacity_mw"],2.8)
        self.assertAlmostEqual(sg["fuels"]["gas"]["import_mw"][1], 2.8+1.2*.2)

    def test_sgw_exactly_combines_sg_and_sw(self):
        s,e=event_fixture()
        sg,_,_=make_event_operation(s,e,"SG",.3)
        sw,_,_=make_event_operation(s,e,"SW",.3)
        both,_,_=make_event_operation(s,e,"SGW",.3)
        self.assertEqual(both["fuels"],sg["fuels"])
        self.assertEqual(both["plants"],sw["plants"])
        self.assertEqual(both["demands"],sw["demands"])

    def test_zero_shocks_leave_all_operation_inputs_identical(self):
        s,e=event_fixture(); e.update(gas_channel_loss=0,renewable_loss=0)
        base,_,_=make_event_operation(s,e,"S0",.3)
        for scenario in ("SG","SW","SGW"):
            self.assertEqual(base,make_event_operation(s,e,scenario,.3)[0])

    def test_real_event_solver_keeps_fuel_and_soc_continuous(self):
        s,e=event_fixture(); run=run_event(s,e,"SGW",.3)
        result=run["result"]
        self.assertLess(result["max_residual"],.001)
        self.assertAlmostEqual(result["storage"][-1]["closing_mwh"],4)
        for previous,current in zip(result["storage"],result["storage"][1:]):
            self.assertAlmostEqual(previous["closing_mwh"],current["opening_mwh"])
        for fuel in s["fuels"]:
            self.assertAlmostEqual([r for r in result["fuel"] if r["fuel"]==fuel][-1]["closing_mwh"],10)

    def test_shock_foreknowledge_cannot_change_pre_event_state(self):
        s,e=event_fixture();e.update(start_hour=24,duration_hours=6,recovery_hours=6)
        baseline=run_event(s,e,"S0",.3)["result"]
        shock=run_event(s,e,"SGW",.3)["result"]
        for kind in ("fuel","storage","demand","generation"):
            self.assertEqual([r for r in baseline[kind] if r["period"]<4],
                             [r for r in shock[kind] if r["period"]<4])

    def test_recovery_not_silently_set_to_zero_if_censored(self):
        s,e=event_fixture(); op,calendar,_=make_event_operation(s,e,"S0",.3)
        rows=[dict(sector="critical",period=i,requested_service_mwh=10,unmet_service_mwh=5 if i>=2 else 0) for i in range(8)]
        report=safety_metrics(dict(operation=op,calendar=calendar,result=dict(demand=rows)),
                              relative_tolerance=1e-8,absolute_tolerance=.001,recovery_periods=2)[0]
        self.assertIsNone(report["recovery_hours"])
        self.assertTrue(report["right_censored"])
        self.assertEqual(report["longest_shortage_hours"],36)

    def test_zero_demand_has_no_fabricated_shortage_ratio(self):
        s,e=event_fixture();op,calendar,_=make_event_operation(s,e,"S0",.3)
        rows=[dict(sector="empty",period=i,requested_service_mwh=0,unmet_service_mwh=0) for i in range(8)]
        r=safety_metrics(dict(operation=op,calendar=calendar,result=dict(demand=rows)),
                         relative_tolerance=1e-8,absolute_tolerance=.001,recovery_periods=2)[0]
        self.assertIsNone(r["unmet_fraction"]);self.assertEqual(r["recovery_status"],"zero_demand")

    def test_interaction_is_per_service_and_requires_complete_pairs(self):
        rows=[dict(sector="heat",scenario=s,unmet_service_mwh=v) for s,v in zip(("S0","SG","SW","SGW"),(1,3,5,10))]
        self.assertEqual(interaction(rows)[0]["J"],3)
        with self.assertRaises(Q2Error):interaction(rows[:-1])
        with self.assertRaises(Q2Error):interaction(rows+rows[:1])


class ReceiptTests(unittest.TestCase):
    def bad_configuration(self, mutate, expected_status):
        config=run_q3.load(ROOT/"workflow/q3_inputs.json")
        mutate(config)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"config.json";path.write_text(json.dumps(config),encoding="utf-8")
            with self.assertRaises(Q2Error) as caught:run_q3.preflight(path)
            self.assertEqual(caught.exception.status,expected_status)

    def test_modified_input_hash_is_rejected_before_simulation(self):
        self.bad_configuration(lambda c:c["input_hashes"].update({next(iter(c["input_hashes"])):"0"*64}),"changed_input")

    def test_new_policy_start_is_not_silently_ignored(self):
        self.bad_configuration(lambda c:c["scenarios"]["SP"].update(effective_year=2030),"invalid_input")

    def test_invalid_cost_multiplier_is_rejected(self):
        self.bad_configuration(lambda c:c["scenarios"]["ST"].update(storage_new_project_cost_multiplier=0),"invalid_input")

    def test_missing_scenario_is_not_full_success(self):
        self.bad_configuration(lambda c:c["scenarios"].pop("SGW"),"missing_input")

    def test_withdrawn_use_is_rejected_even_if_config_hash_is_updated(self):
        actual=run_q3.load
        def withdrawn(path):
            data=actual(path)
            if Path(path).name=="q3_input_review.json":data["permissions"].remove("h02_battery_response_freeze")
            return data
        with patch.object(run_q3,"load",side_effect=withdrawn):
            with self.assertRaises(Q2Error) as caught:run_q3.preflight(ROOT/"workflow/q3_inputs.json")
        self.assertEqual(caught.exception.status,"withdrawn_use")

    def test_missing_config_creates_failed_latest_attempt(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(run_q3,"ROOT",Path(temp)):
            code=run_q3.main(["--config","missing.json","--output-dir","outputs/q3/test"])
            self.assertNotEqual(code,0)
            latest=json.loads((Path(temp)/"outputs/q3/test.latest-attempt.json").read_text())
            self.assertFalse(latest["output_valid_for_this_attempt"])
            self.assertFalse(latest["full_q3_complete"])
            first=latest["run_id"]
            run_q3.main(["--config","missing.json","--output-dir","outputs/q3/test"])
            self.assertTrue((Path(temp)/"outputs/q3/test.attempts"/first/"run_manifest.json").is_file())

    def test_restricted_paths_are_rejected(self):
        with self.assertRaises(Q2Error):run_q3.safe_path("data/restricted/anything.csv")
        with self.assertRaises(Q2Error):run_q3.safe_path("../outside.csv")


if __name__=="__main__":unittest.main()
