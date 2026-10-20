"""Predeclared timing sensitivity with frozen midyear training parameters."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"));sys.path.insert(0,str(ROOT/"src"))
from run_q2_revenue_recalibration import build,preflight,metrics,extract,save,sha,training_loss
from review_q2_revenue_candidate import review


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("historical_run")
    args=parser.parse_args()
    source=(ROOT/args.historical_run).resolve()
    if not source.is_relative_to(ROOT/"outputs/q2_revenue_recalibration"):
        raise ValueError("Expected a frozen historical candidate")
    review(source)
    config=json.loads((source/"design.json").read_text("utf-8"))
    if config["generator_annual_exposure"]["first_year_fraction"]!=.5 or config["exposure_sensitivity_fractions"]!=[0,.5,1]:
        raise ValueError("Unexpected timing design")
    selection=json.loads((source/"training_selection.json").read_text("utf-8"))
    if selection["selection_uses"]!="2015_2021_only":
        raise ValueError("Sensitivity needs training-only selection")
    inputs=json.loads((source/"results.json").read_text("utf-8"))["source_sha256"]
    data,design,_=preflight()
    refs={(r["year"],r["category"]):r["value_twh"]*1e6 for r in extract()[0]}
    folder=ROOT/"outputs/q2_exposure_sensitivity"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    save(folder/"status.json",dict(status="running",scientific_acceptance=False))
    save(folder/"design.json",config)
    cases={}
    try:
        for authority,chosen in selection["scenarios"].items():
            for fraction in config["exposure_sensitivity_fractions"]:
                scenario=deepcopy(config)
                scenario["generator_annual_exposure"]["first_year_fraction"]=fraction
                model,assumptions,*_=build(data,design,scenario,chosen["parameters"],int(authority),end_year=2024)
                if fraction==.5:
                    original=json.loads((source/f"authority_{authority}_full.json").read_text("utf-8"))
                    if model.paths!=original["paths"]:
                        raise ValueError("Midyear base failed exact reproduction")
                name=f"authority_{authority}_first_year_{fraction:g}"
                record=dict(first_year_fraction=fraction,authority=int(authority),assumptions=assumptions,
                    parameters=chosen["parameters"],parameters_refitted=False,paths=model.paths,
                    metrics=metrics(model,refs),training_loss=training_loss(model)[0],
                    finance=model.finance,fund_history=model.revenue_policy.history)
                save(folder/(name+".json"),record)
                cases[name]=dict(first_year_fraction=fraction,authority=int(authority),
                    case_sha256=sha((folder/(name+".json")).relative_to(ROOT)),
                    end_capacity_mw=model.paths[-1]["total_capacity_mw"],metrics=record["metrics"],
                    max_cash_residual_cny=max(abs(r["cash_balance_residual_cny"]) for r in model.paths))
                print(name,"capacity",round(cases[name]["end_capacity_mw"]),flush=True)
        sources=set(inputs)|{Path(__file__).relative_to(ROOT).as_posix(),
            (source/"results.json").relative_to(ROOT).as_posix(),(source/"training_selection.json").relative_to(ROOT).as_posix(),
            (source/"design.json").relative_to(ROOT).as_posix(),"docs/sources/q2_annual_exposure.md"}
        save(folder/"results.json",dict(cases=cases,source_sha256={p:sha(p) for p in sorted(sources)},
            historical_run=source.relative_to(ROOT).as_posix(),evaluation_identity="already_seen_not_blind",
            scenario_selection="none",parameters_refitted=False,scientific_acceptance=False))
        lines=["# 首年运行比例：固定参数敏感性","",
            "全部使用各承诺情景在α=0.5、2015—2021训练所得参数。三种时点均报告，不按已接触评估结果选时点。", "",
            "|承诺情景|首年比例|2024年末总装机MW|气电MAPE|风电MAPE|光伏MAPE|",
            "|---|---:|---:|---:|---:|---:|"]
        for r in cases.values():
            errors="|".join(f"{r['metrics'][t]['already_seen_evaluation']['mape']*100:.2f}%" for t in ("gas","wind","solar"))
            lines.append(f"|{r['authority']}|{r['first_year_fraction']}|{r['end_capacity_mw']:.2f}|{errors}|")
        lines += ["", "此处不是各情景重新拟合后的优劣排名，也不能把差异全归因于实际投产日期。α=1仍包含本版其余修复，不能冒充旧源码结果。", ""]
        (folder/"report.md").write_text("\n".join(lines),"utf-8")
        save(folder/"status.json",dict(status="complete_fixed_parameter_sensitivity",scientific_acceptance=False))
    except Exception as exc:
        save(folder/"status.json",dict(status="failed",error=str(exc),scientific_acceptance=False))
        raise
    print(folder.relative_to(ROOT).as_posix())


if __name__=="__main__":main()
