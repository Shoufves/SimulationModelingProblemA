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

    def test_no_cash_no_new_projects_even_with_positive_npv(self):
        from energy_model.q2_finance import financing_limit
        m=self.model(2024); m.drivers(); m.mature()
        g=m.generators["solar"]
        funded=financing_limit(g,m.capex("solar"))
        self.assertGreater(funded,0)
        g.cash=-1e12
        self.assertEqual(financing_limit(g,m.capex("solar")),0)
        self.assertEqual(g.proposal(g.margin)["amount"],0)

    def test_loan_draw_equity_repayment_and_transfer_conservation(self):
        from energy_model.q2_finance import fund_project,service_debt,debt
        m=self.model(2024);g=m.generators["solar"]
        original=g.cash;cost=1e8
        fund_project(g,cost,"probe")
        self.assertAlmostEqual(original-g.cash,cost*m.a["sponsor_equity_fraction"])
        initial=debt(g);m.year+=1
        service_debt(g)
        self.assertAlmostEqual(initial-debt(g),initial/m.a["loan_term_years"])
        for r in m.finance:
            self.assertAlmostEqual(sum(r.get(k,0) for k in ("actor_cash_transfer_cny","lender_transfer_cny","shareholder_transfer_cny","escrow_transfer_cny")),0,places=5)
        g.cash=0;m.year+=1;service_debt(g)
        from energy_model.q2_finance import financing_limit
        self.assertGreater(g.arrears,0)
        self.assertEqual(financing_limit(g,m.capex("solar")),0)

    def test_generation_addition_cannot_create_network(self):
        m=self.model(2024);m.drivers();m.mature()
        power=m.make_operation()["grid"]["power_mw"]
        m.cohorts.append(dict(tech="solar",status="active",capacity_mw=1e6))
        self.assertEqual(m.make_operation()["grid"]["power_mw"],power)

    def test_grid_construction_is_paid_and_delayed(self):
        m=self.model(2024);m.drivers()
        before=m.grid.network_power()
        amount=m.grid.enqueue("grid",1000,800000,.004,3,50)
        self.assertEqual(m.grid.network_power(),before)
        for _ in range(3):
            m.grid.pay();m.year+=1;m.grid.mature()
        self.assertAlmostEqual(m.grid.network_power(),before+amount)
        self.assertAlmostEqual(m.grid.reserved,0,places=5)
        self.assertGreater(m.construction_cost,0)

    def test_solar_construction_cap_not_proportional_to_fleet(self):
        m=self.model(2024);m.drivers();m.mature();g=m.generators["solar"]
        g.proposal(g.margin)
        before=m.behavior[-1]["construction_limit_mw"]
        m.cohorts.append(dict(tech="solar",status="active",capacity_mw=1e7,book_cost_cny_per_mw=1e6,online_year=2025,exit_year=2050))
        g.proposal(g.margin)
        self.assertEqual(m.behavior[-1]["construction_limit_mw"],before)

    def test_actual_curtailment_is_used_and_storage_starts_empty(self):
        m=self.model(2024).run(2035)
        self.assertTrue(any(r["previous_curtailment_mwh"]>0 for r in m.behavior if r["kind"]=="storage_proposal"))
        for left,right in zip(m.paths,m.paths[1:]):
            self.assertAlmostEqual(left["storage_closing_mwh"]-right["storage_retirement_loss_mwh"],right["storage_opening_mwh"],places=5)

    def test_covered_carbon_bid_is_separate_from_resource_cost(self):
        op=small_operation()
        p=next(iter(op["plants"].values()))
        p["policy_cost_per_mwh"]=50
        r=operate(op)
        self.assertAlmostEqual(r["dispatch_objective"],r["resource_cost"]+r["policy_signal_cost"])
        a=self.model(2024,variant={"carbon_price_multiplier":0});a.drivers();a.mature()
        b=self.model(2024,variant={"carbon_price_multiplier":10});b.drivers();b.mature()
        self.assertNotEqual(a.make_operation()["plants"]["coal"]["policy_cost_per_mwh"],b.make_operation()["plants"]["coal"]["policy_cost_per_mwh"])

    def test_carbon_bid_changes_dispatch_when_merit_order_crosses(self):
        op=small_operation();op["storage"].update(initial_mwh=0,power_mw=0,energy_mwh=0)
        op["fuels"]["gas"]["domestic_mw"]=[5,5]
        op["plants"]["clean"]={**op["plants"]["gas"],"input":None,"variable_cost_per_mwh":20}
        cheap=operate(op)
        op["plants"]["gas"]["policy_cost_per_mwh"]=30
        covered=operate(op)
        generation=lambda result,t:sum(r["output_mwh"] for r in result["generation"] if r["plant"]==t)
        self.assertEqual(generation(cheap,"gas"),10)
        self.assertEqual(generation(covered,"gas"),0)
        self.assertEqual(covered["resource_cost"],200)

    def test_positive_old_margin_cannot_fund_unconnectable_solar(self):
        m=self.model(2024);m.drivers();m.mature()
        m.grid.network[0]["power"]=0
        m.last_operation=m.make_operation()
        g=m.generators["solar"];g.cash=1e15;g.margin=1e7
        self.assertEqual(g.proposal(1e7)["amount"],0)

    def test_new_storage_does_not_invent_initial_energy(self):
        m=self.model(2024);m.drivers();m.mature()
        soc=m.storage_soc
        m.storage_cohorts.append(dict(power=1000,energy=4000,online=m.year,exit=m.year+10))
        self.assertEqual(m.make_operation()["storage"]["initial_mwh"],soc)

    def test_cyclic_fuel_state_is_inherited_after_first_year(self):
        m=self.model(2024).run(2025)
        expected=dict(m.fuel_stocks)
        m.drivers();m.mature();op=m.make_operation()
        self.assertEqual({f:p["initial_mwh"] for f,p in op["fuels"].items()},expected)

    def test_cheaper_new_equipment_does_not_revalue_existing_book_assets(self):
        from energy_model.q2_finance import book_assets
        m=self.model(2024);g=m.generators["solar"]
        original=book_assets(g);g.capex_2024*=.5
        self.assertEqual(book_assets(g),original)

    def test_covered_user_cost_response_and_carbon_settlement(self):
        m=self.model(2024,variant={"direct_carbon_coverage":1,"carbon_price_multiplier":100})
        m.run(2025)
        c=m.consumers["coal"];self.assertGreater(c.proposal()["electric_fraction"],0)
        self.assertGreater(next(r for r in m.finance if r["kind"]=="direct_ETS")["ets_transfer_cny"]*-1,0)
        self.assertLess(abs(m.paths[0]["cash_balance_residual_cny"]),.1)
        self.assertLess(abs(m.paths[0]["ets_balance_cny"]),.1)

    def test_electric_service_growth_cannot_create_free_equipment(self):
        m=self.model(2024);m.drivers();m.mature()
        before=m.make_operation()["demands"]["existing_electric_services"]
        m.electric_activity*=10
        after=m.make_operation()["demands"]["existing_electric_services"]
        self.assertEqual(before["input_capacity_mw"],after["input_capacity_mw"])
        self.assertAlmostEqual(sum(after["service_mwh"])/sum(before["service_mwh"]),10)

    def test_device_approval_needs_cash_and_one_year_to_commission(self):
        m=self.model(2024);m.drivers();m.mature();m.make_operation()
        c=m.consumers["electricity"];c.cash=0
        self.assertEqual(c.proposal()["amount"],0)
        proposal=dict(actor=c.name,amount=1000,electric_fraction=0,capex=1e6)
        m.government.approve_devices([proposal])
        self.assertEqual(c.queue,[])
        c.cash=1e9
        before=sum(p["capacity"] for p in c.cohorts if p["status"]=="active")
        m.government.approve_devices([proposal])
        self.assertEqual(c.cash,0)
        self.assertEqual(sum(p["capacity"] for p in c.cohorts if p["status"]=="active"),before)
        m.year+=1;c.prepare()
        self.assertTrue(any(p["online"]==m.year and p["capacity"]==1000 for p in c.cohorts))
        self.assertEqual(c.queue[0]["paid_cost_cny"],1e9)

    def test_zero_income_and_cash_preserve_unmet_requests(self):
        m=self.model(2024,variant={"consumer_income_multiplier":0})
        for c in m.consumers.values():c.cash=0
        m.run(2025)
        rows=[r for r in m.operations if r["kind"]=="demand" and r["sector"] in m.consumer_by_name]
        self.assertGreater(sum(r["requested_service_mwh"] for r in rows),0)
        self.assertAlmostEqual(sum(r["served_service_mwh"] for r in rows),0,places=5)
        self.assertAlmostEqual(sum(r["unmet_service_mwh"]-r["requested_service_mwh"] for r in rows),0,places=5)
        self.assertTrue(all(not c.queue and c.cash==0 for c in m.consumers.values()))

    def test_shared_wallet_and_scale_do_not_duplicate_budget(self):
        op=small_operation()
        op["storage"].update(initial_mwh=0,power_mw=0,energy_mwh=0)
        op["fuels"]["gas"]["domestic_mw"]=[5,5]
        op["demands"]["second"]=deepcopy(op["demands"]["load"])
        for d in op["demands"].values():d.update(budget_group="household",purchase_price_per_mwh=10)
        op["spending_limits"]={"household":dict(budget_cny=30)}
        for result in (operate(op),operate_national(op)):
            self.assertAlmostEqual(sum(r["input_mwh"] for r in result["demand"]),3,places=6)
            self.assertAlmostEqual(sum(r["unmet_service_mwh"] for r in result["demand"]),17,places=6)
        del op["spending_limits"]
        with self.assertRaises(Q2Error):operate(op)

    def test_consumer_cash_rolls_after_energy_and_device_payments(self):
        m=self.model(2024).run(2027)
        for c in m.consumers.values():
            records=[r for r in m.finance if r["actor"]==c.name and "closing_cash_cny" in r]
            for left,right in zip(records,records[1:]):
                self.assertEqual(left["closing_cash_cny"],right["opening_cash_cny"])
            self.assertEqual(records[-1]["closing_cash_cny"],c.cash)
            for r in records:
                if r["kind"]=="consumer_operation":
                    self.assertLessEqual(r["energy_bill_cny"],r["energy_budget_cny"]+.01)
                    self.assertLess(abs(r["consumer_cash_balance_residual_cny"]),.01)
                else:self.assertLess(abs(r["device_cash_balance_residual_cny"]),.01)

    def test_announced_elasticity_is_shared_by_forecast_and_real_demand(self):
        m=self.model(2024);m.drivers();m.mature();m.make_operation()
        m.year=2045;m.current_growth=.025
        expected=m.expected_service_growth("electricity",3)
        factor=1
        for y in (2046,2047,2048):
            mix=(y-2024)/36
            factor*=1.025**(m.electric_elasticity*(1-mix)+.8*mix)*.99
        self.assertAlmostEqual(expected,factor)
        m.year=2046;m.electric_activity=1;m.drivers()
        self.assertAlmostEqual(m.electric_activity,1.025**m.electricity_elasticity(2046)*.99)

    def test_planning_respects_retiring_and_paid_devices(self):
        m=self.model(2024);m.drivers();m.mature();m.last_operation=m.make_operation()
        c=m.consumers["electricity"]
        future=m.planning_operation(1)["demands"][c.name]
        expected=sum(p["capacity"] for p in c.cohorts if p["exit"]>2026)
        self.assertAlmostEqual(future["input_capacity_mw"],expected)
        c.cash=1e9;m.government.approve([], [dict(actor=c.name,amount=1000,electric_fraction=0,capex=1e6)])
        self.assertAlmostEqual(m.planning_operation(1)["demands"][c.name]["input_capacity_mw"],expected+1000)

    def test_running_review_replaces_stale_success_before_checks(self):
        import tempfile
        from unittest.mock import patch
        import review_q2_national_delivery as audit
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);out=root/"outputs/q2_review/p2_lb_national";out.mkdir(parents=True)
            receipt=out/"verification.json";receipt.write_text('{"passed":true,"status":"old_success"}')
            def interrupted(_):
                state=json.loads(receipt.read_text())
                self.assertFalse(state["passed"]);self.assertEqual(state["status"],"running")
                raise ValueError("injected audit failure")
            with patch.object(audit,"ROOT",root),patch.object(audit,"verify_latest",side_effect=interrupted),patch.object(audit,"sha",return_value="probe"):
                self.assertEqual(audit.main(),1)
            state=json.loads(receipt.read_text());self.assertFalse(state["passed"]);self.assertEqual(state["status"],"failed")

    def test_joint_investment_cannot_sell_same_market_twice(self):
        from unittest.mock import patch
        m=self.model(2024)
        op=small_operation();op["storage"].update(initial_mwh=0,power_mw=0,energy_mwh=0)
        plant={**op["plants"]["gas"],"input":None,"capacity_mw":0,"window_energy_budget_mwh":0}
        op["plants"]={"wind":deepcopy(plant),"solar":deepcopy(plant)}
        m.last_operation=op;m.a["generation_price_cny_per_mwh"]=10000
        for t in ("wind","solar"):
            m.generators[t].capex_2024=1;m.generators[t].margin=1e9
        # Each project alone can serve all 10 MWh; together neither creates
        # incremental sales. A real dispatch LP must force a smaller portfolio.
        with patch.object(m,"planning_operation",side_effect=lambda _:deepcopy(op)):
            for t in ("wind","solar"):self.assertGreater(m.marginal_renewable_margin(t,5),0)
            approved=m.audit_renewable_portfolio({"wind":5,"solar":5})
            self.assertEqual(approved,{"wind":2.5,"solar":2.5})
            for t in approved:self.assertGreater(m.marginal_renewable_margin(t,approved[t],approved),0)
        audits=[r for r in m.behavior if r["kind"]=="joint_renewable_audit"]
        self.assertFalse(audits[0]["approved"]);self.assertTrue(audits[-1]["approved"])

    def test_fuel_price_shock_does_not_reimburse_consumer_income(self):
        a=self.model(2024);b=self.model(2024,variant={"fuel_price_multiplier":2})
        for fuel in ("coal","oil","gas"):
            self.assertEqual(a.consumers[fuel].income_per_service,b.consumers[fuel].income_per_service)


if __name__=="__main__":unittest.main()
