"""Price timing, information boundaries and full annual cash conservation."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
from energy_model.q2_fuel_prices import AnnualFuelPrices, FuelPriceObservation, FuelPriceNationalModel
from energy_model.q2_portfolio import PortfolioNationalModel
from run_q2_national import preflight


def price(year, value, fuel="coal"):
    return FuelPriceObservation(year, fuel, value, "synthetic independent timing test",
                                "conditional_shared_market_proxy")


class FuelPriceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data, cls.design, _ = preflight()
        cls.theta = dict(activity_elasticity=.5, investment_response=1,
                         renewable_mix_response=.7, replacement_adoption=.2,
                         expectation_rate=.25)

    def model(self, rows=None, **kw):
        return FuelPriceNationalModel(deepcopy(self.data), deepcopy(self.design),
            self.theta, 2014, fuel_prices=AnnualFuelPrices(rows) if rows is not None else None, **kw)

    def baseline(self):
        return PortfolioNationalModel(deepcopy(self.data), deepcopy(self.design), self.theta, 2014)

    def test_invalid_and_duplicate_prices_rejected(self):
        for value in (0, -1, float("nan"), float("inf"), True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                price(2014, value)
        with self.assertRaises(ValueError):
            AnnualFuelPrices([price(2014, 10), price(2014, 20)])
        with self.assertRaises(ValueError):
            FuelPriceObservation(2014, "coal", 10, "index", "verified_national")

    def test_disabled_path_exactly_reproduces_old_model(self):
        old, new = self.baseline().run(2015), self.model().run(2015)
        for name in ("paths", "finance", "behavior", "operations", "projects", "cohorts", "balances"):
            self.assertEqual(getattr(old, name), getattr(new, name), name)

    def test_constant_path_exactly_reproduces_old_dynamics(self):
        old = self.baseline()
        p = old.suppliers["coal"].price
        new = self.model([price(2014, p), price(2015, p)]).run(2015)
        old.run(2015)
        for name in ("paths", "finance", "behavior", "operations", "projects"):
            self.assertEqual(getattr(old, name), getattr(new, name), name)

    def test_initial_prices_precede_generator_and_consumer_beliefs(self):
        old = self.baseline()
        delta = 10
        new = self.model([price(2014, old.suppliers["coal"].price - delta)])
        expected_margin_change = old.generators["coal"].reference_cf * 8760 * delta / old.efficiency["coal"]
        self.assertAlmostEqual(new.generators["coal"].margin - old.generators["coal"].margin,
                               expected_margin_change, places=7)
        expected_income_change = -delta / old.a["direct_fuel_efficiency"]["coal"] * old.a["consumer_income_headroom"]
        self.assertAlmostEqual(new.consumers["coal"].income_per_service - old.consumers["coal"].income_per_service,
                               expected_income_change)
        self.assertEqual(new.reference_fuel_prices["coal"], new.suppliers["coal"].price)
        self.assertEqual(new.generators["coal"].cash, old.generators["coal"].cash)
        self.assertEqual(new.projects, old.projects)

    def test_future_prices_do_not_change_past_decisions_or_planning(self):
        left = self.model([price(2014, 80), price(2015, 90), price(2016, 10)]).run(2015)
        right = self.model([price(2014, 80), price(2015, 90), price(2016, 400)]).run(2015)
        for name in ("paths", "finance", "behavior", "operations", "projects"):
            self.assertEqual(getattr(left, name), getattr(right, name), name)
        self.assertEqual(left.planning_operation(4), right.planning_operation(4))
        self.assertEqual(left.planning_operation(4)["fuels"]["coal"]["domestic_cost_per_mwh"], 90)

    def test_annual_price_reaches_dispatch_bills_and_learning(self):
        model = self.model([price(2014, 80), price(2015, 60)])
        fixed_income = model.consumers["coal"].income_per_service
        initial_margin = model.generators["coal"].margin
        model.run(2015)
        self.assertEqual(model.last_operation["fuels"]["coal"]["domestic_cost_per_mwh"], 60)
        self.assertEqual(model.reference_fuel_prices["coal"], 80)
        self.assertEqual(model.consumers["coal"].income_per_service, fixed_income)
        row = next(r for r in model.finance if r["kind"] == "generator_operation" and r["actor"] == "coal")
        generation = model.paths[0]["coal_generation_mwh"]
        self.assertAlmostEqual(row["fuel_bill_cny"], generation / model.efficiency["coal"] * 60, delta=.001)
        learned = .75 * initial_margin + .25 * row["cash_delta_cny"] / row["operating_exposure_mw_year"]
        self.assertAlmostEqual(model.generators["coal"].margin, learned, places=6)
        self.assertLess(abs(model.paths[0]["cash_balance_residual_cny"]), .01)
        self.assertEqual([r["year"] for r in model.fuel_price_history], [2014, 2015])

    def test_missing_window_fails_before_state_changes(self):
        model = self.model([price(2014, 80), price(2015, 90)])
        before = deepcopy((model.year, model.gdp, model.behavior, model.fuel_price_history))
        with self.assertRaisesRegex(ValueError, "2016"):
            model.run(2016)
        self.assertEqual(before, (model.year, model.gdp, model.behavior, model.fuel_price_history))

    def test_variant_applied_once_initial_and_annual(self):
        model = self.model([price(2014, 80), price(2015, 90)], variant={"fuel_price_multiplier": 1.5})
        self.assertEqual(model.suppliers["coal"].price, 120)
        self.assertEqual(model.reference_fuel_prices["coal"], 80)
        model.run(2015)
        self.assertEqual(model.suppliers["coal"].price, 135)
        self.assertEqual(model.last_operation["fuels"]["coal"]["domestic_cost_per_mwh"], 135)


if __name__ == "__main__":
    unittest.main()
