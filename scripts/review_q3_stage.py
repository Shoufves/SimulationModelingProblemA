"""Independent exported-ledger checks; never certify unfinished Q3 packages."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from math import fsum, isclose, sqrt
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from run_q3 import verify_latest, CODE
from run_q2_national import dump, load, sha


def read(path):
    with path.open(encoding="utf-8",newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reproduction-root",type=Path,required=True)
    args=parser.parse_args()
    source=ROOT/"outputs/q3/p3_mmj"
    evidence=ROOT/"outputs/validation/p3_mmj"
    evidence.mkdir(parents=True,exist_ok=True)
    record=dict(status="running",passed=False,q3_complete=False,team_approved=False,
                scope="six-scenario/H02 stage only; not C1-C9 completion",checks=[],
                checked_at_utc=datetime.now(timezone.utc).isoformat(),
                audit_sha256=sha(Path(__file__)))
    target=evidence/"stage_review.json"
    dump(target,record)
    def check(name,passed,detail):
        record["checks"].append(dict(name=name,passed=bool(passed),detail=detail))
        dump(target,record)
        if not passed:raise ValueError(name)
    try:
        manifest=verify_latest(source)
        record["run_id"]=manifest["run_id"]
        record["audited_code_hashes"]=manifest["code_hashes"]
        check("current_stage_receipt",manifest["status"]=="partial_stage_completed" and not manifest["q3_scientific_complete"],manifest["run_id"])
        config=load(source/"frozen_config.json")
        snapshot=load(source/"event_initial_state.json")
        ops=read(source/"event_operations.csv")
        scenarios=read(source/"scenario_comparison.csv")
        check("six_scenario_labels",{r["scenario"] for r in scenarios}=={"S0","SP","SG","ST","SW","SGW"},len(scenarios))
        groups={}
        for r in ops:
            groups.setdefault((r["event"],r["response"],r["scenario"]),[]).append(r)
        check("all_event_cases",len(groups)==len(config["events"])*8,len(groups))
        residuals=[]
        service_reference={}
        for key,rows in groups.items():
            previous={f:p["initial_mwh"] for f,p in snapshot["fuels"].items()}
            soc=snapshot["storage"]["initial_mwh"]
            periods=sorted({int(r["period"]) for r in rows})
            expected_days=next(e["window_days"] for e in config["events"] if e["id"]==key[0])
            if len(periods)!=expected_days*4:raise ValueError("Missing time periods")
            for i in periods:
                part=[r for r in rows if int(r["period"])==i]
                battery=next(r for r in part if r["kind"]=="storage")
                residuals += [abs(float(battery["opening_mwh"])-soc),
                    abs(float(battery["closing_mwh"])-(soc+float(battery["charge_mwh"])*snapshot["storage"]["charge_efficiency"]-
                        float(battery["discharge_mwh"])/snapshot["storage"]["discharge_efficiency"]))]
                soc=float(battery["closing_mwh"])
                for r in part:
                    if r["kind"]=="fuel":
                        fuel=r["fuel"]
                        residuals.append(abs(float(r["closing_mwh"])-(previous[fuel]+float(r["fill_mwh"])-float(r["withdrawal_mwh"]))))
                        residuals.append(abs(float(r["domestic_mwh"])+float(r["import_mwh"])+float(r["withdrawal_mwh"])-
                                             float(r["fill_mwh"])-float(r["direct_mwh"])-float(r["conversion_mwh"])))
                        previous[fuel]=float(r["closing_mwh"])
                    if r["kind"]=="demand":
                        residuals.append(abs(float(r["requested_service_mwh"])-float(r["served_service_mwh"])-float(r["unmet_service_mwh"])))
                        name=(key[0],i,r["device"])
                        requested=float(r["requested_service_mwh"])
                        if name in service_reference and requested!=service_reference[name]:raise ValueError("Paired demand changed")
                        service_reference[name]=requested
                electric=fsum(float(r["output_mwh"]) for r in part if r["kind"]=="generation" and r["output"]=="electricity")
                electric+=float(battery["discharge_mwh"])-float(battery["charge_mwh"])
                electric-=fsum(float(r["input_mwh"])/snapshot["grid"]["efficiency"] for r in part if r["kind"]=="demand" and r["carrier"]=="electricity")
                residuals.append(abs(electric))
            residuals.append(abs(soc-snapshot["storage"]["initial_mwh"]))
            residuals.extend(abs(previous[f]-snapshot["fuels"][f]["initial_mwh"]) for f in previous)
        check("continuous_fuel_SOC_energy_service_and_terminal_balances",max(residuals,default=0)<=.001,dict(max_absolute_mwh=max(residuals),checks=len(residuals)))
        for event in config["events"]:
            normal=groups[event["id"],"normal","S0"]
            limits={int(r["period"]):float(r["discharge_mwh"]) for r in normal if r["kind"]=="storage"}
            for scenario in ("S0","SG","SW","SGW"):
                frozen=groups[event["id"],"frozen_battery_discharge",scenario]
                if any(float(r["discharge_mwh"])-limits[int(r["period"])]>.001 for r in frozen if r["kind"]=="storage"):
                    raise ValueError("Frozen response exceeded reference")
        check("frozen_battery_action_bound",True,"Compared every exported action to matched S0, without resetting state")
        safety=read(source/"safety_metrics.csv")
        indexed={(r["event"],r["response"],r["scenario"],r["sector"]):float(r["unmet_service_mwh"]) for r in safety}
        h02=read(source/"h02_results.csv")
        for r in h02:
            values={}
            for response in ("normal","frozen_battery_discharge"):
                v={s:indexed[r["event"],response,s,r["sector"]] for s in ("S0","SG","SW","SGW")}
                values[response]=v["SGW"]-v["SG"]-v["SW"]+v["S0"]
            if not isclose(float(r["J"]),values["normal"],abs_tol=.001):raise ValueError("H02 interaction mismatch")
            if not isclose(float(r["J_normal_minus_frozen"]),values["normal"]-values["frozen_battery_discharge"],abs_tol=.001):raise ValueError("H02 freeze difference mismatch")
        check("H02_recomputed_from_service_outputs",True,len(h02))
        check("Q2_S0_current_numeric_replay",load(source/"q2_baseline_replay.json")["passed"],"Original cash-conservation tolerance; no claim of bitwise match")
        reproduction=args.reproduction_root.resolve()
        if reproduction==ROOT:raise ValueError("Reproduction must use a separate checkout")
        check("independent_checkout_same_code_inputs",all(sha(reproduction/p)==v for p,v in {**manifest["code_hashes"],**manifest["input_hashes"]}.items()),str(reproduction))
        env=os.environ.copy();env["PYTHONHASHSEED"]="1729"
        started=time.perf_counter()
        command=[sys.executable,"-B","-X","utf8","scripts/run_q3.py","--config","workflow/q3_inputs.json","--output-dir","outputs/q3/p3_mmj_reproduction","--stage","scenarios-h02"]
        run=subprocess.run(command,cwd=reproduction,env=env,capture_output=True,text=True,encoding="utf-8")
        (evidence/"independent_reproduction.log").write_text(run.stdout+run.stderr,encoding="utf-8")
        check("independent_full_stage_process",run.returncode==0,dict(returncode=run.returncode,seconds=time.perf_counter()-started,hash_seed="1729",command=command))
        rep=reproduction/"outputs/q3/p3_mmj_reproduction"
        rep_manifest=load(rep/"run_manifest.json")
        check("independent_receipt_and_outputs",rep_manifest["status"]=="partial_stage_completed" and all(sha(rep/p)==v for p,v in rep_manifest["outputs"].items()),rep_manifest["run_id"])
        compared=[]
        max_numeric=0.0
        for file in sorted(source.glob("*.csv")):
            if file.name=="gaps_and_conflicts.csv":continue
            left,right=read(file),read(rep/file.name)
            if len(left)!=len(right):raise ValueError("Reproduction row count "+file.name)
            for a,b in zip(left,right):
                if set(a)!=set(b):raise ValueError("Reproduction columns "+file.name)
                for k,v in a.items():
                    if v==b[k]:continue
                    try:
                        x,y=float(v),float(b[k])
                    except ValueError:
                        raise ValueError("Reproduction text differs "+file.name+":"+k)
                    if "residual_cny" in k:
                        same=abs(x-y)<=.01
                    else:
                        same=isclose(x,y,rel_tol=1e-10,abs_tol=1e-6)
                    if not same:raise ValueError("Reproduction numeric difference "+file.name+":"+k)
                    max_numeric=max(max_numeric,abs(x-y))
            compared.append(dict(file=file.name,rows=len(left),bitwise_equal=sha(file)==sha(rep/file.name)))
        check("independent_scientific_CSV_comparison",True,dict(files=compared,max_accepted_numeric_difference=max_numeric))
        check("code_unchanged_during_review",all(sha(ROOT/p)==v for p,v in manifest["code_hashes"].items()),"Current-stage fingerprints remain valid")
        record.update(status="stage_passed_full_Q3_pending",passed=True)
    except Exception as exc:
        record.update(status="failed",error=type(exc).__name__+": "+str(exc))
    dump(target,record)
    print(json.dumps({k:record[k] for k in ("status","passed","q3_complete")}),flush=True)
    return 0 if record["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
