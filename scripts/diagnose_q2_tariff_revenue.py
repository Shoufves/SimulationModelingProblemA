"""A fixed-V10-parameter revenue diagnostic, not a repaired/accepted forecast.

Only years with actual downloaded NEA reports are simulated (2015--2018).
Annual realised prices are exogenous hindsight conditions, not information a
prospective investor knew. Their all-in level is an entitlement upper bound,
not evidence of full subsidy cash payment. No observation loss is minimised.
"""
import csv
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"))
from run_q2_national import preflight,NationalModel,CODE,INPUTS


def sha(path):
    return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()


def main():
    data,design,_=preflight()
    calibration_path="outputs/q2/p2_lb_national/calibration.json"
    calibration=json.loads((ROOT/calibration_path).read_text(encoding="utf-8"))
    theta=calibration["best"]["parameters"]
    table_path="data/processed/q2/revenue/nea_tariff_and_auxiliary_use.csv"
    with (ROOT/table_path).open(encoding="utf-8-sig",newline="") as stream:
        rows=list(csv.DictReader(stream))
    cells={(int(r["year"]),r["technology"],r["metric"]):float(r["value"]) for r in rows}

    class ObservedRevenueDiagnostic(NationalModel):
        def tariff(self,tech):
            # Restrict the intervention to the questioned gas/biomass income.
            # Oil is excluded because its current classification is invalid.
            if tech not in {"gas","biomass"}:
                return super().tariff(tech)
            value=cells[self.year,tech,"feed_in_tariff"]
            auxiliary=cells[self.year,tech,"auxiliary_own_use"]/100
            # Equal monthly exported output is an explicit approximation for
            # the mid-2018 tax change; no claimed fleet effective tax rate.
            tax_factor=1/1.17 if self.year<=2017 else (4/12/1.17+8/12/1.16)
            return value*(1-auxiliary)*tax_factor*data[2024,"cpi"]/data[self.year,"cpi"]

    variants={"legacy_v10_income":NationalModel,"nea_all_in_revenue_upper_bound":ObservedRevenueDiagnostic}
    output={}
    for name,cls in variants.items():
        model=cls(data,design,theta,2014,detail=True).run(2018)
        output[name]=dict(paths=[{k:r[k] for k in ("year","gas_capacity_mw","biomass_capacity_mw","gas_generation_mwh","biomass_generation_mwh")} for r in model.paths],
            proposals=[r for r in model.behavior if r["kind"]=="investment_proposal" and r["actor"] in {"gas","biomass"}],
            finance=[r for r in model.finance if r["kind"]=="generator_operation" and r["actor"] in {"gas","biomass"}],
            autonomous_projects=[p for p in model.projects if p["tech"] in {"gas","biomass"} and not p["initial_reconstruction"]])
    destination=ROOT/"outputs/q2_revenue_diagnostic"
    destination.mkdir(parents=True,exist_ok=True)
    # Never overwrite a completed scientific diagnostic.
    run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path=destination/(run_id+".json")
    evidence={p:sha(p) for p in [*CODE,*INPUTS,calibration_path,table_path,
        "scripts/diagnose_q2_tariff_revenue.py","data/catalog/q2_revenue_review.json"]}
    report=dict(status="mechanism_diagnostic_not_scientific_acceptance",run_id=run_id,
        windows=[2015,2016,2017,2018],fixed_parameters=theta,evidence_sha256=evidence,results=output,
        limitations=["Original V10 physical/statistical scope defects retained as common controls",
        "Only gas and biomass effective receipts changed; no whole-market price or welfare claim",
        "Annual realised mean tariff is hindsight-conditioned, VAT conversion assumes general regime and equal monthly volume",
        "Auxiliary use adjusted only in effective billing; this is not a new gross/net physical model",
        "Full all-in receipt is an upper-bound diagnostic, not fiscal-budget-constrained payment",
        "Existing-fleet revenue extrapolated in original investment rule; vintage-specific new-project eligibility still required",
        "No parameter retuning, heldout-window experiment, or final forecast"])
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    for name, result in output.items():
        print(name,{t:len([p for p in result["autonomous_projects"] if p["tech"]==t]) for t in ("gas","biomass")},result["paths"][-1])
    print(path.relative_to(ROOT).as_posix())


if __name__=="__main__":
    main()
