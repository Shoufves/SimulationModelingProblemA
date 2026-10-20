"""Train revised mechanisms on 2015--2021; report all authority scenarios.

This is an explicitly conditional candidate. Municipal composition/delivery,
new-project yields and commitment authority are assumptions, not observations.
No evaluation result is used by the coordinate search or scenario selection.
"""
from copy import deepcopy
from datetime import datetime,timezone
from itertools import product
from pathlib import Path
import argparse
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"));sys.path.insert(0,str(ROOT/"src"))
from run_q2_historical_support import run_case,metrics,preflight,extract,CODE,INPUTS,sha
from run_q2_cost_review import cost_inputs
from run_q2_national import loss
from energy_model.q2_renewable_vintages import RenewableVintages
from energy_model.q2_bioenergy import CompositeBioenergy
from energy_model.q2_exposure import AnnualExposure

DESIGN="workflow/q2_revenue_recalibration.json"
EVIDENCE="docs/sources/q2_revenue_recalibration.md"


def bio_inputs(data,config,p):
    a=config["bioenergy"]
    initial=data[2014,"biofuel_electricity_mwh"]/.3*p["waste_fuel_fraction"]/a["waste_lhv_mwh_per_t"]
    quantity={y:min(a["maximum_municipal_waste_delivery_t"],initial*a["initial_delivery_headroom"]*(1+p["waste_delivery_growth"])**(y-2014)) for y in range(2015,2033)}
    fee=a["treatment_fee_real_2024_cny_per_t"]
    return CompositeBioenergy(waste_fuel_fraction=p["waste_fuel_fraction"],
        waste_fossil_energy_fraction=a["waste_fossil_energy_fraction"],
        fossil_co2_t_per_mwh_whole_waste=a["fossil_co2_t_per_mwh_whole_waste"],waste_lhv_mwh_per_t=a["waste_lhv_mwh_per_t"],
        waste_delivery_t_by_year=quantity,treatment_fee_real_cny_per_t={y:fee for y in quantity},
        municipal_appropriation_real_cny_by_year={y:q*fee*a["municipal_funding_fraction_of_full_service"] for y,q in quantity.items()},
        expected_collection_fraction=a["expected_collection_fraction"],initial_year=2014,evidence=EVIDENCE)


def build(data,design,config,parameters,authority,*,end_year,include_bio=True,include_vintages=True):
    # Obtain the same complete EI vintage used by the model before reconstructing
    # an initial waste-delivery envelope. No evaluation observations set it.
    d=deepcopy(data)
    refs={(r["year"],r["category"]):r["value_twh"]*1e6 for r in extract()[0]}
    d[2014,"biofuel_electricity_mwh"]=refs[2014,"geothermal_biomass_other_renewables"]
    vintage=RenewableVintages(new_project_cf={"wind":parameters["new_wind_cf"],"solar":parameters["new_solar_cf"]},evidence=EVIDENCE) if include_vintages else None
    timing=config.get("generator_annual_exposure")
    exposure=AnnualExposure(**timing) if timing is not None else None
    return run_case(data,design,parameters,authority_multiple=authority,generation_costs=cost_inputs(data,design),
        renewable_vintages=vintage,bioenergy=bio_inputs(d,config,parameters) if include_bio else None,
        end_year=end_year,annual_exposure=exposure)


def training_loss(model):
    d=deepcopy(model.design)
    for t in d["targets"]:
        values=[model.data[y,t["observation"]]*t["multiplier"] for y in range(2015,2022) if (y,t["observation"]) in model.data]
        t["scale"]=t.get("absolute_scale") or sum(values)/len(values)*t["scale_from_training_mean_fraction"]
    return loss(model.paths,model.data,d,list(range(2015,2022)),"revenue_cost_vintage_candidate")


