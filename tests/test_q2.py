"""Q2 mechanisms and failure semantics; fixtures never create real-data approval."""
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
sys.path.insert(0,str(ROOT/"scripts"))
AVAILABLE = all(importlib.util.find_spec(name) for name in ("mesa","scipy"))
if AVAILABLE:
    from energy_model.q2_operations import operate,Q2Error
    from energy_model.q2_agents import simulate,AnnualModel
    from energy_model.q2_experiments import calibrate,losses,peak_check,validate_model,validate_design
from run_q2 import preflight,within


def small_operation():
    return dict(periods=[dict(hours=1),dict(hours=1)],annual_repeats=1,cyclic=False,
        grid=dict(efficiency=1,power_mw=100),
        storage=dict(power_mw=5,energy_mwh=5,initial_mwh=5,terminal_mwh=0,
                     charge_efficiency=1,discharge_efficiency=1,throughput_cost=.01),
        fuels=dict(gas=dict(domestic_mw=[5,0],import_mw=[0,0],domestic_cost_per_mwh=10,
            import_cost_per_mwh=20,emission_t_per_mwh=.2,tank_mwh=0,initial_mwh=0,injection_mw=0,withdrawal_mw=0)),
        plants=dict(gas=dict(input="gas",output="electricity",efficiency=1,capacity_mw=5,availability=[1,1],
            variable_cost_per_mwh=0,minimum_fraction=0,ramp_mw_per_hour=100,window_energy_budget_mwh=100)),
        demands=dict(load=dict(sector="building",carrier="electricity",efficiency=1,input_capacity_mw=100,
                              priority=0,service_mwh=[5,5])))


@unittest.skipUnless(AVAILABLE,"Install requirements-q2.txt to run the Q2 model tests")
class OperationTests(unittest.TestCase):
    def test_save_battery_for_future_unavailable_fuel(self):
        r = operate(small_operation())
        self.assertAlmostEqual(r["storage"][0]["discharge_mwh"],0)
        self.assertAlmostEqual(r["storage"][1]["discharge_mwh"],5)
        self.assertAlmostEqual(sum(d["unmet_service_mwh"] for d in r["demand"]),0)
        self.assertLess(r["max_residual"],1e-7)

    def test_shared_fuel_priority_is_lexicographic(self):
        c = small_operation()
        c["storage"].update(initial_mwh=0,energy_mwh=0,power_mw=0)
        c["fuels"]["gas"]["domestic_mw"] = [5,5]
        c["demands"]["load"]["priority"] = 1
        c["demands"]["direct"] = dict(sector="critical",carrier="gas",efficiency=1,input_capacity_mw=100,priority=0,service_mwh=[4,4])
        r = operate(c)
        self.assertAlmostEqual(sum(x["unmet_service_mwh"] for x in r["demand"] if x["device"] == "direct"),0)
        self.assertAlmostEqual(sum(x["unmet_service_mwh"] for x in r["demand"] if x["device"] == "load"),8)
        self.assertAlmostEqual(sum(x["direct_mwh"]+x["conversion_mwh"] for x in r["fuel"]),10)

    def test_efficiency_and_mw_hours_applied_once(self):
        c = small_operation()
        c["periods"] = [dict(hours=2),dict(hours=2)]
        c["storage"].update(initial_mwh=0,energy_mwh=0,power_mw=0)
        c["plants"]["gas"]["efficiency"] = .5
        c["fuels"]["gas"]["domestic_mw"] = [5,5]
        r = operate(c)
        self.assertAlmostEqual(sum(x["output_mwh"] for x in r["generation"]),10)
        self.assertAlmostEqual(sum(x["conversion_mwh"] for x in r["fuel"]),20)
        self.assertAlmostEqual(sum(x["combustion_co2_t"] for x in r["fuel"]),4)

    def test_representative_weight_does_not_multiply_soc(self):
        c = small_operation()
        c["cyclic"] = True
        c["fuels"]["gas"]["domestic_mw"] = [5,5]
        a = operate(c)
        c["annual_repeats"] = 365
        b = operate(c)
        self.assertEqual(a["storage"],b["storage"])
        self.assertAlmostEqual(b["resource_cost"],365*a["resource_cost"])
        self.assertAlmostEqual(b["storage"][-1]["closing_mwh"],5)

    def test_noncyclic_repetition_rejected(self):
        c = small_operation();c["annual_repeats"] = 2
        with self.assertRaises(Q2Error):operate(c)

    def test_fuel_inventory_not_replenished_each_period(self):
        c = small_operation();c["storage"].update(initial_mwh=0,energy_mwh=0,power_mw=0)
        c["fuels"]["gas"].update(domestic_mw=[0,0],tank_mwh=5,initial_mwh=5,withdrawal_mw=5)
        r = operate(c)
        self.assertAlmostEqual(sum(x["conversion_mwh"] for x in r["fuel"]),5)
        self.assertAlmostEqual(sum(x["unmet_service_mwh"] for x in r["demand"]),5)

    def test_infeasible_must_run_not_zero_shortage(self):
        c = small_operation();c["plants"]["gas"]["minimum_fraction"] = 1
        c["demands"]["load"]["service_mwh"] = [0,0]
        c["storage"].update(initial_mwh=0,energy_mwh=0,power_mw=0)
        with self.assertRaises(Q2Error) as caught:operate(c)
        self.assertEqual(caught.exception.status,"infeasible")

    def test_solver_error_separate_from_infeasible(self):
        def bad(*args,**kwargs):return SimpleNamespace(success=False,status=4,message="injected numerical error")
        with self.assertRaises(Q2Error) as caught:operate(small_operation(),solver=bad)
        self.assertEqual(caught.exception.status,"solver_failure")

    def test_missing_inputs_do_not_default_zero(self):
        c = small_operation();del c["fuels"]["gas"]["withdrawal_mw"]
        with self.assertRaises(KeyError):operate(c)

    def test_nan_input_rejected(self):
        c = small_operation();c["grid"]["efficiency"] = float("nan")
        with self.assertRaises(Q2Error):operate(c)


