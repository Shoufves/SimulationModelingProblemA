"""Subsidy counterexamples: eligibility is not cash, cash is not resource cost."""
from copy import deepcopy
from dataclasses import replace
from math import fsum
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from energy_model.q2_subsidies import Claim,SupportTerms,SubsidyFund,accrue,billed_energy_revenue


class SubsidyTests(unittest.TestCase):
    def test_roundoff_never_pays_above_binding_authority_or_cash(self):
        amount=104062868.19648509
        for opening,limit in ((1e6,2e6),(2e6,1e6)):
            fund=SubsidyFund(opening_cash_cny=opening,opening_payables=[],initial_year=2019)
            result=fund.settle(year=2020,claims=[Claim("p","gas",2020,0,amount)],
                levy_receipts_cny=0,treasury_transfer_cny=0,expenditure_limit_cny=limit)
            self.assertLessEqual(result["paid_cny"],1e6)
            self.assertGreaterEqual(result["closing_cash_cny"],0)
            self.assertEqual(result["paid_cny"],fsum(p["paid_cny"] for p in result["payments"]))
            self.assertAlmostEqual(result["paid_cny"]+result["closing_arrears_cny"],amount)

    def terms(self, **updates):
        base = SupportTerms("biomass1","biomass",True,2010,2020,15,10,82500,1,"synthetic fixture; not China observations")
        return replace(base,**updates)

    def entitlement(self,terms=None,**updates):
        args = dict(year=2020,metered_mwh=1000,prior_lifetime_mwh=100000,
                    supported_tariff_cny_per_mwh=750,reference_tariff_cny_per_mwh=400,vat_rate=.13)
        args.update(updates)
        return accrue(terms or self.terms(),**args)

    def fund(self,**updates):
        args = dict(opening_cash_cny=0,opening_payables=[],initial_year=2019)
        args.update(updates)
        return SubsidyFund(**args)

    def settle(self,fund,**updates):
        args = dict(year=fund.last_year+1,claims=[],levy_receipts_cny=0,treasury_transfer_cny=0,expenditure_limit_cny=1000)
        args.update(updates)
        return fund.settle(**args)

    def test_tariff_support_is_split_not_added_twice(self):
        energy = billed_energy_revenue(gross_mwh=1000,own_use_fraction=.1,tariff_vat_inclusive=400,vat_rate=.13)
        subsidy = self.entitlement(metered_mwh=900)["claim"].amount_cny
        self.assertAlmostEqual(energy+subsidy,900*750/1.13)

    def test_own_use_is_not_billed_as_exported_electricity(self):
        self.assertEqual(billed_energy_revenue(gross_mwh=100,own_use_fraction=.12,tariff_vat_inclusive=500,vat_rate=0),44000)

    def test_age_expiry_uses_commissioning_not_simulation_start(self):
        self.assertGreater(self.entitlement(year=2024)["claim"].amount_cny,0)
        self.assertEqual(self.entitlement(year=2025)["claim"].amount_cny,0)

    def test_quota_counts_generation_before_current_policy(self):
        row = self.entitlement(prior_lifetime_mwh=824900)
        self.assertEqual(row["eligible_mwh"],100)
        self.assertEqual(row["closing_lifetime_mwh"],825900)
        self.assertEqual(self.entitlement(prior_lifetime_mwh=825000)["claim"].amount_cny,0)

    def test_ineligible_project_gets_no_support(self):
        self.assertEqual(self.entitlement(self.terms(eligible=False))["claim"].amount_cny,0)

    def test_no_retroactive_rule_application(self):
        self.assertEqual(self.entitlement(year=2019)["claim"].amount_cny,0)

    def test_no_output_before_project_exists(self):
        with self.assertRaises(ValueError):self.entitlement(year=2009)

    def test_no_negative_subsidy_if_reference_price_higher(self):
        self.assertEqual(self.entitlement(reference_tariff_cny_per_mwh=800)["claim"].amount_cny,0)

    def test_entitlement_without_budget_does_not_become_cash(self):
        fund=self.fund()
        row=self.settle(fund,claims=[Claim("a","gas",2020,1,100)])
        self.assertEqual(row["paid_cny"],0)
        self.assertEqual(row["closing_arrears_cny"],100)
        self.assertEqual(row["closing_cash_cny"],0)

    def test_cash_and_appropriation_both_bind(self):
        for cash,limit,expected in ((100,30,30),(30,100,30),(100,0,0)):
            fund=self.fund(opening_cash_cny=cash)
            row=self.settle(fund,claims=[Claim("a","wind",2020,1,200)],expenditure_limit_cny=limit)
            self.assertEqual(row["paid_cny"],expected)
            self.assertEqual(row["closing_cash_cny"],cash-expected)
            self.assertEqual(row["closing_arrears_cny"],200-expected)

    def test_old_receivable_is_paid_even_after_new_eligibility_expires(self):
        fund=self.fund(initial_year=2024,opening_payables=[Claim("biomass1","biomass",2024,1,200)])
        expired=self.entitlement(year=2025)["claim"]
        row=self.settle(fund,claims=[expired],levy_receipts_cny=150)
        self.assertEqual(row["new_entitlement_cny"],0)
        self.assertEqual(row["paid_cny"],150)
        self.assertEqual(row["closing_arrears_cny"],50)

    def test_priority_then_oldest_then_pro_rata(self):
        fund=self.fund(opening_payables=[Claim("old","wind",2019,1,60)])
        row=self.settle(fund,claims=[Claim("priority","household",2020,0,20),
                                   Claim("a","wind",2020,1,100),Claim("b","solar",2020,1,300)],
                        levy_receipts_cny=180)
        paid={p["project"]:p["paid_cny"] for p in row["payments"]}
        self.assertEqual(paid,dict(priority=20,old=60,a=25,b=75))

    def test_claim_iteration_order_does_not_allocate_privilege(self):
        claims=[Claim("a","wind",2020,1,100),Claim("b","solar",2020,1,300)]
        a=self.settle(self.fund(),claims=claims,levy_receipts_cny=100)
        b=self.settle(self.fund(),claims=list(reversed(claims)),levy_receipts_cny=100)
        self.assertEqual(a,b)

    def test_subsidy_journal_conserves_cash_and_adds_no_resource_cost(self):
        row=self.settle(self.fund(),claims=[Claim("a","wind",2020,1,900)],levy_receipts_cny=100,treasury_transfer_cny=200)
        self.assertEqual(row["paid_cny"],300)
        self.assertEqual(fsum(r["cash_delta_cny"] for r in row["journal"]),0)
        self.assertEqual(fsum(r["resource_cost_cny"] for r in row["journal"]),0)

    def test_duplicate_claim_failure_is_atomic(self):
        fund=self.fund(); before=deepcopy(fund.__dict__)
        with self.assertRaises(ValueError):
            self.settle(fund,claims=[Claim("a","wind",2020,1,100)]*2,levy_receipts_cny=100)
        self.assertEqual(fund.__dict__,before)

    def test_missing_or_repeated_year_fails(self):
        fund=self.fund()
        for year in (2019,2021):
            with self.assertRaises(ValueError):self.settle(fund,year=year)

    def test_ownership_or_priority_cannot_change_silently(self):
        fund=self.fund(opening_payables=[Claim("a","wind",2019,1,100)])
        with self.assertRaises(ValueError):self.settle(fund,claims=[Claim("a","solar",2020,1,100)])
        with self.assertRaises(ValueError):self.settle(fund,claims=[Claim("a","wind",2020,0,100)])

    def test_nan_infinity_negative_values_and_implicit_eligibility_rejected(self):
        for bad in (float("nan"),float("inf"),-1,True):
            with self.assertRaises(ValueError):self.fund(opening_cash_cny=bad)
            with self.assertRaises(ValueError):self.entitlement(vat_rate=bad)
            with self.assertRaises(ValueError):self.settle(self.fund(),expenditure_limit_cny=bad)
        with self.assertRaises(ValueError):self.terms(eligible=1)

    def test_national_scale_multiyear_payable_and_fund_stock_conservation(self):
        rng=random.Random(431)
        fund=self.fund(opening_cash_cny=1.1e10)
        received,entitled,paid=0.,0.,0.
        for year in range(2020,2050):
            claims=[Claim(f"project_{j}","wind" if j%2 else "solar",year,j%3,rng.random()*1e10) for j in range(20)]
            levy=rng.random()*5e10; treasury=rng.random()*1e10
            row=self.settle(fund,claims=claims,levy_receipts_cny=levy,treasury_transfer_cny=treasury,expenditure_limit_cny=rng.random()*1e11)
            received+=levy+treasury;entitled+=fsum(c.amount_cny for c in claims);paid+=row["paid_cny"]
            self.assertGreaterEqual(fund.cash,-.001)
            self.assertAlmostEqual((1.1e10+received-paid-fund.cash)/max(1,received),0,places=12)
            self.assertAlmostEqual((entitled-paid-fsum(c.amount_cny for c in fund.payables))/max(1,entitled),0,places=12)


if __name__=="__main__":
    unittest.main()
