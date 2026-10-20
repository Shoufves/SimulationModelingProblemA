"""Cost meaning, physical boundary, and cash reconciliation regressions."""
from copy import deepcopy
import sys
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"));sys.path.insert(0,str(ROOT/"scripts"))
from build_q2_project_costs import extract
from energy_model.q2_project_costs import GenerationCosts
from energy_model.q2_national import NationalModel
from run_q2_national import preflight


class ProjectCostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data,cls.design,_=preflight()
        cls.theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,
                       replacement_adoption=.2,expectation_rate=.25)

    def costs(self,fixed=100000,variable=70):
        return GenerationCosts(parameters={"gas":dict(fixed_real_cny_per_net_mw_year=fixed,
            variable_real_cny_per_net_mwh=variable,overnight_real_cny_per_net_mw=4e6)},
            reference_net_fractions={"gas":.97},evidence="explicit regression scenario")

    def model(self,**kw):
        return NationalModel(deepcopy(self.data),self.design,self.theta,2014,investment=False,**kw)

    def test_source_cases_recover_exact_known_components(self):
        p=extract()["parameters"]
        for t,f,v in (("gas",26000,10),("coal",37000,10),("nuclear",85000,15)):
            self.assertAlmostEqual(p[t]["fixed_usd_2018_per_net_mw_year"],f,places=6)
            self.assertAlmostEqual(p[t]["variable_om_usd_2018_per_net_mwh"],v,places=8)
            values=list(p[t]["source_cells"].values())
            self.assertAlmostEqual(p[t]["recovered_at_85"],values[0],places=10)
            self.assertAlmostEqual(p[t]["recovered_at_50"],values[1],places=10)
        self.assertEqual(p["nuclear"]["nuclear_fuel_usd_2018_per_net_mwh"],10)

    def test_nameplate_and_actual_meter_are_distinct(self):
        c=self.costs()
        self.assertEqual(c.capex("gas"),3880000)
        self.assertEqual(c.fixed_per_mw("gas"),97000)
        self.assertAlmostEqual(c.variable_per_gross_mwh("gas",.8),56)
        self.assertAlmostEqual(c.variable_per_gross_mwh("gas",.9),63)
        self.assertEqual(c.fixed_per_mw("gas"),97000)

    def test_invalid_costs_rejected(self):
        for bad in (-1,float("inf"),float("nan")):
            with self.assertRaises(ValueError):self.costs(fixed=bad)
        with self.assertRaises(ValueError):
            GenerationCosts(parameters={},reference_net_fractions={"gas":.9},evidence="x")
        with self.assertRaises(ValueError):self.costs().variable_per_gross_mwh("gas",1.1)
        c=self.costs()
        with self.assertRaises(ValueError):
            GenerationCosts(parameters={"wind":c.parameters["gas"]},reference_net_fractions={"wind":1},evidence="x")

    def test_fixed_cost_does_not_change_same_year_dispatch(self):
        a=self.model(generation_costs=self.costs(fixed=0)).run(2015)
        b=self.model(generation_costs=self.costs(fixed=1e6)).run(2015)
        # Large fixed costs may change future investment; they cannot alter
        # current merit order or be avoided by idling an existing paid asset.
        self.assertEqual(a.paths[0]["gas_generation_mwh"],b.paths[0]["gas_generation_mwh"])
        capacity=a.paths[0]["gas_capacity_mw"]
        delta=capacity*.97*1e6
        self.assertAlmostEqual(b.paths[0]["operating_resource_cost_cny"]-a.paths[0]["operating_resource_cost_cny"],delta,delta=.01)
        af=next(r for r in a.finance if r["kind"]=="generator_operation" and r["actor"]=="gas")
        bf=next(r for r in b.finance if r["kind"]=="generator_operation" and r["actor"]=="gas")
        self.assertAlmostEqual(af["cash_delta_cny"]-bf["cash_delta_cny"],delta,delta=.01)
        self.assertLess(abs(b.paths[0]["cash_balance_residual_cny"]),.05)

    def test_actual_tariff_meter_converts_variable_cost_not_fixed_nameplate(self):
        # A full empirical policy provides all required annual fiscal inputs.
        from run_q2_historical_support import policy_inputs
        policy,*_=policy_inputs(self.data,self.design,cash_fraction=1,gas_price_factor=1,new_support=False)
        policy.metering_fraction[2015]["gas"]=.8
        model=self.model(generation_costs=self.costs(),revenue_policy=policy)
        self.assertAlmostEqual(model.variable_om("gas"),56)
        model.run(2015)
        r=next(r for r in model.finance if r["kind"]=="generator_operation" and r["actor"]=="gas")
        self.assertAlmostEqual(r["fixed_om_cny"],model.paths[0]["gas_capacity_mw"]*97000,delta=.01)
        self.assertAlmostEqual(r["variable_om_and_embedded_nuclear_fuel_cny"],model.paths[0]["gas_generation_mwh"]*56,delta=.01)
        self.assertLess(abs(model.paths[0]["cash_balance_residual_cny"]),.05)


if __name__=="__main__":unittest.main()
