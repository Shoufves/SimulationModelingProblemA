"""National experiment regressions: evidence boundaries, timing, dimensions, money.

Empirical fit is checked by the separate delivery audit, not these unit tests.
"""
from copy import deepcopy
import csv
import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src")); sys.path.insert(0,str(ROOT/"scripts"))
AVAILABLE=all(importlib.util.find_spec(x) for x in ("mesa","scipy"))
if AVAILABLE:
    from energy_model.q2_national import NationalModel,operate_national,EF,TCE_MWH
    from energy_model.q2_operations import operate,Q2Error
    from run_q2_national import preflight,loss,targets
    from test_q2 import small_operation


@unittest.skipUnless(AVAILABLE,"Install requirements-q2.txt")
class NationalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data,cls.design,_=preflight()
        cls.theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,
                       replacement_adoption=.2,expectation_rate=.25)

    def model(self,year=2014,**kw):
        return NationalModel(deepcopy(self.data),self.design,self.theta,year,**kw)

    def test_uniform_numerical_scale_keeps_prices_and_emissions(self):
        operation=small_operation()
        original=operate(operation); scaled=operate_national(operation)
        self.assertAlmostEqual(original["resource_cost"],scaled["resource_cost"],places=5)
        for kind,key in (("fuel","combustion_co2_t"),("generation","output_mwh"),("storage","discharge_mwh")):
            self.assertAlmostEqual(sum(r[key] for r in original[kind]),sum(r[key] for r in scaled[kind]),places=5)

    def test_missing_real_observation_fails_closed(self):
        d=deepcopy(self.data); del d[2014,"consumption_coal_pct"]
        with self.assertRaises(Q2Error):NationalModel(d,self.design,self.theta,2014)

    def test_future_physical_observations_do_not_enter_hindcast(self):
        original=self.model(detail=False).run(2021).paths
        d=deepcopy(self.data)
        for (year,metric),v in list(d.items()):
            if year>=2015 and ("capacity" in metric or metric.startswith("consumption") or "electricity" in metric):
                d[year,metric]=v*17
        other=NationalModel(d,self.design,self.theta,2014,detail=False).run(2021).paths
        self.assertEqual(original,other)

    def test_forecast_uses_distinct_current_state(self):
        a,b=self.model(),self.model(2024)
        self.assertGreater(sum(g.capacity for g in b.generators.values()),2*sum(g.capacity for g in a.generators.values()))
        self.assertNotEqual(a.gdp0,b.gdp0)

    def test_2024_storage_matches_source_and_not_2025(self):
        m=self.model(2024)
        self.assertAlmostEqual(sum(c["power"] for c in m.storage_cohorts),73760)
        self.assertAlmostEqual(sum(c["energy"] for c in m.storage_cohorts),168200)

    def test_nuclear_initial_dates_not_before_first_grid_date(self):
        for y in (2014,2024):
            m=self.model(y)
            self.assertGreaterEqual(min(c["online_year"] for c in m.cohorts if c["tech"]=="nuclear"),1991)

    def test_heldout_observations_never_set_loss_scales(self):
        d,c,_=preflight()
        expected={t["metric"]:t["scale"] for t in c["targets"]}
        for t in c["targets"]:
            if "absolute_scale" not in t:
                values=[d[y,t["observation"]]*t["multiplier"] for y in c["training_years"] if (y,t["observation"]) in d]
                self.assertAlmostEqual(expected[t["metric"]],sum(values)/len(values)*t["scale_from_training_mean_fraction"])

    def test_no_fake_emissions_holdout_zero_error(self):
        m=self.model(detail=False).run(2024)
        _,parts,_=loss(m.paths,self.data,self.design,[2022,2023,2024],"test")
        p=next(r for r in parts if r["metric"]=="combustion_co2_t")
        self.assertEqual(p["n"],0);self.assertIsNone(p["mape"]);self.assertIsNone(p["loss"])

    def test_device_retirement_and_commissioning_are_real_stock_events(self):
        m=self.model().run(2032)
        for consumer in m.consumers.values():
            old=[c for c in consumer.cohorts if c["online"]<=2014]
            self.assertTrue(old);self.assertTrue(all(c["status"]=="retired" for c in old))
            self.assertTrue(any(c["online"]>2014 and c["status"]=="active" for c in consumer.cohorts))
        for p in m.projects:
            if not p["initial_reconstruction"]:
                self.assertGreater(p["online_year"],p["decision_year"])
            if p["status"]=="commissioned":self.assertLess(abs(p["remaining"]),.01)

    def test_paid_construction_equal_authorised_commitments(self):
        m=self.model(2024).run(2035)
        for r in m.paths:
            self.assertLess(abs(r["construction_fund_residual_cny"]),.1)
        for p in m.projects:
            paid=sum(-r["amount_cny"] for r in m.finance if r.get("project")==p["id"] and r["kind"]=="construction")
            if not p["initial_reconstruction"]:
                self.assertAlmostEqual((paid+p["remaining"])/p["cost"],1,places=10)

    def test_ets_is_net_allowance_transfer_and_not_tax(self):
        m=self.model(2024).run(2027)
        for r in m.finance:
            if r["kind"]=="generator_operation":
                self.assertAlmostEqual(r["net_allowances_t"],r["covered_emissions_t"]-r["free_allowances_t"],places=5)
            if r["kind"]=="ETS_clearing_counterparty":self.assertEqual(r["public_tax_revenue_cny"],0)
        for r in m.paths:
            self.assertLess(abs(r["ets_balance_cny"]),.001)
            self.assertLess(abs(r["cash_balance_residual_cny"]),.1)

    def test_nonenergy_inputs_never_count_as_combustion(self):
        m=self.model(2024).run(2025)
        fuel=[r for r in m.operations if r["kind"]=="fuel"]
        self.assertGreater(sum(r["nonenergy_mwh"] for r in fuel),0)
        expected=sum((r["direct_mwh"]+r["conversion_mwh"]-r["nonenergy_mwh"])*EF[r["fuel"]]*365 for r in fuel)
        exported=sum(r["combustion_co2_t"]*365 for r in fuel)
        self.assertAlmostEqual(expected/exported,1,places=12)
        self.assertAlmostEqual(exported/m.paths[0]["combustion_co2_t"],1,places=12)

    def test_primary_energy_does_not_add_fossil_generation_again(self):
        m=self.model(2024).run(2025)
        row=m.paths[0]
        fossil=sum((r["direct_mwh"]+r["conversion_mwh"])*365 for r in m.operations if r["kind"]=="fuel" and r["fuel"]!="biomass")
        self.assertAlmostEqual(fossil/(row["primary_energy_tce"]*TCE_MWH),1-row["peo_share"],places=10)

    def test_storage_cyclic_conservation_and_capacity(self):
        m=self.model(2024).run(2025)
        rows=[r for r in m.operations if r["kind"]=="storage"]
        self.assertAlmostEqual(rows[0]["opening_mwh"],rows[-1]["closing_mwh"],places=5)
        for left,right in zip(rows,rows[1:]):self.assertAlmostEqual(left["closing_mwh"],right["opening_mwh"],places=6)

    def test_numpy_lhs_values_are_normalised_before_strict_solver_validation(self):
        import numpy as np
        m=self.model(2024,variant=dict(gdp_growth_delta=np.float64(.005),carbon_price_multiplier=np.float64(.9))).run(2025)
        self.assertEqual(type(m.variant["gdp_growth_delta"]),float)
        self.assertEqual(m.paths[0]["year"],2025)

    def test_carbon_bridge_and_targets_keep_co2_scope(self):
        m=self.model(2024,detail=False).run(2060)
        for r in m.paths:
            self.assertAlmostEqual(r["positive_co2_t"]-r["net_removals_t"],r["net_co2_t"],places=5)
            self.assertAlmostEqual(r["neutralisation_ratio"],r["net_removals_t"]/r["positive_co2_t"])
        records,_=targets(m.paths,self.data,self.design)
        self.assertTrue(any(r["metric"]=="carbon_intensity_reduction_vs_2005" for r in records))
        self.assertTrue(any(r["metric"]=="carbon_intensity_reduction_vs_2025" for r in records))
        self.assertIn("not_all_GHG",m.paths[-1]["scope"])


if __name__=="__main__":unittest.main()