@unittest.skipUnless(AVAILABLE,"Install requirements-q2.txt to run the Q2 model tests")
class AnnualTests(unittest.TestCase):
    def setUp(self):
        self.config = json.loads((ROOT/"examples/q2/history_model.json").read_text(encoding="utf-8"))
        self.theta = dict(activity_elasticity=1,investment_rate=.5,replacement_rate=.5,expectation_rate=.5)

    def test_projects_do_not_commission_at_decision(self):
        m = simulate(self.config,self.theta,2018)
        self.assertTrue(m.projects)
        for p in m.projects:
            self.assertGreater(p["online_year"],p["decision_year"])
            if p["kind"] == "plant":
                before = [r for r in m.asset_log if r["id"] == p["id"] and r["year"] < p["online_year"]]
                self.assertFalse(before)

    def test_staged_construction_spends_once(self):
        m = simulate(self.config,self.theta,2019)
        for p in m.projects:
            paid = sum(r["resource_cost"] for r in m.accounts if r.get("project") == p["id"])
            self.assertAlmostEqual(paid+p["remaining"],p["cost"],places=6)
        for a in m.agents:
            reserved = sum(p["remaining"] for p in m.projects if p["actor"] == a.name)
            self.assertAlmostEqual(a.reserved,reserved,places=6)

    def test_cash_transfer_resource_accounts_close(self):
        m = simulate(self.config,self.theta,2018)
        for p in m.paths:
            rows = [r for r in m.accounts if r["year"] == p["year"]]
            self.assertAlmostEqual(sum(r["transfer"] for r in rows),0,places=6)
            self.assertAlmostEqual(sum(r["resource_cost"] for r in rows),p["resource_cost"],places=6)
            self.assertAlmostEqual(sum(r["cash_delta"]-r.get("income",0)+r["resource_cost"] for r in rows),0,places=6)

    def test_future_information_cannot_rewrite_history(self):
        base = simulate(self.config,self.theta,2021)
        c = deepcopy(self.config)
        c["drivers"]["2030"]["carbon_price"] = 1000000
        c["drivers"]["2030"]["gdp_index"] = 1000000
        c["policies"].append(dict(id="future",published_year=2028,effective_year=2030,
            basis="future synthetic test",coverage={n:0 for n in c["generators"]}))
        other = simulate(c,self.theta,2021)
        self.assertEqual(base.paths,other.paths)
        self.assertEqual(base.behavior,other.behavior)

    def test_permanent_retirement_never_reverses(self):
        self.config["initial_cohorts"][0].update(retirement_year=2017,legal_exit_year=2017)
        m = simulate(self.config,self.theta,2020)
        name = self.config["initial_cohorts"][0]["id"]
        retired = [r for r in m.asset_log if r["id"] == name and r["year"] >= 2017]
        self.assertTrue(retired)
        self.assertTrue(all(r["status"] == "retired" for r in retired))

    def test_order_independence_and_mechanism_counterexample(self):
        a = simulate(self.config,self.theta,2024)
        c = deepcopy(self.config)
        for key in ("generators","consumers","suppliers"):
            c[key] = dict(reversed(list(c[key].items())))
        b = simulate(c,self.theta,2024)
        frozen = simulate(c,self.theta,2024,investment=False,substitution=False)
        self.assertEqual(a.paths,b.paths)
        self.assertNotEqual(a.paths,frozen.paths)

    def test_reserved_cash_not_overcommitted(self):
        m = simulate(self.config,self.theta,2020)
        for a in m.agents:self.assertGreaterEqual(a.cash+1e-6,a.reserved)

    def test_mesa_registers_real_actors(self):
        m = AnnualModel(self.config,self.theta)
        self.assertEqual(len(m.agents),len(m.suppliers)+len(m.generators)+len(m.consumers)+2)

    def test_process_hash_seed_does_not_change_results(self):
        program = """import sys,json,hashlib
from pathlib import Path
sys.path.insert(0,'src')
from energy_model.q2_agents import simulate
c=json.loads(Path('examples/q2/history_model.json').read_text())
m=simulate(c,dict(activity_elasticity=1,investment_rate=.5,replacement_rate=.5,expectation_rate=.5),2024)
print(hashlib.sha256(json.dumps([m.paths,m.balance_log,m.stage_log],sort_keys=True).encode()).hexdigest())
"""
        hashes = []
        for seed in ("1","71"):
            env = {**os.environ,"PYTHONHASHSEED":seed}
            hashes.append(subprocess.check_output([sys.executable,"-B","-X","utf8","-c",program],cwd=ROOT,env=env,text=True).strip())
        self.assertEqual(hashes[0],hashes[1])

    def test_national_cannot_be_claimed_by_relabeling_fixture(self):
        self.config["scope"] = "China_mainland_conditional"
        with self.assertRaises(Q2Error):validate_model(self.config)


