"""Test price and new-plant heat rate jointly on the complete 2015-2019 window."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from q2_thermal_factory import build
from q2_corrected_factory import preflight, save, sha
from energy_model.q2_fuel_prices import AnnualFuelPrices, FuelPriceObservation
from review_q2_revenue_candidate import review


def main():
    base = ROOT / "outputs/q2_revenue_recalibration/20261019T225922280430Z"
    prices_run = ROOT / "outputs/q2_coal_index_window/20261019T233144607111Z"
    thermal_run = ROOT / "outputs/q2_thermal_pairs/20261019T235331010638Z"
    review(base)
    sources = {}
    for run in (base, prices_run, thermal_run):
        record = json.loads((run / "results.json").read_text("utf-8"))
        for path, digest in record["source_sha256"].items():
            if sha(path) != digest or (path in sources and sources[path] != digest):
                raise ValueError("Changed or conflicting parent source: " + path)
            sources[path] = digest
        sources[(run / "results.json").relative_to(ROOT).as_posix()] = sha(run / "results.json")
    index = json.loads((prices_run / "results.json").read_text("utf-8"))
    months = index["source_months"]
    if len({(r["year"], r["month"]) for r in months}) != 72 or len(months) != 72:
        raise ValueError("Complete 2014-2019 monthly inputs required")
    means = {}
    for year in range(2014, 2020):
        rows = [r for r in months if r["year"] == year]
        if {r["month"] for r in rows} != set(range(1, 13)):
            raise ValueError("Missing index months")
        means[year] = sum(r["value"] for r in rows) / 12
    design = json.loads((base / "design.json").read_text("utf-8"))
    selection = json.loads((base / "training_selection.json").read_text("utf-8"))
    if selection["selection_uses"] != "2015_2021_only":
        raise ValueError("Training-only fixed parameter provenance required")
    sources[Path(__file__).relative_to(ROOT).as_posix()] = sha(Path(__file__))
    folder = ROOT / "outputs/q2_thermal_coal_window" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    save(folder / "design.json", dict(thermal_modes=["net55", "net58"], authorities=[5,25,100],
        assumed_tax_divisors=[1.,1.17], initial_modes=["original", "index"],
        start_year=2015, end_year=2019, parameter_search=False,
        fixed_parameter_source=base.relative_to(ROOT).as_posix(),
        price_scope="conditional_shared_market_proxy; annual arithmetic month mean; tax unknown",
        mechanism_selection=False, technology_history="reference sensitivity; not observed fleet"))
    save(folder / "status.json", dict(status="running"))
    data, national, _ = preflight()
    summary = []
    try:
        for mode in ("net55", "net58"):
            for authority in (5,25,100):
                parameters = selection["scenarios"][str(authority)]["parameters"]
                reference, a, *_ = build(data, national, design, parameters, authority,
                                          end_year=2019, thermal_mode=mode)
                prior_path = thermal_run / f"authority_{authority}_{mode}.json"
                prior = json.loads(prior_path.read_text("utf-8"))
                sources[prior_path.relative_to(ROOT).as_posix()] = sha(prior_path)
                if reference.paths != [r for r in prior["paths"] if r["year"] <= 2019]:
                    raise ValueError("Thermal baseline prefix does not reproduce")
                cases = [("reference", reference, a)]
                for vat in (0., .17):
                    for initial in ("original", "index"):
                        rows = []
                        for year, mean in means.items():
                            price = mean / 5.815 * data[2024,"cpi"] / data[year,"cpi"] / (1+vat)
                            if year == 2014 and initial == "original":
                                price = reference.reference_fuel_prices["coal"]
                            rows.append(FuelPriceObservation(year,"coal",price,
                                f"CTCI monthly arithmetic mean; tax divisor {1+vat}; initial {initial}",
                                "conditional_shared_market_proxy"))
                        m, assumptions, *_, extra = build(data, national, design, parameters, authority,
                            end_year=2019, thermal_mode=mode, fuel_prices=AnnualFuelPrices(rows))
                        if not set(extra).issubset(sources):
                            raise ValueError("Unfrozen source used")
                        cases.append((f"tax_{vat}_initial_{initial}",m,assumptions))
                for name, model, assumptions in cases:
                    label = f"{mode}_authority_{authority}_{name}"
                    proposals = [r for r in model.behavior if r["kind"] == "investment_proposal" and r["actor"] == "coal"]
                    autonomous = [p for p in model.projects if p["tech"] == "coal" and not p["initial_reconstruction"]]
                    entry = dict(label=label, coal_new_approved_mw=sum(p["capacity_mw"] for p in autonomous),
                        coal_new_commissioned_mw=sum(p["capacity_mw"] for p in autonomous if p["status"] == "commissioned"),
                        coal_end_capacity_mw=model.paths[-1]["coal_capacity_mw"],
                        coal_proposal_npv_by_year={r["year"]: r["npv_cny_per_mw"] for r in proposals},
                        max_cash_residual_cny=max(abs(r["cash_balance_residual_cny"]) for r in model.paths))
                    summary.append(entry)
                    save(folder / (label+".json"), dict(summary=entry, assumptions=assumptions,
                        paths=model.paths, projects=model.projects, behavior=model.behavior, finance=model.finance,
                        operations=model.operations, balances=model.balances, price_history=model.fuel_price_history,
                        thermal_fuel_ledger=model.thermal_fuel_ledger))
                    print(label, entry["coal_new_approved_mw"], flush=True)
        if any(sha(path) != digest for path,digest in sources.items()):
            raise ValueError("Source changed during combined experiment")
        save(folder / "results.json", dict(source_sha256=sources, summary=summary,
            default_inputs_changed=False, scientific_acceptance=False, newly_calibrated=False))
        save(folder / "status.json", dict(status="completed", cases=len(summary), scientific_acceptance=False))
        lines = ["# 煤价与新机效率联合动态对照", "", "固定既有训练参数，全部30组报告；2015—2019完整月价格窗口，税基和共用市场仍为条件假设。", "",
                 "|案例|煤电新批准MW|新投产MW|2019装机MW|", "|---|---:|---:|---:|"]
        lines += [f"|{r['label']}|{r['coal_new_approved_mw']:.2f}|{r['coal_new_commissioned_mw']:.2f}|{r['coal_end_capacity_mw']:.2f}|" for r in summary]
        (folder / "report.md").write_text("\n".join(lines)+"\n", "utf-8")
    except Exception as exc:
        save(folder / "status.json", dict(status="failed", error=str(exc)))
        raise
    print(folder.relative_to(ROOT).as_posix(), flush=True)


if __name__ == "__main__":
    main()
