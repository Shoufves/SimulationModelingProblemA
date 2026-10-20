"""Whole-MSW accounting, finite service funding, and no double fuel benefit."""
from pathlib import Path
from types import SimpleNamespace
from math import fsum
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"));sys.path.insert(0,str(ROOT/"scripts"))
from energy_model.q2_bioenergy import CompositeBioenergy


class BioenergyTests(unittest.TestCase):
    def policy(self,**kw):
        args=dict(waste_fuel_fraction=.5,waste_fossil_energy_fraction=.5,
            fossil_co2_t_per_mwh_whole_waste=.2,waste_lhv_mwh_per_t=2,
            waste_delivery_t_by_year={2015:100,2016:100},
            treatment_fee_real_cny_per_t={2015:50,2016:50},
            municipal_appropriation_real_cny_by_year={2015:500,2016:500},
            expected_collection_fraction=.8,initial_year=2014,evidence="explicit regression assumptions")
        return CompositeBioenergy(**{**args,**kw})

    def model(self):
        return SimpleNamespace(year=2015,efficiency={"biomass":.25},finance=[],
            generators={"biomass":SimpleNamespace(cash=0,reference_cf=.5,capacity=1)})

    def test_carbon_factor_is_per_whole_waste_not_fossil_substream(self):
        d=self.policy().physical(self.model(),20)
        self.assertEqual(d["bioenergy_fuel_input_mwh"],80)
        self.assertEqual(d["msw_treated_t"],20)
        self.assertEqual(d["msw_fossil_co2_t"],8)  # not 4: no extra multiplication by fossil fraction
        self.assertEqual(d["bioenergy_physical_nonfossil_generation_mwh"],15)
        self.assertEqual(d["bioenergy_physical_fossil_generation_mwh"],5)

    def test_service_arrears_are_not_cash_and_retired_service_can_be_paid(self):
        m=self.model();p=self.policy()
        a=p.settle(m,20)
        self.assertEqual(a["msw_service_paid_real_cny"],500)
        self.assertEqual(a["msw_service_arrears_real_cny"],500)
        self.assertEqual(m.generators["biomass"].cash,500)
        self.assertAlmostEqual(fsum(r["cash_delta_cny"] for r in m.finance),0)
        self.assertEqual(fsum(r["resource_cost_cny"] for r in m.finance),0)
        m.year=2016;b=p.settle(m,0)
        self.assertEqual(b["msw_service_entitlement_real_cny"],0)
        self.assertEqual(b["msw_service_paid_real_cny"],500)
        self.assertEqual(b["msw_service_arrears_real_cny"],0)
        self.assertEqual(m.generators["biomass"].cash,1000)

    def test_treatment_is_bounded_by_actual_delivery(self):
        p=self.policy();m=self.model()
        with self.assertRaises(ValueError):p.physical(m,101)
        op={"fuels":{"biomass":{}},"plants":{"biomass":{"window_energy_budget_mwh":10000}}}
        p.apply(m,op)
        self.assertAlmostEqual(op["plants"]["biomass"]["window_energy_budget_mwh"],100/365)
        self.assertEqual(op["fuels"]["biomass"]["emission_t_per_mwh"],.1)

    def test_missing_year_or_impossible_fossil_composition_rejected(self):
        with self.assertRaises(ValueError):self.policy(waste_fossil_energy_fraction=0)
        with self.assertRaises(ValueError):self.policy(waste_lhv_mwh_per_t=0)
        with self.assertRaises(ValueError):self.policy().annual(2017)
        with self.assertRaises(ValueError):self.policy(municipal_appropriation_real_cny_by_year={2015:0})

    def test_zero_budget_yields_no_expected_service_income(self):
        p=self.policy(municipal_appropriation_real_cny_by_year={2015:0,2016:0})
        self.assertEqual(p.expected_margin_per_mw(self.model()),0)

    def test_expected_service_income_obeys_shared_delivery_and_funding(self):
        p=self.policy();m=self.model()
        self.assertEqual(p.expected_margin_per_mw(m),500)
        self.assertEqual(p.expected_margin_per_mw(m,additional_capacity_mw=1),250)
        for extra in (0,1,10,100):
            per_mw=p.expected_margin_per_mw(m,additional_capacity_mw=extra)
            self.assertLessEqual(per_mw*(m.generators["biomass"].capacity+extra),500+1e-9)
        with self.assertRaises(ValueError):p.expected_margin_per_mw(m,additional_capacity_mw=-1)

    def test_expected_service_income_also_obeys_plant_throughput(self):
        p=self.policy(waste_delivery_t_by_year={2015:1e8,2016:1e8},
            municipal_appropriation_real_cny_by_year={2015:1e10,2016:1e10})
        m=self.model()
        self.assertEqual(p.expected_margin_per_mw(m),4380*50*.8)

    def test_expected_service_reserves_feedstock_for_known_construction(self):
        p=self.policy();m=self.model()
        m.projects=[dict(tech="biomass",capacity_mw=8,status="construction",online_year=2018),
                    dict(tech="biomass",capacity_mw=1,status="commissioned",online_year=2014),
                    dict(tech="biomass",capacity_mw=100,status="construction",online_year=2020),
                    dict(tech="wind",capacity_mw=100,status="construction",online_year=2016)]
        self.assertEqual(p.expected_margin_per_mw(m,additional_capacity_mw=1),50)

    def test_planning_rebuilds_supply_bound_in_both_directions(self):
        from run_q2_national import preflight
        from energy_model.q2_national import NationalModel
        data,design,_=preflight()
        theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,replacement_adoption=.2,expectation_rate=.25)
        for current,future in ((0,1e8),(1e8,0)):
            p=self.policy(waste_delivery_t_by_year={2015:current,2016:future})
            m=NationalModel(data,design,theta,2014,investment=False,bioenergy=p)
            m.drivers();m.mature();m.last_operation=m.make_operation();m.planning_cache={}
            planned=m.planning_operation(1)
            self.assertAlmostEqual(planned["fuels"]["biomass"]["emission_t_per_mwh"],.1)
            cap=planned["plants"]["biomass"]["capacity_mw"]
            expected=min(cap*24*m.generators["biomass"].reference_cf,future*2/.5*.3/365)
            self.assertAlmostEqual(planned["plants"]["biomass"]["window_energy_budget_mwh"],expected)

    def test_national_loop_separates_statistical_and_physical_carbon(self):
        from run_q2_historical_support import run_case,preflight
        data,design,_=preflight()
        theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,replacement_adoption=.2,expectation_rate=.25)
        p=self.policy(waste_delivery_t_by_year={2015:1e8,2016:1e8},
            municipal_appropriation_real_cny_by_year={2015:1e10,2016:1e10})
        m,*_=run_case(data,design,theta,bioenergy=p,end_year=2015)
        r=m.paths[0]
        self.assertAlmostEqual(m.suppliers["biomass"].price,design["assumptions"]["biomass_cost_cny_per_mwh"]*.5)
        self.assertAlmostEqual(r["msw_fossil_co2_t"],r["biomass_generation_mwh"]/.3*.5*.2)
        self.assertAlmostEqual(r["bioenergy_physical_fossil_generation_mwh"]+r["bioenergy_physical_nonfossil_generation_mwh"],r["biomass_generation_mwh"])
        physical=fsum(x["combustion_co2_t"]*365 for x in m.operations if x["kind"]=="fuel")
        self.assertAlmostEqual(physical,r["combustion_co2_t"],delta=.001)
        self.assertLess(abs(r["cash_balance_residual_cny"]),.05)
        self.assertGreater(r["msw_service_paid_real_cny"],0)


if __name__=="__main__":unittest.main()