def save(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+"\n","utf-8")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design",default=DESIGN)
    args=parser.parse_args()
    selected_design=(ROOT/args.design).resolve()
    if not selected_design.is_relative_to(ROOT/"workflow"):
        raise ValueError("Research search design must be in workflow")
    design_path=selected_design.relative_to(ROOT).as_posix()
    config=json.loads(selected_design.read_text("utf-8"))
    if config["training_years"]!=list(range(2015,2022)) or config["evaluation_years"]!=[2022,2023,2024]:
        raise ValueError("Unreviewed training windows")
    data,design,_=preflight()
    old="outputs/q2/p2_lb_national/calibration.json"
    initial={**json.loads((ROOT/old).read_text("utf-8"))["best"]["parameters"],**config["initial"]}
    folder=ROOT/"outputs/q2_revenue_recalibration"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    save(folder/"design.json",config)
    save(folder/"status.json",dict(status="running",scientific_acceptance=False))
    alltrials=[];selected={};sources=set(CODE+INPUTS+[design_path,EVIDENCE,old,__file__,
        "docs/sources/q2_annual_exposure.md",
        "scripts/run_q2_historical_support.py","scripts/run_q2_empirical_support.py","scripts/run_q2_cost_review.py",
        "scripts/build_q2_project_costs.py","scripts/build_q2_electricity_scope.py","scripts/build_q2_revenue_evidence.py",
        "data/processed/q2/revenue/nea_tariff_and_auxiliary_use.csv","data/raw/q2_fiscal/annual_renewable_levy.csv",
        "data/raw/q2_technology_scope/ei_2025_original.xlsx","data/raw/q2_project_costs/iea_projected_costs_2020_data.xlsx"])
    def trial(p,authority):
        record=dict(index=len(alltrials),authority=authority,parameters=dict(p))
        try:
            model,*_,extra=build(data,design,config,p,authority,end_year=2021)
            sources.update(extra)
            score,components,residuals=training_loss(model)
            record.update(status="success",loss=score,components=components,paths=model.paths)
        except (ValueError,RuntimeError) as exc:
            record.update(status="failed",loss=None,error=str(exc))
        alltrials.append(record)
        save(folder/"trials.json",alltrials)
        return record
    for authority in config["authority_scenarios"]:
        best=trial(initial,authority)
        if best["loss"] is None:raise ValueError("Initial candidate failed: "+best["error"])
        for sweep in range(config["passes"]):
            for block in config["blocks"]:
                parent=dict(best["parameters"]);keys=sorted(block)
                for values in product(*(block[k] for k in keys)):
                    item=trial({**parent,**dict(zip(keys,values))},authority)
                    if item["loss"] is not None and item["loss"]<best["loss"]:best=item
                print("trained",authority,"block",keys,"loss",round(best["loss"],5),"trials",len(alltrials),flush=True)
        selected[str(authority)]={k:best[k] for k in ("index","parameters","loss","components")}
    # Persist selection BEFORE executing any evaluation path.
    save(folder/"training_selection.json",dict(selection_uses="2015_2021_only",scenarios=selected))
    refs={(r["year"],r["category"]):r["value_twh"]*1e6 for r in extract()[0]}
    results={}
    for key,best in selected.items():
        for mode,options in (("full",{}),("without_municipal_composition",dict(include_bio=False))):
            name=f"authority_{key}_{mode}"
            m,assumptions,prices,changes,extra=build(data,design,config,best["parameters"],int(key),end_year=2024,**options)
            sources.update(extra)
            out=dict(parameters=best["parameters"],assumptions=assumptions,metrics=metrics(m,refs),paths=m.paths,
                finance=m.finance,operations=m.operations,projects=m.projects,assets=m.assets,balances=m.balances,
                behavior=m.behavior,price_inputs=prices,lifetime_rule_changes=changes,fund_history=m.revenue_policy.history,
                municipal_service_history=m.bioenergy.history if m.bioenergy else [],
                training_components=training_loss(m)[1])
            save(folder/(name+".json"),out)
            results[name]=dict(metrics=out["metrics"],end=m.paths[-1],
                max_cash_residual_cny=max(abs(r["cash_balance_residual_cny"]) for r in m.paths),
                max_physical_residual=max(r["max_residual"] for r in m.paths))
            print(name,{t:round(out["metrics"][t]["already_seen_evaluation"]["mape"]*100,2) for t in ("gas","oil","biomass","wind","solar")},flush=True)
    sources.update(json.loads((ROOT/"data/catalog/q2_revenue_review.json").read_text("utf-8"))["source_sha256"])
    for name in ("q2_fiscal","q2_bioeconomics","q2_waste_boundary","q2_waste_fossil_ef"):
        sources.update(p.relative_to(ROOT).as_posix() for p in (ROOT/"data/raw"/name).iterdir() if p.is_file() and p.suffix.lower() in {".pdf",".html",".json",".csv",".py"})
    sources.update(["docs/sources/q2_project_costs.md","docs/sources/q2_bioeconomics.md","docs/sources/q2_waste_boundary_review.md"])
    paths={(ROOT/p).resolve().relative_to(ROOT).as_posix() for p in sources}
    save(folder/"results.json",dict(status="conditional_retrained_candidate_not_final_acceptance",
        training_only_selection=True,evaluation_identity="already_seen_not_blind",production_default_changed=False,
        source_sha256={p:sha(p) for p in sorted(paths)},results=results))
    lines=["# 收益、成本和项目队列重新训练","","2015—2021训练，2022—2024已接触评估。三种未知承诺额度分别报告，未按评估结果选择。","",
        "| 条件 | 气电MAPE | 纯油MAPE | 生物能源MAPE | 风电MAPE | 光伏MAPE |","|---|---:|---:|---:|---:|---:|"]
    for name,r in results.items():
        lines.append("| "+name+" | "+" | ".join(f"{r['metrics'][t]['already_seen_evaluation']['mape']*100:.2f}%" for t in ("gas","oil","biomass","wind","solar"))+" |")
    lines += ["","全部技术逐年发电、装机和利用小时见各组JSON。全国正式误差阈值没有放宽，本轮不是官方政策效应估计。潜在初始在建倍数、新项目CF、垃圾供给与组成等均为条件参数，不能写成原始观测。",""]
    (folder/"report.md").write_text("\n".join(lines),"utf-8")
    save(folder/"status.json",dict(status="complete_conditional_experiment",scientific_acceptance=False,trial_count=len(alltrials)))
    print(folder.relative_to(ROOT).as_posix())


if __name__=="__main__":main()
