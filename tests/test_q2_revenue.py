"""Cash propagation through the actual national actor/debt/decision loop."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"));sys.path.insert(0,str(ROOT/"scripts"))
from energy_model.q2_subsidies import SupportTerms,Claim
from energy_model.q2_revenue import AnnualRevenuePolicy
AVAILABLE=all(importlib.util.find_spec(x) for x in ("mesa","scipy"))
if AVAILABLE:
    from energy_model.q2_national import NationalModel,TECHS
    from run_q2_national import preflight


@unittest.skipUnless(AVAILABLE,"Install requirements-q2.txt")
class RevenueIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data,cls.design,_=preflight()
        cls.theta=dict(activity_elasticity=.5,investment_response=1,renewable_mix_response=.7,
                       replacement_adoption=.2,expectation_rate=.25)

    def model(self,**kwargs):
        return NationalModel(self.data,self.design,self.theta,2024,investment=False,**kwargs)

    def policy(self,**changes):
        m=self.model()
        cohort=next(c for c in m.cohorts if c["tech"]=="biomass" and c["online_year"]==2024 and c["capacity_mw"]>0)
        terms=SupportTerms(cohort["id"],"biomass",True,2024,2025,15,cohort["capacity_mw"],82500,1,"synthetic integration fixture")
        args=dict(energy_tariffs={2025:{t:449 for t in TECHS}},
            annual_funding={2025:dict(levy_receipts_cny=1e8,treasury_transfer_cny=1e8,expenditure_limit_cny=2e8)},
            support_rates={2025:{terms.project:dict(supported_tariff_cny_per_mwh=750,reference_tariff_cny_per_mwh=449,vat_rate=.13)}},
            positions=[dict(terms=terms,prior_lifetime_mwh=0)],opening_cash_cny=0,opening_payables=[],initial_year=2024,
            real_2024_per_nominal={2025:1.1},metering_fraction={y:{t:1 for t in TECHS} for y in (2024,2025)},evidence="synthetic test, not national input")
        args.update(changes)
        return AnnualRevenuePolicy(**args)

    def test_default_is_opt_out_and_does_not_grant_free_subsidies(self):
        model=self.model().run(2025)
        self.assertIsNone(model.revenue_policy)
        self.assertNotIn("subsidy_paid_real_cny",model.paths[0])

    def test_only_actual_payment_enters_generator_cash_once(self):
        without=self.model().run(2025)
        with_support=self.model(revenue_policy=self.policy()).run(2025)
        row=with_support.paths[0]
        paid=row["subsidy_paid_real_cny"]
        self.assertGreater(paid,0)
        self.assertAlmostEqual(with_support.generators["biomass"].cash-without.generators["biomass"].cash,paid,delta=.001)
        self.assertAlmostEqual(row["resource_cost_cny"],without.paths[0]["resource_cost_cny"],delta=.01)
        self.assertLess(abs(row["cash_balance_residual_cny"]),.1)
        self.assertEqual(with_support.generators["biomass"].margin,without.generators["biomass"].margin)

    def test_entitlements_cannot_finance_investment_when_fund_unfunded(self):
        policy=self.policy(annual_funding={2025:dict(levy_receipts_cny=0,treasury_transfer_cny=0,expenditure_limit_cny=1e12)})
        baseline=self.model().run(2025)
        model=self.model(revenue_policy=policy).run(2025)
        self.assertGreater(model.paths[0]["subsidy_arrears_nominal_cny"],0)
        self.assertEqual(model.paths[0]["subsidy_paid_real_cny"],0)
        self.assertEqual(model.generators["biomass"].cash,baseline.generators["biomass"].cash)

    def test_settlement_precedes_actual_debt_service(self):
        models=[self.model(),self.model(revenue_policy=self.policy())]
        for model in models:
            model.generators["biomass"].loans=[dict(project="synthetic",remaining=1e14,annual_principal=1e14,
                due=2025,overdue=0,interest_overdue=0)]
            model.run(2025)
        loans=[m.generators["biomass"].loans[0] for m in models]
        unpaid=lambda l:l["remaining"]+l["interest_overdue"]
        self.assertAlmostEqual(unpaid(loans[0])-unpaid(loans[1]),models[1].paths[0]["subsidy_paid_real_cny"],delta=.1)

    def test_missing_tariff_is_rejected_instead_of_carried_forward(self):
        with self.assertRaises(ValueError):self.model(revenue_policy=self.policy(energy_tariffs={}))

    def test_station_meter_is_shared_by_initial_demand_physics_and_claims(self):
        fractions={y:{t:.9 for t in TECHS} for y in (2024,2025)}
        model=self.model(revenue_policy=self.policy(metering_fraction=fractions))
        expected=(self.data[2024,"electricity_generation_mwh"]-.1*sum(model.initial_generation.values()))*model.a["grid_efficiency"]-model.base_export
        self.assertAlmostEqual(model.base_electric,expected,delta=.001)
        model.run(2025)
        row=model.paths[0]
        self.assertAlmostEqual(row["generation_auxiliary_use_mwh"],.1*row["electricity_generation_mwh"],delta=.001)
        self.assertAlmostEqual(row["generation_bus_output_mwh"],.9*row["electricity_generation_mwh"],delta=.001)
        demand=sum(r["input_mwh"] for r in model.operations if r["kind"]=="demand" and r["carrier"]=="electricity")*365/model.a["grid_efficiency"]
        stored=sum(r["charge_mwh"]-r["discharge_mwh"] for r in model.operations if r["kind"]=="storage")*365
        self.assertAlmostEqual(row["generation_bus_output_mwh"],demand+stored,delta=.1)
        self.assertLess(abs(row["cash_balance_residual_cny"]),.1)

    def test_missing_initial_station_meter_cannot_create_implicit_zero_loss(self):
        with self.assertRaisesRegex(ValueError,"2024"):
            self.model(revenue_policy=self.policy(metering_fraction={2025:{t:.9 for t in TECHS}}))

    def test_fund_and_model_clock_must_match(self):
        with self.assertRaises(ValueError):self.model(revenue_policy=self.policy(initial_year=2023))

    def test_levy_must_be_a_funded_retail_component(self):
        policy=self.policy(annual_funding={2025:dict(levy_receipts_cny=1e20,treasury_transfer_cny=0,expenditure_limit_cny=1e20)})
        model=self.model(revenue_policy=policy)
        with self.assertRaises(ValueError):model.run(2025)
        self.assertEqual(model.revenue_policy.fund.last_year,2024)

    def test_unknown_initial_payable_owner_fails_before_fund_changes(self):
        policy=self.policy(opening_payables=[Claim("unknown","fake_recipient",2024,1,100)])
        model=self.model(revenue_policy=policy)
        with self.assertRaises(ValueError):model.run(2025)
        self.assertEqual(model.revenue_policy.fund.last_year,2024)

    def test_payment_year_deflator_applies_to_older_nominal_arrears(self):
        policy=self.policy(positions=[],opening_payables=[Claim("retired","biomass",2015,1,1e8)],
                           annual_funding={2025:dict(levy_receipts_cny=1e8,treasury_transfer_cny=0,expenditure_limit_cny=1e8)})
        model=self.model(revenue_policy=policy).run(2025)
        self.assertAlmostEqual(model.paths[0]["subsidy_paid_real_cny"],1.1e8,delta=.000001)
        self.assertEqual(model.paths[0]["subsidy_entitlement_nominal_cny"],0)

    def test_nonfinite_closing_cash_rejected_before_any_commit(self):
        policy=self.policy(positions=[],opening_cash_cny=1e308,
                           opening_payables=[Claim("retired","biomass",2024,1,1e308)],
                           annual_funding={2025:dict(levy_receipts_cny=0,treasury_transfer_cny=0,expenditure_limit_cny=1e308)},
                           real_2024_per_nominal={2025:1})
        actor=SimpleNamespace(cash=1e308)
        model=SimpleNamespace(year=2025,cohorts=[],generators={"biomass":actor},finance=[])
        with self.assertRaisesRegex(ValueError,"closing cash"):
            policy.settle(model,{"biomass":0})
        self.assertEqual(actor.cash,1e308)
        self.assertEqual(model.finance,[])
        self.assertEqual(policy.fund.last_year,2024)
        self.assertEqual(policy.history,[])


if __name__=="__main__":
    unittest.main()
