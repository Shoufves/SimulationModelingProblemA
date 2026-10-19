"""Read-only model probes; writes separate evidence, never recalibrates S0.

Counterexamples are diagnostics, not proposed policy settings or new forecasts.
"""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from run_q2_national import preflight
from energy_model.q2_national import NationalModel, TECHS, operate_national


def rows(name):
    with (ROOT / "outputs/q2/p2_lb_national" / name).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    data, design, _ = preflight()
    if design["model_revision"] != 4:
        raise ValueError("V4-only historical diagnostic. Original code, design and evidence are preserved in archive/q2_national_v4_mechanism_review.zip; use the current delivery review for revision 5.")
    theta = json.loads((ROOT / "outputs/q2/p2_lb_national/calibration.json").read_text(encoding="utf-8"))["best"]["parameters"]
    report = {"reviewed_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "purpose": "Independent mechanism diagnostics; no calibration or production output replacement"}

    def model(**kw):
        return NationalModel(data, design, theta, 2024, **kw)

    # Identical physical initial state; change only carbon price.
    pairs = [model(variant={"carbon_price_multiplier": v}) for v in (0, 100)]
    ops, results, devices, margins = [], [], [], []
    for m in pairs:
        m.drivers(); m.mature()
        op = m.make_operation(); result = operate_national(op)
        _, margin = m.settle(op, result)
        ops.append(op); results.append(result); margins.append(margin)
        devices.append([c.proposal() for c in m.consumers.values()])
    report["carbon_same_state"] = {
        "prices_cny_per_t": [m.carbon for m in pairs],
        "lp_inputs_exactly_equal": ops[0] == ops[1],
        "dispatch_exactly_equal": results[0] == results[1],
        "device_proposals_exactly_equal": devices[0] == devices[1],
        "coal_margin_cny_per_mw": [x["coal"] for x in margins],
        "interpretation": "Price reaches generator settlement, but not dispatch or device choice. Resource-cost dispatch may be deliberate; no conclusion that carbon has zero effect at all prices."}
    sensitivity = rows("sensitivity.csv")
    report["carbon_published_sensitivity"] = {
        label: {"rows": len(selected), "max_abs_delta": max(abs(float(r["delta_from_S0"])) for r in selected if r["delta_from_S0"])}
        for label in ("carbon_price_multiplier=0.5", "carbon_price_multiplier=1.5")
        if (selected := [r for r in sensitivity if r["label"] == label])}

    # Change cash only, holding expectations, costs and national financing fixed.
    cash_models = [model() for _ in range(2)]
    for m, cash in zip(cash_models, (1e15, -1e15)):
        for g in m.generators.values():
            g.cash = cash
        m.step()
    projects = [[p for p in m.projects if not p["initial_reconstruction"]] for m in cash_models]
    report["cash_counterexample"] = {
        "initial_cash_per_generator_cny": [1e15, -1e15],
        "approved_projects_exactly_equal": projects[0] == projects[1],
        "approved_capacity_mw": [sum(p["capacity_mw"] for p in pp) for pp in projects],
        "approved_cost_cny": [sum(p["cost"] for p in pp) for pp in projects]}

    # Adding source nameplate silently adds equal network capacity.
    m = model(); m.drivers(); m.mature()
    before = m.make_operation()
    m.cohorts.append(dict(tech="solar", status="active", capacity_mw=1000000))
    after = m.make_operation()
    report["grid_counterexample"] = {
        "added_solar_mw": 1000000,
        "grid_limit_delta_mw": after["grid"]["power_mw"] - before["grid"]["power_mw"],
        "construction_cost_cny": m.construction_cost,
        "note": "State perturbation isolates mapping; no commissioned grid asset was added."}

    # Reproduce all years once and retain diagnostic operation snapshots.
    m = model()
    captures = {}
    storage_gaps = []
    prev_close = None
    while m.year <= 2060:
        m.step()
        y = m.year - 1
        st = [r for r in m.operations if r["year"] == y and r["kind"] == "storage"]
        if prev_close is not None:
            storage_gaps.append(dict(year=y, opening_minus_prior_close_mwh=st[0]["opening_mwh"] - prev_close))
        prev_close = st[-1]["closing_mwh"]
        row = m.paths[-1]
        if y in (2025, 2030, 2040, 2050, 2060):
            captures[y] = dict(row)
            for t in ("wind", "solar"):
                available = sum(min(1, m.generators[t].reference_cf * shape) * 6 for shape in m.a[t + "_shape"])
                potential = row[t + "_capacity_mw"] * available * 365
                captures[y][t + "_available_generation_mwh"] = potential
                captures[y][t + "_unused_available_fraction"] = 1 - row[t + "_generation_mwh"] / potential
                captures[y][t + "_realised_cf"] = row[t + "_generation_mwh"] / (row[t + "_capacity_mw"] * 8760)
            captures[y]["unmet_share"] = row["unmet_service_mwh"] / row["requested_service_mwh"]
    old = rows("baseline_path.csv")
    report["baseline_reproduction_max_relative_difference"] = max(
        abs(float(r[k]) - oldv) / max(1, abs(oldv))
        for r, o in zip(m.paths, old) for k in r if isinstance(r[k], (int, float))
        for oldv in [float(o[k])])
    report["snapshots"] = captures
    report["storage_boundary_gaps"] = storage_gaps
    report["solar_requests"] = [r for r in m.behavior if r["actor"] == "solar" and r["kind"] == "investment_proposal"]
    report["loss_making_generators_2060"] = [r for r in m.finance if r["year"] == 2060 and r["kind"] == "generator_operation" and r["cash_delta_cny"] < 0]
    report["storage_curtailment_feedback_all_zero"] = all(r["previous_curtailment_mwh"] == 0 for r in m.behavior if r["kind"] == "storage_proposal")
    report["unmet_by_sector_2060_mwh"] = {sector: sum(r["unmet_service_mwh"] * 365 for r in m.operations if r["year"] == 2060 and r["kind"] == "demand" and r["sector"] == sector)
        for sector in sorted({r["sector"] for r in m.operations if r["kind"] == "demand"})}
    report["demand_extrapolation"] = {
        "electricity_elasticity": m.electric_elasticity,
        "gdp_ratio_2060_vs_2024": m.gdp / m.gdp0,
        "existing_electricity_multiplier_2060": (m.gdp / m.gdp0) ** m.electric_elasticity * .99 ** 36,
        "constant_elasticity_0_7_multiplier_only": (m.gdp / m.gdp0) ** .7 * .99 ** 36,
        "note": "Formula-only counterfactual; 0.7 is a diagnostic value, not calibrated or recommended."}
    report["bridge"] = {"peo_mwh_per_clean_mwh": m.peo_coefficient,
        "historical_2024_gcb_btr_bridge_t": data[2024, "gcb_positive_co2_t"] * data[2021, "btr_positive_co2_t"] / data[2021, "gcb_positive_co2_t"],
        "forecast_2025_positive_co2_t": m.paths[0]["positive_co2_t"]}
    # Anchor-only bookkeeping reconstruction, not a simulation or correction.
    fuel_total = data[2024, "consumption_10ktce"] * 1e4 * (29.3076 / 3.6)
    from energy_model.q2_national import EF
    reconstructed = sum(fuel_total * data[2024, "consumption_" + f + "_pct"] / 100 * (1-m.a["nonenergy_fuel_fraction"][f]) * EF[f] for f in ("coal", "oil", "gas"))
    process_2024 = (data[2021, "btr_process_co2_t"] + data[2021, "btr_waste_co2_t"]) * (data[2024, "real_gdp"] / data[2021, "real_gdp"]) ** .5 * .98 ** 3
    report["bridge"]["initial_2024_formula_positive_co2_t"] = reconstructed + process_2024
    files = ["src/energy_model/q2_national.py", "src/energy_model/q2_operations.py", "workflow/q2_national_design.json", "data/processed/q2/national_observations.csv", "outputs/q2/p2_lb_national/calibration.json", "outputs/q2/p2_lb_national/baseline_path.csv", "scripts/diagnose_q2_national_mechanisms.py"]
    report["sha256"] = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files}
    folder = ROOT / "outputs/q2_review/p2_lb_mechanism_diagnosis"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k not in {"snapshots", "solar_requests", "storage_boundary_gaps", "sha256"}}, ensure_ascii=False, indent=2))
    for year, row in captures.items():
        print(year, json.dumps({k:v for k,v in row.items() if "capacity_mw" in k or "unused_available" in k or k == "unmet_share"}))


if __name__ == "__main__":
    main()
