"""Cohort yields: no free retrofit, early output, or fictitious support meter."""
from copy import deepcopy
from math import fsum
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"));sys.path.insert(0,str(ROOT/"scripts"))
from energy_model.q2_renewable_vintages import RenewableVintages
from energy_model.q2_national import NationalGenerator,NationalModel
from run_q2_national import preflight


class VintageTests(unittest.TestCase):
    def simple(self):
        return SimpleNamespace(year=2015,variant={},a={"wind_shape":[1]*4,"solar_shape":[0,1,2,1]},
            generators={"wind":SimpleNamespace(reference_cf=.2),"solar":SimpleNamespace(reference_cf=.1)},
            cohorts=[dict(id="old",tech="wind",capacity_mw=100,online_year=2000,exit_year=2025,status="active"),
                     dict(id="new",tech="wind",capacity_mw=100,online_year=2015,exit_year=2040,status="active",generation_cf=.4)],
            projects=[dict(id="pending",tech="wind",capacity_mw=100,online_year=2017,exit_year=2042,generation_cf=.4)])

    def policy(self):
        return RenewableVintages(new_project_cf={"wind":.4,"solar":.2},evidence="test")

    def test_new_yield_does_not_retrofit_old_or_commission_pending(self):
        m=self.simple();p={}
        self.policy().update_plant(m,"wind",p,2015)
        self.assertEqual(p["capacity_mw"],200)
        self.assertEqual(p["availability"],[.3]*4)
        self.assertNotIn("generation_cf",m.cohorts[0])
        self.policy().update_plant(m,"wind",p,2017)
        self.assertEqual(p["capacity_mw"],300)
        self.assertAlmostEqual(p["availability"][0],1/3)
        self.policy().update_plant(m,"wind",p,2025)
        self.assertEqual(p["capacity_mw"],200)
        self.assertAlmostEqual(p["availability"][0],.4)

    def test_actual_output_is_allocated_by_available_energy(self):
        m=self.simple()
        result={"generation":[dict(plant="wind",period=i,output_mwh=180) for i in range(4)]}
        values=self.policy().allocate_actual(m,{},result)
        self.assertAlmostEqual(values["new"],2*values["old"])
        self.assertAlmostEqual(fsum(values.values()),720*365)
        self.assertNotIn("pending",values)

    def test_marginal_candidate_meter_uses_its_own_yield(self):
        m=self.simple();p={};v=self.policy();v.update_plant(m,"wind",p,2015)
        v.add_candidate(m,"wind",p,100)
        result={"generation":[dict(plant="wind",period=i,output_mwh=300) for i in range(4)]}
        self.assertAlmostEqual(v.candidate_hours(m,"wind",p,result),1752)

    def test_invalid_and_missing_yields_rejected(self):
        for cf in (-.1,0,1.1,float("nan")):
            with self.assertRaises(ValueError):RenewableVintages(new_project_cf={"wind":cf,"solar":.2},evidence="x")
        with self.assertRaises(ValueError):RenewableVintages(new_project_cf={"wind":.3},evidence="x")

    def sample(self,*,tech="wind",cf=None,dispatch=None):
        m=self.simple();v=self.policy()
        if cf is not None:v.new_project_cf[tech]=cf
        m.renewable_vintages=v;m.bioenergy=None;m.theta={"expectation_rate":1}
        m.fixed_om_per_mw=lambda name:100
        plant={};v.update_plant(m,tech,plant,m.year)
        dispatch=[.5]*4 if dispatch is None else dispatch
        result={"generation":[dict(plant=tech,period=i,
            output_mwh=plant["capacity_mw"]*a*6*dispatch[i])
            for i,a in enumerate(plant["availability"])]}
        realised=fsum(r["output_mwh"]*365 for r in result["generation"])/plant["capacity_mw"]*10-100 if plant["capacity_mw"] else 0
        return m,{"plants":{tech:plant}},result,realised

    def belief(self,m,tech="wind"):
        # Exercise the production learning path without unrelated financing.
        g=NationalGenerator.__new__(NationalGenerator)
        g.model=m;g.name=tech;g.reference_cf=.2;g.margin=500;g.project_margin=700
        return g

    def test_all_new_fleet_does_not_multiply_new_project_income_twice(self):
        m,op,result,_=self.sample()
        for cohort in m.cohorts:cohort["generation_cf"]=.4
        m.renewable_vintages.update_plant(m,"wind",op["plants"]["wind"],m.year)
        for row in result["generation"]:row["output_mwh"]=200*.4*6*.5
        realised=.4*8760*.5*10-100
        g=self.belief(m)
        for _ in range(2):
            g.learn_margin(realised,operation=op,result=result)
            self.assertAlmostEqual(g.expected_project_margin(),realised)
            self.assertAlmostEqual(g.margin,realised)

    def test_mixed_fleet_observation_is_normalised_before_smoothing(self):
        m,op,result,realised=self.sample();g=self.belief(m)
        m.theta["expectation_rate"]=.25
        candidate=.4*8760*.5*10-100
        g.learn_margin(realised,operation=op,result=result)
        self.assertAlmostEqual(g.expected_project_margin(),.75*700+.25*candidate)
        self.assertAlmostEqual(g.margin,.75*500+.25*realised)
        self.assertNotEqual(g.expected_project_margin(),(g.margin+100)*2-100)

    def test_clipped_profiles_and_period_curtailment_set_candidate_income(self):
        m=self.simple()
        for c in m.cohorts:c["tech"]="solar";c["generation_cf"]=.1 if c["id"]=="old" else .8
        m.renewable_vintages=RenewableVintages(new_project_cf={"wind":.4,"solar":.8},evidence="test")
        m.fixed_om_per_mw=lambda name:100;m.theta={"expectation_rate":1};m.bioenergy=None
        p={};m.renewable_vintages.update_plant(m,"solar",p,m.year)
        dispatch=[0,.25,.75,1]
        result={"generation":[dict(plant="solar",period=i,output_mwh=200*a*6*dispatch[i])
                              for i,a in enumerate(p["availability"])]}
        realised=fsum(r["output_mwh"] for r in result["generation"])*365/200*10-100
        g=self.belief(m,"solar")
        g.learn_margin(realised,operation={"plants":{"solar":p}},result=result)
        expected=(.8*.25+1*.75+.8*1)*6*365*10-100
        self.assertAlmostEqual(g.expected_project_margin(),expected)
        # A ratio of raw CFs, or daily potential totals, loses the period mix.
        self.assertNotAlmostEqual(g.expected_project_margin(),(realised+100)*.8/.45-100)

    def test_zero_output_learns_only_fixed_loss_without_invented_sales(self):
        m,op,result,realised=self.sample(dispatch=[0]*4);g=self.belief(m)
        g.learn_margin(realised,operation=op,result=result)
        self.assertEqual(g.expected_project_margin(),-100)
        op["plants"]["wind"]["availability"]=[0]*4
        g.learn_margin(realised,operation=op,result=result)
        self.assertEqual(g.expected_project_margin(),-100)

    def test_absent_fleet_or_missing_dispatch_retains_project_prior(self):
        m,op,result,realised=self.sample();g=self.belief(m)
        op["plants"]["wind"]["capacity_mw"]=0
        for row in result["generation"]:row["output_mwh"]=0
        g.learn_margin(0,operation=op,result=result)
        self.assertEqual(g.expected_project_margin(),700)
        g.learn_margin(realised)
        self.assertEqual(g.expected_project_margin(),700)

    def test_future_queues_do_not_enter_current_income_sample(self):
        m,op,result,realised=self.sample();g=self.belief(m)
        before=deepcopy((op,result,m.cohorts,m.projects))
        g.learn_margin(realised,operation=op,result=result);expected=g.expected_project_margin()
        self.assertEqual((op,result,m.cohorts,m.projects),before)
        m.projects.append(dict(id="future",tech="wind",capacity_mw=1e12,
            online_year=2030,exit_year=2050,generation_cf=1))
        g.learn_margin(realised,operation=op,result=result)
        self.assertEqual(g.expected_project_margin(),expected)

    def test_without_vintages_margin_learning_keeps_default_behavior(self):
        m,op,result,realised=self.sample();m.renewable_vintages=None;g=self.belief(m)
        m.theta["expectation_rate"]=.25
        g.learn_margin(realised,operation=op,result=result)
        self.assertEqual(g.expected_project_margin(),.75*500+.25*realised)

    def test_initial_project_prior_uses_clipped_known_profile_and_fixed_fee(self):
        data,design,_=preflight()
        theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,replacement_adoption=.2,expectation_rate=.25)
        v=RenewableVintages(new_project_cf={"wind":.9,"solar":.8},evidence="test")
        m=NationalModel(deepcopy(data),design,theta,2014,investment=False,renewable_vintages=v,
                        variant={"renewable_availability_multiplier":1.3})
        priors={t:m.generators[t].expected_project_margin() for t in ("wind","solar")}
        for tech in ("wind","solar"):
            hours=fsum(min(1,v.new_project_cf[tech]*x*1.3) for x in m.a[tech+"_shape"])*6*365
            expected=hours*(m.tariff(tech)-m.variable_om(tech))-m.fixed_om_per_mw(tech)
            self.assertAlmostEqual(m.generators[tech].expected_project_margin(),expected)
        m.step()
        result={"generation":[r for r in m.operations if r["kind"]=="generation"]}
        for tech in ("wind","solar"):
            cash=next(r["cash_delta_cny"] for r in m.finance if r["kind"]=="generator_operation" and r["actor"]==tech)
            realised=cash/m.generators[tech].capacity
            observed=v.observed_project_margin(m,tech,m.last_operation,result,realised)
            self.assertAlmostEqual(m.generators[tech].expected_project_margin(),.75*priors[tech]+.25*observed)

    def test_inherited_only_dispatch_unchanged(self):
        data,design,_=preflight()
        theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,replacement_adoption=.2,expectation_rate=.25)
        a=NationalModel(deepcopy(data),design,theta,2014,investment=False).run(2015)
        b=NationalModel(deepcopy(data),design,theta,2014,investment=False,renewable_vintages=self.policy()).run(2015)
        for t in ("wind","solar"):
            self.assertAlmostEqual(a.paths[0][t+"_generation_mwh"],b.paths[0][t+"_generation_mwh"],delta=.0001)
            self.assertAlmostEqual(a.generators[t].cash,b.generators[t].cash,delta=.01)
            self.assertEqual([x for x in a.finance if x["kind"]=="generator_operation" and x["actor"]==t],
                             [x for x in b.finance if x["kind"]=="generator_operation" and x["actor"]==t])

    def test_supported_full_loop_cohort_payments_close(self):
        from run_q2_historical_support import run_case
        data,design,_=preflight()
        theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,replacement_adoption=.2,expectation_rate=.25)
        m,*_=run_case(data,design,theta,renewable_vintages=self.policy(),end_year=2017)
        new=[p for p in m.projects if p.get("generation_cf")]
        self.assertTrue(new)
        for row in m.paths:self.assertLess(abs(row["cash_balance_residual_cny"]),.05)
        for c in m.cohorts:
            if c["id"] in {p["id"] for p in new}:
                self.assertEqual(c["generation_cf"],self.policy().new_project_cf[c["tech"]])


if __name__=="__main__":unittest.main()
