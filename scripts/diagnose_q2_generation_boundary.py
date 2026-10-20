"""Preserve legacy outputs; expose target-label defects without claiming a rerun."""
import csv
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def read(path):
    with path.open(encoding="utf-8-sig",newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    source=ROOT/"data/processed/q2/electricity_scope/ei2025_china_generation.csv"
    legacy=ROOT/"outputs/q2/p2_lb_national/generation_validation.csv"
    data={(int(r["year"]),r["category"]):float(r["value_twh"]) for r in read(source)}
    rows=[]
    for old in read(legacy):
        if old["technology"]!="oil":
            continue
        year=int(old["year"])
        simulated=float(old["simulated_mwh"])/1e6
        pure=data[year,"oil"]
        rows.append(dict(year=year,legacy_simulated_oil_label_twh=simulated,
            legacy_observed_oil_label_twh=float(old["observed_mwh"])/1e6,
            reviewed_pure_oil_twh=pure,other_unallocated_twh=data[year,"other_unallocated"],
            apparent_relative_error_against_legacy_label=float(old["relative_error"]),
            diagnostic_relative_error_if_interpreted_as_pure_oil=simulated/pure-1,
            status="legacy_model_counterfactual_reinterpretation_not_recalibrated_result"))
    out=ROOT/"outputs/q2_boundary_diagnostic"
    out.mkdir(parents=True,exist_ok=True)
    result=dict(status="diagnostic_only_not_fixed_model",source_sha256={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (source,legacy,Path(__file__))},
        findings=rows,explanation="Legacy oil target combines pure oil and EI Other. Retargeting alone is not a model repair: capacity, fuel demand, dispatch and emissions must be rebuilt together.")
    (out/"legacy_oil_target_review.json").write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    print(json.dumps(rows[-1],ensure_ascii=False))


if __name__=="__main__":main()
