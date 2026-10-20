"""Fixed-parameter dynamic early-coal-price sensitivity; no national admission."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from q2_corrected_factory import preflight
from q2_fuel_price_factory import build
from energy_model.q2_fuel_prices import AnnualFuelPrices, FuelPriceObservation
from review_q2_revenue_candidate import review
from run_q2_revenue_recalibration import save


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    run = (ROOT / sys.argv[1]).resolve()
    if not run.is_relative_to(ROOT / "outputs/q2_revenue_recalibration"):
        raise ValueError("Expected a frozen historical training run")
    review(run)
    config = json.loads((run / "design.json").read_text("utf-8"))
    selected = json.loads((run / "training_selection.json").read_text("utf-8"))
    if selected["selection_uses"] != "2015_2021_only":
        raise ValueError("Parameters were not selected on training only")
    old_results = json.loads((run / "results.json").read_text("utf-8"))
    sources = dict(old_results["source_sha256"])
    evidence_path = ROOT / "data/raw/q2_coal_prices/evidence.json"
    evidence = json.loads(evidence_path.read_text("utf-8"))
    manifest_path = evidence_path.with_name("source_manifest.json")
    manifest = json.loads(manifest_path.read_text("utf-8"))
    for item in manifest:
        if digest(ROOT / item["path"]) != item["sha256"]:
            raise ValueError("Changed coal-price original")
        sources[item["path"]] = item["sha256"]
    means = {}
    for year in (2014, 2015):
        rows = [r for r in evidence["deduplicated_national_months"] if r["year"] == year]
        if len(rows) != 12 or {r["month"] for r in rows} != set(range(1, 13)) or any(r["value"] is None for r in rows):
            raise ValueError("Missing complete initial/operating-year price observations")
        means[year] = sum(r["value"] for r in rows) / 12
        if abs(means[year] - evidence["annual_simple_means"][str(year)]) > 1e-9:
            raise ValueError("Annual mean disagrees with monthly source")
    for path in (Path(__file__), ROOT / "scripts/q2_fuel_price_factory.py",
                 ROOT / "src/energy_model/q2_fuel_prices.py", ROOT / "docs/sources/q2_fuel_price_timing.md",
                 evidence_path, manifest_path, run / "training_selection.json", run / "design.json", run / "results.json"):
        sources[path.relative_to(ROOT).as_posix()] = digest(path)
    folder = ROOT / "outputs/q2_fuel_price_diagnostic" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    save(folder / "design.json", dict(parameter_source=run.relative_to(ROOT).as_posix(),
        authority_scenarios=[5, 25, 100], assumed_vat=[0, .17], end_year=2015,
        initial_modes=["original_initial_price", "index_initial_price"],
        status="conditional_shared_market_sensitivity_not_national_calibration"))
    save(folder / "status.json", dict(status="running"))
    data, design, _ = preflight()
    summaries, exact_checks = [], []
    try:
        for authority in (5, 25, 100):
            parameters = selected["scenarios"][str(authority)]["parameters"]
            baseline, *_ = build(data, design, config, parameters, authority, end_year=2024)
            previous = json.loads((run / f"authority_{authority}_full.json").read_text("utf-8"))
            for name in ("paths", "finance", "behavior", "operations", "projects", "assets", "balances"):
                if getattr(baseline, name) != previous[name]:
                    raise ValueError(f"Disabled price factory differs from frozen {authority}: {name}")
            exact_checks.append(dict(authority=authority, years="2015-2024", exact=True))
            original = baseline.reference_fuel_prices["coal"]
            def record(model, label, assumptions, tax=None, initial=None):
                y = model.paths[0]
                proposal = next(r for r in model.behavior if r["year"] == 2015 and r["actor"] == "coal"
                                and r["kind"] == "investment_proposal")
                summary = dict(label=label, authority=authority, assumed_vat=tax, initial_mode=initial,
                    coal_generation_mwh=y["coal_generation_mwh"], total_capacity_mw=y["total_capacity_mw"],
                    coal_npv_cny_per_mw=proposal["npv_cny_per_mw"],
                    coal_expected_margin_cny_per_mw=proposal["expected_new_project_margin_cny_per_mw"],
                    coal_requested_mw=proposal["requested_mw"],
                    coal_approved_mw=sum(p["capacity_mw"] for p in model.projects if p["tech"] == "coal" and p["decision_year"] == 2015),
                    cash_balance_residual_cny=y["cash_balance_residual_cny"])
                summaries.append(summary)
                save(folder / (label + ".json"), dict(summary=summary, assumptions=assumptions,
                    price_history=model.fuel_price_history, paths=model.paths, finance=model.finance,
                    behavior=model.behavior, operations=model.operations, projects=model.projects))
            short, assumptions, *_ = build(data, design, config, parameters, authority, end_year=2015)
            record(short, f"authority_{authority}_reference", assumptions)
            for tax in (0, .17):
                for initial in ("original_initial_price", "index_initial_price"):
                    inputs = []
                    for year in (2014, 2015):
                        value = means[year] / evidence["heat_mwh_per_tonne"] * data[2024, "cpi"] / data[year, "cpi"] / (1 + tax)
                        locator = f"data/raw/q2_coal_prices/evidence.json; {year} monthly arithmetic mean; assumed VAT={tax}"
                        if year == 2014 and initial == "original_initial_price":
                            value, locator = original, "unchanged technical-reference initial price"
                        inputs.append(FuelPriceObservation(year, "coal", value, locator, "conditional_shared_market_proxy"))
                    model, assumptions, *_ = build(data, design, config, parameters, authority,
                                                   end_year=2015, fuel_prices=AnnualFuelPrices(inputs))
                    label = f"authority_{authority}_vat_{tax}_{initial}"
                    record(model, label, assumptions, tax, initial)
        mismatches = [p for p, h in sources.items() if digest(ROOT / p) != h]
        if mismatches:
            raise ValueError("Sources changed during diagnostic: " + str(mismatches))
        save(folder / "results.json", dict(source_sha256=sources, summary=summaries,
            disabled_factory_exact_checks=exact_checks, actual_model_rerun=True, selected_on_results=False,
            scientific_acceptance=False, default_inputs_changed=False,
            limits=["power index is only a shared-market sensitivity", "index tax basis unverified",
                    "2015 endpoint cannot establish later capacity fit", "monthly arithmetic mean is not procurement-weighted annual price"]))
        lines = ["# 2015年煤价动态敏感性", "", "固定训练参数；三组权限均报告。电煤指数仅作共用市场敏感性，税基未核清，未改默认输入。",
                 "", "|案例|煤电NPV 元/MW|申请MW|批准MW|煤电发电TWh|", "|---|---:|---:|---:|---:|"]
        for r in summaries:
            lines.append(f"|{r['label']}|{r['coal_npv_cny_per_mw']:.2f}|{r['coal_requested_mw']:.2f}|{r['coal_approved_mw']:.2f}|{r['coal_generation_mwh']/1e6:.2f}|")
        lines += ["", "关闭接口，三组完整2015—2024路径及财务、行为、运行、项目、资产、守恒与原实验逐项一致。",
                  "", "这是实际动态重跑，不是固定发电量的会计回算。2015终点不能证明后续装机误差改善；共用价格同时作用于非电需求，不能将全部差异解释为电厂成本效应。"]
        (folder / "report.md").write_text("\n".join(lines) + "\n", "utf-8")
        save(folder / "status.json", dict(status="completed", scientific_acceptance=False))
    except Exception as exc:
        save(folder / "status.json", dict(status="failed", error=str(exc)))
        raise
    print(folder.relative_to(ROOT).as_posix())
    print(json.dumps(summaries, ensure_ascii=False))


if __name__ == "__main__":
    main()