@unittest.skipUnless(AVAILABLE,"Install requirements-q2.txt to run the Q2 model tests")
class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.c = json.loads((ROOT/"examples/q2/history_model.json").read_text(encoding="utf-8"))
        self.d = json.loads((ROOT/"examples/q2/design.json").read_text(encoding="utf-8"))
        self.o = json.loads((ROOT/"examples/q2/observations.json").read_text(encoding="utf-8"))

    def test_multi_target_mean_by_actual_coverage(self):
        d = deepcopy(self.d);d["targets"] = [dict(metric="x",scale=2,weight=.5)]
        obs = [dict(year=2015,metric="x",value=2,source_ref="fixture"),dict(year=2017,metric="x",value=6,source_ref="fixture")]
        value,parts,_ = losses([dict(year=2015,x=4),dict(year=2017,x=6)],obs,d,[2015,2016,2017])
        self.assertAlmostEqual(value,.25)
        self.assertEqual(parts[0]["missing_years"],[2016])

    def test_holdout_cannot_select_parameters(self):
        # Restrict the declared engineering search to two candidates to keep test cheap.
        self.d["parameter_grid"].update(investment_rate=[.5],replacement_rate=[.5],activity_elasticity=[.9,1])
        self.d["search_budget"] = 2
        a,_ = calibrate(self.c,self.o,self.d)
        other = deepcopy(self.o)
        for r in other:
            if r["year"] >= 2022:r["value"] *= 2
        b,_ = calibrate(self.c,other,self.d)
        self.assertEqual(a["best"],b["best"])
        self.assertNotEqual(a["quality"]["already_seen_evaluation"],b["quality"]["already_seen_evaluation"])

    def test_design_cannot_omit_emissions_or_change_budget(self):
        self.d["targets"] = [t for t in self.d["targets"] if t["family"] != "emissions"]
        with self.assertRaises(Q2Error):validate_design(self.d)

    def test_endpoint_plateau_and_rebound_not_early_peak(self):
        def series(values):return [dict(year=2020+i,positive_co2_t=v) for i,v in enumerate(values)]
        self.assertEqual(peak_check(series([1,2,3]),2)["status"],"not_confirmed")
        self.assertIsNone(peak_check(series([3,3,3,3]),2)["year"])
        self.assertEqual(peak_check(series([3,2,1,4,3]),2)["status"],"not_confirmed")
        self.assertEqual(peak_check(series([5,3,4,2]),2)["status"],"not_confirmed")
        self.assertEqual(peak_check(series([3,2,1]),2)["year"],2020)


class ContractTests(unittest.TestCase):
    def test_fingerprint_mismatch(self):
        c = json.loads((ROOT/"examples/q2/config.json").read_text(encoding="utf-8"))
        c["inputs"][0]["sha256"] = "0"*64
        with self.assertRaises(ValueError):preflight(c)

    def test_unapproved_use(self):
        c = json.loads((ROOT/"examples/q2/config.json").read_text(encoding="utf-8"))
        c["inputs"][0]["allowed_use"] = "national_ABM"
        with self.assertRaises(ValueError):preflight(c)

    def test_restricted_and_escape_paths_rejected(self):
        for path in ("data/restricted/x","../outside"):
            with self.assertRaises(ValueError):within(path)


if __name__ == "__main__":unittest.main()
