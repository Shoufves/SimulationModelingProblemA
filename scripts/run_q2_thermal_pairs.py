"""Three authority conditions x two new technologies and disabled control."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from q2_thermal_factory import build
from q2_corrected_factory import preflight, metrics, extract, save, sha
from review_q2_revenue_candidate import review


def main():
    run = (ROOT / sys.argv[1]).resolve()
    if not run.is_relative_to(ROOT / "outputs/q2_revenue_recalibration"):
        raise ValueError("Expected a frozen historical training run")
    review(run)
    config = json.loads((run / "design.json").read_text("utf-8"))
    selected = json.loads((run / "training_selection.json").read_text("utf-8"))
    sources = dict(json.loads((run / "results.json").read_text("utf-8"))["source_sha256"])
    for p in (Path(__file__).relative_to(ROOT).as_posix(), "src/energy_model/q2_thermal_vintages.py",
              "scripts/q2_thermal_factory.py", "docs/sources/q2_thermal_vintages.md",
              "src/energy_model/q2_fuel_prices.py", "scripts/q2_fuel_price_factory.py",
              (run / "results.json").relative_to(ROOT).as_posix(),
              (run / "training_selection.json").relative_to(ROOT).as_posix()):
        sources[p] = sha(p)
    folder = ROOT / "outputs/q2_thermal_pairs" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    save(folder / "design.json", dict(source_run=run.relative_to(ROOT).as_posix(),
        modes=["disabled", "net55", "net58"], authorities=[5,25,100],
        window="2015-2024", parameter_selection="existing training-only selection; no new search",
        evaluation="2022-2024 already seen; no mechanism selection"))
    save(folder / "status.json", dict(status="running"))
    data, design, _ = preflight()
    refs = {(r["year"], r["category"]): r["value_twh"]*1e6 for r in extract()[0]}
    summaries = {}
    try:
        for authority in (5,25,100):
            parameters = selected["scenarios"][str(authority)]["parameters"]
            for mode in ("disabled", "net55", "net58"):
                model, assumptions, prices, changes, extra = build(data, design, config, parameters, authority,
                                                                 end_year=2024, thermal_mode=mode)
                for p in extra:
                    sources.setdefault(p, sha(p))
                if mode == "disabled":
                    old = json.loads((run / f"authority_{authority}_full.json").read_text("utf-8"))
                    for field in ("paths", "finance", "behavior", "operations", "projects", "assets", "balances"):
                        if getattr(model, field) != old[field]:
                            raise ValueError(f"Disabled thermal module differs: {field}")
                score = metrics(model, refs)
                label = f"authority_{authority}_{mode}"
                record = dict(assumptions=assumptions, metrics=score, price_inputs=prices, lifetime_rule_changes=changes,
                    paths=model.paths, projects=model.projects, finance=model.finance, behavior=model.behavior,
                    operations=model.operations, assets=model.assets, balances=model.balances,
                    thermal_fuel_ledger=model.thermal_fuel_ledger,
                    fund_history=model.revenue_policy.history, year_end_operation=model.year_end_operation())
                save(folder / (label + ".json"), record)
                summaries[label] = dict(metrics=score, end=model.paths[-1],
                    autonomous_thermal_projects={t:sum(1 for p in model.projects if p["tech"]==t and not p["initial_reconstruction"]) for t in ("coal","gas")},
                    max_cash_residual=max(abs(r["cash_balance_residual_cny"]) for r in model.paths))
                print(label, summaries[label]["autonomous_thermal_projects"], flush=True)
        if any(sha(p) != h for p,h in sources.items()):
            raise ValueError("Experiment source changed during run")
        save(folder / "results.json", dict(source_sha256=sources, summary=summaries,
            parameter_selection=False, mechanism_selection=False, scientific_acceptance=False))
        save(folder / "status.json", dict(status="completed", scientific_acceptance=False))
        lines=["# 新老煤气机组固定参数对照", "", "三组承诺条件和两种新机效率全部报告；评估已接触，未据结果选机制。", "",
               "|案例|煤电自主项目数|气电自主项目数|气电发电MAPE|2024总装机MW|", "|---|---:|---:|---:|---:|"]
        for label,r in summaries.items():
            lines.append(f"|{label}|{r['autonomous_thermal_projects']['coal']}|{r['autonomous_thermal_projects']['gas']}|{r['metrics']['gas']['already_seen_evaluation']['mape']*100:.2f}%|{r['end']['total_capacity_mw']:.2f}|")
        lines += ["", "实际项目、燃料/碳队列、现金与年末状态均已保存。此对照固定旧参数，不能替代新机制重训和逐项科学验收。"]
        (folder / "report.md").write_text("\n".join(lines)+"\n", "utf-8")
    except Exception as exc:
        save(folder / "status.json", dict(status="failed", error=str(exc)))
        raise
    print(folder.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
