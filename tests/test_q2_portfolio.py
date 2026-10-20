"""Versioned portfolio selection: retain viable projects without double sales."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
AVAILABLE = all(importlib.util.find_spec(x) for x in ("mesa", "scipy"))
if AVAILABLE:
    from energy_model.q2_national import LEAD, LIFE, NationalModel
    from energy_model.q2_portfolio import PortfolioNationalModel
    from energy_model.q2_revenue import AnnualRevenuePolicy
    from run_q2_national import preflight
    from test_q2 import small_operation
    from test_q2_support_investment import offer, programme


@unittest.skipUnless(AVAILABLE, "Install requirements-q2.txt")
class PortfolioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.design, _ = preflight()

    def model(self):
        theta = dict(activity_elasticity=.5, investment_response=1,
                     renewable_mix_response=.7, replacement_adoption=.2,
                     expectation_rate=.25)
        return PortfolioNationalModel(deepcopy(self.data), deepcopy(self.design), theta, 2024)

    @contextmanager
    def dispatch_fixture(self):
        """Real LP: two 5-MWh loads, ample grid, no storage or subsidy."""
        model = self.model()
        operation = small_operation()
        operation["storage"].update(initial_mwh=0, power_mw=0, energy_mwh=0)
        template = {**operation["plants"]["gas"], "input": None,
                    "capacity_mw": 0, "window_energy_budget_mwh": 0}
        operation["plants"] = {t: deepcopy(template) for t in ("wind", "solar")}
        model.last_operation = operation
        costs = dict(wind=1., solar=1.)
        for tech in costs:
            model.generators[tech].margin = 1e12
        with ExitStack() as stack:
            stack.enter_context(patch.object(model, "planning_operation",
                                              side_effect=lambda _: deepcopy(operation)))
            stack.enter_context(patch.object(model, "fixed_om_per_mw", return_value=0.))
            stack.enter_context(patch.object(model, "variable_om", return_value=0.))
            stack.enter_context(patch.object(model, "tariff", return_value=100.))
            stack.enter_context(patch.object(model, "capex", side_effect=lambda t: costs[t]))
            yield model, costs

    def npv(self, model, tech, portfolio):
        margin, _ = model.marginal_renewable_economics(tech, portfolio[tech], portfolio)
        cost = sum(model.capex(tech) / LEAD[tech] /
                   (1 + model.a["discount_rate"]) ** k for k in range(LEAD[tech]))
        return min(model.generators[tech].expected_project_margin(), margin) * \
            model.energy_pv_factor(lead=LEAD[tech], life=LIFE[tech]) - cost

    def set_asymmetric_cost(self, model, costs):
        # Solar alone is viable; competition from 2 MW wind makes 4 MW
        # solar fail. The cost is between these two actual LP valuations.
        unit = sum(1 / LEAD["solar"] / (1 + model.a["discount_rate"]) ** k
                   for k in range(LEAD["solar"]))
        alone = self.npv(model, "solar", {"solar": 4.})
        joint = self.npv(model, "solar", {"wind": 2., "solar": 4.})
        costs["solar"] = (alone + joint + 2 * unit) / 2 / unit

    def test_real_dispatch_retains_profitable_wind_when_only_solar_fails(self):
        with self.dispatch_fixture() as (model, costs):
            self.set_asymmetric_cost(model, costs)
            request = dict(wind=2., solar=4.)
            self.assertGreater(self.npv(model, "wind", {"wind": 2.}), 0)
            self.assertGreater(self.npv(model, "solar", {"solar": 4.}), 0)
            self.assertGreater(self.npv(model, "wind", request), 0)
            self.assertLess(self.npv(model, "solar", request), 0)
            self.assertEqual(NationalModel.audit_renewable_portfolio(model, request),
                             {"wind": 1., "solar": 2.})
            approved = model.audit_renewable_portfolio(request)
            self.assertEqual(approved, {"wind": 2., "solar": 2.})
            self.assertEqual(request, {"wind": 2., "solar": 4.})
            for tech in approved:
                self.assertGreater(self.npv(model, tech, approved), 0)

    def test_real_dispatch_symmetric_crowding_still_reduces_both(self):
        with self.dispatch_fixture() as (model, _):
            request = dict(wind=5., solar=5.)
            for tech in request:
                self.assertGreater(self.npv(model, tech, {tech: 5.}), 0)
                self.assertLess(self.npv(model, tech, request), 0)
            approved = model.audit_renewable_portfolio(request)
            self.assertEqual(approved, {"wind": 2.5, "solar": 2.5})
            for tech in approved:
                self.assertGreater(self.npv(model, tech, approved), 0)

    def test_exhaustion_removes_failed_solar_then_reaudits_surviving_wind(self):
        with self.dispatch_fixture() as (model, costs):
            self.set_asymmetric_cost(model, costs)
            model.a["marginal_investment_halvings"] = 0
            with patch.object(model, "marginal_renewable_economics",
                              wraps=model.marginal_renewable_economics) as economics:
                approved = model.audit_renewable_portfolio({"wind": 2., "solar": 4.})
            self.assertEqual(approved, {"wind": 2., "solar": 0.})
            calls = [c for c in economics.call_args_list if c.args[0] == "wind"]
            self.assertGreaterEqual(len(calls), 2)
            self.assertTrue(any(c.args[2].get("solar", 0) == 0 for c in calls))
            self.assertGreater(self.npv(model, "wind", approved), 0)

    def test_all_failed_projects_are_rejected_without_affecting_other_technologies(self):
        model = self.model()
        model.last_operation = {}
        model.a["marginal_investment_halvings"] = 1
        with patch.object(model, "marginal_renewable_economics", return_value=(-1., 0.)):
            approved = model.audit_renewable_portfolio({"wind": 2., "solar": 4., "coal": 7.})
        self.assertEqual(approved, {"wind": 0., "solar": 0., "coal": 7.})

    def test_shrink_budget_is_bounded_and_only_failed_capacity_changes(self):
        model = self.model()
        model.last_operation = {}
        model.a["marginal_investment_halvings"] = 2
        with patch.object(model, "marginal_renewable_economics",
                          side_effect=lambda tech, amount, portfolio:
                          ((1. if tech == "wind" else -1.), 0.)) as economics, \
                patch.object(model, "capex", return_value=0.):
            approved = model.audit_renewable_portfolio({"wind": 2., "solar": 4.})
        self.assertEqual(approved, {"wind": 2., "solar": 0.})
        solar_amounts = [c.args[1] for c in economics.call_args_list if c.args[0] == "solar"]
        wind_amounts = [c.args[1] for c in economics.call_args_list if c.args[0] == "wind"]
        self.assertEqual(solar_amounts, [4., 2., 1.])
        self.assertEqual(wind_amounts, [2., 2., 2., 2.])

    def test_removal_rechecks_survivor_and_can_remove_it_too(self):
        model = self.model()
        model.last_operation = {}
        model.a["marginal_investment_halvings"] = 0

        def economics(tech, amount, portfolio):
            # A deterministic economics fixture makes the recheck essential;
            # returning the initially profitable survivor would be untested.
            return (1. if tech == "wind" and portfolio.get("solar", 0) else -1.), 0.

        with patch.object(model, "marginal_renewable_economics", side_effect=economics), \
                patch.object(model, "capex", return_value=0.):
            approved = model.audit_renewable_portfolio({"wind": 2., "solar": 4.})
        self.assertEqual(approved, {"wind": 0., "solar": 0.})

    def test_zero_support_fraction_cannot_rescue_merchant_npv(self):
        model = self.model()
        model.last_operation = {}
        model.revenue_policy = SimpleNamespace(investment_value=lambda *a, **kw: 100.)
        for tech in ("wind", "solar"):
            model.generators[tech].margin = 0.
        with patch.object(model, "marginal_renewable_economics", return_value=(0., 500.)), \
                patch.object(model, "capex", return_value=50.):
            self.assertEqual(model.audit_renewable_portfolio({"wind": 2.}), {"wind": 2.})
            self.assertEqual(model.audit_renewable_portfolio(
                {"wind": 2.}, support_fractions={"wind": 0.}), {"wind": 0.})
            self.assertEqual(model.audit_renewable_portfolio(
                {"wind": 2., "solar": 4.}, support_fractions={"wind": 0.}),
                {"wind": 0., "solar": 4.})

    def test_invalid_support_fraction_is_rejected(self):
        model = self.model()
        model.last_operation = {}
        with patch.object(model, "marginal_renewable_economics", return_value=(0., 500.)):
            for fraction in (-.1, 1.1, float("nan"), "0"):
                with self.subTest(fraction=fraction), self.assertRaises(ValueError):
                    model.audit_renewable_portfolio({"wind": 1.},
                                                   support_fractions={"wind": fraction})

    def test_failed_merchant_expansion_preserves_validated_supported_portfolio(self):
        model = self.model()
        model.year = 2025
        model.gdp_cny = model.a["gdp_2024_price_level_cny"]
        support = programme([offer(), offer(technology="wind")], budget=150000)
        model.revenue_policy = AnnualRevenuePolicy(
            energy_tariffs={}, annual_funding={}, support_rates={}, positions=[],
            opening_cash_cny=0, opening_payables=[], initial_year=2024,
            real_2024_per_nominal={}, metering_fraction={}, evidence="portfolio fixture",
            new_support=support)
        model.generators["wind"].margin = 1e8
        model.generators["biomass"].margin = -1e8
        proposals = [dict(tech=t, amount=2, capex=model.capex(t), lead=LEAD[t], life=LIFE[t])
                     for t in ("wind", "biomass")]
        with patch.object(model, "audit_renewable_portfolio", side_effect=[
                {"wind": .5, "biomass": .5}, {"wind": 0., "biomass": .5}]) as audit:
            model.government.approve(proposals, [])
        self.assertEqual(audit.call_args.kwargs["support_fractions"], {"wind": 0.})
        projects = [p for p in model.projects if not p["initial_reconstruction"]]
        self.assertEqual(len(projects), 2)
        self.assertTrue(all(p["capacity_mw"] == .5 for p in projects))
        self.assertFalse(any(p.get("support_eligible") is False for p in projects))
        self.assertAlmostEqual(model.construction_fund,
                               sum(p["remaining"] for p in model.projects))


if __name__ == "__main__":
    unittest.main()
