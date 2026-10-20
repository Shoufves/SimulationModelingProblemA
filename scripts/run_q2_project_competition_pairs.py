"""Fixed-parameter controls for unified-owner versus private-project decisions."""
from datetime import datetime,timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"scripts"),str(ROOT/"src")]
from q2_competition_factory import build
from q2_corrected_factory import preflight,metrics,extract,save,sha,training_loss
from review_q2_revenue_candidate import review


def main():
    previous = ROOT/"outputs/q2_thermal_pairs/20261019T235331010638Z"
    base = ROOT/"outputs/q2_revenue_recalibration/20261019T225922280430Z"
    review(base)
    sources = dict(json.loads((previous/"results.json").read_text("utf-8"))["source_sha256"])
    if any(sha(p)!=h for p,h in sources.items()):
        raise ValueError("Frozen thermal comparison source changed")
    for p in (Path(__file__).relative_to(ROOT).as_posix(),"scripts/q2_competition_factory.py",
              "src/energy_model/q2_project_competition.py","docs/sources/q2_project_competition.md",
              (previous/"results.json").relative_to(ROOT).as_posix()):
        sources[p] = sha(p)
    config = json.loads((base/"design.json").read_text("utf-8"))
    selected = json.loads((base/"training_selection.json").read_text("utf-8"))
    folder = ROOT/"outputs/q2_project_competition_pairs"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    save(folder/"design.json",dict(window="2015-2024",modes=["net55","net58"],authorities=[5,25,100],
        competition=[False,True],parameter_search=False,parameter_source=base.relative_to(ROOT).as_posix(),
        purpose="project-private objective versus aggregate-owner objective; no evaluation-based selection"))
    save(folder/"status.json",dict(status="running"))
    data,design,_ = preflight()
    refs = {(r["year"],r["category"]):r["value_twh"]*1e6 for r in extract()[0]}
    summary = {}
    try:
        for mode in ("net55","net58"):
            for authority in (5,25,100):
                params = selected["scenarios"][str(authority)]["parameters"]
                for enabled in (False,True):
                    m,assumptions,prices,changes,extra = build(data,design,config,params,authority,
                        end_year=2024,thermal_mode=mode,project_competition=enabled)
                    if not set(extra).issubset(sources):
                        raise ValueError("Unfrozen factory source")
                    if not enabled:
                        p = previous/f"authority_{authority}_{mode}.json"
                        sources[p.relative_to(ROOT).as_posix()] = sha(p)
                        old = json.loads(p.read_text("utf-8"))
                        for field in ("paths","finance","behavior","operations","projects","assets","balances","thermal_fuel_ledger"):
                            if getattr(m,field)!=old[field]:
                                raise ValueError("Disabled project competition differs: "+field)
                        if m.year_end_operation()!=old["year_end_operation"]:
                            raise ValueError("Disabled project competition snapshot differs")
                    label = f"{mode}_authority_{authority}_{'project' if enabled else 'owner'}"
                    score = metrics(m,refs)
                    entry = dict(metrics=score,training_loss=training_loss(m)[0],end=m.paths[-1],
                        autonomous_projects={t:sum(p["capacity_mw"] for p in m.projects if p["tech"]==t and not p["initial_reconstruction"])
                                             for t in ("coal","gas","wind","solar")},
                        max_cash_residual_cny=max(abs(r["cash_balance_residual_cny"]) for r in m.paths))
                    summary[label] = entry
                    save(folder/(label+".json"),dict(summary=entry,parameters=params,assumptions=assumptions,
                        price_inputs=prices,lifetime_rule_changes=changes,paths=m.paths,finance=m.finance,behavior=m.behavior,
                        operations=m.operations,projects=m.projects,assets=m.assets,balances=m.balances,
                        thermal_fuel_ledger=m.thermal_fuel_ledger,project_forecasts=m.project_forecasts,
                        project_operation_accounts=m.project_operation_accounts,year_end_operation=m.year_end_operation(),
                        fund_history=m.revenue_policy.history))
                    print(label,entry["training_loss"],entry["end"]["total_capacity_mw"],flush=True)
        if any(sha(p)!=h for p,h in sources.items()):
            raise ValueError("Sources changed during paired comparison")
        save(folder/"results.json",dict(source_sha256=sources,summary=summary,scientific_acceptance=False,
            default_inputs_changed=False,new_parameter_selection=False))
        save(folder/"status.json",dict(status="completed",cases=len(summary),scientific_acceptance=False))
        lines = ["# 项目竞争与统一业主固定参数对照", "", "全部12组保留；关闭时逐表精确恢复热机对照。未依据评估选择效率、财政额度或参数。", "",
                 "|案例|训练损失|2024总装机MW|气电MAPE|光伏MAPE|", "|---|---:|---:|---:|---:|"]
        for name,r in summary.items():
            lines.append(f"|{name}|{r['training_loss']:.6f}|{r['end']['total_capacity_mw']:.2f}|{r['metrics']['gas']['already_seen_evaluation']['mape']*100:.2f}%|{r['metrics']['solar']['already_seen_evaluation']['mape']*100:.2f}%|")
        (folder/"report.md").write_text("\n".join(lines)+"\n","utf-8")
    except Exception as exc:
        save(folder/"status.json",dict(status="failed",error=str(exc)))
        raise
    print(folder.relative_to(ROOT).as_posix(),flush=True)


if __name__=="__main__":
    main()
