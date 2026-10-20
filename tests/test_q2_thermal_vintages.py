"""Independent heat-rate, learning, commissioning and cash regressions."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
from energy_model.q2_thermal_vintages import ThermalVintages, ThermalNationalModel
from energy_model.q2_fuel_prices import FuelPriceNationalModel
from energy_model.q2_exposure import AnnualExposure
from energy_model.q2_national import EF
from energy_model.q2_renewable_vintages import RenewableVintages
from run_q2_national import preflight
from test_q2 import small_operation


class ThermalVintageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.design, _ = preflight()
        cls.theta = dict(activity_elasticity=.5, investment_response=1,
                         renewable_mix_response=.7, replacement_adoption=.2, expectation_rate=.25)

    def model(self, *, enabled=True, start=2015, exposure=None, **kw):
        vintage = ThermalVintages(new_gross_efficiencies={"coal": .5, "gas": .6},
            decision_start_year=start, evidence="synthetic efficiency test") if enabled else None
        return ThermalNationalModel(deepcopy(self.data), deepcopy(self.design), self.theta, 2014,
                                    thermal_vintages=vintage, annual_exposure=exposure, **kw)

    def test_invalid_technology_and_efficiency(self):
        for values in ({"coal": 0}, {"gas": 1.1}, {"coal": float("nan")}, {"gas": True}, {"oil": .4}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                ThermalVintages(new_gross_efficiencies=values, decision_start_year=2015, evidence="fixture")

    def test_disabled_and_unavailable_exactly_reproduce_original(self):
        old = FuelPriceNationalModel(deepcopy(self.data), deepcopy(self.design), self.theta, 2014).run(2015)
        for new in (self.model(enabled=False).run(2015), self.model(start=2025).run(2015)):
            for name in ("paths", "finance", "behavior", "operations", "projects", "assets", "balances"):
                self.assertEqual(getattr(old, name), getattr(new, name), name)

    def test_initial_fleet_and_initial_pipeline_not_retrofitted(self):
        m = self.model()
        self.assertEqual(m.efficiency["coal"], .41)
        self.assertEqual(m.efficiency["gas"], .52)
        self.assertFalse(any("gross_thermal_efficiency" in c for c in m.cohorts + m.projects))
        old = self.model(enabled=False)
        self.assertEqual(m.feedstock, old.feedstock)
        self.assertEqual({k:c.base_service for k,c in m.consumers.items()}, {k:c.base_service for k,c in old.consumers.items()})

    def test_mixture_is_exposure_weighted_harmonic_not_arithmetic(self):
        m = self.model(exposure=AnnualExposure(.5, "fixture"))
        m.cohorts = [dict(id="old", tech="coal", capacity_mw=40, online_year=2010, exit_year=2030,
                         status="active", gross_thermal_efficiency=.4),
                     dict(id="new", tech="coal", capacity_mw=60, online_year=2015, exit_year=2055,
                         status="active", gross_thermal_efficiency=.5)]
        m.projects = []
        self.assertAlmostEqual(m.mixed_efficiency("coal", 2015), 70 / (40/.4 + 30/.5))
        self.assertAlmostEqual(m.mixed_efficiency("coal", 2015, physical=True), 100 / (40/.4 + 60/.5))
        self.assertAlmostEqual(m.mixed_efficiency("coal", 2030), 80 / (20/.4 + 60/.5))
        self.assertEqual(m.mixed_efficiency("coal", 2030, physical=True), .5)

    def test_candidate_learning_does_not_count_new_fleet_savings_twice(self):
        m = self.model()
        g, b = m.generators["coal"], m.thermal_beliefs["coal"]
        b.project_margin = 100
        op = {"plants": {"coal": {"capacity_mw": 10, "efficiency": .5}}}
        result = {"generation": [{"plant": "coal", "output_mwh": 1000/365}]}
        g.learn_margin(500, operation=op, result=result)
        self.assertEqual(b.project_margin, 200)  # .75*100 + .25*500; no extra savings

    def test_candidate_learning_uses_actual_mixture_and_ets_fuel_term(self):
        m = self.model()
        m.year, m.carbon = 2022, 100
        m.suppliers["coal"].price = 200
        b = m.thermal_beliefs["coal"]
        b.project_margin = 0
        op = {"plants": {"coal": {"capacity_mw": 10, "efficiency": .4}}}
        result = {"generation": [{"plant": "coal", "output_mwh": 1000/365}]}
        m.generators["coal"].learn_margin(1000, operation=op, result=result)
        expected = .25 * (1000 + 100 * (200 + 100 * EF["coal"]) * (1/.4 - 1/.5))
        self.assertAlmostEqual(b.project_margin, expected)

    def test_zero_exposure_does_not_invent_learning_sample(self):
        m = self.model()
        b = m.thermal_beliefs["coal"]
        prior = b.project_margin
        m.generators["coal"].learn_margin(1e15, operation={"plants":{"coal":{"capacity_mw":0}}}, result={})
        self.assertEqual(b.project_margin, prior)

    def test_paid_commissioning_preserves_project_efficiency(self):
        m = self.model()
        p = next(p for p in m.projects if p["tech"] == "coal" and p["online_year"] == 2015)
        p["gross_thermal_efficiency"] = .47
        m.drivers()
        m.mature()
        cohort = next(c for c in m.cohorts if c["id"] == p["id"])
        self.assertEqual(cohort["gross_thermal_efficiency"], .47)
        self.assertEqual(m.thermal_vintages.new_gross_efficiencies["coal"], .5)

    def test_real_annual_fuel_cash_and_cohort_emissions_close(self):
        m = self.model(investment=False)
        # Synthetic subset of inherited stock upgraded only for this fixture.
        for cohort in m.cohorts[:8]:
            if cohort["tech"] == "coal":
                cohort["gross_thermal_efficiency"] = .5
        m.run(2015)
        for tech in ("coal", "gas"):
            ledger = [r for r in m.thermal_fuel_ledger if r["tech"] == tech]
            fuel = sum(r["fuel_mwh"] for r in ledger)
            physical = sum(r["conversion_mwh"]*365 for r in m.operations if r["kind"] == "fuel" and r["fuel"] == tech)
            self.assertAlmostEqual(fuel, physical, delta=.001)
            paid = next(r["fuel_bill_cny"] for r in m.finance if r["kind"] == "generator_operation" and r["actor"] == tech)
            self.assertAlmostEqual(paid, fuel*m.suppliers[tech].price, delta=.01)
            self.assertAlmostEqual(sum(r["combustion_co2_t"] for r in ledger), physical*EF[tech], delta=.001)
        self.assertLess(abs(m.paths[0]["cash_balance_residual_cny"]), .01)

    def test_future_planning_uses_known_commissioning_and_retires_old_units(self):
        m = self.model(investment=False)
        m.run(2015)
        p = next(p for p in m.projects if p["tech"] == "coal" and p["online_year"] > m.year)
        p["gross_thermal_efficiency"] = .5
        current = m.efficiency["coal"]
        planned = m.planning_operation(4)
        self.assertEqual(planned["plants"]["coal"]["efficiency"], m.mixed_efficiency("coal", m.year+4))
        self.assertGreater(planned["plants"]["coal"]["efficiency"], current)
        self.assertEqual(m.efficiency["coal"], current)

    def test_marginal_audit_values_fuel_saving_without_fictitious_energy_sales(self):
        m = self.model()
        op = small_operation()
        op["storage"].update(initial_mwh=0, energy_mwh=0, power_mw=0)
        op["fuels"]["gas"].update(domestic_mw=[100,100], domestic_cost_per_mwh=1, import_cost_per_mwh=1)
        op["plants"]["gas"].update(capacity_mw=10, efficiency=.5)
        m.suppliers["gas"].price = 1
        m.thermal_beliefs["gas"].project_margin = 1e9
        with patch.object(m, "planning_operation", side_effect=lambda _: deepcopy(op)), \
             patch.object(m, "variable_om", return_value=0), patch.object(m, "fixed_om_per_mw", return_value=0), \
             patch.object(m, "tariff", return_value=100), patch.object(m, "capex", return_value=1):
            # With fixed 10MWh sales, adding 10MW at eta=.6 lowers heat use
            # from 20 to 18.3333MWh/day under shared utilisation.
            expected_margin = (20 - 10*((10/.5+10/.6)/20)) * 365 / 10
            expected_npv = expected_margin*m.energy_pv_factor(lead=3,life=30) - sum(1/3/(1+m.a["discount_rate"])**k for k in range(3))
            self.assertAlmostEqual(m.thermal_candidate_npv("gas", 10), expected_npv, places=6)

    def test_thermal_candidate_coexists_with_renewable_vintage_module(self):
        m = self.model(renewable_vintages=RenewableVintages(new_project_cf={"wind":.3,"solar":.18}, evidence="fixture"))
        plant = dict(capacity_mw=10, efficiency=.5, ramp_mw_per_hour=2,
                     window_energy_budget_mwh=240, availability=[.85]*4)
        m.add_renewable_candidate("gas", plant, 10)
        self.assertEqual(plant["capacity_mw"], 20)
        self.assertAlmostEqual(plant["efficiency"], 20/(10/.5+10/.6))
        self.assertEqual(plant["window_energy_budget_mwh"], 480)

    def test_other_candidate_keeps_annual_energy_budget(self):
        m = self.model()
        plant = dict(capacity_mw=10, efficiency=.3, ramp_mw_per_hour=2,
                     window_energy_budget_mwh=20, availability=[.85]*4)
        m.add_renewable_candidate("biomass", plant, 5)
        self.assertAlmostEqual(plant["window_energy_budget_mwh"], 20+5*24*m.generators["biomass"].reference_cf)

    def test_thermal_support_requires_incremental_energy_and_honours_zero_fraction(self):
        m = self.model()
        m.run(2015)
        calls = []
        def quote(model, tech, *, full_load_hours):
            calls.append(full_load_hours)
            return 100000.
        m.revenue_policy = SimpleNamespace(investment_value=quote, energy_tariff=lambda year, tech: 100.)
        op = small_operation()
        with patch.object(m, "planning_operation", side_effect=lambda _: deepcopy(op)):
            full = m.thermal_candidate_npv("gas", 10)
            none = m.thermal_candidate_npv("gas", 10, support_fraction=0.)
            half = m.thermal_candidate_npv("gas", 10, support_fraction=.5)
        self.assertAlmostEqual(full - none, 100000.)
        self.assertAlmostEqual(half - none, 50000.)
        self.assertEqual(calls, [0., 0., 0.])  # no extra sales in this fixed-load case
        for invalid in (-1, 1.1, float("nan"), True):
            with self.assertRaises(ValueError):
                m.thermal_candidate_npv("gas", 10, support_fraction=invalid)

    def test_joint_thermal_audit_removes_failed_plant_then_rescreens_survivor(self):
        m = self.model()
        m.last_operation = {"fixture": True}
        seen = []
        def npv(tech, amount, portfolio, *, support_fraction):
            seen.append((tech, dict(portfolio), support_fraction))
            # Gas is viable only while coal is present. Removing coal therefore
            # requires a second review, rather than blindly retaining gas.
            return -1 if tech == "coal" or portfolio["coal"] == 0 else 1
        with patch.object(m, "thermal_candidate_npv", side_effect=npv):
            result = m.audit_renewable_portfolio({"coal": 100., "gas": 50.},
                                                support_fractions={"coal": 0., "gas": .5})
        self.assertEqual(result, {"coal": 0., "gas": 0.})
        self.assertTrue(any(t == "gas" and p["coal"] == 0 for t, p, _ in seen))
        self.assertTrue(all(f == (0. if t == "coal" else .5) for t, _, f in seen))


if __name__ == "__main__":
    unittest.main()
