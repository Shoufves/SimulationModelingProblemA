"""Complete-source 2015--2019 dynamics, fixed parameters, all assumptions reported."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from run_q2_fuel_price_diagnostic import digest, preflight, review, save
from q2_fuel_price_factory import build
from energy_model.q2_fuel_prices import AnnualFuelPrices, FuelPriceObservation


def main():
    run = (ROOT / sys.argv[1]).resolve()
    if not run.is_relative_to(ROOT / "outputs/q2_revenue_recalibration"):
        raise ValueError("Expected historical calibration directory")
    review(run)
    sources = dict(json.loads((run / "results.json").read_text("utf-8"))["source_sha256"])
    config = json.loads((run / "design.json").read_text("utf-8"))
    selection = json.loads((run / "training_selection.json").read_text("utf-8"))
    if selection["selection_uses"] != "2015_2021_only":
        raise ValueError("Training parameter provenance failed")
    months = {}
    for subdir in ("q2_coal_prices", "q2_coal_prices_extension"):
        base = ROOT / "data/raw" / subdir
        manifest = json.loads((base / "source_manifest.json").read_text("utf-8"))
        for item in manifest:
            if digest(ROOT / item["path"]) != item["sha256"]:
                raise ValueError("Changed index original")
            sources[item["path"]] = item["sha256"]
        for name in ("evidence.json", "source_manifest.json"):
            sources[(base / name).relative_to(ROOT).as_posix()] = digest(base / name)
        evidence = json.loads((base / "evidence.json").read_text("utf-8"))
        for row in evidence["deduplicated_national_months"]:
            if row["value"] is None:
                continue
            key = row["year"], row["month"]
            if key in months and months[key]["value"] != row["value"]:
                raise ValueError("Conflicting monthly index")
            if digest(ROOT / row["source"]) != row["source_sha256"]:
                raise ValueError("Broken monthly provenance")
            months.setdefault(key, row)
    means = {}
    for year in range(2014, 2020):
        if any((year, month) not in months for month in range(1, 13)):
            raise ValueError(f"Incomplete year {year}; no annual proxy generated")
        means[year] = sum(months[year, month]["value"] for month in range(1, 13)) / 12
    for path in (Path(__file__), ROOT / "scripts/run_q2_fuel_price_diagnostic.py",
                 ROOT / "scripts/q2_fuel_price_factory.py", ROOT / "src/energy_model/q2_fuel_prices.py",
                 ROOT / "scripts/collect_q2_coal_prices_extension.py", ROOT / "docs/sources/q2_coal_index_window.md",
                 run / "results.json", run / "training_selection.json", run / "design.json"):
        sources[path.relative_to(ROOT).as_posix()] = digest(path)
    folder = ROOT / "outputs/q2_coal_index_window" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    save(folder / "design.json", dict(start_year=2015, end_year=2019, initial_year=2014,
        authority_scenarios=[5, 25, 100], assumed_vat=[0, .17],
        initial_modes=["original_initial_price", "index_initial_price"],
        parameter_source=run.relative_to(ROOT).as_posix(), parameter_search=False,
        classification="conditional_shared_market_price_sensitivity_not_calibration"))
    save(folder / "status.json", dict(status="running"))
    data, design, _ = preflight()
    summaries = []
    try:
        for authority in (5, 25, 100):
            parameters = selection["scenarios"][str(authority)]["parameters"]
            reference, assumptions, *_ = build(data, design, config, parameters, authority, end_year=2019)
            old = json.loads((run / f"authority_{authority}_full.json").read_text("utf-8"))
            if reference.paths != [r for r in old["paths"] if r["year"] <= 2019]:
                raise ValueError("Reference does not reproduce old training prefix")
            cases = [("reference", reference, assumptions)]
            for tax in (0, .17):
                for mode in ("original_initial_price", "index_initial_price"):
                    rows = []
                    for year, mean in means.items():
                        # Tax basis is deliberately a scenario, not a statement
                        # about national VAT rules or the index's tax definition.
                        value = mean / 5.815 * data[2024, "cpi"] / data[year, "cpi"] / (1 + tax)
                        evidence = f"archived CTCI {year} 12-month mean; assumed tax divisor {1+tax}"
                        if year == 2014 and mode == "original_initial_price":
                            value = reference.reference_fuel_prices["coal"]
                            evidence = "original initial-year technical-price assumption"
                        rows.append(FuelPriceObservation(year, "coal", value, evidence, "conditional_shared_market_proxy"))
                    m, a, *_ = build(data, design, config, parameters, authority, end_year=2019,
                                     fuel_prices=AnnualFuelPrices(rows))
                    cases.append((f"vat_{tax}_{mode}", m, {**a, "assumed_vat": tax, "initial_mode": mode}))
            for name, model, assumptions in cases:
                label = f"authority_{authority}_{name}"
                projects = [p for p in model.projects if p["tech"] == "coal" and p["decision_year"] >= 2015]
                proposals = [r for r in model.behavior if r["kind"] == "investment_proposal" and r["actor"] == "coal"]
                summary = dict(label=label, authority=authority,
                    coal_approved_mw=sum(p["capacity_mw"] for p in projects),
                    coal_end_capacity_mw=model.paths[-1]["coal_capacity_mw"],
                    coal_npv_by_year={r["year"]: r["npv_cny_per_mw"] for r in proposals},
                    max_cash_balance_residual_cny=max(abs(r["cash_balance_residual_cny"]) for r in model.paths),
                    end=model.paths[-1])
                summaries.append(summary)
                save(folder / (label + ".json"), dict(summary=summary, assumptions=assumptions,
                    price_history=model.fuel_price_history, paths=model.paths, finance=model.finance,
                    behavior=model.behavior, projects=model.projects, operations=model.operations, balances=model.balances))
        mismatch = [p for p, h in sources.items() if digest(ROOT / p) != h]
        if mismatch:
            raise ValueError("Source changed during run: " + str(mismatch))
        save(folder / "results.json", dict(source_sha256=sources, summary=summaries,
            annual_arithmetic_means=means, source_months=[months[y, m] for y in means for m in range(1, 13)],
            default_inputs_changed=False, actual_model_rerun=True, scientific_acceptance=False,
            newly_calibrated=False, national_tax_basis_verified=False,
            power_price_as_nonpower_observation=False))
        lines = ["# 2015—2019完整月指数窗口：动态机制对照", "",
                 "15组固定参数实际重跑。税基及共用市场范围是假设；不改默认输入、不按结果选参数。",
                 "", "|案例|累计煤电批准MW|2019煤电装机MW|2019煤电NPV 元/MW|最大现金残差 元|",
                 "|---|---:|---:|---:|---:|"]
        for r in summaries:
            lines.append(f"|{r['label']}|{r['coal_approved_mw']:.2f}|{r['coal_end_capacity_mw']:.2f}|{r['coal_npv_by_year'][2019]:.2f}|{r['max_cash_balance_residual_cny']:.6f}|")
        lines += ["", "仅2014—2019月指数完整；2020以后资料缺口不以年内部分月份代替全年。这里只诊断历史价格与学习路径，不能宣布2024总装机或全国历史拟合已通过。"]
        (folder / "report.md").write_text("\n".join(lines) + "\n", "utf-8")
        save(folder / "status.json", dict(status="completed", scientific_acceptance=False))
    except Exception as exc:
        save(folder / "status.json", dict(status="failed", error=str(exc)))
        raise
    print(folder.relative_to(ROOT).as_posix())
    print(json.dumps([{k: v for k, v in r.items() if k != "end"} for r in summaries], ensure_ascii=False))


if __name__ == "__main__":
    main()
