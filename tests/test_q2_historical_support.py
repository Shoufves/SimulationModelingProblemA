"""Full-window scenarios: provenance labels, vintage and lifetime invariants."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"));sys.path.insert(0,str(ROOT/"src"))
AVAILABLE=all(importlib.util.find_spec(x) for x in ("mesa","scipy","pdfplumber"))
if AVAILABLE:
    from run_q2_historical_support import (preflight,scope_inputs,policy_inputs,add_initial_support,
        apply_announced_lifetime_limits,NationalModel,YEARS)


@unittest.skipUnless(AVAILABLE,"Install research dependencies")
class HistoricalSupportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d,s,_=preflight()
        theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,
            replacement_adoption=.2,expectation_rate=.25)
        cls.data,cls.design,cls.theta,cls.boundary,_,_=scope_inputs(d,s,theta,recovery_share=.5)

    def inputs(self,**kwargs):
        args=dict(cash_fraction=1,gas_price_factor=1,new_support=True)
        args.update(kwargs)
        return policy_inputs(self.data,self.design,**args)

    def test_price_assumptions_and_fiscal_observations_are_not_confused(self):
        policy,cells,tax,rows,actual,authority=self.inputs(gas_price_factor=.8)
        self.assertEqual(cells[2019,"gas","feed_in_tariff"],584.1*.8)
        self.assertEqual(cells[2018,"gas","feed_in_tariff"],584.1)
        self.assertTrue(all("assumption" in r["status"] for r in rows if r["year"]>=2019))
        self.assertAlmostEqual(tax[2019],.25/1.16+.75/1.13)
        self.assertEqual(policy.annual_funding[2022]["treasury_transfer_cny"],0)
        self.assertEqual(policy.annual_funding[2022]["levy_receipts_cny"],1083.72e8)
        self.assertEqual(policy.annual_funding[2022]["expenditure_limit_cny"],3087.44e8)
        with self.assertRaisesRegex(ValueError,"Missing energy-only"):
            policy.energy_tariff(2025,"gas")

    def test_future_rule_is_not_in_early_offer_and_new_wind_stops_not_old_rights(self):
        policy,*_=self.inputs()
        offers=policy.new_support.offers
        self.assertEqual(offers[2015,"biomass"].eligible_years,25)
        self.assertEqual(offers[2021,"biomass"].eligible_years,15)
        self.assertEqual(offers[2021,"biomass"].lifetime_hours,82500)
        self.assertIn((2020,"wind"),offers)
        self.assertNotIn((2021,"wind"),offers)
        self.assertNotIn((2021,"solar"),offers)
        early=deepcopy(offers[2015,"biomass"])
        policy.new_support.actual_rates[2024]["biomass"]["supported_tariff_cny_per_mwh"]=float("nan")
        self.assertEqual(offers[2015,"biomass"],early)

    def test_pipeline_receives_no_early_output_and_lifetime_update_preserves_history(self):
        policy,cells,tax,rows,actual,authority=self.inputs()
        model=NationalModel(self.data,self.design,self.theta,2014,revenue_policy=policy,operating_boundary=self.boundary)
        add_initial_support(model,actual)
        pipeline={p["id"] for p in model.projects if p["initial_reconstruction"]}
        positions=[p for p in model.revenue_policy.positions if p["terms"].project in pipeline]
        self.assertTrue(positions)
        self.assertTrue(all(p["prior_lifetime_mwh"]==0 for p in positions))
        before={p["terms"].project:p["prior_lifetime_mwh"] for p in model.revenue_policy.positions}
        with self.assertRaisesRegex(ValueError,"backdate"):
            apply_announced_lifetime_limits(model,zone="lower")
        model.run(2015)
        known={c["id"]:c for c in model.cohorts if c["status"]=="active"}
        for p in model.revenue_policy.positions:
            if p["terms"].project not in known:
                self.assertEqual(p["prior_lifetime_mwh"],before.get(p["terms"].project,0))
        history={p["terms"].project:p["prior_lifetime_mwh"] for p in model.revenue_policy.positions}
        payables=deepcopy(model.revenue_policy.fund.payables)
        reserved=deepcopy(model.revenue_policy.new_support.reserved)
        model.year=2021
        changes=apply_announced_lifetime_limits(model,zone="lower")
        self.assertTrue(changes)
        self.assertEqual({p["terms"].project:p["prior_lifetime_mwh"] for p in model.revenue_policy.positions},history)
        self.assertEqual(model.revenue_policy.fund.payables,payables)
        self.assertEqual(model.revenue_policy.new_support.reserved,reserved)


if __name__=="__main__":unittest.main()
