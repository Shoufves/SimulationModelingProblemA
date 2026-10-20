"""Fixed-path new-project efficiency consistency diagnostic, not new dispatch."""
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from build_q2_project_costs import cells, SOURCE, HASH
from run_q2_fuel_price_diagnostic import digest, preflight, save
from q2_fuel_price_factory import build


def main():
    folder = (ROOT / sys.argv[1]).resolve()
    if not folder.is_relative_to(ROOT / "outputs/q2_coal_index_window"):
        raise ValueError("Expected completed coal-index window")
    result = json.loads((folder / "results.json").read_text("utf-8"))
    sources = dict(result["source_sha256"])
    if any(digest(ROOT / p) != h for p, h in sources.items()):
        raise ValueError("Changed diagnostic input")
    if digest(ROOT / SOURCE) != HASH:
        raise ValueError("Changed IEA workbook")
    book = cells(ROOT / SOURCE)
    specifications = {"coal": ("3.3", 22, "Ultra-supercritical"), "gas": ("3.2.a.b", 24, "CCGT")}
    net_efficiencies = {}
    for tech, (sheet, row, name) in specifications.items():
        table = book[sheet]
        if table[f"B{row}"] != "China" or table[f"C{row}"] != name or "efficiency" not in str(table["E4"]).lower():
            raise ValueError("Unverified technical efficiency cell")
        net_efficiencies[tech] = table[f"E{row}"]
    design_record = json.loads((folder / "design.json").read_text("utf-8"))
    prior = ROOT / design_record["parameter_source"]
    config = json.loads((prior / "design.json").read_text("utf-8"))
    selected = json.loads((prior / "training_selection.json").read_text("utf-8"))
    data, design, _ = preflight()
    rows, definitions = [], {}
    for authority in (5, 25, 100):
        parameters = selected["scenarios"][str(authority)]["parameters"]
        baseline, *_ = build(data, design, config, parameters, authority, end_year=2015)
        rate = baseline.theta["expectation_rate"]
        for summary in result["summary"]:
            if summary["authority"] != authority:
                continue
            path = folder / (summary["label"] + ".json")
            case = json.loads(path.read_text("utf-8"))
            sources[path.relative_to(ROOT).as_posix()] = digest(path)
            actual_prices = {(r["year"], r["fuel"]): r["effective_price_real_2024_cny_per_mwh"]
                             for r in case["price_history"]}
            for tech in ("coal", "gas"):
                eta_old = baseline.efficiency[tech]
                net_fraction = baseline.generation_costs.reference_net_fractions[tech]
                eta_new = net_efficiencies[tech] / net_fraction
                if not 0 < eta_old <= 1 or not 0 < eta_new <= 1:
                    raise ValueError("Invalid net-to-gross efficiency conversion")
                definitions[tech] = dict(source_cell=f"{specifications[tech][0]}!E{specifications[tech][1]}",
                    net_efficiency=net_efficiencies[tech], reference_net_fraction=net_fraction,
                    candidate_gross_efficiency=eta_new, existing_gross_efficiency=eta_old,
                    note="2025 hypothetical new plant; constant historical application is a scenario, not observation")
                initial_price = actual_prices.get((2014, tech), baseline.reference_fuel_prices[tech])
                difference = baseline.generators[tech].reference_cf * 8760 * initial_price * (1 / eta_old - 1 / eta_new)
                for year in range(2015, 2020):
                    operation = next(r for r in case["finance"] if r["kind"] == "generator_operation"
                                     and r["actor"] == tech and r["year"] == year)
                    proposal = next(r for r in case["behavior"] if r["kind"] == "investment_proposal"
                                    and r["actor"] == tech and r["year"] == year)
                    generation = next(r for r in case["paths"] if r["year"] == year)[tech + "_generation_mwh"]
                    exposure = operation["operating_exposure_mw_year"]
                    price = actual_prices.get((year, tech), baseline.reference_fuel_prices[tech])
                    hours = generation / exposure if exposure else 0
                    savings = hours * price * (1 / eta_old - 1 / eta_new)
                    if exposure:
                        difference = (1 - rate) * difference + rate * savings
                    old_npv = proposal["npv_cny_per_mw"]
                    adjusted_npv = old_npv + difference * proposal["expected_operating_pv_factor"]
                    rows.append(dict(case=summary["label"], authority=authority, year=year, tech=tech,
                        fixed_path_realised_savings_cny_per_mw=savings,
                        learned_margin_difference_cny_per_mw=difference,
                        original_npv_cny_per_mw=old_npv, candidate_npv_cny_per_mw=adjusted_npv,
                        sign_changes=old_npv <= 0 < adjusted_npv))
    for path in (Path(__file__), folder / "results.json", folder / "design.json"):
        sources[path.relative_to(ROOT).as_posix()] = digest(path)
    sources[SOURCE] = HASH
    if any(digest(ROOT / p) != h for p, h in sources.items()):
        raise ValueError("Changed source during efficiency diagnosis")
    output = dict(created_at=datetime.now(timezone.utc).isoformat(), source_sha256=sources,
        scope="fixed_2015_2019_paths_new_project_profit_consistency_only", definitions=definitions, rows=rows,
        actual_model_rerun=False, new_projects_approved=False, default_inputs_changed=False,
        scientific_acceptance=False,
        limits=["new-plant 2025 reference is not annual historical fleet efficiency",
                "fixed output and cost; no dispatch/investment/cash effects simulated",
                "actual implementation needs cohort efficiencies and fuel/emission conservation",
                "2015-2019 precedes model ETS; formula must include ETS effects for later windows"])
    target = ROOT / "outputs/validation/new_thermal_efficiency_diagnostic_20261020.json"
    save(target, output)
    print(json.dumps(dict(definitions=definitions, sign_changes=[r for r in rows if r["sign_changes"]]), ensure_ascii=False))


if __name__ == "__main__":
    main()
