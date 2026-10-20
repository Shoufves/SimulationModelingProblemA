"""Apply verified solar support years and run fixed-parameter full-history pairs.

This is an explicitly changed policy-input candidate, not a new calibration.
The original experiment remains reproducible against its own source hashes.
"""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from run_q2_revenue_recalibration import (preflight, save, sha, metrics, extract, training_loss,
                                         bio_inputs, cost_inputs)
from run_q2_historical_support import (scope_inputs, policy_inputs, NationalModel,
                                       add_initial_support, apply_announced_lifetime_limits)
from energy_model.q2_renewable_vintages import RenewableVintages
from energy_model.q2_exposure import AnnualExposure
from energy_model.q2_solar_entitlement import apply_solar_duration
from review_q2_revenue_candidate import review


def verify_policy():
    folder = ROOT / "data/raw/q2_solar_entitlement"
    manifest = json.loads((folder / "source_manifest.json").read_text("utf-8"))[0]
    path = ROOT / manifest["path"]
    if not path.is_relative_to(folder) or hashlib.sha256(path.read_bytes()).hexdigest() != manifest["sha256"]:
        raise ValueError("Solar-duration policy original changed")
    text = path.read_text("utf-8")
    if any(phrase not in text for phrase in ("期限原则上为20年", "2014年1月1日及以后投运", "2013年8月26日")):
        raise ValueError("Solar-duration applicability was not verified")


