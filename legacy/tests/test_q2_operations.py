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


@unittest.skipUnless(AVAILABLE, "Install requirements-q2.txt")
class FossilDisplacementTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
