"""Counterexamples for optional dispatch priority and fossil allocation."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
AVAILABLE = importlib.util.find_spec("scipy") is not None
if AVAILABLE:
    from energy_model.q2_operations import operate, Q2Error


def dispatch_case():
    fuel = dict(domestic_mw=[20, 20], import_mw=[0, 0],
                domestic_cost_per_mwh=1, import_cost_per_mwh=1,
                emission_t_per_mwh=.3, tank_mwh=0, initial_mwh=0,
                injection_mw=0, withdrawal_mw=0)
    plant = dict(input="coal", output="electricity", efficiency=1,
                 capacity_mw=20, availability=[1, 1],
                 variable_cost_per_mwh=0, minimum_fraction=0,
                 ramp_mw_per_hour=100, window_energy_budget_mwh=40)
    return dict(periods=[dict(hours=1), dict(hours=1)], annual_repeats=1,
                cyclic=True, grid=dict(efficiency=1, power_mw=100),
                storage=dict(power_mw=10, energy_mwh=10, initial_mwh=0,
                             charge_efficiency=.8, discharge_efficiency=.8,
                             throughput_cost=.01),
                fuels=dict(coal=deepcopy(fuel),
                           biomass={**fuel, "domestic_cost_per_mwh": 100,
                                    "import_cost_per_mwh": 100,
                                    "emission_t_per_mwh": 0}),
                plants=dict(coal=deepcopy(plant),
                            biomass={**plant, "input": "biomass"}),
                demands=dict(load=dict(sector="building", carrier="electricity",
                                       efficiency=1, input_capacity_mw=20,
                                       priority=0, service_mwh=[5, 5])))


def generation(result, plant):
    return sum(r["output_mwh"] for r in result["generation"] if r["plant"] == plant)


def allocation_case():
    case = dispatch_case()
    case["demands"]["load"]["service_mwh"] = [10, 10]
    case["plants"] = {"coal": case["plants"]["coal"]}
    case["plants"]["gas"] = deepcopy(case["plants"]["coal"])
    case["plants"]["gas"]["input"] = "gas"
    case["fuels"]["gas"] = deepcopy(case["fuels"]["coal"])
    case["fuels"]["gas"].update(domestic_cost_per_mwh=3, import_cost_per_mwh=3)
    case["fossil_allocation_score"] = dict(kappa=20, plants={
        "coal": dict(reference_cf=.25, initial_marginal_cost=1),
        "gas": dict(reference_cf=.25, initial_marginal_cost=3)})
    return case


def recovered_case():
    case=dispatch_case()
    carrier={**deepcopy(case["fuels"]["coal"]), "domestic_mw":[0,0],
             "domestic_cost_per_mwh":0,"import_cost_per_mwh":0,
             "emission_t_per_mwh":0,"internal_recovered_carrier":True}
    case["fuels"]={"coal":case["fuels"]["coal"],"recovered_heat":carrier}
    case["plants"]={"waste_heat":{**case["plants"]["coal"],"input":"recovered_heat"}}
    case["demands"]["factory"] = dict(sector="industry",carrier="coal",efficiency=.5,
        input_capacity_mw=20,priority=0,service_mwh=[5,5])
    case["recoveries"]={"industry":dict(output="recovered_heat",source_input_fractions={"factory":.5})}
    return case


@unittest.skipUnless(AVAILABLE,"Install requirements-q2.txt")
class RecoveryAndIndependentStorageTests(unittest.TestCase):
    def test_recovery_uses_actual_upstream_loss_and_counts_primary_and_carbon_once(self):
        result=operate(recovered_case())
        coal=[r for r in result["fuel"] if r["fuel"]=="coal"]
        self.assertAlmostEqual(sum(r["domestic_mwh"] for r in coal),20)
        self.assertAlmostEqual(sum(r["combustion_co2_t"] for r in result["fuel"]),6)
        self.assertAlmostEqual(generation(result,"waste_heat"),10)
        self.assertAlmostEqual(sum(r["recovered_mwh"] for r in result["recoveries"]),10)
        self.assertAlmostEqual(result["resource_cost"],20)
        self.assertAlmostEqual(sum(r["served_service_mwh"] for r in result["demand"]),20)

    def test_unserved_upstream_cannot_produce_free_power(self):
        case=recovered_case()
        case["fuels"]["coal"]["domestic_mw"]=[0,0]
        result=operate(case)
        self.assertEqual(generation(result,"waste_heat"),0)
        self.assertEqual(sum(r["recovered_mwh"] for r in result["recoveries"]),0)
        self.assertEqual(sum(r["unmet_service_mwh"] for r in result["demand"]),20)

    def test_duplicate_recovery_claims_and_untraced_inventory_fail(self):
        case=recovered_case()
        case["recoveries"]["duplicate"]=deepcopy(case["recoveries"]["industry"])
        with self.assertRaisesRegex(Q2Error,"exceed"):operate(case)
        case=recovered_case()
        case["fuels"]["recovered_heat"].update(tank_mwh=5,initial_mwh=5)
        with self.assertRaisesRegex(Q2Error,"opening stock"):operate(case)

    def test_nonenergy_feedstock_cannot_generate_zero_carbon_recovery(self):
        case=recovered_case()
        case["demands"]["factory"]["sector"]="nonenergy_feedstock"
        with self.assertRaisesRegex(Q2Error,"Recovery source"):operate(case)

    def test_internal_carrier_cannot_hide_primary_supply_without_recovery_spec(self):
        case=recovered_case()
        case.pop("recoveries")
        case["fuels"]["recovered_heat"]["domestic_mw"]=[1,1]
        with self.assertRaises(Q2Error):operate(case)

    def test_independent_pump_has_own_efficiency_stock_and_losses(self):
        case=dispatch_case()
        case["plants"]={"coal":case["plants"]["coal"]}
        case["plants"]["coal"]["availability"]=[1,0]
        case["demands"]["load"]["service_mwh"]=[0,4]
        case["storage"].update(power_mw=0,energy_mwh=0)
        case["additional_storage"]={"pump":dict(power_mw=8,energy_mwh=8,
            initial_mwh=0,charge_efficiency=1,discharge_efficiency=.5,throughput_cost=.01)}
        result=operate(case)
        self.assertAlmostEqual(generation(result,"coal"),8)
        pump=result["additional_storage"]
        self.assertAlmostEqual(pump[0]["charge_mwh"],8)
        self.assertAlmostEqual(pump[1]["discharge_mwh"],4)
        self.assertAlmostEqual(pump[1]["discharging_loss_mwh"],4)
        self.assertEqual(pump[-1]["closing_mwh"],0)
        self.assertEqual(sum(r["charge_mwh"]+r["discharge_mwh"] for r in result["storage"]),0)
        case["annual_repeats"]=365
        repeated=operate(case)
        self.assertEqual(repeated["additional_storage"],pump)
        self.assertAlmostEqual(repeated["resource_cost"],result["resource_cost"]*365)

    def test_pump_cannot_borrow_battery_opening_stock(self):
        case=dispatch_case()
        case["plants"]={"coal":case["plants"]["coal"]}
        case["plants"]["coal"]["capacity_mw"]=0
        case["cyclic"]=False
        case["storage"].update(power_mw=0,initial_mwh=10,terminal_mwh=10)
        case["additional_storage"]={"pump":dict(power_mw=10,energy_mwh=10,
            initial_mwh=0,terminal_mwh=0,charge_efficiency=1,discharge_efficiency=1,throughput_cost=.01)}
        result=operate(case)
        self.assertEqual(sum(r["unmet_service_mwh"] for r in result["demand"]),10)
        self.assertEqual(sum(r["discharge_mwh"] for r in result["additional_storage"]),0)

    @unittest.skipUnless(importlib.util.find_spec("mesa"),"Install mesa")
    def test_national_scaling_preserves_recovery_and_carbon_units(self):
        from energy_model.q2_national import operate_national
        case=recovered_case()
        case["additional_storage"]={"pump":dict(power_mw=1,energy_mwh=1,initial_mwh=0,
            charge_efficiency=.9,discharge_efficiency=.9,throughput_cost=1)}
        ordinary=operate(case);national=operate_national(case)
        for group in ("fuel","generation","demand","recoveries","additional_storage"):
            for a,b in zip(ordinary[group],national[group]):
                for key,value in a.items():
                    if key.endswith(("_mwh","_co2_t")):
                        self.assertAlmostEqual(value,b[key],places=7)


@unittest.skipUnless(AVAILABLE, "Install requirements-q2.txt")
class FossilDisplacementTests(unittest.TestCase):
    def test_station_own_use_reduces_delivery_without_reducing_fuel_or_gross_generation(self):
        case=dispatch_case()
        case["plants"]={"coal":case["plants"]["coal"]}
        case["plants"]["coal"]["auxiliary_use_fraction"]=.5
        result=operate(case)
        self.assertAlmostEqual(generation(result,"coal"),20)
        self.assertAlmostEqual(sum(r["conversion_mwh"] for r in result["fuel"]),20)
        self.assertAlmostEqual(sum(r["bus_output_mwh"] for r in result["generation"]),10)
        self.assertAlmostEqual(sum(r["auxiliary_use_mwh"] for r in result["generation"]),10)
        self.assertAlmostEqual(sum(r["unmet_service_mwh"] for r in result["demand"]),0)

    def test_station_loss_cannot_be_reused_when_capacity_is_exhausted(self):
        case=dispatch_case()
        case["plants"]={"coal":case["plants"]["coal"]}
        case["plants"]["coal"].update(auxiliary_use_fraction=.5,capacity_mw=5)
        result=operate(case)
        self.assertAlmostEqual(generation(result,"coal"),10)
        self.assertAlmostEqual(sum(r["unmet_service_mwh"] for r in result["demand"]),5)
        for r in result["generation"]:
            self.assertAlmostEqual(r["output_mwh"],r["bus_output_mwh"]+r["auxiliary_use_mwh"])

    def test_impossible_or_wrong_carrier_auxiliary_use_is_rejected(self):
        case=dispatch_case()
        case["plants"]["coal"]["auxiliary_use_fraction"]=1.1
        with self.assertRaises(Q2Error):operate(case)
        case["plants"]["coal"].update(auxiliary_use_fraction=.1,output="hydrogen")
        with self.assertRaises(Q2Error):operate(case)

    def test_default_keeps_cost_dispatch_and_empty_option_is_identical(self):
        case = dispatch_case()
        original = operate(case)
        self.assertAlmostEqual(generation(original, "coal"), 10)
        self.assertAlmostEqual(generation(original, "biomass"), 0)
        case["fossil_displacement_priority_plants"] = []
        self.assertEqual(original, operate(case))
        self.assertEqual([r["stage"] for r in original["stages"]],
                         ["service-priority-0", "resource-cost"])

    def test_expensive_biomass_displaces_coal_without_cost_or_revenue_fabrication(self):
        case = dispatch_case()
        case["fossil_displacement_priority_plants"] = ["coal"]
        result = operate(case)
        self.assertAlmostEqual(generation(result, "coal"), 0)
        self.assertAlmostEqual(generation(result, "biomass"), 10)
        self.assertAlmostEqual(result["resource_cost"], 1000)
        self.assertAlmostEqual(result["dispatch_objective"], 1000)
        self.assertAlmostEqual(result["policy_signal_cost"], 0)
        self.assertEqual([r["stage"] for r in result["stages"]],
                         ["service-priority-0", "fossil-displacement-priority", "resource-cost"])
        self.assertEqual(result["stages"][1]["plants"], ["coal"])
        self.assertAlmostEqual(result["stages"][1]["objective"], 0)

    def test_fuel_shortage_keeps_service_and_feasible_fossil_fallback(self):
        case = dispatch_case()
        case["fossil_displacement_priority_plants"] = ["coal"]
        case["fuels"]["biomass"]["domestic_mw"] = [2, 2]
        result = operate(case)
        self.assertAlmostEqual(generation(result, "biomass"), 4)
        self.assertAlmostEqual(generation(result, "coal"), 6)
        self.assertAlmostEqual(sum(r["unmet_service_mwh"] for r in result["demand"]), 0)
        case["fuels"]["coal"]["domestic_mw"] = [0, 0]
        result = operate(case)
        self.assertAlmostEqual(sum(r["unmet_service_mwh"] for r in result["demand"]), 6)
        self.assertAlmostEqual(generation(result, "biomass"), 4)

    def test_no_demand_never_forces_generation_or_storage_dissipation(self):
        case = dispatch_case()
        case["fossil_displacement_priority_plants"] = ["coal"]
        case["demands"]["load"]["service_mwh"] = [0, 0]
        result = operate(case)
        self.assertAlmostEqual(generation(result, "coal") + generation(result, "biomass"), 0)
        self.assertAlmostEqual(sum(r["charge_mwh"] + r["discharge_mwh"]
                                   for r in result["storage"]), 0)

    def test_lossy_storage_does_not_inflate_prioritised_biomass(self):
        case = dispatch_case()
        case["fossil_displacement_priority_plants"] = ["coal"]
        result = operate(case)
        self.assertAlmostEqual(generation(result, "biomass"), 10)
        self.assertAlmostEqual(sum(r["charge_mwh"] + r["discharge_mwh"]
                                   for r in result["storage"]), 0)

    def test_grid_bottleneck_is_not_overridden(self):
        case = dispatch_case()
        case["fossil_displacement_priority_plants"] = ["coal"]
        case["grid"]["power_mw"] = 2
        result = operate(case)
        self.assertAlmostEqual(generation(result, "biomass"), 4)
        self.assertAlmostEqual(sum(r["unmet_service_mwh"] for r in result["demand"]), 6)

    def test_invalid_priority_plants_are_rejected(self):
        for names in ("coal", ["missing"], ["coal", "coal"], [None]):
            with self.subTest(names=names):
                case = dispatch_case()
                case["fossil_displacement_priority_plants"] = names
                with self.assertRaises(Q2Error):
                    operate(case)


@unittest.skipUnless(AVAILABLE, "Install requirements-q2.txt")
class FossilAllocationTests(unittest.TestCase):
    def test_unequal_auxiliary_use_does_not_freeze_fuel_mix(self):
        # The same delivered fossil electricity must permit different gross
        # outputs. Fixing gross AND net totals would force a single fuel mix.
        for priority in (False, True):
            case = allocation_case()
            case["plants"]["coal"]["auxiliary_use_fraction"] = .1
            if priority:
                case["fossil_displacement_priority_plants"] = ["coal", "gas"]
            result = operate(case)
            coal, gas = generation(result,"coal"), generation(result,"gas")
            self.assertAlmostEqual(.9*coal+gas,20)
            self.assertGreater(coal,5)
            self.assertGreater(gas,5)
            self.assertLess(gas,15)
            self.assertAlmostEqual(result["reference_fossil_mwh"],20)
            self.assertEqual(result["reference_fossil_energy_basis"],"net_bus_output_mwh")

    def test_clean_priority_does_not_prefer_expensive_low_auxiliary_gas(self):
        case = allocation_case()
        case.pop("fossil_allocation_score")
        case["plants"]["coal"]["auxiliary_use_fraction"] = .1
        case["fossil_displacement_priority_plants"] = ["coal", "gas"]
        result = operate(case)
        self.assertAlmostEqual(generation(result,"gas"),0)
        self.assertAlmostEqual(.9*generation(result,"coal"),20)

    def test_disabled_option_keeps_old_stages_and_result_fields(self):
        case = allocation_case()
        case.pop("fossil_allocation_score")
        result = operate(case)
        case["fossil_allocation_score"] = None
        self.assertEqual(operate(case), result)
        self.assertEqual([r["stage"] for r in result["stages"]],
                         ["service-priority-0", "resource-cost"])
        self.assertNotIn("behavioral_score", result)
        self.assertAlmostEqual(generation(result, "coal"), 20)

    def test_anchor_knots_recover_initial_mix_for_different_segment_widths(self):
        for width in (.2, .1, .05, .02):
            with self.subTest(width=width):
                case = allocation_case()
                case["fossil_allocation_score"]["ratio_step"] = width
                result = operate(case)
                self.assertAlmostEqual(generation(result, "coal"), 10, places=8)
                self.assertAlmostEqual(generation(result, "gas"), 10, places=8)
                self.assertAlmostEqual(result["reference_fossil_mwh"], 20)

    def test_behavioral_score_does_not_enter_resource_or_policy_cost(self):
        result = operate(allocation_case())
        self.assertAlmostEqual(result["resource_cost"], 40)
        self.assertAlmostEqual(result["resource_cost"] + result["policy_signal_cost"],
                               result["actual_dispatch_cost"])
        self.assertAlmostEqual(result["dispatch_objective"],
                               result["actual_dispatch_cost"] + result["behavioral_score"])
        self.assertNotAlmostEqual(result["resource_cost"], result["dispatch_objective"])
        self.assertEqual([r["stage"] for r in result["stages"]],
                         ["service-priority-0", "reference-resource-cost", "fossil-allocation-score"])
        case = allocation_case()
        case["plants"]["gas"]["policy_cost_per_mwh"] = .5
        result = operate(case)
        physical_cost = generation(result, "coal") + 3 * generation(result, "gas")
        self.assertAlmostEqual(result["resource_cost"], physical_cost)
        self.assertAlmostEqual(result["policy_signal_cost"], .5 * generation(result, "gas"))

    def test_zero_demand_has_no_forced_generation(self):
        case = allocation_case()
        case["demands"]["load"]["service_mwh"] = [0, 0]
        result = operate(case)
        self.assertEqual(generation(result, "coal") + generation(result, "gas"), 0)
        self.assertEqual(result["resource_cost"], 0)

    def test_fuel_absence_allows_gas_zero_without_extra_shortage(self):
        case = allocation_case()
        case["fuels"]["gas"]["domestic_mw"] = [0, 0]
        result = operate(case)
        self.assertEqual(generation(result, "gas"), 0)
        self.assertAlmostEqual(generation(result, "coal"), 20)
        self.assertAlmostEqual(sum(r["unmet_service_mwh"] for r in result["demand"]), 0)

    def test_real_price_shock_changes_mix_without_refitting_initial_cost(self):
        case = allocation_case()
        before = operate(case)
        case["fuels"]["gas"].update(domestic_cost_per_mwh=30, import_cost_per_mwh=30)
        after = operate(case)
        self.assertLess(generation(after, "gas"), generation(before, "gas"))
        self.assertGreater(generation(after, "coal"), generation(before, "coal"))
        self.assertEqual(case["fossil_allocation_score"]["plants"]["gas"]["initial_marginal_cost"], 3)
        self.assertEqual(after["reference_fossil_mwh"], before["reference_fossil_mwh"])

    def test_segment_approximation_error_shrinks_to_quadratic_solution(self):
        # With Bcoal=Bgas=10, kappa=20, total=20, a gas cost increase
        # of 3 gives the continuous convex optimum gas=9.25, coal=10.75.
        errors = []
        for width in (.2, .1, .05, .02):
            case = allocation_case()
            case["fossil_allocation_score"]["ratio_step"] = width
            case["fuels"]["gas"].update(domestic_cost_per_mwh=6, import_cost_per_mwh=6)
            result = operate(case)
            error = abs(generation(result, "gas") - 9.25)
            self.assertLessEqual(error, 10 * width + 1e-8)
            self.assertAlmostEqual(generation(result, "gas") + generation(result, "coal"), 20)
            errors.append(error)
        self.assertLess(errors[-1], errors[0])
        self.assertLessEqual(errors[-1], .2 + 1e-8)

    def test_reference_total_preserves_clean_dispatch_before_priority(self):
        case = allocation_case()
        case["plants"]["wind"] = deepcopy(case["plants"]["coal"])
        case["plants"]["wind"].update(input=None, capacity_mw=5)
        baseline = deepcopy(case)
        baseline.pop("fossil_allocation_score")
        original, result = operate(baseline), operate(case)
        self.assertAlmostEqual(generation(original, "wind"), generation(result, "wind"))
        self.assertAlmostEqual(sum(generation(original, f) for f in ("coal", "gas")),
                               sum(generation(result, f) for f in ("coal", "gas")))

    def test_nonfossil_priority_and_allocation_both_preserve_physics(self):
        case = allocation_case()
        case["plants"]["biomass"] = deepcopy(case["plants"]["coal"])
        case["plants"]["biomass"].update(input="biomass", capacity_mw=3)
        case["fossil_displacement_priority_plants"] = ["coal", "gas"]
        result = operate(case)
        self.assertAlmostEqual(generation(result, "biomass"), 6)
        self.assertAlmostEqual(generation(result, "coal") + generation(result, "gas"), 14)
        self.assertEqual([r["stage"] for r in result["stages"]],
                         ["service-priority-0", "fossil-displacement-priority",
                          "reference-resource-cost", "fossil-allocation-score"])

    def test_negative_score_slopes_do_not_reward_lossy_storage_cycles(self):
        case = allocation_case()
        case["storage"].update(power_mw=20, energy_mwh=20,
                               charge_efficiency=.8, discharge_efficiency=.8)
        result = operate(case)
        self.assertAlmostEqual(generation(result, "coal") + generation(result, "gas"), 20)
        self.assertAlmostEqual(sum(r["charge_mwh"] + r["discharge_mwh"]
                                   for r in result["storage"]), 0)

    def test_capacity_grid_and_shortage_limits_still_hold(self):
        case = allocation_case()
        case["plants"]["gas"]["capacity_mw"] = 1
        self.assertLessEqual(generation(operate(case), "gas"), 2 + 1e-8)
        case = allocation_case()
        case["grid"]["power_mw"] = 4
        result = operate(case)
        self.assertAlmostEqual(sum(r["served_service_mwh"] for r in result["demand"]), 8)
        self.assertAlmostEqual(generation(result, "coal") + generation(result, "gas"), 8)

    def test_zero_capacity_and_small_initial_cf_keep_finite_segments(self):
        case = allocation_case()
        case["plants"]["gas"]["capacity_mw"] = 0
        self.assertEqual(generation(operate(case), "gas"), 0)
        case = allocation_case()
        case["fossil_allocation_score"]["plants"]["gas"]["reference_cf"] = 1e-8
        result = operate(case)
        self.assertLessEqual(result["max_residual"], 1e-6)

    def test_annual_repeats_scale_cost_and_score_not_physical_stocks(self):
        case = allocation_case()
        before = operate(case)
        case["annual_repeats"] = 2
        after = operate(case)
        self.assertEqual(before["generation"], after["generation"])
        self.assertEqual(before["storage"], after["storage"])
        self.assertAlmostEqual(after["resource_cost"], 2 * before["resource_cost"])
        self.assertAlmostEqual(after["behavioral_score"], 2 * before["behavioral_score"])

    def test_uniform_energy_scaling_preserves_mix_and_unit_scores(self):
        def scaled(obj):
            if not isinstance(obj, dict):
                return deepcopy(obj)
            return {k: ([x * 1000 for x in v] if isinstance(v, list) else v * 1000)
                    if ((k.endswith(("_mwh", "_mw")) and "_per_" not in k) or
                        k == "ramp_mw_per_hour") else scaled(v) for k, v in obj.items()}
        case = allocation_case()
        before, after = operate(case), operate(scaled(case))
        for fuel in ("coal", "gas"):
            self.assertAlmostEqual(generation(after, fuel), 1000 * generation(before, fuel))
        for key in ("resource_cost", "behavioral_score", "actual_dispatch_cost", "reference_fossil_mwh"):
            self.assertAlmostEqual(after[key], 1000 * before[key])

    def test_invalid_allocation_is_rejected(self):
        for change in (
                lambda c: c.update(fossil_allocation_score=[]),
                lambda c: c["fossil_allocation_score"].update(kappa=0),
                lambda c: c["fossil_allocation_score"].update(kappa=float("nan")),
                lambda c: c["fossil_allocation_score"].update(ratio_step=0),
                lambda c: c["fossil_allocation_score"].update(unexpected=True),
                lambda c: c["fossil_allocation_score"]["plants"].pop("gas"),
                lambda c: c["fossil_allocation_score"]["plants"]["gas"].update(reference_cf=0),
                lambda c: c["fossil_allocation_score"]["plants"]["gas"].update(initial_marginal_cost=-1),
                lambda c: c["fossil_allocation_score"]["plants"].update(
                    missing=dict(reference_cf=.2, initial_marginal_cost=3)),
                lambda c: c["fossil_allocation_score"]["plants"].update(
                    biomass=dict(reference_cf=.2, initial_marginal_cost=100))):
            case = allocation_case()
            change(case)
            with self.subTest(case=case["fossil_allocation_score"]):
                with self.assertRaises(Q2Error):
                    operate(case)


@unittest.skipUnless(AVAILABLE, "scipy required")
class FuelReserveTests(unittest.TestCase):
    def case(self):
        case = dispatch_case()
        case["cyclic"] = False
        case["storage"]["terminal_mwh"] = 0
        case["plants"] = {"coal": case["plants"]["coal"]}
        case["fuels"] = {"coal": case["fuels"]["coal"]}
        case["fuels"]["coal"].update(domestic_mw=[0, 0], tank_mwh=10,
            initial_mwh=10, injection_mw=10, withdrawal_mw=10)
        return case

    def test_terminal_reserve_prevents_free_end_inventory_exhaustion(self):
        case = self.case()
        self.assertAlmostEqual(generation(operate(case), "coal"), 10)
        case["fuels"]["coal"]["minimum_terminal_mwh"] = 6
        result = operate(case)
        self.assertAlmostEqual(generation(result, "coal"), 4)
        self.assertAlmostEqual(result["fuel"][-1]["closing_mwh"], 6)
        self.assertAlmostEqual(sum(r["unmet_service_mwh"] for r in result["demand"]), 6)

    def test_reserve_can_be_refilled_and_is_not_a_daily_reset(self):
        case = self.case()
        case["fuels"]["coal"].update(domestic_mw=[0, 10], minimum_terminal_mwh=10)
        result = operate(case)
        self.assertAlmostEqual(generation(result, "coal"), 10)
        self.assertAlmostEqual(result["fuel"][0]["closing_mwh"], 5)
        self.assertAlmostEqual(result["fuel"][-1]["closing_mwh"], 10)

    def test_invalid_and_conflicting_reserves_rejected(self):
        for value in (-1, 11, float("nan")):
            case = self.case()
            case["fuels"]["coal"]["minimum_terminal_mwh"] = value
            with self.assertRaises(Q2Error):
                operate(case)
        case = self.case()
        case["cyclic"] = True
        case["fuels"]["coal"].update(initial_mwh=5, minimum_terminal_mwh=6)
        with self.assertRaises(Q2Error):
            operate(case)


@unittest.skipUnless(AVAILABLE, "scipy required")
class DecisionCeilingTests(unittest.TestCase):
    def test_restricted_action_keeps_physical_bounds_and_score_unchanged(self):
        from scipy.optimize import linprog
        import numpy as np
        case = allocation_case()
        before = deepcopy(case)
        def solve_and_capture(c):
            calls = []
            def solver(costs, **kwargs):
                calls.append((costs.copy(), deepcopy(kwargs["bounds"])))
                return linprog(costs, **kwargs)
            return operate(c, solver=solver), calls
        full, full_calls = solve_and_capture(case)
        case["plants"]["gas"]["decision_ceiling_mwh"] = [1.25, 1.25]
        limited, limited_calls = solve_and_capture(case)
        self.assertGreater(generation(full, "gas"), 2.5)
        self.assertLessEqual(generation(limited, "gas"), 2.5 + 1e-7)
        self.assertEqual(case["plants"]["gas"]["availability"], before["plants"]["gas"]["availability"])
        self.assertEqual(len(full_calls), len(limited_calls))
        for (a, bounds_a), (b, bounds_b) in zip(full_calls, limited_calls):
            np.testing.assert_array_equal(a, b)
            self.assertEqual(bounds_a, bounds_b)

    def test_ceiling_cannot_relax_minimum_output_or_physical_capacity(self):
        case = dispatch_case()
        case["plants"]["coal"].update(minimum_fraction=.2, decision_ceiling_mwh=[1, 1])
        with self.assertRaises(Q2Error) as ctx:
            operate(case)
        self.assertEqual(ctx.exception.status, "infeasible")
        case = allocation_case()
        case["plants"]["gas"]["decision_ceiling_mwh"] = [1000, 1000]
        self.assertAlmostEqual(generation(operate(case), "gas"), generation(operate(allocation_case()), "gas"))
        for value in (None, [1], [1, float("nan")], [-1, 0], "invalid"):
            case["plants"]["gas"]["decision_ceiling_mwh"] = value
            with self.assertRaises(Q2Error):
                operate(case)


if __name__ == "__main__":
    unittest.main()
