"""Finite awards, commissioning and decision-information regression tests."""
from copy import deepcopy
from dataclasses import replace
import importlib.util
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(ROOT/"scripts"))
from energy_model.q2_support_investment import NewProjectSupport, SupportOffer
from energy_model.q2_revenue import AnnualRevenuePolicy


def offer(**changes):
    values=dict(technology="biomass", decision_year=2025, announced_year=2024,
        commissioning_deadline=2030, eligible_years=2, lifetime_hours=1500,
        premium_cap_nominal_cny_per_mwh=100, expected_premium_nominal_cny_per_mwh=100, metering_fraction=.9,
        expected_collection_fraction=.5, expected_payment_delay_years=1,
        expected_real_2024_per_nominal=1, priority=1, evidence="synthetic research fixture")
    values.update(changes)
    return SupportOffer(**values)


def programme(offers=None, budget=150000, actual=None):
    return NewProjectSupport(offers=[offer()] if offers is None else offers,
        commitment_authority_cny={2025:budget}, actual_rates=actual or {},
        evidence="synthetic finite lifetime authority; no national eligibility claim")


def project(name="p", capacity=1, tech="biomass", online=2028):
    return dict(id=name,tech=tech,decision_year=2025,online_year=online,capacity_mw=capacity)


class SupportInvestmentTests(unittest.TestCase):
    def test_duration_hours_delay_and_collection_all_affect_npv(self):
        # Year2028:900 MWh, year2029:600 MWh; receipts one year later.
        actual=offer().pv_per_mw(lead=3,life=20,gross_full_load_hours=1000,discount_rate=.1)
        self.assertAlmostEqual(actual,(900/1.1**4+600/1.1**5)*100*.5)
        self.assertEqual(offer().pv_per_mw(lead=6,life=20,gross_full_load_hours=1000,discount_rate=.1),0)

    def test_optimistic_receipts_do_not_reduce_legal_commitment_reserve(self):
        a=offer(expected_collection_fraction=0)
        self.assertEqual(a.reserve_per_mw,150000)
        self.assertEqual(a.pv_per_mw(lead=3,life=20,gross_full_load_hours=1000,discount_rate=.1),0)

    def test_future_announcement_and_unphysical_hours_rejected(self):
        with self.assertRaises(ValueError):offer(announced_year=2026)
        with self.assertRaises(ValueError):offer().pv_per_mw(lead=3,life=20,gross_full_load_hours=9000,discount_rate=.1)
        with self.assertRaises(ValueError):offer(expected_collection_fraction=1.01)

    def test_no_offer_after_expiry_and_no_information_from_future_actual_rates(self):
        p=programme(actual={2030:{"biomass":{"invalid_future_value":float("nan")}}})
        args=dict(tech="biomass",lead=3,life=20,gross_full_load_hours=1000,discount_rate=.1)
        self.assertGreater(p.pv_per_mw(year=2025,**args),0)
        self.assertEqual(p.pv_per_mw(year=2026,**args),0)
        self.assertEqual(p.pv_per_mw(year=2024,**args),0)

    def test_pro_rata_allocation_is_order_independent_and_repeat_calls_preserve_cap(self):
        p=programme([offer(),offer(technology="wind")],budget=300000)
        requests=[dict(tech="biomass",lead=3),dict(tech="wind",lead=3)]
        capacities={"biomass":2,"wind":2}
        allocation=p.limit(2025,requests,capacities)
        self.assertEqual(allocation,{"biomass":1,"wind":1})
        self.assertEqual(p.limit(2025,list(reversed(requests)),capacities),allocation)
        p.register(project())
        p.register(project("w",tech="wind"))
        self.assertEqual(p.reserved[2025],300000)
        self.assertEqual(p.limit(2025,requests,capacities),{"biomass":0,"wind":0})
        with self.assertRaises(ValueError):p.register(project("excess"))
        self.assertNotIn("excess",p.awards)

    def test_duplicate_and_actual_rate_above_reserved_ceiling_rejected(self):
        p=programme(actual={2028:{"biomass":dict(supported_tariff_cny_per_mwh=200,
                     reference_tariff_cny_per_mwh=0,vat_rate=0)}})
        p.register(project())
        with self.assertRaises(ValueError):p.register(project())
        with self.assertRaises(ValueError):p.rates(2028,"p")
        with self.assertRaises(ValueError):p.rates(2029,"p")
        self.assertEqual(p.reserved[2025],150000)

    def test_rejected_and_unawarded_projects_create_no_position(self):
        p=programme()
        self.assertIsNone(p.register(project("late",online=2031)))
        self.assertIsNone(p.register(project("gas",tech="gas")))
        self.assertEqual(p.awards,{})

    def test_backdated_or_immediate_commissioning_cannot_reserve_authority(self):
        p=programme()
        for online in (2024,2025,2028.0):
            with self.assertRaises(ValueError):p.register(project(online=online))
            self.assertEqual(p.awards,{})
            self.assertEqual(p.reserved,{})

    def test_explicit_unawarded_project_never_reserves_or_gets_entitlement(self):
        p=programme(budget=0)
        self.assertIsNone(p.register({**project(),"support_eligible":False}))
        self.assertEqual(p.awards,{})
        self.assertEqual(p.reserved,{})
        with self.assertRaises(ValueError):
            p.register({**project(),"support_eligible":"false"})