def build(data, design, config, parameters, authority, *, end_year, include_bio=True, include_vintages=True):
    verify_policy()
    d, s, p, boundary, assumptions, source_paths = scope_inputs(data, design, parameters, recovery_share=.5)
    policy, cells, tax, prices, actual, _ = policy_inputs(d, s, cash_fraction=1, gas_price_factor=1,
        new_support=True, authority_multiple=authority)
    # New offers are configured before the model forms its first investment
    # expectation. Initial positions are adjusted before the first annual run.
    offer_changes = apply_solar_duration(policy)
    m = NationalModel(d, s, p, 2014, revenue_policy=policy, operating_boundary=boundary, detail=True,
        generation_costs=cost_inputs(data, design),
        renewable_vintages=RenewableVintages(new_project_cf={t: parameters["new_"+t+"_cf"] for t in ("wind", "solar")},
                                            evidence="docs/sources/q2_revenue_recalibration.md") if include_vintages else None,
        bioenergy=bio_inputs(d, config, parameters) if include_bio else None,
        annual_exposure=AnnualExposure(**config["generator_annual_exposure"]))
    add_initial_support(m, actual)
    initial_changes = apply_solar_duration(m.revenue_policy)
    changes = []
    if end_year not in range(2015, 2025):
        raise ValueError("Expected a historical endpoint")
    for year in range(2015, end_year+1):
        if year >= 2021:
            changes.extend(apply_announced_lifetime_limits(m, zone="lower"))
        m.run(year)
    assumptions.update(solar_duration_rule="2013_1638_twenty_years_for_known_applicable_cohorts",
        pre2014_solar_approval_dates="unknown; prior entitlement reconstruction retained",
        solar_settlement_scope="aggregate central-style proxy; distributed self-consumption not separately reconstructed",
        policy_duration_changes=offer_changes+initial_changes,
        support_rates="unchanged historical aggregate effective spread; not 2013 tariff frozen for all years",
        commitment_authority_multiple_of_current_budget=authority,
        physical_solar_lifetime_years=25, solar_standard_eligibility_years=20,
        annual_exposure=m.annual_exposure.__dict__, extra_free_cash_or_assets=False)
    source_paths += ["data/raw/q2_solar_entitlement/ndrc_solar_2013_1638.html",
                     "data/raw/q2_solar_entitlement/source_manifest.json",
                     "src/energy_model/q2_solar_entitlement.py"]
    return m, assumptions, prices, changes, source_paths


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("historical_run")
    args = parser.parse_args()
    source = (ROOT / args.historical_run).resolve()
    if not source.is_relative_to(ROOT / "outputs/q2_revenue_recalibration"):
        raise ValueError("Expected historical search")
    review(source)
    original = json.loads((source / "results.json").read_text("utf-8"))
    config = json.loads((source / "design.json").read_text("utf-8"))
    selection = json.loads((source / "training_selection.json").read_text("utf-8"))
    if selection["selection_uses"] != "2015_2021_only" or set(selection["scenarios"]) != {"5", "25", "100"}:
        raise ValueError("Require all original training-only authority selections")
    data, design, _ = preflight()
    verify_policy()
    folder = ROOT / "outputs/q2_solar_entitlement" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    save(folder / "status.json", dict(status="running", scientific_acceptance=False))
    save(folder / "design.json", dict(base_config=config, base_run=source.relative_to(ROOT).as_posix(),
        parameters_refitted=False, authority_selection="none", changed="applicable solar support duration 25 to 20; plant life remains 25"))
    sources = set(original["source_sha256"]) | {Path(__file__).relative_to(ROOT).as_posix(),
        "src/energy_model/q2_solar_entitlement.py", "data/raw/q2_solar_entitlement/ndrc_solar_2013_1638.html",
        "data/raw/q2_solar_entitlement/source_manifest.json", "docs/sources/q2_solar_entitlement.md",
        (source / "training_selection.json").relative_to(ROOT).as_posix(), (source / "results.json").relative_to(ROOT).as_posix()}
    hashes = {p: sha(p) for p in sorted(sources)}
    save(folder / "source_snapshot.json", hashes)
    refs = {(r["year"], r["category"]): r["value_twh"]*1e6 for r in extract()[0]}
    results = {}
    try:
        for authority, selected in selection["scenarios"].items():
            for mode, options in (("full", {}), ("without_municipal_composition", dict(include_bio=False))):
                name = f"authority_{authority}_{mode}"
                m, assumptions, prices, changes, extra = build(data, design, config, selected["parameters"], int(authority), end_year=2024, **options)
                if not set(extra).issubset(sources): raise ValueError("Unfrozen input")
                old = json.loads((source / (name+".json")).read_text("utf-8"))
                output = dict(parameters=selected["parameters"], assumptions=assumptions, metrics=metrics(m, refs),
                    paths=m.paths, finance=m.finance, operations=m.operations, projects=m.projects,
                    assets=m.assets, balances=m.balances, behavior=m.behavior, price_inputs=prices,
                    lifetime_rule_changes=changes, fund_history=m.revenue_policy.history,
                    municipal_service_history=m.bioenergy.history if m.bioenergy else [], training_components=training_loss(m)[1])
                save(folder / (name+".json"), output)
                results[name] = dict(metrics=output["metrics"], end=m.paths[-1],
                    training_loss=training_loss(m)[0], old_training_loss=selected["loss"],
                    same_physical_paths_as_old=m.paths==old["paths"],
                    max_cash_residual_cny=max(abs(r["cash_balance_residual_cny"]) for r in m.paths),
                    max_physical_residual=max(r["max_residual"] for r in m.paths))
                print(name, results[name]["training_loss"], {t:round(output["metrics"][t]["already_seen_evaluation"]["mape"]*100,2)
                    for t in ("gas","oil","biomass","wind","solar")}, flush=True)
        if any(sha(p)!=h for p,h in hashes.items()): raise ValueError("Source changed during policy comparison")
        save(folder / "results.json", dict(source_sha256=hashes, results=results,
            parameters_refitted=False, production_default_changed=False, scientific_acceptance=False,
            evaluation_identity="already_seen_not_blind"))
        save(folder / "status.json", dict(status="complete_conditional_experiment", scientific_acceptance=False))
    except Exception as exc:
        save(folder / "status.json", dict(status="failed", scientific_acceptance=False, error=str(exc)))
        raise
    print(folder.relative_to(ROOT).as_posix())


if __name__ == "__main__": main()
