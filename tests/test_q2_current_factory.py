"""Observed opening and reconstructed liabilities are independently closed."""
from pathlib import Path
from math import fsum
import json
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/"scripts"),str(ROOT/"src")]
from run_q2_national import preflight
from q2_current_factory import build, THROUGHPUT_2024


class CurrentFactoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data,cls.design,_=preflight()
        source=ROOT/"outputs/q2_revenue_recalibration/20261020T001729054583Z"
        cls.config=json.loads((source/"design.json").read_text("utf-8"))
        cls.parameters=json.loads((source/"training_selection.json").read_text("utf-8"))["scenarios"]["25"]["parameters"]

    def make(self,**options):
        return build(self.data,self.design,self.config,self.parameters,25,opening_variant=options)[0]

    def test_observed_physical_opening_is_exact_and_separate(self):
        m=self.make()
        self.assertEqual((m.initial_year,m.year,m.paths),(2024,2025,[]))
        self.assertAlmostEqual(m.initial_capacities["hydro"]+58690,self.data[2024,"hydro_capacity_mw"])
        self.assertEqual(m.initial_capacities["coal"],1190000)
        self.assertEqual(m.initial_capacities["gas"],140000)
        for t in ("nuclear","wind","solar"):
            self.assertAlmostEqual(m.generators[t].capacity,self.data[2024,t+"_capacity_mw"])
        m.operating_boundary.check_initial(m)
        self.assertAlmostEqual(m.operating_boundary.initial_pumped_generation_mwh,65.7e6)
        year=m.year
        m.year=2024
        for tech,amount in THROUGHPUT_2024.items():
            self.assertAlmostEqual(m.generators[tech].construction_limit(),amount,places=5)
        m.year=year
        self.assertEqual(self.data[2024,"total_capacity_mw"],3349220)

    def test_opening_assets_have_debt_equity_and_escrow(self):
        m=self.make()
        for row in m.opening_balance_sheet:
            self.assertAlmostEqual(row["assets_cny"],row["debt_cny"]+row["opening_equity_cny"],places=2)
            self.assertGreater(row["debt_cny"],0)
        self.assertAlmostEqual(fsum(p["remaining"] for p in m.projects),m.construction_fund,places=2)
        self.assertTrue(all(p["initial_reconstruction"] for p in m.projects))
        self.assertEqual(m.revenue_policy.fund.last_year,2024)
        self.assertTrue(any(p["prior_lifetime_mwh"]>0 for p in m.revenue_policy.positions))
        self.assertTrue(all(not p["terms"].eligible for p in m.revenue_policy.positions
            if p["terms"].actor in {"wind","solar"} and p["terms"].commissioned_year>=2021))

    def test_opening_sensitivities_change_assumptions_not_observations(self):
        a=self.make()
        b=self.make(initial_age_multiplier=.8,future_initial_pipeline_multiplier=0,
            opening_debt_asset_ratio=.3,opening_cash_capex_fraction=.05,
            opening_subsidy_arrears_multiplier=2,pumped_generation_cf=.1)
        self.assertEqual(a.initial_capacities,b.initial_capacities)
        self.assertGreater(a.construction_fund,b.construction_fund)
        self.assertGreater(sum(r["debt_cny"] for r in a.opening_balance_sheet),
                           sum(r["debt_cny"] for r in b.opening_balance_sheet))
        with self.assertRaises(ValueError):self.make(unknown=1)

    def test_one_future_year_physical_and_cash_closure(self):
        m=self.make()
        # This factory supplies the first operating year. The versioned
        # forward adapter supplies subsequent explicit future fiscal years.
        m.revenue_policy.new_support.actual_rates[2025]=m.revenue_policy.new_support.actual_rates[2024]
        m.revenue_policy.new_support.authority[2025]=m.revenue_policy.new_support.authority[2024]
        m.run(2025)
        row=m.paths[-1]
        self.assertLess(abs(row["cash_balance_residual_cny"]),.1)
        self.assertLess(abs(row["construction_fund_residual_cny"]),.1)
        self.assertLess(abs(row["financing_transfer_residual_cny"]),.1)
        self.assertLess(abs(row["max_residual"]),1e-4)
        self.assertTrue(any(f["kind"]=="debt_service" for f in m.finance))


if __name__=="__main__":unittest.main()
