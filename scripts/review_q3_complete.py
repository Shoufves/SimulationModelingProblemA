"""Independent checks from exported ledgers, plus optional fresh full reproduction.

This audit does not call the model's accounting or screening helpers to validate
their own outputs. It cannot confer team approval or empirical validity.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import csv
import gzip
import hashlib
import json
from math import fsum,isclose,sqrt
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from run_q3 import verify_latest
from q3_scientific_equivalence import compare_runs


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text(encoding="utf-8-sig"))
def unpack(p):return json.loads(gzip.decompress(Path(p).read_bytes()))
def csv_read(p):
    with Path(p).open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))
def save(p,value):Path(p).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
def close(a,b,label,absolute=.001,relative=1e-10):
    if not isclose(a,b,abs_tol=absolute,rel_tol=relative):raise ValueError(f"{label}: {a} != {b}")
def service(r):return r["sector"]+("/"+r["carrier"] if r["sector"]=="nonenergy_feedstock" else "")


def verify_flows(rows,period_hours,efficiency,grid_efficiency,opening=None):
    """Fuel/stock/SOC/electricity/service/combustion identities, original units."""
    grouped=defaultdict(list)
    for r in rows:grouped[int(r["period"])].append(r)
    fuels=sorted({r["fuel"] for r in rows if r["kind"]=="fuel"})
    previous = ({f:[r for r in rows if r["kind"]=="fuel" and r["fuel"]==f][-1]["closing_mwh"] for f in fuels}
                if opening is None else {f:opening["fuels"][f]["initial_mwh"] for f in fuels})
    previous_soc=None if opening is None else opening["storage"]["initial_mwh"]
    ef=dict(coal=.34056,oil=.26388,gas=.20196,biomass=0.)
    for i,part in sorted(grouped.items()):
        battery=next(r for r in part if r["kind"]=="storage")
        if previous_soc is not None:close(battery["opening_mwh"],previous_soc,"SOC continuity")
        close(battery["closing_mwh"],battery["opening_mwh"]+battery["charge_mwh"]*efficiency-battery["discharge_mwh"]/efficiency,"SOC state")
        previous_soc=battery["closing_mwh"]
        electric=fsum(r["output_mwh"] for r in part if r["kind"]=="generation" and r["output"]=="electricity")
        electric+=battery["discharge_mwh"]-battery["charge_mwh"]
        electric-=fsum(r["input_mwh"]/grid_efficiency for r in part if r["kind"]=="demand" and r["carrier"]=="electricity")
        close(electric,0,"electric conservation")
        for r in part:
            if r["kind"]=="fuel":
                fuel=r["fuel"]
                close(r["closing_mwh"],previous[fuel]+r["fill_mwh"]-r["withdrawal_mwh"],"fuel stock")
                close(r["domestic_mwh"]+r["import_mwh"]+r["withdrawal_mwh"]-r["fill_mwh"],r["direct_mwh"]+r["conversion_mwh"],"fuel flow")
                material=fsum(d["input_mwh"] for d in part if d["kind"]=="demand" and d["sector"]=="nonenergy_feedstock" and d["carrier"]==fuel)
                close(r["combustion_co2_t"],(r["direct_mwh"]+r["conversion_mwh"]-material)*ef[fuel],"combustion")
                previous[fuel]=r["closing_mwh"]
            if r["kind"]=="demand":close(r["served_service_mwh"]+r["unmet_service_mwh"],r["requested_service_mwh"],"service conservation")
    if opening is not None:
        for f in fuels:close(previous[f],opening["fuels"][f]["initial_mwh"],"restored fuel boundary")
        close(previous_soc,opening["storage"]["initial_mwh"],"restored SOC boundary")
    return len(grouped)


def audit_case(evidence,config,design):
    if evidence["outcome"]["status"]!="completed":return dict(status="failed_record_preserved")
    paths=evidence["paths"]
    if [p["year"] for p in paths]!=list(range(2025,2061)):raise ValueError("Incomplete annual horizon")
    by_year=defaultdict(list)
    for r in evidence["operations"]:by_year[r["year"]].append(r)
    r=design["assumptions"]["discount_rate"]
    efficiency=sqrt(design["assumptions"]["storage_roundtrip_efficiency"])
    public_fraction=config["transition"]["public_budget_fraction_gdp"]
    if evidence["label"].get("parameter")=="transition.public_budget_fraction_gdp":public_fraction*=evidence["label"]["multiplier"]
    total_emissions,total_cost=0.,0.
    for p in paths:
        year=p["year"]
        rows=by_year[year]
        periods=verify_flows(rows,[6]*4,efficiency,design["assumptions"]["grid_efficiency"])
        if periods!=4:raise ValueError("Wrong annual period count")
        emission=fsum(z["combustion_co2_t"] for z in rows if z["kind"]=="fuel")*365
        close(emission,p["combustion_co2_t"],"annual emission",absolute=.01)
        finance=[z for z in evidence["finance"] if z["year"]==year]
        public=[z for z in evidence["public_ledger"] if z["year"]==year]
        cost=fsum(z.get("resource_cost_cny",0) for z in finance)+fsum(z["resource_cost_cny"] for z in public)
        close(cost,p["resource_cost_cny"],"resource costs (no transfer double count)",absolute=.1)
        appropriation=fsum(z["appropriation_cny"] for z in public)
        expected_budget=p["gdp_index"]*design["assumptions"]["gdp_2024_price_level_cny"]*public_fraction
        close(p["public_budget_cny"],expected_budget,"frozen GDP budget envelope",absolute=.01)
        close(appropriation,p["public_appropriation_cny"],"public commitment",absolute=.01)
        if appropriation>p["public_budget_cny"]+.01:raise ValueError("Public ceiling exceeded")
        close(fsum(z["public_payment_cny"]+z["recipient_receipt_cny"] for z in public),0,"public counterpart",absolute=.01)
        close(fsum(z.get("ets_transfer_cny",0) for z in finance),0,"ETS counterpart",absolute=.01)
        for key in ("infrastructure_fund_residual_cny","construction_fund_residual_cny","public_escrow_residual_cny"):
            close(p[key],0,key,absolute=.01)
        sectors=defaultdict(lambda:[0.,0.])
        for d in rows:
            if d["kind"]=="demand":
                sectors[service(d)][0]+=d["requested_service_mwh"]*365
                sectors[service(d)][1]+=d["unmet_service_mwh"]*365
        for metric in [z for z in evidence["annual_services"] if z["year"]==year]:
            requested,unmet=sectors[metric["sector"]]
            close(metric["requested_service_mwh"],requested,"annual requested")
            close(metric["unmet_service_mwh"],unmet,"annual unmet")
            close(metric["unmet_fraction"],unmet/requested if requested else 0.,"annual shortage ratio",absolute=1e-10)
        total_emissions+=emission
        total_cost+=cost/(1+r)**(year-2024)
    terminal=evidence["terminal_accounts"]
    close(terminal["cumulative_combustion_co2_t"],total_emissions,"cumulative emission",absolute=.01)
    close(terminal["discounted_resource_cost_cny"],total_cost,"discounted cost",absolute=.1)
    parts=["terminal_generation_value_cny","terminal_device_value_cny","terminal_grid_value_cny","terminal_storage_value_cny","terminal_gas_release_value_cny","terminal_paid_construction_value_cny"]
    residual=lambda cost,online,exit:cost*max(0,min(1,(exit-2060)/(exit-online)))
    a=design["assumptions"]
    physical=[
        fsum(residual(c["capacity_mw"]*c["book_cost_cny_per_mw"],c["online_year"],c["exit_year"]) for c in evidence["terminal_cohorts"] if c["status"]=="active"),
        fsum(residual(c["capacity"]*a["device_capex_cny_per_service_mw"],c["online"],c["exit"]) for stock in evidence["terminal_device_cohorts"].values() for c in stock if c["status"]=="active"),
        fsum(residual(c["power"]*a["grid_capex_cny_per_mw"],c["online"],c["exit"]) for c in evidence["terminal_grid"] if c["online"]<=2060<c["exit"]),
        fsum(residual(c["energy"]*a["storage_capex_cny_per_mwh"],c["online"],c["exit"]) for c in evidence["terminal_storage"] if c["online"]<=2060<c["exit"]),
        fsum(residual(p["cost"],p["online"],p["exit"]) for p in evidence["policy_projects"] if p["kind"]=="gas_release" and p["online"]<=2060<p["exit"]),
        fsum(p["cost"]-p["remaining"] for p in evidence["projects"] if p["status"]=="construction")+
        fsum(p["cost"]-p["remaining"] for p in evidence["infrastructure"]+evidence["policy_projects"] if p["online"]>2060)+
        fsum(p["paid_cost_cny"] for queue in evidence["devices"].values() for p in queue if p["online"]>2060)]
    for key,value in zip(parts,physical):close(terminal[key],value,"independent "+key,absolute=.1)
    close(fsum(terminal[k] for k in parts),terminal["terminal_asset_value_cny"],"terminal components",absolute=.1)
    close(total_cost-terminal["terminal_asset_value_cny"]/(1+r)**36,terminal["net_resource_cost_cny"],"net asset-adjusted cost",absolute=.1)
    for c in evidence["terminal_cohorts"]:
        if c["status"]=="active" and c.get("scheduled_exit_year",c["exit_year"])<=2060:
            raise ValueError("Deferred retirement crossed terminal deadline")
        if c["status"]=="active" and c["exit_year"]<=2060:raise ValueError("Technical life exceeded")
    for p in evidence["policy_projects"]:
        if p["online"]<=p["decision"] or p["exit"]<=p["online"]:raise ValueError("Instant or invalid project lifetime")
        payments=fsum(z["resource_cost_cny"] for z in evidence["public_ledger"] if z["project"]==p["id"] and z["kind"]=="public_construction")
        close(payments+p["remaining"],p["cost"],"public project funded cost",absolute=.01)
        if p["online"]<=2060 and p["remaining"]>.01:raise ValueError("Unpaid commissioned policy asset")
        early=[z for z in evidence["public_ledger"] if z["project"]==p["id"] and z["kind"]=="public_construction" and z["year"]>=p["online"]]
        if early:raise ValueError("Construction paid after commissioning")
    return dict(status="passed",years=len(paths),operations=len(evidence["operations"]),projects=len(evidence["projects"])+len(evidence["policy_projects"]))


def audit_events(folder,config,cases):
    metrics={(r["id"],r["event"],int(r["year"]),r["scenario"],r["sector"]):r for r in csv_read(folder/"transition_event_metrics.csv")}
    checked=0
    for path in sorted((folder/"events").glob("*.json.gz")):
        batch=unpack(path)
        if isinstance(batch,dict):raise ValueError("Failed event file: "+path.name)
        caseid=path.name.rsplit("-",1)[0]
        grouped=defaultdict(list)
        for event in batch:grouped[(event["event"],event["year"])].append(event)
        for (_,year),events in grouped.items():
            snapshot=cases[caseid]["snapshots"][str(year)]
            service_signature=None
            for event in events:
                rows=[dict(kind=kind,**r) for kind in ("fuel","storage","generation","demand") for r in event["result"][kind]]
                op=event["operation"]
                verify_flows(rows,[p["hours"] for p in op["periods"]],op["storage"]["charge_efficiency"],op["grid"]["efficiency"],snapshot)
                signature=[(r["period"],r["device"],r["requested_service_mwh"]) for r in event["result"]["demand"]]
                if service_signature is not None and signature!=service_signature:raise ValueError("Paired service requests changed")
                service_signature=signature
                requested,unmet=defaultdict(float),defaultdict(float)
                for row in event["result"]["demand"]:
                    requested[service(row)]+=row["requested_service_mwh"]
                    unmet[service(row)]+=row["unmet_service_mwh"]
                for sector,total in requested.items():
                    m=metrics[(caseid,event["event"],year,event["scenario"],sector)]
                    close(float(m["requested_service_mwh"]),total,"event requested")
                    close(float(m["unmet_service_mwh"]),unmet[sector],"event unmet")
                    close(float(m["unmet_fraction"]) if m["unmet_fraction"] else 0,unmet[sector]/total if total else 0,"event shortage fraction",absolute=1e-10)
                checked+=1
    return dict(event_cases=checked,per_service_rows=len(metrics))


def audit_h02(folder,config):
    snapshot=load(folder/"event_initial_state.json")
    raw=csv_read(folder/"event_operations.csv")
    groups=defaultdict(list)
    for row in raw:
        for key,value in list(row.items()):
            if value and (key.endswith("_mwh") or key in ("period","start_hour","end_hour","combustion_co2_t")):
                row[key]=float(value)
        groups[row["event"],row["response"],row["scenario"]].append(row)
    if len(groups)!=len(config["events"])*8:raise ValueError("H02 paired case count")
    totals={}
    metrics={(r["event"],r["response"],r["scenario"],r["sector"]):r for r in csv_read(folder/"safety_metrics.csv")}
    for key,rows in groups.items():
        event=next(e for e in config["events"] if e["id"]==key[0])
        count=verify_flows(rows,[6]*event["window_days"]*4,snapshot["storage"]["charge_efficiency"],snapshot["grid"]["efficiency"],snapshot)
        if count!=event["window_days"]*4:raise ValueError("H02 event duration")
        sectors=defaultdict(list)
        for r in rows:
            if r["kind"]=="demand":sectors[service(r)].append(r)
        for sector,demand in sectors.items():
            m=metrics[(*key,sector)]
            requested=fsum(d["requested_service_mwh"] for d in demand)
            unmet=fsum(d["unmet_service_mwh"] for d in demand)
            close(float(m["unmet_service_mwh"]),unmet,"H02 service total")
            close(float(m["requested_service_mwh"]),requested,"H02 requested total")
            totals[(*key,sector)]=unmet
            short=[]
            for i in range(count):
                req=fsum(d["requested_service_mwh"] for d in demand if d["period"]==i)
                u=fsum(d["unmet_service_mwh"] for d in demand if d["period"]==i)
                short.append(u>max(config["safety"]["absolute_shortage_tolerance_mwh"],config["safety"]["relative_shortage_tolerance"]*req))
            longest=streak=0
            for missing in short:
                streak=streak+6 if missing else 0;longest=max(longest,streak)
            close(float(m["longest_shortage_hours"]),longest,"H02 longest interruption")
            affected=[i for i,missing in enumerate(short) if missing and (i+1)*6>event["start_hour"]]
            if not requested:state,recovery="zero_demand",None
            elif not affected:state,recovery="no_service_interruption",0.
            elif count-max(affected)-1>=config["safety"]["recovery_periods"]:
                state,recovery="recovered",(max(affected)+1)*6-event["start_hour"]
            else:state,recovery="not_recovered_or_right_censored",None
            if m["recovery_status"]!=state:raise ValueError("Recovery state mismatch")
            if recovery is None:
                if m["recovery_hours"]!="":raise ValueError("Unknown recovery incorrectly filled")
            else:close(float(m["recovery_hours"]),recovery,"recovery time")
        if key[1]=="frozen_battery_discharge":
            reference={r["period"]:r["discharge_mwh"] for r in groups[key[0],"normal","S0"] if r["kind"]=="storage"}
            if any(r["discharge_mwh"]>reference[r["period"]]+.001 for r in rows if r["kind"]=="storage"):
                raise ValueError("Frozen response is not bounded by matched S0 action")
    h02=csv_read(folder/"h02_results.csv")
    for row in h02:
        interaction={}
        for response in ("normal","frozen_battery_discharge"):
            v={s:totals[row["event"],response,s,row["sector"]] for s in ("S0","SG","SW","SGW")}
            interaction[response]=v["SGW"]-v["SG"]-v["SW"]+v["S0"]
        close(float(row["J"]),interaction["normal"],"J")
        close(float(row["J_frozen"]),interaction["frozen_battery_discharge"],"J frozen")
        close(float(row["J_normal_minus_frozen"]),interaction["normal"]-interaction["frozen_battery_discharge"],"J contrast")
    return dict(events=len(groups),service_interactions=len(h02),resource_and_recovery_checks=True)


def independently_screen(rows,policy):
    baseline=next(r for r in rows if r["policy_id"]=="none")
    feasible=[]
    for row in rows:
        if row["status"]!="completed":continue
        if float(row["cumulative_combustion_co2_t"])>float(baseline["cumulative_combustion_co2_t"])*policy["carbon_limit_ratio"]+1e-5:continue
        if float(row["discounted_resource_cost_cny"])>float(baseline["discounted_resource_cost_cny"])*policy["gross_cost_limit_ratio"]+.01:continue
        if max(float(row["worst_selection_service_fraction"]),float(row["worst_annual_service_fraction"]))>policy["service_limit"]+1e-10:continue
        feasible.append(row["policy_id"])
    return sorted(feasible)


def audit_summary_tables(folder,cases,config):
    """Connect every selection row back to independently checked physical accounts."""
    events=csv_read(folder/"transition_event_metrics.csv")
    worst=defaultdict(float)
    for row in events:
        key=(row["id"],row["split"])
        worst[key]=max(worst[key],float(row["unmet_fraction"]) if row["unmet_fraction"] else 0.)
    checked=[]
    for name in ("h01_results.csv","policy_results.csv","sensitivity_results.csv"):
        rows=csv_read(folder/name)
        for row in rows:
            detail=cases[row["id"]]
            if row["status"]!=detail["outcome"]["status"]:raise ValueError("Summary status differs: "+row["id"])
            if row["status"]!="completed":continue
            for key,value in detail["terminal_accounts"].items():
                close(float(row[key]),value,"summary "+key,absolute=.1 if key.endswith("_cny") else .001)
            close(float(row["worst_annual_service_fraction"]),detail["annual_worst"],"independent annual worst",absolute=1e-10)
            for split in ("selection","test"):
                if (row["id"],split) not in worst:raise ValueError("Missing event evaluation: "+row["id"]+"/"+split)
                close(float(row["worst_"+split+"_service_fraction"]),worst[row["id"],split],"independent event worst",absolute=1e-10)
        checked.append(dict(file=name,rows=len(rows)))
    sensitivity=csv_read(folder/"sensitivity_results.csv")
    for variant in config["sensitivity"]:
        rows=[r for r in sensitivity if r["sensitivity"]==variant["id"]]
        if len(rows)!=len(config["policy"]["candidates"]):raise ValueError("Incomplete sensitivity candidates")
        decision=load(folder/"sensitivity_locks"/(variant["id"]+".json"))["decision"]
        feasible=independently_screen(rows,config["policy"])
        if feasible!=sorted(decision["feasible"]):raise ValueError("Sensitivity feasibility differs")
        if decision["selected"] is not None and decision["selected"] not in feasible:raise ValueError("Inadmissible sensitivity choice")
    return dict(tables=checked,sensitivity_choices=len(config["sensitivity"]))


def compare_files(left,right):
    return compare_runs(left,right)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",default="outputs/q3/p3_mmj_v5")
    parser.add_argument("--evidence",default="outputs/validation/p3_mmj/complete_review_round1.json")
    parser.add_argument("--reproduction-root",type=Path)
    parser.add_argument("--reproduction-output",help="Path within the independent checkout; defaults to the source name plus _reproduction")
    parser.add_argument("--reproduction-seed",default="1729",help="Seed when this auditor launches a new run; existing-run seeds are not inferred")
    parser.add_argument("--existing-reproduction",action="store_true",help="Validate the already executed independent full-entry run, including its current fingerprints and latest-attempt receipt")
    args=parser.parse_args()
    source=(ROOT/args.output_dir).resolve();target=(ROOT/args.evidence).resolve()
    record=dict(status="running",passed=False,team_approved=False,checked_at_utc=datetime.now(timezone.utc).isoformat(),
                auditor_sha256=sha(__file__),checks=[])
    def check(name,value):
        record["checks"].append(dict(name=name,passed=True,detail=value));save(target,record)
    save(target,record)
    try:
        manifest=verify_latest(source)
        if manifest["status"]!="conditional_experiments_completed":raise ValueError("Full experiment receipt missing")
        record["run_id"]=manifest["run_id"];record["code_hashes"]=manifest["code_hashes"]
        check("current_complete_experiment_receipt",manifest["run_id"])
        config,design=load(source/"frozen_config.json"),load(source/"inherited_q2_design.json")
        check("six_scenario_event_balances_H02_freeze_and_recovery",audit_h02(source,config))
        case_paths=sorted((source/"cases").glob("*.json.gz"))
        cases={}
        status=csv_read(source/"transition_case_status.csv")
        if len(case_paths)!=116 or len(status)!=116 or len({r["id"] for r in status})!=116:raise ValueError("Frozen experiment grid incomplete")
        check("all_frozen_grid_points_recorded",len(case_paths))
        counts=[]
        common_policy_requests={}
        for path in case_paths:
            key=path.name.removesuffix(".json.gz");value=unpack(path)
            counts.append(dict(id=key,**audit_case(value,config,design)))
            cases[key]={"snapshots":value["snapshots"],"outcome":value["outcome"],
                        "terminal_accounts":value.get("terminal_accounts",{}),
                        "annual_worst":max((r["unmet_fraction"] for r in value["annual_services"]),default=0.)}
            if value["label"]["family"]=="policy" and value["outcome"]["status"]=="completed":
                for row in value["annual_services"]:
                    index=(row["year"],row["sector"])
                    if index in common_policy_requests:close(row["requested_service_mwh"],common_policy_requests[index],"common policy requested service")
                    common_policy_requests[index]=row["requested_service_mwh"]
        check("annual_energy_carbon_cash_budget_lifetime_and_terminal_accounts",counts)
        check("continuous_events_same_services_and_restored_stocks",audit_events(source,config,cases))
        check("all_summary_rows_trace_to_accounts_and_sensitivity_decisions",audit_summary_tables(source,cases,config))
        lock=load(source/"selection_lock.json")
        feasible=independently_screen(csv_read(source/"policy_results.csv"),config["policy"])
        if feasible!=sorted(lock["policy"]["feasible"]):raise ValueError("Independent feasible-policy set differs")
        check("designated_constraints_recomputed_without_relaxation",dict(feasible=feasible,selected=lock["policy"]["selected"]))
        h01=csv_read(source/"h01_results.csv")
        h01_feasible={r["id"]:r["feasible_selection"]=="True" for r in csv_read(source/"h01_feasibility.csv")}
        for row in h01:
            ref=next(r for r in h01 if r["mode"]==row["mode"] and r["vR"]==row["vR"] and r["vE"]==row["vE"] and r["delay"]==row["delay"] and r["rule"]=="fixed_schedule")
            feasible_here=False
            if row["status"]==ref["status"]=="completed":
                p=config["policy"]
                feasible_here=(float(row["cumulative_combustion_co2_t"])<=float(ref["cumulative_combustion_co2_t"])*p["carbon_limit_ratio"]+1e-5
                    and float(row["discounted_resource_cost_cny"])<=float(ref["discounted_resource_cost_cny"])*p["gross_cost_limit_ratio"]+.01
                    and max(float(row["worst_annual_service_fraction"]),float(row["worst_selection_service_fraction"]))<=p["service_limit"]+1e-10)
            if h01_feasible[row["id"]]!=feasible_here:raise ValueError("Independent H01 cell feasibility differs")
        permissible=[]
        for epsilon in config["transition"]["epsilon_candidates"]:
            subset=[r for r in h01 if r["mode"]=="full_response" and r["rule"]=="anticipatory" and float(r["epsilon"])==epsilon]
            if all(h01_feasible[r["id"]] for r in subset):permissible.append(epsilon)
        if lock["h01_epsilon"] is not None and lock["h01_epsilon"] not in permissible:raise ValueError("Inadmissible H01 threshold selected")
        if not permissible and lock["h01_epsilon"] is not None:raise ValueError("No feasible H01 threshold was hidden")
        check("H01_threshold_feasibility_separate_from_ranking",dict(permissible=permissible,selected=lock["h01_epsilon"]))
        comparisons=csv_read(source/"h01_comparisons.csv")
        fixed=[r for r in comparisons if r["mode"]=="fixed_projects" and r["status"]=="completed"]
        if any(r["fixed_capital_set_equal"]!="True" for r in fixed):raise ValueError("Fixed project comparison changed set")
        check("fixed_project_comparisons_are_actually_same_set",len(fixed))
        original_contracts=["data/sources.json","data/evidence_reviews.json","workflow/model_inputs.json"]
        original_contracts += [p.relative_to(ROOT).as_posix() for p in (ROOT/"只读工作区").iterdir() if p.is_file()]
        original_contracts += [p.name for p in ROOT.iterdir() if p.is_file() and p.suffix.lower() in {".xlsx",".pdf"}]
        for rel in original_contracts:
            content=subprocess.run(["git","show",config["base_sha"]+":"+rel],cwd=ROOT,capture_output=True,check=True).stdout
            if hashlib.sha256(content).hexdigest()!=sha(ROOT/rel):raise ValueError("Protected original changed: "+rel)
        check("protected_originals_equal_locked_base",len(original_contracts))
        if args.reproduction_root:
            reproduction=args.reproduction_root.resolve()
            if reproduction==ROOT:raise ValueError("Independent checkout required")
            for rel,expected in {**manifest["code_hashes"],**manifest["input_hashes"]}.items():
                if sha(reproduction/rel)!=expected:raise ValueError("Independent checkout input/code mismatch: "+rel)
            check("independent_checkout_has_identical_code_and_inputs",str(reproduction))
            env=os.environ.copy();env["PYTHONHASHSEED"]=args.reproduction_seed
            output_name=source.name+"_reproduction"
            output_relative=args.reproduction_output or "outputs/q3/"+output_name
            rep=(reproduction/output_relative).resolve()
            if not rep.is_relative_to(reproduction/"outputs/q3"):raise ValueError("Reproduction output outside independent Q3 directory")
            output_name=rep.name
            command=[sys.executable,"-B","-X","utf8","run.py","q3","--config",manifest["config_path"],"--output-dir",output_relative]
            log=target.with_suffix(".reproduction.log")
            started=time.perf_counter()
            if not args.existing_reproduction:
                with log.open("w",encoding="utf-8") as f:
                    result=subprocess.run(command,cwd=reproduction,env=env,stdout=f,stderr=subprocess.STDOUT)
                if result.returncode:raise ValueError("Independent full entry failed; see reproduction log")
            repeated=load(rep/"run_manifest.json")
            attempt=load(rep.parent/(output_name+".latest-attempt.json"))
            if not attempt["output_valid_for_this_attempt"] or attempt["run_id"]!=repeated["run_id"] or attempt["manifest_sha256"]!=sha(rep/"run_manifest.json"):
                raise ValueError("Independent latest attempt invalid or stale")
            if repeated["status"]!="conditional_experiments_completed":raise ValueError("Independent receipt incomplete")
            if repeated["code_hashes"]!=manifest["code_hashes"] or repeated["input_hashes"]!=manifest["input_hashes"]:raise ValueError("Independent run used different code/inputs")
            if any(sha(rep/p)!=v for p,v in repeated["outputs"].items()):raise ValueError("Independent output hashes changed")
            check("independent_full_entry",dict(returncode=repeated["exit_code"],seconds=repeated["elapsed_seconds"],pythonhashseed=None if args.existing_reproduction else args.reproduction_seed,command=repeated["command"],run_id=repeated["run_id"],receipt_mode="separately_executed" if args.existing_reproduction else "executed_by_auditor"))
            check("independent_all_scientific_outputs",compare_files(source,rep))
        verify_latest(source)
        record.update(status="author_round_passed",passed=True,
            scope="Conditional-computation audit only; empirical/Q2 scope limitations and C9 remain")
    except Exception as exc:
        record.update(status="failed",error=type(exc).__name__+": "+str(exc))
    save(target,record)
    print(json.dumps({k:record[k] for k in ("status","passed")}),flush=True)
    if not record["passed"]:print(record["error"],file=sys.stderr)
    return 0 if record["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
