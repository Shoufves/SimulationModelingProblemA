"""Replay the inherited Q2 historical path; compare Q1/Q2 numerical outputs.

The frozen 1012-trial calibration search is deliberately not repeated: the new
hooks have unchanged defaults and this tests the selected solution and historical
control. This is an explicit replay receipt, not a replacement Q2 calibration.
"""
import csv
import json
from math import isclose
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from run_q2_national import preflight,evaluate,load,dump,sha,CODE


def read(p):
    with p.open(encoding="utf-8-sig",newline="") as f:return list(csv.DictReader(f))


def compare(a,b):
    x,y=read(a),read(b)
    if len(x)!=len(y):raise ValueError("Regression rows: "+a.name)
    differences=[]
    for left,right in zip(x,y):
        if set(left)!=set(right):raise ValueError("Regression columns: "+a.name)
        for key,value in left.items():
            if value==right[key]:continue
            try:v,w=float(value),float(right[key])
            except ValueError:raise ValueError("Regression text: "+a.name+"/"+key)
            if not isclose(v,w,rel_tol=1e-10,abs_tol=.01 if "cny" in key else 1e-6):
                raise ValueError("Regression value: "+a.name+"/"+key)
            differences.append(dict(column=key,reference=v,actual=w))
    return dict(file=a.name,rows=len(x),bitwise_equal=sha(a)==sha(b),within_numeric_tolerance=differences)


def main():
    out=ROOT/"outputs/validation/p3_mmj/q2_replay"
    out.mkdir(parents=True,exist_ok=True)
    target=out/"replay_receipt.json"
    record=dict(status="running",passed=False,search_repeated=False,team_approved=False,
                code_hashes={p:sha(ROOT/p) for p in CODE},checks=[],
                scope="Selected-parameter Q2 historical replay and Q1 artifact comparison; not a new 1012-trial search")
    dump(target,record)
    started=time.perf_counter()
    try:
        data,design,_=preflight()
        calibration=load(ROOT/"outputs/q2/p2_lb_national/calibration.json")
        history=evaluate(data,design,calibration,out)
        for name in ("historical_path.csv","history_fit.csv","statistical_bridge_backtest.csv","fuel_share_validation.csv","generation_validation.csv","external_emissions_diagnostic.csv"):
            record["checks"].append(compare(ROOT/"outputs/q2/p2_lb_national"/name,out/name))
        old=load(ROOT/"outputs/q2/p2_lb_national/calibration.json")["quality"]["acceptance"]
        if calibration["quality"]["acceptance"]!=old:raise ValueError("Historical acceptance status changed")
        record["inherited_acceptance"]=old
        original=ROOT/"outputs/q1/p1_yx"
        replay=ROOT/"outputs/q1/p3_mmj_regression"
        q1=load(original/"run_manifest.json")
        record["q1_comparisons"]=[]
        for name in q1["outputs"]:
            if name.endswith(".csv"):record["q1_comparisons"].append(compare(original/name,replay/name))
        if not record["q1_comparisons"]:raise ValueError("Missing Q1 replay files")
        record["q1_replay_manifest_sha256"]=sha(replay/"run_manifest.json")
        if record["code_hashes"]!={p:sha(ROOT/p) for p in CODE}:raise ValueError("Code changed during regression")
        record.update(status="passed_scoped_replay",passed=True)
    except Exception as exc:record.update(status="failed",error=type(exc).__name__+": "+str(exc))
    record["seconds"]=time.perf_counter()-started
    dump(target,record)
    print(json.dumps({k:record[k] for k in ("status","passed","seconds")}),flush=True)
    if not record["passed"]:print(record["error"],file=sys.stderr)
    return 0 if record["passed"] else 1


if __name__=="__main__":raise SystemExit(main())
