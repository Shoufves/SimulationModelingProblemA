"""Read-only arithmetic capacity gap and revealed investment constraint diagnosis."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import fsum
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from q2_corrected_factory import preflight, extract
from run_q2_empirical_support import reviewed_capacity_history

RUNS = {
    "net55": Path("outputs/q2_revenue_recalibration/20261020T001729046749Z"),
    "net58": Path("outputs/q2_revenue_recalibration/20261020T001729054583Z"),
}
TECHS = ("coal", "gas", "oil", "biomass", "hydro", "nuclear", "wind", "solar")


def read(path):
    return json.loads((ROOT / path).read_text("utf-8"))


def main():
    data, _, _ = preflight()
    historical, _, _, _ = reviewed_capacity_history()
    official = {key: data[2024, key + "_capacity_mw"] for key in ("thermal", "hydro", "nuclear", "wind", "solar", "other")}
    assert fsum(official.values()) == data[2024, "total_capacity_mw"]
    references = {(r["year"], r["category"]): r["value_twh"] * 1e6 for r in extract()[0]}
    results, source_hashes = {}, {}
    for mode, run in RUNS.items():
        assert read(run / "status.json")["status"] == "complete_conditional_experiment"
        assert read(run / "design.json")["model_factory"] == "q2_competition_factory:build"
        for authority in (5, 25, 100):
            path = run / f"authority_{authority}_full.json"
            case = read(path)
            source_hashes[path.as_posix()] = sha256((ROOT / path).read_bytes()).hexdigest()
            end = case["paths"][-1]
            model_groups = {
                "thermal": fsum(end[t + "_capacity_mw"] for t in ("coal", "gas", "oil", "biomass"))
                    + end["supplementary_capacity_mw"] - end["pumped_capacity_mw"],
                "hydro": end["hydro_including_pumped_capacity_mw"],
                "nuclear": end["nuclear_capacity_mw"], "wind": end["wind_capacity_mw"],
                "solar": end["solar_capacity_mw"], "other": 0.,
            }
            assert abs(fsum(model_groups.values()) - end["total_capacity_mw"]) < 1e-6
            gap = data[2024, "total_capacity_mw"] - end["total_capacity_mw"]
            decomposition = {
                key: dict(observed_mw=official[key], model_mw=model_groups[key],
                          missing_mw=official[key]-model_groups[key],
                          share_of_total_gap=(official[key]-model_groups[key])/gap)
                for key in official
            }
            assert abs(fsum(d["missing_mw"] for d in decomposition.values()) - gap) < 1e-6
            final_assets = {a["id"]: a for a in case["assets"] if a.get("year") == 2024 and a.get("tech") in TECHS}
            stock, annual_decisions = {}, {}
            for tech in TECHS:
                assets = [a for a in final_assets.values() if a["tech"] == tech]
                projects = [p for p in case["projects"] if p["tech"] == tech]
                inherited = fsum(a["capacity_mw"] for a in assets
                                 if a["online_year"] <= 2014 < a["exit_year"])
                initial_online = fsum(p["capacity_mw"] for p in projects if p["initial_reconstruction"] and p["online_year"] <= 2024)
                autonomous_online = fsum(p["capacity_mw"] for p in projects if not p["initial_reconstruction"] and p["online_year"] <= 2024)
                retirements = fsum(a["capacity_mw"] for a in assets if 2014 < a["exit_year"] <= 2024)
                autonomous_queue = fsum(p["capacity_mw"] for p in projects if not p["initial_reconstruction"] and p["online_year"] > 2024)
                assert abs(inherited - historical[2014][tech]) < .001
                assert abs(inherited + initial_online + autonomous_online - retirements - end[tech + "_capacity_mw"]) < .001
                stock[tech] = dict(initial_2014_stock_mw=inherited, initial_pipeline_commissioned_mw=initial_online,
                    autonomous_commissioned_mw=autonomous_online, retired_2015_2024_mw=retirements,
                    autonomous_still_in_construction_after_2024_mw=autonomous_queue,
                    end_2024_stock_mw=end[tech + "_capacity_mw"])
                annual = []
                for proposal in (b for b in case["behavior"] if b["kind"] == "investment_proposal" and b["actor"] == tech):
                    year = proposal["year"]
                    approved = [p for p in projects if not p["initial_reconstruction"] and p["decision_year"] == year]
                    approval_logs = [b for b in case["behavior"] if b["kind"] == "approval"
                                     and b["project"] in {p["id"] for p in approved}]
                    amount = fsum(p["capacity_mw"] for p in approved)
                    limit = proposal["construction_limit_mw"]
                    finance = proposal["finance_limit_mw"]
                    stages = [b for b in case["behavior"] if b["year"] == year
                              and b["kind"] == "joint_renewable_audit" and b.get("approved") and tech in b.get("capacities_mw", {})]
                    physical = next(p for p in case["paths"] if p["year"] == year)
                    realised = next(f for f in case["finance"] if f["year"] == year and f["kind"] == "generator_operation" and f["actor"] == tech)
                    annual.append(dict(year=year, npv_cny_per_mw=proposal["npv_cny_per_mw"],
                        new_project_margin_cny_per_mw=proposal["expected_new_project_margin_cny_per_mw"],
                        energy_pv_factor=proposal["expected_operating_pv_factor"],
                        capex_cny_per_mw=proposal["capex_cny_per_mw"],
                        requested_mw=proposal["requested_mw"], approved_mw=amount,
                        construction_limit_mw=limit, finance_limit_mw=finance,
                        npv_nonpositive=proposal["npv_cny_per_mw"] <= 0,
                        request_at_construction_ceiling=proposal["requested_mw"] > 0 and abs(proposal["requested_mw"] - limit) <= max(.001, limit*1e-8),
                        approval_at_construction_ceiling=amount > 0 and abs(amount-limit) <= max(.001,limit*1e-8),
                        finance_above_construction_ceiling=finance > limit,
                        min_common_budget_ratio=min((b["common_budget_ratio"] for b in approval_logs), default=None),
                        positive_joint_project_npvs=[b["incremental_npvs_cny_per_mw"][tech] for b in stages],
                        observed_capacity_mw=data.get((year, tech + "_capacity_mw")),
                        model_capacity_mw=physical[tech + "_capacity_mw"],
                        operating_exposure_mw_year=physical[tech + "_operating_exposure_mw_year"],
                        realised_generation_mwh=physical[tech + "_generation_mwh"],
                        own_operating_profit_cny=realised["cash_delta_cny"]))
                annual_decisions[tech] = annual
            # Rounded CEC report anchors only; this is not a claimed exact
            # subtechnology split of the exact national thermal aggregate.
            approximate_thermal = {
                "coal": dict(observed_rounded_mw=1190000, model_mw=end["coal_capacity_mw"],
                             approximate_gap_mw=1190000-end["coal_capacity_mw"]),
                "gas": dict(observed_rounded_mw=140000, model_mw=end["gas_capacity_mw"],
                            approximate_gap_mw=140000-end["gas_capacity_mw"]),
                "biomass": dict(observed_cec_mw=45970, model_mw=end["biomass_capacity_mw"],
                                gap_mw=45970-end["biomass_capacity_mw"]),
            }
            results[f"{mode}_authority_{authority}"] = dict(total_observed_mw=data[2024, "total_capacity_mw"],
                total_model_mw=end["total_capacity_mw"], total_gap_mw=gap,
                total_relative_error=-gap/data[2024, "total_capacity_mw"],
                exact_group_decomposition=decomposition,
                rounded_thermal_detail=approximate_thermal,
                stock_flow=stock, annual_investment_evidence=annual_decisions,
                solar_2024_generation_mwh=end["solar_generation_mwh"],
                solar_2024_ei_reference_generation_mwh=references[2024, "solar"],
                parameters=case["parameters"])
    paths = ["data/processed/q2/national_observations.csv",
             "data/raw/q2_technology_scope/cec_annual2025_release.txt",
             "data/raw/q2_technology_scope/technology_capacity_generation_anchors.csv",
             "src/energy_model/q2_national.py", "scripts/diagnose_q2_capacity_gap.py"]
    source_hashes.update({p: sha256((ROOT / p).read_bytes()).hexdigest() for p in paths})
    receipt = dict(created_at=datetime.now(timezone.utc).isoformat(),
        status="read_only_diagnostic_not_recalibration", runs={m: p.as_posix() for m, p in RUNS.items()},
        diagnosis_scope="Arithmetic accounting and revealed constraints, not causal counterfactual attribution",
        results=results, source_sha256=source_hashes,
        limitations=["Coal/gas CEC anchors are rounded and cannot turn a thermal aggregate into an exact coal census",
                     "No evaluation-driven parameter changes or hypothetical completed plants are introduced",
                     "Uniform reconstruction ages and inherited pipeline are assumptions, not observed retirement records",
                     "An inactive ceiling is not evidence that loosening it would alter equilibrium investment"])
    out = ROOT / "outputs/validation/capacity_gap_diagnosis_20261020.json"
    assert not out.exists()
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
    sample = results["net58_authority_25"]
    print(json.dumps(dict(path=out.relative_to(ROOT).as_posix(), total_gap_mw=sample["total_gap_mw"],
        groups=sample["exact_group_decomposition"], stock={t: sample["stock_flow"][t] for t in ("coal", "hydro", "solar")},
        decisions={t: sample["annual_investment_evidence"][t] for t in ("coal", "hydro", "solar")}), ensure_ascii=False))


if __name__ == "__main__":
    main()
