"""Adversarial tests for Q3 timing, finance, information and policy selection."""
from copy import deepcopy
from math import fsum
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"));sys.path.insert(0,str(ROOT/"scripts"))
from run_q3 import preflight
from q3_campaign import screen, h01_cells, validate_protocol, digest
from energy_model.q3_transition import TransitionModel, schedule_retirements, service_totals
from energy_model.q2_operations import Q2Error


class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c,_,cls.data,cls.design,cls.theta=preflight(ROOT/"workflow/q3_inputs_v5.json")

    def model(self, **kwargs):
        defaults=dict(vR=.01,vE=.6,delay=0,rule="fixed_schedule")
        defaults.update(kwargs)
        return TransitionModel(self.data,self.design,self.theta,deepcopy(self.c),**defaults)

    def test_cohort_split_conserves_initial_capacity_and_annual_authorisation(self):
        model=self.model()
        coal=[c for c in model.cohorts if c["tech"]=="coal" and c["status"]=="active"]
        self.assertAlmostEqual(fsum(c["capacity_mw"] for c in coal),model.initial_capacities["coal"],places=6)
        for year in range(2025,2061):
            scheduled=[c for c in coal if c["scheduled_exit_year"]==year and c["scheduled_exit_year"]<c["technical_exit_year"]]
            self.assertLessEqual(fsum(c["capacity_mw"] for c in scheduled),model.initial_capacities["coal"]*.01+1e-6)
            for c in scheduled:self.assertLessEqual(c["technical_exit_year"]-year,5)

    def test_fuel_material_services_are_not_aggregated(self):
        rows=[dict(sector="nonenergy_feedstock",carrier=f,requested_service_mwh=10,unmet_service_mwh=u) for f,u in (("coal",0),("gas",10))]
        metrics=service_totals(rows)
        self.assertEqual(len(metrics),2)
        self.assertEqual(max(r["unmet_fraction"] for r in metrics),1.)

    def test_two_grids_are_not_full_factorial_or_duplicates(self):
        cells=h01_cells(self.c["transition"])
        self.assertEqual(len(cells),6)
        self.assertTrue(all(r["vR"]==.01 or r["vE"]==.6 for r in cells))

    def test_new_asset_needs_funding_and_positive_construction_time(self):
        model=self.model(actions=("gas_release",))
        model.step()
        project=model.policy_queue[0]
        self.assertEqual(project["kind"],"gas_release")
        self.assertEqual(project["online"],2027)
        self.assertGreater(project["remaining"],0)
        self.assertEqual(model.policy_gas_power,0)
        original=model.last_operation["fuels"]["gas"]
        model.step();model.step()
        self.assertGreater(model.policy_gas_power,0)
        gas=model.last_operation["fuels"]["gas"]
        self.assertEqual(gas["tank_mwh"],original["tank_mwh"])
        self.assertAlmostEqual(gas["initial_mwh"],original["initial_mwh"],places=4)
        self.assertAlmostEqual(model.public_escrow,fsum(p["remaining"] for p in model.policy_queue),places=4)
        self.assertTrue(all(r["public_payment_cny"]+r["recipient_receipt_cny"]==0 for r in model.public_ledger))

    def test_unpaid_project_cannot_commission(self):
        model=self.model(actions=("storage",))
        model.step()
        self.assertTrue(model.policy_queue)
        p=model.policy_queue[0]
        p["online"]=model.year;p["remaining"]=100.
        with self.assertRaises(Q2Error) as error:model.step()
        self.assertEqual(error.exception.status,"accounting_failure")

    def test_extra_delay_never_adds_devices_or_generation_immediately(self):
        a,b=self.model(delay=0),self.model(delay=3)
        a.step();b.step()
        for key in ("total_capacity_mw","storage_power_mw","grid_power_mw"):
            self.assertEqual(a.paths[0][key],b.paths[0][key])
        self.assertEqual(a.consumers["coal"].queue,b.consumers["coal"].queue)
        self.assertEqual(b.a["storage_lead_years"]-a.a["storage_lead_years"],3)

    def test_fixed_comparator_reproduces_project_set(self):
        reference=self.model();reference.run(2027)
        plan=reference.export_plan()
        replay=self.model(fixed_plan=plan);replay.run(2027)
        self.assertEqual(digest(plan),digest(replay.export_plan()))
        for a,b in zip(reference.paths,replay.paths):
            self.assertAlmostEqual(a["combustion_co2_t"],b["combustion_co2_t"],delta=.001)
            self.assertAlmostEqual(a["resource_cost_cny"],b["resource_cost_cny"],delta=.1)

    def test_fixed_project_cash_failure_is_not_silently_resized(self):
        reference=self.model();reference.run(2025)
        plan=reference.export_plan()
        replay=self.model(fixed_plan=plan)
        # A finite but impossible commitment; do not award missing capital.
        p=plan["2025"]["generation"][0]
        replay.fixed_plan["2025"]["generation"][0]["cost"]*=1e6
        with self.assertRaises(Q2Error) as error:replay.step()
        self.assertEqual(error.exception.status,"fixed_schedule_infeasible")

    def test_forecast_never_uses_unrevealed_fixed_applications(self):
        a=self.model(rule="anticipatory",fixed_plan={})
        b=self.model(rule="anticipatory",fixed_plan={"2050":{"generation":[{"fake_future":True}]}})
        a.step();b.step()
        self.assertEqual(a.forecasts,b.forecasts)
        self.assertEqual(a.decisions,b.decisions)
        self.assertEqual(a.paths,b.paths)

    def test_retirement_cannot_be_deferred_past_experiment_deadline(self):
        model=self.model(rule="service_ready",epsilon=0)
        model.q3["end_year"]=2025
        model.step()
        due=[c for c in model.cohorts if c.get("scheduled_exit_year",c["exit_year"])<=2025<c["exit_year"]]
        self.assertTrue(due)
        self.assertTrue(all(c["status"]=="retired" for c in due))
        self.assertEqual(model.retention_cost,0)

    def test_safe_current_service_does_not_override_known_future_shortage(self):
        model=self.model(rule="anticipatory",epsilon=.01)
        original=model.planning_operation
        def missing_future_power(lead):
            op=original(lead)
            for plant in op["plants"].values():
                plant.update(capacity_mw=0.,ramp_mw_per_hour=0.,window_energy_budget_mwh=0.)
            op["storage"]["power_mw"]=0.
            return op
        with patch.object(model,"planning_operation",side_effect=missing_future_power):model.step()
        self.assertEqual(max(r["unmet_fraction"] for r in model.annual_services),0.)
        self.assertTrue(model.decisions)
        self.assertTrue(all(r["decision"]=="retain_within_technical_life" for r in model.decisions))
        self.assertTrue(all(r["forecast_worst_shortage"]>.01 for r in model.decisions))
        self.assertGreater(model.retention_cost,0.)

    def test_public_and_base_infrastructure_share_construction_limit(self):
        model=self.model(actions=("grid","storage"));model.run(2028)
        for year in range(2025,2029):
            gdp=next(p["gdp_index"] for p in model.paths if p["year"]==year)
            for kind in ("grid","storage"):
                actual=fsum(p["power"] for p in model.grid.queue+model.policy_queue if p["kind"]==kind and p["decision"]==year)
                limit=model.a[kind+"_build_fraction"]*model.grid.initial_power*gdp
                self.assertLessEqual(actual,limit+1e-6)

    def test_maintenance_has_same_public_budget_and_cannot_be_free(self):
        model=self.model(actions=("gas_release",))
        model.run(2026)
        model.spec["public_budget_fraction_gdp"]=0
        with self.assertRaises(Q2Error) as error:model.step()
        self.assertEqual(error.exception.status,"budget_failure")

    def test_paid_devices_beyond_terminal_date_are_construction_assets(self):
        model=self.model();model.step()
        model.q3["end_year"]=2025
        paid_devices=fsum(p["paid_cost_cny"] for c in model.consumers.values() for p in c.queue if p["online"]>2025)
        self.assertGreater(paid_devices,0)
        other=fsum(p["cost"]-p["remaining"] for p in model.projects if p["status"]=="construction")
        other+=fsum(p["cost"]-p["remaining"] for p in model.grid.queue+model.policy_queue if p["online"]>2025)
        terminal=model.terminal_accounts()
        self.assertAlmostEqual(terminal["terminal_paid_construction_value_cny"],other+paid_devices,delta=.01)
        self.assertEqual(terminal["terminal_paid_device_value_cny"],paid_devices)

    def test_invalid_grid_values_rejected(self):
        for key,value in (("vR",[-.1]),("delay_years",[.5]),("gas_release_lead_years",0)):
            config=deepcopy(self.c);config["transition"][key]=value
            with self.assertRaises(Q2Error):validate_protocol(config)


