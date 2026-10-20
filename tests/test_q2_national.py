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
        m.cohorts.append(dict(id="test/new_solar",tech="solar",status="active",capacity_mw=1e6,
            online_year=m.year,exit_year=m.year+25))
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


    def test_positive_npv_and_high_response_cannot_exceed_construction(self):
        m=self.model(2024);m.drivers();m.mature()
        m.theta={**m.theta,"investment_response":1.75,"renewable_mix_response":.4}
        m.gdp_cny=1e20
        proposals=[]
        for g in m.generators.values():
            g.cash=1e18;g.margin=1e10
            p=g.proposal(1e10)
            self.assertGreater(m.behavior[-1]["npv_cny_per_mw"],0)
            self.assertGreater(p["amount"],0)
            self.assertLessEqual(p["amount"],g.construction_limit())
            proposals.append(p)
        m.government.approve(proposals,[])
        for p in m.projects:
            if not p["initial_reconstruction"]:
                self.assertLessEqual(p["capacity_mw"],m.generators[p["tech"]].construction_limit())

    def test_approval_rechecks_cap_and_cumulative_annual_commitments(self):
        m=self.model(2024);m.drivers();m.mature();m.gdp_cny=1e20
        g=m.generators["hydro"];g.cash=1e18;g.margin=1e10
        p=g.proposal(1e10);p["amount"]=g.construction_limit()*10
        p["construction_limit_mw"]=1e30
        for _ in range(2):m.government.approve([p],[])
        projects=[p for p in m.projects if not p["initial_reconstruction"] and p["tech"]=="hydro"]
        self.assertEqual(len(projects),1)
        self.assertAlmostEqual(sum(p["capacity_mw"] for p in projects),g.construction_limit())
        with self.assertRaises(Q2Error):m.government.approve([p,p],[])

    def test_pending_or_withdrawn_source_rejected_without_byte_changes(self):
        import run_q2_national as runner
        from unittest.mock import patch
        original=runner.load
        for field,value in (("status","pending_review"),("allowed_use","candidate_inventory_only_NOT_national_initialization_or_calibration"),("allowed_operations",[])):
            reviewed=deepcopy(original(ROOT/runner.INPUTS[0]))
            for source in reviewed["sources"]:source[field]=value
            def changed(path):
                return reviewed if Path(path)==ROOT/runner.INPUTS[0] else original(path)
            with self.subTest(field=field),patch.object(runner,"load",side_effect=changed):
                with self.assertRaises(ValueError):runner.preflight()

    def test_each_required_source_cannot_be_removed_or_duplicated(self):
        from energy_model.q2_admission import validate_admission
        import run_q2_national as runner
        review=runner.load(ROOT/runner.INPUTS[0]);_,design,rows=preflight()
        for i in range(len(review["sources"])):
            missing=deepcopy(review);missing["sources"].pop(i)
            with self.subTest(source=i),self.assertRaises(ValueError):validate_admission(missing,rows,design)
        duplicate=deepcopy(review);duplicate["sources"].append(duplicate["sources"][0])
        with self.assertRaises(ValueError):validate_admission(duplicate,rows,design)

    def test_actual_observation_use_is_bound_to_reviewed_source(self):
        from energy_model.q2_admission import validate_admission
        import run_q2_national as runner
        review=runner.load(ROOT/runner.INPUTS[0]);_,design,rows=preflight()
        for change in ({"use":"initialization"},{"source_path":review["sources"][0]["path"]},{"source_sha256":"0"*64}):
            changed=deepcopy(rows)
            next(r for r in changed if r["metric"]=="gcb_positive_co2_t").update(change)
            with self.subTest(change=change),self.assertRaises(ValueError):validate_admission(review,changed,design)
        design["targets"][0]["observation"]="gcb_positive_co2_t"
        with self.assertRaisesRegex(ValueError,"not admitted to calibration"):validate_admission(review,rows,design)

    def test_gcb_peak_use_requires_separate_admission(self):
        from energy_model.q2_admission import validate_admission
        import run_q2_national as runner
        review=runner.load(ROOT/runner.INPUTS[0]);_,design,rows=preflight()
        gcb=next(s for s in review["sources"] if "GCB2025" in s["path"])
        gcb["allowed_operations"].remove("conditional_peak_bridge")
        with self.assertRaisesRegex(ValueError,"operations"):validate_admission(review,rows,design)

    def _missing_startup_and_retry(self, previous_success):
        import run_q2_national as runner
        import tempfile
        from types import SimpleNamespace
        from unittest.mock import patch
        (ROOT/"tmp").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/"tmp") as temp:
            root=Path(temp).resolve();out=root/"outputs/q2/probe"
            for name in runner.CODE+runner.INPUTS:
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text("{}",encoding="utf-8")
            if previous_success:
                out.mkdir(parents=True)
                runner.dump(out/"run_manifest.json",dict(run_id="previous",owner="p2/lb",status="success_conditional_candidate"))
                runner.dump(out.parent/(out.name+".latest-attempt.json"),dict(run_id="previous",status="success_conditional_candidate",output_valid_for_this_attempt=True))
                (out/"old-result.txt").write_text("preserve me")
            missing=root/runner.INPUTS[1];missing.unlink()
            calibration={"quality":{"acceptance":{"all_thresholds_passed":True}}}
            model=SimpleNamespace(paths=[{"max_residual":0}])
            with patch.object(runner,"ROOT",root),patch.object(sys,"argv",["probe","--output-dir","outputs/q2/probe"]),\
                patch.object(runner,"preflight",return_value=({}, {}, [])) as flight,\
                patch.object(runner,"calibrate",return_value=calibration),\
                patch.object(runner,"evaluate",return_value=model),\
                patch.object(runner,"experiments",return_value=(model,[],[],[])),\
                patch.object(runner,"plot"),patch.object(runner,"report"):
                with self.assertRaises(FileNotFoundError):runner.main()
                flight.assert_not_called()
                latest=runner.load(out.parent/(out.name+".latest-attempt.json"))
                manifest=runner.load(out/"run_manifest.json")
                self.assertEqual(latest["status"],"failed");self.assertFalse(latest["output_valid_for_this_attempt"])
                self.assertEqual(manifest["owner"],"p2/lb");self.assertEqual(manifest["error_type"],"FileNotFoundError")
                if previous_success:
                    self.assertEqual((out.parent/"probe.attempts/previous/old-result.txt").read_text(),"preserve me")
                missing.write_text("{}",encoding="utf-8")
                runner.main()
                self.assertEqual(runner.verify_latest(out)["status"],"success_conditional_candidate")
                self.assertTrue((out.parent/"probe.attempts"/manifest["run_id"]/"run_manifest.json").exists())

    def test_first_run_missing_input_records_failure_and_can_retry(self):
        self._missing_startup_and_retry(False)

    def test_existing_success_missing_input_invalidates_and_can_retry(self):
        self._missing_startup_and_retry(True)

    def test_common_q2_entry_dispatches_reviewed_national_runner(self):
        from unittest.mock import patch
        spec=importlib.util.spec_from_file_location("q2_common_entry",ROOT/"run.py")
        entry=importlib.util.module_from_spec(spec);spec.loader.exec_module(entry)
        for config in ("workflow/q2_inputs.json","workflow/q2_national_design.json",str(ROOT/"workflow/q2_inputs.json")):
            with patch.object(sys,"argv",["run.py","q2","--config",config,"--output-dir","outputs/q2/review_pr9_common_entry"]),patch.object(entry,"script",return_value=0) as dispatch:
                self.assertEqual(entry.main(),0)
                dispatch.assert_called_once_with("run_q2_national.py","--output-dir","outputs/q2/review_pr9_common_entry")

    def test_fuel_shares_reconcile_to_physical_fuel_and_primary_total(self):
        m=self.model(2024).run(2025);r=m.paths[0]
        self.assertAlmostEqual(sum(r[f+"_share"] for f in ("coal","oil","gas"))+r["nonfossil_share"],1,places=12)
        for fuel in ("coal","oil","gas"):
            physical=sum(v["direct_mwh"]+v["conversion_mwh"] for v in m.operations if v["kind"]=="fuel" and v["fuel"]==fuel)*365
            self.assertAlmostEqual(physical/(r[fuel+"_primary_tce"]*TCE_MWH),1,places=12)
            self.assertAlmostEqual(r[fuel+"_share"],r[fuel+"_primary_tce"]/r["primary_energy_tce"],places=12)

    def test_oil_gas_errors_cannot_escape_training_loss(self):
        m=self.model(detail=False).run(2021)
        original,_,_=loss(m.paths,self.data,self.design,self.design["training_years"],"probe")
        changed=deepcopy(m.paths)
        for row in changed:
            row["oil_share"]+=1;row["gas_share"]+=1
        other,parts,_=loss(changed,self.data,self.design,self.design["training_years"],"probe")
        self.assertGreater(other,original)
        self.assertEqual({p["metric"] for p in parts if p["metric"].endswith("_share")},{"coal_share","oil_share","gas_share","peo_share"})

    def test_statistical_bridge_fit_never_reads_evaluation_observations(self):
        from energy_model.q2_statistics import fit_bridge
        original=fit_bridge(self.data,self.design)
        changed=deepcopy(self.data)
        for key in changed:
            if key[0]>=2022:changed[key]*=11 if "consumption" in key[1] else 3
        self.assertEqual(original,fit_bridge(changed,self.design))

    def test_bridge_constant_baseline_and_forecast_anchor(self):
        from energy_model.q2_statistics import coefficient,observed_coefficient
        for anchor in (2014,2024):
            for year in (anchor,anchor+10,2060):
                self.assertEqual(coefficient(self.data,self.design,anchor,year,{"bridge_trend_multiplier":0}),observed_coefficient(self.data,anchor))
        self.assertNotEqual(coefficient(self.data,self.design,2014,2025),coefficient(self.data,self.design,2024,2025))

    def test_carrier_elasticities_affect_their_own_requests(self):
        a=self.model();b=self.model()
        b.theta["gas_activity_elasticity"]=2.5
        a.drivers();b.drivers()
        self.assertGreater(b.consumers["gas"].service_request(),a.consumers["gas"].service_request())
        self.assertEqual(b.consumers["oil"].service_request(),a.consumers["oil"].service_request())
        self.assertEqual(b.consumers["coal"].service_request(),a.consumers["coal"].service_request())

    def test_policy_comparison_never_certifies_official_attainment(self):
        m=self.model(2024,detail=False).run(2060)
        rows,_=targets(m.paths,self.data,self.design)
        nf=[r for r in rows if r["metric"]=="nonfossil_share"]
        self.assertEqual([r["target"] for r in nf],[.25,.8])
        self.assertTrue(all(not r["official_attainment_certified"] and r["judgement"].startswith("conditional_") for r in nf))

    def test_missing_fuel_calibration_target_is_rejected(self):
        from energy_model.q2_admission import validate_admission
        from run_q2_national import load
        _,design,rows=preflight()
        design["targets"]=[t for t in design["targets"] if t["metric"]!="gas_share"]
        with self.assertRaisesRegex(ValueError,"Required calibration target"):
            validate_admission(load(ROOT/"data/catalog/q2_national_input_review.json"),rows,design)

    def test_planning_supply_follows_announced_path_without_side_effects(self):
        m=self.model(2024);m.drivers();m.mature();m.last_operation=m.make_operation()
        before=len(m.behavior)
        future=m.planning_operation(3)
        self.assertEqual(len(m.behavior),before)
        for fuel,supplier in m.suppliers.items():
            expected=supplier.offer(m.year+3,record=False)
            self.assertEqual(future["fuels"][fuel]["domestic_mw"],expected["domestic_mw"])
            self.assertEqual(future["fuels"][fuel]["import_mw"],expected["import_mw"])
            self.assertEqual(future["fuels"][fuel]["initial_mwh"],m.last_operation["fuels"][fuel]["initial_mwh"])

    def test_priority_has_publication_boundary_and_cost_only_counterfactual(self):
        m=self.model();m.drivers();m.mature();m.last_operation=m.make_operation()
        self.assertNotIn("fossil_displacement_priority_plants",m.last_operation)
        self.assertNotIn("fossil_displacement_priority_plants",m.planning_operation(3))
        m.year=2016
        self.assertEqual(m.make_operation()["fossil_displacement_priority_plants"],["coal","oil","gas"])
        m.variant["nonfossil_dispatch_priority"]=0
        self.assertNotIn("fossil_displacement_priority_plants",m.make_operation())

    def test_generation_diagnostic_exposes_mix_error_despite_equal_total(self):
        from run_q2_national import generation_diagnostics
        from energy_model.q2_national import TECHS
        row={"year":2021}
        for tech in TECHS:
            row[tech+"_generation_mwh"]=self.data[2021,("biofuel" if tech=="biomass" else tech)+"_electricity_mwh"]
        total=sum(row[t+"_generation_mwh"] for t in TECHS)
        row["coal_generation_mwh"]+=row["gas_generation_mwh"]
        row["gas_generation_mwh"]=0
        self.assertEqual(total,sum(row[t+"_generation_mwh"] for t in TECHS))
        result=generation_diagnostics([row],self.data,self.design)
        self.assertEqual(len(result),8)
        self.assertEqual([r["technology"] for r in result if r["zero_model_with_positive_observation"]],["gas"])
        self.assertAlmostEqual(sum(r["residual_mwh"] for r in result),0,places=4)

    def test_nonpower_identification_is_training_only_and_not_simulated_power(self):
        from energy_model.q2_identification import fit_nonpower,identified_parameters
        original=fit_nonpower(self.data,self.design)
        data=deepcopy(self.data)
        for key in data:
            if key[0]>=2022:data[key]*=17
        self.assertEqual(original,fit_nonpower(data,self.design))
        self.assertFalse(original["observed_final_energy"])
        params=identified_parameters(original)
        self.assertEqual({k:self.design["calibration_search"]["initial_parameters"][k] for k in params},params)
        self.assertFalse(set(params)&set(self.design["parameter_grid"]))

    def test_initial_utilisation_uses_only_average_initial_capacity(self):
        m=self.model()
        for t in ("hydro","nuclear","wind","solar"):
            average=(self.data[2013,t+"_capacity_mw"]+self.data[2014,t+"_capacity_mw"])/2
            expected=min(.9,self.data[2014,t+"_electricity_mwh"]/(8760*average))
            self.assertAlmostEqual(m.generators[t].reference_cf,expected)
        self.assertGreater(m.supply_growth["biomass"],self.design["assumptions"]["fuel_supply_annual_growth"])

    def test_training_pipeline_inference_is_not_transferred_to_2024(self):
        theta={**self.theta,"nuclear_initial_pipeline_multiplier":2,"hydro_initial_pipeline_multiplier":.5}
        past=NationalModel(self.data,self.design,theta,2014)
        present=NationalModel(self.data,self.design,theta,2024)
        for m,factor in ((past,2),(present,1)):
            projects=[p for p in m.projects if p["tech"]=="nuclear"]
            for p in projects:
                self.assertAlmostEqual(p["capacity_mw"],m.initial_additions["nuclear"]*factor)
                self.assertAlmostEqual(p["cost"],p["capacity_mw"]*m.generators["nuclear"].capex_2024)
            self.assertAlmostEqual(m.construction_fund,sum(p["remaining"] for p in m.projects))

    def test_national_allocation_score_is_scaled_and_not_money(self):
        m=self.model();m.drivers();m.mature();op=m.make_operation()
        raw=operate(op);scaled=operate_national(op)
        for key in ("actual_dispatch_cost","behavioral_score","reference_fossil_mwh","resource_cost"):
            self.assertAlmostEqual(raw[key]/scaled[key],1,places=8)
        self.assertAlmostEqual(scaled["actual_dispatch_cost"]/(scaled["resource_cost"]+scaled["policy_signal_cost"]),1,places=12)
        self.assertAlmostEqual(scaled["dispatch_objective"]/(scaled["actual_dispatch_cost"]+scaled["behavioral_score"]),1,places=12)
        m.variant["dispatch_kappa_multiplier"]=0
        self.assertNotIn("fossil_allocation_score",m.make_operation())

    def test_fuel_price_shock_does_not_recalibrate_behavioral_anchor(self):
        a=self.model();b=self.model(variant={"fuel_price_multiplier":1.3})
        for m in (a,b):m.drivers();m.mature()
        left=a.make_operation();right=b.make_operation()
        self.assertEqual(left["fossil_allocation_score"],right["fossil_allocation_score"])
        self.assertNotEqual(left["fuels"]["gas"]["domestic_cost_per_mwh"],right["fuels"]["gas"]["domestic_cost_per_mwh"])

    def test_hydro_construction_response_limits_actual_approvals(self):
        theta={**self.theta,"hydro_construction_response":.5}
        m=NationalModel(self.data,self.design,theta,2024)
        baseline=self.model(2024)
        for model in (m,baseline):model.drivers();model.mature()
        g=m.generators["hydro"]
        self.assertAlmostEqual(g.construction_limit(),baseline.generators["hydro"].construction_limit()*.5)
        m.gdp_cny=1e20;g.cash=1e18;g.margin=1e10
        proposal=g.proposal(1e10);proposal["amount"]=1e20
        m.government.approve([proposal],[])
        self.assertAlmostEqual(sum(p["capacity_mw"] for p in m.projects if not p["initial_reconstruction"] and p["tech"]=="hydro"),g.construction_limit())

    def test_generation_and_capacity_losses_cannot_hide_technology_mix(self):
        d=self.design
        generation=[t for t in d["targets"] if t["metric"].endswith("_generation_mwh")]
        capacity=[t for t in d["targets"] if t["metric"].endswith("_capacity_mw")]
        self.assertEqual(len(generation),9);self.assertEqual(len(capacity),5)
        self.assertAlmostEqual(sum(t["weight"] for t in generation),1)
        self.assertAlmostEqual(sum(t["weight"] for t in capacity),1)

    def test_independent_scenarios_match_serial_and_preserve_order(self):
        from concurrent.futures import ProcessPoolExecutor
        from run_q2_national import scenario_trial
        import os
        for key in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS"):os.environ[key]="1"
        theta=self.design["calibration_search"]["initial_parameters"]
        settings=[("probe","base",{},theta,self.data,self.design),
                  ("probe","shock",{"carbon_price_multiplier":1.5},theta,self.data,self.design)]
        serial=[scenario_trial(p) for p in settings]
        with ProcessPoolExecutor(max_workers=2) as pool:
            parallel=list(pool.map(scenario_trial,settings,chunksize=1))
        self.assertEqual(serial,parallel)
        self.assertEqual([r["label"] for r in parallel],["base","shock"])
        self.assertTrue(all(r["status"]=="success" for r in parallel))

if __name__=="__main__":unittest.main()
