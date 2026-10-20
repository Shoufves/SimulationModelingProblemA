"""Paired full-window cost-meaning experiment, with no re-fitting or acceptance."""
from datetime import datetime, timezone
from pathlib import Path
from math import fsum
import json
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"));sys.path.insert(0,str(ROOT/"scripts"))
from build_q2_project_costs import extract as extract_costs, SOURCE
from run_q2_historical_support import run_case, metrics, policy_inputs, preflight, extract, sha, CODE, INPUTS
from energy_model.q2_project_costs import GenerationCosts

EVIDENCE="docs/sources/q2_project_costs.md"


def cost_inputs(data,design,*,convert_net_capex=True):
    policy,*_=policy_inputs(data,design,cash_fraction=1,gas_price_factor=1,new_support=False)
    conversion=6.62*data[2024,"cpi"]/data[2018,"cpi"]
    params={};fractions={}
    for t,row in extract_costs()["parameters"].items():
        fractions[t]=policy.export_fraction(2014,t)
        params[t]=dict(fixed_real_cny_per_net_mw_year=row["fixed_usd_2018_per_net_mw_year"]*conversion,
            variable_real_cny_per_net_mwh=(row["variable_om_usd_2018_per_net_mwh"]+row["nuclear_fuel_usd_2018_per_net_mwh"])*conversion,
            overnight_real_cny_per_net_mw=row["overnight_usd_2018_per_net_kw"]*1000*conversion)
        if not convert_net_capex:
            # Control retains the previous gross-nameplate cost while changing
            # O&M only. This is NOT a reinterpretation of the source net unit.
            params[t]["overnight_real_cny_per_net_mw"]/=fractions[t]
    return GenerationCosts(parameters=params,reference_net_fractions=fractions,evidence=EVIDENCE)


def main():
    data,design,_=preflight()
    calibration="outputs/q2/p2_lb_national/calibration.json"
    theta=json.loads((ROOT/calibration).read_text("utf-8"))["best"]["parameters"]
    refs={(r["year"],r["category"]):r["value_twh"]*1e6 for r in extract()[0]}
    folder=ROOT/"outputs/q2_cost_review"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    specs={"legacy":None,"split_om_retained_capex":cost_inputs(data,design,convert_net_capex=False),
           "split_om_net_capex":cost_inputs(data,design)}
    sources=set(CODE+INPUTS+[calibration,SOURCE,EVIDENCE,__file__,
        "src/energy_model/q2_project_costs.py","scripts/build_q2_project_costs.py",
        "scripts/run_q2_historical_support.py","scripts/run_q2_empirical_support.py",
        "scripts/build_q2_revenue_evidence.py","scripts/build_q2_electricity_scope.py",
        "data/processed/q2/revenue/nea_tariff_and_auxiliary_use.csv",
        "data/raw/q2_fiscal/annual_renewable_levy.csv","data/raw/q2_technology_scope/ei_2025_original.xlsx"])
    outcomes={}
    for name,cost in specs.items():
        m,assumptions,prices,changes,extra=run_case(data,design,theta,generation_costs=cost)
        sources.update(extra)
        result=dict(assumptions=assumptions,cost_inputs=(cost.__dict__ if cost else None),
            metrics=metrics(m,refs),paths=m.paths,projects=m.projects,finance=m.finance,
            behavior=m.behavior,operations=m.operations,balances=m.balances,
            price_inputs=prices,lifetime_rule_changes=changes,fund_history=m.revenue_policy.history)
        (folder/(name+".json")).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n","utf-8")
        outcomes[name]={"metrics":result["metrics"],"end":m.paths[-1],
            "max_cash_residual_cny":max(abs(r["cash_balance_residual_cny"]) for r in m.paths)}
        print(name,{t:round(result["metrics"][t]["already_seen_evaluation"]["mape"]*100,2) for t in ("gas","oil","biomass","wind","solar")},flush=True)
    sources.update(json.loads((ROOT/"data/catalog/q2_revenue_review.json").read_text("utf-8"))["source_sha256"])
    sources.update(p.relative_to(ROOT).as_posix() for p in (ROOT/"data/raw/q2_fiscal").glob("*.html"))
    paths={(ROOT/p).resolve().relative_to(ROOT).as_posix() for p in sources}
    report=dict(status="conditional_cost_mechanism_comparison_not_acceptance",new_calibration=False,
        evaluation="already_seen_2022_2024_no_selection",future_plant_reference_is_not_historical_observation=True,
        source_sha256={p:sha(p) for p in sorted(paths)},results=outcomes)
    (folder/"results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n","utf-8")
    lines=["# 分项运维成本对照","","同一2015—2024路径，V10参数固定；IEA2025新机技术参考恒定外推旧机属于研究假设，未宣称历史实测或最终验收。","",
        "| 条件 | 气电MAPE | 纯油MAPE | 复合生物能源MAPE | 风电MAPE | 光伏MAPE |","|---|---:|---:|---:|---:|---:|"]
    for name,r in outcomes.items():
        lines.append("| "+name+" | "+" | ".join(f"{100*r['metrics'][t]['already_seen_evaluation']['mape']:.2f}%" for t in ("gas","oil","biomass","wind","solar"))+" |")
    lines += ["","MAPE均为2022—2024已接触评估。分项费用须按其含义修正；指标改善与否不改变源表单位。补贴承诺限制、项目资源/新老机组效率及垃圾边界尚需继续研究。",""]
    (folder/"report.md").write_text("\n".join(lines),"utf-8")
    print(folder.relative_to(ROOT).as_posix())


if __name__=="__main__":main()
