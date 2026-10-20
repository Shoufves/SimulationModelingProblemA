"""Independent annual-exposure counterexamples; no empirical fit assertions."""
from copy import deepcopy
from math import fsum
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(ROOT/"scripts"))

from energy_model.q2_exposure import AnnualExposure
from energy_model.q2_national import NationalModel
from energy_model.q2_revenue import AnnualRevenuePolicy
from energy_model.q2_subsidies import SupportTerms
from energy_model.q2_support_investment import SupportOffer, NewProjectSupport
from energy_model.q2_renewable_vintages import RenewableVintages
from run_q2_national import preflight


def asset(name, *, tech="wind", capacity=100, online=2000, exit=2040):
    return dict(id=name, tech=tech, capacity_mw=capacity, online_year=online,
                exit_year=exit, status="active", reconstruction=True,
                book_cost_cny_per_mw=1)


def offer(**changes):
    values = dict(technology="biomass", decision_year=2014, announced_year=2014,
        commissioning_deadline=2020, eligible_years=2, lifetime_hours=1500,
        premium_cap_nominal_cny_per_mwh=1,
        expected_premium_nominal_cny_per_mwh=1, metering_fraction=1,
        expected_collection_fraction=1, expected_payment_delay_years=0,
        expected_real_2024_per_nominal=1, priority=1, evidence="synthetic")
    values.update(changes)
    return SupportOffer(**values)


class ExposureMathTests(unittest.TestCase):
    def test_birth_middle_death_and_outside_calendar_years(self):
        e = AnnualExposure(first_year_fraction=.25, evidence="synthetic")
        a = asset("p", online=2015, exit=2018)
        self.assertEqual([e.weight(a, y) for y in range(2014, 2020)],
                         [0, .25, 1, 1, .75, 0])

    def test_full_life_exposure_is_conserved_even_at_endpoints(self):
        for alpha in (0, .25, .5, 1):
            for life in (1, 2, 25):
                e = AnnualExposure(first_year_fraction=alpha, evidence="synthetic")
                a = asset("p", online=2015, exit=2015+life)
                self.assertAlmostEqual(fsum(e.weight(a, y)
                    for y in range(2014, 2017+life)), life)

    def test_one_year_life_has_two_partial_calendar_years(self):
        e = AnnualExposure(first_year_fraction=.5, evidence="synthetic")
        a = asset("p", online=2015, exit=2016)
        self.assertEqual(e.weight(a, 2015), .5)
        self.assertEqual(e.weight(a, 2016), .5)
        self.assertEqual(e.weight(a, 2017), 0)

    def test_pv_uses_first_and_last_partial_years_separately(self):
        e = AnnualExposure(first_year_fraction=.25, evidence="synthetic")
        expected = .25/1.1**2 + 1/1.1**3 + .75/1.1**4
        self.assertAlmostEqual(e.energy_pv_factor(
            lead=2, life=2, discount_rate=.1), expected)
        self.assertEqual(e.energy_pv_factor(
            lead=2, life=2, discount_rate=0), 2)

    def test_alpha_one_reproduces_original_full_year_annuity(self):
        e = AnnualExposure(first_year_fraction=1, evidence="synthetic")
        expected = fsum(1/1.08**k for k in range(3, 23))
        self.assertAlmostEqual(e.energy_pv_factor(
            lead=3, life=20, discount_rate=.08), expected)

    def test_invalid_fraction_and_missing_evidence_rejected(self):
        for fraction in (-.1, 1.1, float("nan"), float("inf"), True):
            with self.subTest(fraction=fraction), self.assertRaises(ValueError):
                AnnualExposure(first_year_fraction=fraction, evidence="synthetic")
        with self.assertRaises(ValueError):
            AnnualExposure(first_year_fraction=.5, evidence="")


class NationalExposureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.design, _ = preflight()
        cls.theta = dict(activity_elasticity=.5, investment_response=1,
            renewable_mix_response=.7, replacement_adoption=.2, expectation_rate=1)

    def model(self, *, enabled=True, vintages=False):
        kwargs = dict(investment=False)
        if enabled:
            kwargs["annual_exposure"] = AnnualExposure(
                first_year_fraction=.5, evidence="synthetic")
        if vintages:
            kwargs["renewable_vintages"] = RenewableVintages(
                new_project_cf={"wind":.2, "solar":.1}, evidence="synthetic")
        return NationalModel(deepcopy(self.data), self.design, self.theta, 2014,
                             **kwargs)

    def replace_assets(self, m, rows, tech="wind"):
        m.cohorts = [c for c in m.cohorts if c["tech"] != tech] + rows
        removed = fsum(p["remaining"] for p in m.projects if p["tech"] == tech)
        m.projects = [p for p in m.projects if p["tech"] != tech]
        m.construction_fund -= removed

    def test_old_plus_new_separates_stock_from_annual_operation(self):
        m = self.model()
        self.replace_assets(m, [asset("old"), asset("new", online=2015)])
        m.drivers()
        m.mature()
        self.assertEqual(m.generators["wind"].capacity, 200)
        self.assertEqual(m.generation_capacity("wind", 2015), 150)
        self.assertEqual(m.generation_capacity("wind", 2015, physical=True), 200)
        self.assertEqual(m.make_operation()["plants"]["wind"]["capacity_mw"], 150)

    def test_retirement_year_has_output_exposure_but_zero_end_stock(self):
        m = self.model()
        self.replace_assets(m, [asset("retiring", exit=2015)])
        m.drivers()
        m.mature()
        self.assertEqual(m.generators["wind"].capacity, 0)
        self.assertEqual(m.generation_capacity("wind", 2015), 50)
        self.assertEqual(m.generation_capacity("wind", 2015, physical=True), 0)
        self.assertEqual(m.make_operation()["plants"]["wind"]["capacity_mw"], 50)

    def test_real_maturity_adds_one_weighted_cohort_without_duplicate_pipeline(self):
        m = self.model(vintages=True)
        self.replace_assets(m, [asset("old")])
        m.projects.append(dict(id="paid-new", tech="wind", capacity_mw=100,
            decision_year=2014, online_year=2015, exit_year=2040,
            remaining=0, status="construction", cost=1000000,
            instalment=1000000, initial_reconstruction=False, generation_cf=.2))
        m.mature()
        rows = m.generation_assets("wind", 2015)
        self.assertEqual(sum(c["id"] == "paid-new" for c, w in rows), 1)
        self.assertEqual(m.projects[-1]["status"], "commissioned")
        self.assertEqual(m.generation_capacity("wind", 2015), 150)
        self.assertEqual(m.generation_capacity("wind", 2015, physical=True), 200)

    def test_equal_addition_and_retirement_cannot_use_net_stock_change(self):
        m = self.model()
        self.replace_assets(m, [asset("old", capacity=50),
            asset("retiring", capacity=50, exit=2015),
            asset("new", capacity=50, online=2015)])
        m.mature()
        self.assertEqual(m.generation_capacity("wind", 2015, physical=True), 100)
        self.assertEqual(m.generation_capacity("wind", 2015), 100)
        weights = {c["id"]: w for c, w in m.generation_assets("wind", 2015)}
        self.assertEqual(weights, {"old":1, "retiring":.5, "new":.5})

    def test_initial_year_cohort_is_full_in_next_year_and_cf_not_halved_again(self):
        old, new = self.model(enabled=False), self.model()
        for tech in ("hydro", "nuclear", "wind", "solar"):
            self.assertEqual(old.generators[tech].reference_cf,
                             new.generators[tech].reference_cf)
        self.replace_assets(new, [asset("initial2014", online=2014)])
        new.mature()
        self.assertEqual(new.generation_capacity("wind", 2015), 100)

    def test_opt_out_keeps_full_birth_year_and_zero_retirement_year(self):
        m = self.model(enabled=False)
        self.replace_assets(m, [asset("new", online=2015),
                                asset("retiring", exit=2015)])
        m.drivers()
        m.mature()
        self.assertEqual(m.make_operation()["plants"]["wind"]["capacity_mw"], 100)

    def test_fixed_fee_and_learned_full_year_margin_use_same_exposure(self):
        for vintages in (False, True):
            with self.subTest(vintages=vintages):
                m = self.model(vintages=vintages)
                self.replace_assets(m, [asset("old"), asset("new", online=2015)])
                m.generators["wind"].reference_cf = .2
                m.a["wind_shape"] = [1]*4
                fixed = m.fixed_om_per_mw
                m.fixed_om_per_mw = lambda t: 100 if t == "wind" else fixed(t)
                m.run(2015)
                finance = next(r for r in m.finance
                    if r["kind"] == "generator_operation" and r["actor"] == "wind")
                self.assertAlmostEqual(finance["fixed_om_cny"], 15000)
                self.assertAlmostEqual(m.generators["wind"].margin,
                                       finance["cash_delta_cny"]/150)
                if vintages:
                    self.assertAlmostEqual(
                        m.generators["wind"].expected_project_margin(),
                        finance["cash_delta_cny"]/150, delta=.001)
                self.assertEqual(m.paths[0]["wind_capacity_mw"], 200)
                self.assertLess(abs(m.paths[0]["cash_balance_residual_cny"]), .1)

    def test_zero_birth_year_exposure_retains_both_margin_priors(self):
        m = self.model(vintages=True)
        m.annual_exposure = AnnualExposure(first_year_fraction=0, evidence="synthetic")
        self.replace_assets(m, [asset("new", online=2015)])
        fleet_prior = m.generators["wind"].margin
        candidate_prior = m.generators["wind"].expected_project_margin()
        m.run(2015)
        self.assertEqual(m.last_operation["plants"]["wind"]["capacity_mw"], 0)
        self.assertEqual(m.paths[0]["wind_generation_mwh"], 0)
        self.assertEqual(m.generators["wind"].margin, fleet_prior)
        self.assertEqual(m.generators["wind"].expected_project_margin(), candidate_prior)
        self.assertEqual(m.year_end_operation()["plants"]["wind"]["capacity_mw"], 100)

    def test_only_retiring_asset_still_pays_fixed_fee_and_teaches_a_full_year_margin(self):
        m = self.model(vintages=True)
        self.replace_assets(m, [asset("retiring", exit=2015)])
        m.generators["wind"].reference_cf = .2
        m.a["wind_shape"] = [1]*4
        fixed = m.fixed_om_per_mw
        m.fixed_om_per_mw = lambda t: 100 if t == "wind" else fixed(t)
        m.run(2015)
        finance = next(r for r in m.finance
            if r["kind"] == "generator_operation" and r["actor"] == "wind")
        self.assertEqual(m.paths[0]["wind_capacity_mw"], 0)
        self.assertGreater(m.paths[0]["wind_generation_mwh"], 0)
        self.assertEqual(finance["fixed_om_cny"], 5000)
        self.assertAlmostEqual(m.generators["wind"].margin,
                               finance["cash_delta_cny"]/50)
        self.assertAlmostEqual(m.generators["wind"].expected_project_margin(),
                               finance["cash_delta_cny"]/50, delta=.001)
        self.assertEqual(m.year_end_operation()["plants"]["wind"]["capacity_mw"], 0)

    def test_planning_includes_partial_retirement_and_partial_committed_birth(self):
        m = self.model(vintages=True)
        self.replace_assets(m, [asset("old"), asset("retiring", exit=2016)])
        m.projects.append(dict(id="future", tech="wind", capacity_mw=100,
            decision_year=2014, online_year=2016, exit_year=2041,
            remaining=0, status="construction", cost=1000000,
            instalment=1000000, initial_reconstruction=False, generation_cf=.2))
        m.drivers()
        m.mature()
        m.last_operation = m.make_operation()
        weights = {c["id"]:w for c, w in m.generation_assets("wind", 2016)}
        self.assertEqual(weights, {"old":1, "retiring":.5, "future":.5})
        future = m.planning_operation(1)
        self.assertEqual(future["plants"]["wind"]["capacity_mw"], 200)
        self.assertEqual(future["plants"]["wind"]["ramp_mw_per_hour"], 40)
        self.assertEqual(m.projects[-1]["status"], "construction")

    def test_marginal_candidate_normalises_birth_weight_and_deducts_variable_om(self):
        from test_q2 import small_operation
        for alpha in (0, .5, 1):
            with self.subTest(alpha=alpha):
                m = self.model()
                m.annual_exposure = AnnualExposure(
                    first_year_fraction=alpha, evidence="synthetic")
                op = small_operation()
                op["grid"]["power_mw"] = 1000
                op["storage"].update(initial_mwh=0, power_mw=0, energy_mwh=0)
                op["demands"]["load"].update(input_capacity_mw=1000,
                                            service_mwh=[1000,1000])
                plant = {**op["plants"]["gas"], "input":None, "capacity_mw":0,
                    "window_energy_budget_mwh":0, "ramp_mw_per_hour":0,
                    "variable_cost_per_mwh":7}
                op["plants"] = {"wind":deepcopy(plant), "solar":deepcopy(plant)}
                m.tariff = lambda tech: 100
                m.variable_om = lambda tech: 7
                m.fixed_om_per_mw = lambda tech: 11
                with patch.object(m, "planning_operation",
                                  side_effect=lambda _:deepcopy(op)) as planning:
                    margin, hours = m.marginal_renewable_economics("wind", 100)
                self.assertAlmostEqual(hours, 730)
                self.assertAlmostEqual(margin, 730*(100-7)-11)
                self.assertEqual(planning.call_args.args[0], 2 if alpha == 0 else 1)

    def test_vintage_output_allocation_is_two_to_one_and_closes(self):
        m = self.model(vintages=True)
        self.replace_assets(m, [asset("old"), asset("new", online=2015)])
        m.generators["wind"].reference_cf = .2
        m.a["wind_shape"] = [1]*4
        m.drivers()
        m.mature()
        op = m.make_operation()
        result = {"generation":[dict(plant="wind", period=i, output_mwh=180)
                                for i in range(4)]}
        allocation = m.renewable_vintages.allocate_actual(m, op, result)
        self.assertAlmostEqual(allocation["old"], 2*allocation["new"])
        self.assertAlmostEqual(allocation["old"]+allocation["new"], 720*365)

    def test_q3_snapshot_restores_end_stock_and_preserves_opening_inventories(self):
        m = self.model(vintages=True)
        self.replace_assets(m, [asset("old"), asset("new", online=2015),
                                asset("retiring", capacity=40, exit=2015)])
        m.generators["wind"].reference_cf = .2
        m.a["wind_shape"] = [1]*4
        m.run(2015)
        saved = deepcopy(m.last_operation)
        snapshot = m.year_end_operation()
        self.assertEqual(snapshot["plants"]["wind"]["capacity_mw"], 200)
        self.assertEqual(saved["plants"]["wind"]["capacity_mw"], 170)
        self.assertEqual(snapshot["plants"]["wind"]["ramp_mw_per_hour"], 40)
        self.assertEqual(snapshot["fuels"], saved["fuels"])
        self.assertEqual(snapshot["storage"], saved["storage"])
        self.assertEqual(snapshot.get("additional_storage"),
                         saved.get("additional_storage"))
        snapshot["plants"]["wind"]["capacity_mw"] = -1
        self.assertEqual(m.last_operation, saved)

    def policy(self, rows):
        positions = [dict(terms=SupportTerms(c["id"], "biomass", True,
            c["online_year"], c["online_year"], 30, c["capacity_mw"], 10000,
            1, "synthetic"), prior_lifetime_mwh=0) for c in rows]
        return AnnualRevenuePolicy(energy_tariffs={2015:{"biomass":1}},
            annual_funding={2015:dict(levy_receipts_cny=0,
                treasury_transfer_cny=1e9, expenditure_limit_cny=1e9)},
            support_rates={2015:{c["id"]:dict(supported_tariff_cny_per_mwh=2,
                reference_tariff_cny_per_mwh=1, vat_rate=0) for c in rows}},
            positions=positions, opening_cash_cny=0, opening_payables=[],
            initial_year=2014, real_2024_per_nominal={2015:1},
            metering_fraction={2015:{"biomass":1}}, evidence="synthetic")

    def test_nonrenewable_policy_meter_uses_exposure_not_nameplate(self):
        m = self.model()
        rows = [asset("old", tech="biomass", online=2010),
                asset("new", tech="biomass", online=2015)]
        self.replace_assets(m, rows, tech="biomass")
        m.mature()
        policy = self.policy(rows)
        policy.settle(m, {"biomass":150000})
        self.assertEqual([p["prior_lifetime_mwh"] for p in policy.positions],
                         [100000, 50000])

    def test_retired_end_stock_still_accrues_its_actual_retirement_year_meter(self):
        m = self.model()
        rows = [asset("retiring", tech="biomass", online=2010, exit=2015)]
        self.replace_assets(m, rows, tech="biomass")
        m.mature()
        policy = self.policy(rows)
        result = policy.settle(m, {"biomass":50000})
        self.assertEqual(policy.positions[0]["prior_lifetime_mwh"], 50000)
        self.assertEqual(result["subsidy_entitlement_nominal_cny"], 50000)