AVAILABLE=all(importlib.util.find_spec(x) for x in ("mesa","scipy"))
@unittest.skipUnless(AVAILABLE,"Install requirements-q2.txt")
class SupportNationalLoopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from run_q2_national import preflight
        cls.data,cls.design,_=preflight()

    def merchant_fixture(self):
        from energy_model.q2_national import NationalModel,LIFE,LEAD
        theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,
                   replacement_adoption=.2,expectation_rate=.25)
        m=NationalModel(self.data,self.design,theta,2024)
        m.year=2025
        m.gdp_cny=m.a["gdp_2024_price_level_cny"]
        p=programme([offer(),offer(technology="wind")],budget=150000)
        m.revenue_policy=AnnualRevenuePolicy(energy_tariffs={},annual_funding={},support_rates={},
            positions=[],opening_cash_cny=0,opening_payables=[],initial_year=2024,
            real_2024_per_nominal={},metering_fraction={},evidence="synthetic award separation",new_support=p)
        m.generators["wind"].margin=1e8
        m.generators["biomass"].margin=-1e8
        proposals=[dict(tech=t,amount=2,capex=m.capex(t),lead=LEAD[t],life=LIFE[t]) for t in ("wind","biomass")]
        return m,proposals

    def test_profitable_unawarded_capacity_is_financed_without_free_support(self):
        m,proposals=self.merchant_fixture()
        initial_cash=m.generators["wind"].cash
        m.government.approve(proposals,[])
        projects=[p for p in m.projects if not p["initial_reconstruction"]]
        wind=[p for p in projects if p["tech"]=="wind"]
        bio=[p for p in projects if p["tech"]=="biomass"]
        self.assertAlmostEqual(sum(p["capacity_mw"] for p in wind),2)
        self.assertAlmostEqual(sum(p["capacity_mw"] for p in bio),.5)
        merchant=next(p for p in wind if p.get("support_eligible") is False)
        self.assertAlmostEqual(merchant["capacity_mw"],1.5)
        self.assertNotIn(merchant["id"],m.revenue_policy.new_support.awards)
        self.assertNotIn(merchant["id"],{p["terms"].project for p in m.revenue_policy.positions})
        self.assertAlmostEqual(m.revenue_policy.new_support.reserved[2025],150000)
        self.assertLess(m.generators["wind"].cash,initial_cash)
        self.assertEqual(merchant["online_year"],2026)
        self.assertEqual(merchant["remaining"],merchant["cost"])
        self.assertAlmostEqual(m.construction_fund,sum(p["remaining"] for p in m.projects))

    def test_failed_merchant_market_audit_keeps_only_supported_portfolio(self):
        from unittest.mock import patch
        m,proposals=self.merchant_fixture()
        with patch.object(m,"audit_renewable_portfolio",side_effect=[{"wind":.5,"biomass":.5},{"wind":0,"biomass":.5}]) as audit:
            m.government.approve(proposals,[])
        self.assertEqual(audit.call_args.kwargs["support_fractions"],{"wind":0.0})
        projects=[p for p in m.projects if not p["initial_reconstruction"]]
        self.assertEqual(len(projects),2)
        self.assertTrue(all(p["capacity_mw"]==.5 for p in projects))
        self.assertFalse(any(p.get("support_eligible") is False for p in projects))

    def test_support_meter_does_not_disappear_when_candidate_displaces_other_renewables(self):
        from unittest.mock import patch
        from energy_model.q2_national import NationalModel
        theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,
                   replacement_adoption=.2,expectation_rate=.25)
        model=NationalModel(self.data,self.design,theta,2024)
        op=dict(plants={"wind":dict(capacity_mw=5,ramp_mw_per_hour=1,window_energy_budget_mwh=120)})
        before=dict(generation=[dict(plant="wind",output_mwh=5),dict(plant="solar",output_mwh=15)])
        after=dict(generation=[dict(plant="wind",output_mwh=15),dict(plant="solar",output_mwh=5)])
        with patch.object(model,"planning_operation",return_value=op),patch("energy_model.q2_national.operate_national",side_effect=[before,after]):
            margin,eligible_gross_hours=model.marginal_renewable_economics("wind",5)
        self.assertAlmostEqual(eligible_gross_hours,15*365/10)
        self.assertAlmostEqual(margin,-29*model.fx*1000)  # No net extra energy sales.

    def test_approved_project_waits_for_commissioning_and_receives_only_funded_cash(self):
        from energy_model.q2_national import NationalModel,TECHS,LEAD
        theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,
                   replacement_adoption=.2,expectation_rate=.25)
        o=offer(eligible_years=15,lifetime_hours=82500,premium_cap_nominal_cny_per_mwh=1000,
                expected_premium_nominal_cny_per_mwh=1000,
                expected_collection_fraction=1,expected_payment_delay_years=0)
        online=2025+LEAD["biomass"]
        years=range(2025,online+1)
        p=programme([o],budget=o.reserve_per_mw*10,actual={online:{"biomass":dict(
                    supported_tariff_cny_per_mwh=800,reference_tariff_cny_per_mwh=449,vat_rate=.13)}})
        policy=AnnualRevenuePolicy(energy_tariffs={y:{t:449 for t in TECHS} for y in years},
            annual_funding={y:dict(levy_receipts_cny=0,treasury_transfer_cny=1000000,expenditure_limit_cny=1000000) for y in years},
            support_rates={},positions=[],opening_cash_cny=0,opening_payables=[],initial_year=2024,
            real_2024_per_nominal={y:1 for y in years},metering_fraction={y:{t:.9 for t in TECHS} for y in [2024,*years]},
            evidence="synthetic national-loop test only",new_support=p)
        model=NationalModel(self.data,self.design,theta,2024,revenue_policy=policy).run(online)
        awards=model.revenue_policy.new_support.awards
        self.assertEqual(len(awards),1)
        built=next(p for p in model.projects if p["id"] in awards)
        self.assertGreater(built["capacity_mw"],0)
        self.assertLessEqual(built["capacity_mw"],10+1e-9)
        for row in model.paths:
            if row["year"]<online:
                self.assertEqual(row["subsidy_entitlement_nominal_cny"],0)
                self.assertEqual(row["subsidy_paid_nominal_cny"],0)
        self.assertGreater(model.paths[-1]["subsidy_entitlement_nominal_cny"],0)
        self.assertGreater(model.paths[-1]["subsidy_arrears_nominal_cny"],0)
        self.assertLessEqual(model.paths[-1]["subsidy_paid_nominal_cny"],1000000)
        self.assertEqual(policy.positions,[])  # Original caller inputs untouched.
        self.assertEqual(p.awards,{})
        proposal=next(r for r in model.behavior if r["kind"]=="investment_proposal" and r["actor"]=="biomass" and r["year"]==2025)
        self.assertGreater(proposal["new_support_npv_cny_per_mw"],0)
        self.assertAlmostEqual(proposal["npv_cny_per_mw"],proposal["energy_only_npv_cny_per_mw"]+proposal["new_support_npv_cny_per_mw"])

    def test_actual_export_fraction_can_change_without_rewriting_offer_or_commitment(self):
        from types import SimpleNamespace
        p=programme([offer(eligible_years=3,lifetime_hours=1500,expected_collection_fraction=1)],
            budget=150000,actual={y:{"biomass":dict(supported_tariff_cny_per_mwh=100,
                reference_tariff_cny_per_mwh=0,vat_rate=0)} for y in (2028,2029,2030)})
        original=p.offers[2025,"biomass"]
        position=p.register(project())
        policy=AnnualRevenuePolicy(energy_tariffs={},
            annual_funding={y:dict(levy_receipts_cny=0,treasury_transfer_cny=200000,
                expenditure_limit_cny=200000) for y in (2028,2029,2030)},
            support_rates={},positions=[position],opening_cash_cny=0,opening_payables=[],initial_year=2027,
            real_2024_per_nominal={y:1 for y in (2028,2029,2030)},
            metering_fraction={2028:{"biomass":.8},2029:{"biomass":1.},2030:{"biomass":.95}},
            evidence="synthetic observed annual meter change",new_support=p)
        model=SimpleNamespace(year=2028,cohorts=[dict(id="p",tech="biomass",online_year=2028,
            capacity_mw=1,status="active")],projects=[],generators={"biomass":SimpleNamespace(cash=0)},finance=[])
        paid=[]
        for year in (2028,2029,2030):
            model.year=year
            paid.append(policy.settle(model,{"biomass":1000})["subsidy_paid_nominal_cny"])
        self.assertEqual(paid,[80000,70000,0])
        self.assertEqual(model.generators["biomass"].cash,150000)
        self.assertEqual(policy.positions[0]["prior_lifetime_mwh"],2750)
        self.assertEqual(policy.new_support.offers[2025,"biomass"],original)
        self.assertEqual(policy.new_support.reserved[2025],150000)


if __name__=="__main__":
    unittest.main()