class ScreeningTests(unittest.TestCase):
    def rows(self):
        baseline=dict(policy_id="none",status="completed",cumulative_combustion_co2_t=100.,discounted_resource_cost_cny=100.,
                      net_resource_cost_cny=90.,worst_annual_service_fraction=.02,worst_selection_service_fraction=.02)
        return [baseline,{**baseline,"policy_id":"storage","discounted_resource_cost_cny":200.,"worst_selection_service_fraction":0.,"worst_annual_service_fraction":0.}]

    def test_no_feasible_solution_does_not_relax_constraints(self):
        result=screen(self.rows(),dict(carbon_limit_ratio=1,gross_cost_limit_ratio=1.05,service_limit=.01))
        self.assertIsNone(result["selected"])
        self.assertEqual(result["reason"],"no_feasible_candidate")
        self.assertEqual(result["records"][0]["violations"],"service")
        self.assertEqual(result["records"][1]["violations"],"cost")

    def test_failed_simulation_cannot_beat_working_policy(self):
        rows=self.rows();rows[0]["worst_annual_service_fraction"]=0;rows[0]["worst_selection_service_fraction"]=0
        rows[1]={"policy_id":"storage","status":"failed"}
        result=screen(rows,dict(carbon_limit_ratio=1,gross_cost_limit_ratio=1.05,service_limit=.01))
        self.assertEqual(result["selected"],"none")

    def test_test_values_cannot_change_selection(self):
        rows=self.rows()
        policy=dict(carbon_limit_ratio=1,gross_cost_limit_ratio=3,service_limit=.03)
        first=screen(rows,policy)
        for r in rows:r["worst_test_service_fraction"]=100 if r["policy_id"]==first["selected"] else 0
        self.assertEqual(first,screen(rows,policy))


if __name__=="__main__":unittest.main()