class ExposureSupportPvTests(unittest.TestCase):
    def test_first_half_year_consumes_half_quota_before_next_year(self):
        o = offer()
        actual = o.pv_per_mw(lead=1, life=20, gross_full_load_hours=1000,
            discount_rate=.1, first_year_fraction=.5)
        self.assertAlmostEqual(actual, 500/1.1 + 1000/1.1**2)
        self.assertEqual(o.reserve_per_mw, 1500)

    def test_calendar_eligibility_window_is_not_extended(self):
        actual = offer(eligible_years=1).pv_per_mw(lead=1, life=20,
            gross_full_load_hours=1000, discount_rate=0, first_year_fraction=.5)
        self.assertEqual(actual, 500)

    def test_one_year_physical_life_can_have_two_partial_policy_years(self):
        actual = offer().pv_per_mw(lead=1, life=1, gross_full_load_hours=1000,
            discount_rate=.1, first_year_fraction=.5)
        self.assertAlmostEqual(actual, 500/1.1 + 500/1.1**2)

    def test_programme_propagates_fraction_without_reducing_commitment(self):
        p = NewProjectSupport(offers=[offer()], commitment_authority_cny={2014:1e9},
                              actual_rates={}, evidence="synthetic")
        actual = p.pv_per_mw(year=2014, tech="biomass", lead=1, life=20,
            gross_full_load_hours=1000, discount_rate=.1, first_year_fraction=.5)
        self.assertAlmostEqual(actual, 500/1.1 + 1000/1.1**2)
        self.assertEqual(p.reserved, {})


if __name__ == "__main__":
    unittest.main()
