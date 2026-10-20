"""Historical thermal-vintage sensitivity with coherent fuel and project accounts."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from q2_fuel_price_factory import (verify_policy, scope_inputs, policy_inputs,
    apply_solar_duration, cost_inputs, RenewableVintages, bio_inputs, AnnualExposure,
    add_initial_support, apply_announced_lifetime_limits)
from energy_model.q2_thermal_vintages import ThermalNationalModel, ThermalVintages
from build_q2_project_costs import extract as verified_costs

ROOT = Path(__file__).resolve().parents[1]
HISTORY = "data/raw/q2_thermal_efficiency_history"
HISTORICAL_PDFS = {
    "iea_nea_projected_costs_2010.pdf": "673a6a22cc62e26ff19cf07b0120be7e1fca99fa9033fac7150e33826a168c77",
    "iea_nea_projected_costs_2015.pdf": "8c4bb17d76204408c7069232d1dea9e727cf1ee7f783f4f8291ffecbaa16afdc",
}


@lru_cache(maxsize=1)
def verify_history():
    """Verify independently read historical references; never admit fleet values.

    A worker verifies originals on first use; experiment snapshots verify all
    sources again after the run. No mutable model object is cached.
    """
    evidence = json.loads((ROOT / HISTORY / "evidence.json").read_text("utf-8"))
    manifest = json.loads((ROOT / HISTORY / "source_manifest.json").read_text("utf-8"))
    for entry in manifest:
        path = (ROOT / entry["path"]).resolve()
        if not path.is_relative_to(ROOT / HISTORY) or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Thermal historical original changed")
        if evidence["source_sha256"].get(entry["path"]) != entry["sha256"]:
            raise ValueError("Historical extraction and source manifest disagree")
    for name, expected in HISTORICAL_PDFS.items():
        if evidence["source_sha256"].get(HISTORY + "/" + name) != expected:
            raise ValueError("Unreviewed historical thermal PDF")
    rows = {(r["report_year"], r["fuel"], r["net_lhv_efficiency"], r["pdf_page"]) for r in evidence["rows"]}
    if not {(2010, "gas", .58, 57), (2015, "gas", .55, 40), (2015, "coal", .45, 41)}.issubset(rows):
        raise ValueError("Missing reviewed historical technical reference")
    if evidence["default_model_admission"] is not False:
        raise ValueError("Historical technical references are not fleet observations")
    return tuple([r["path"] for r in manifest] + [HISTORY + "/source_manifest.json", HISTORY + "/evidence.json",
        "docs/sources/q2_thermal_efficiency_history.md", "scripts/collect_q2_thermal_efficiency_history.py"])


def build(data, design, config, parameters, authority, *, end_year, fuel_prices=None,
          include_bio=True, include_vintages=True, thermal_mode="net58", decision_start_year=2015):
    if end_year not in range(2015, 2025) or thermal_mode not in {"disabled", "net55", "net58"}:
        raise ValueError("Expected explicit historical endpoint and thermal reference scenario")
    if fuel_prices is not None:
        fuel_prices.validate_window(2014, end_year)
    verify_policy()
    verified_costs()
    history_sources = verify_history()
    costs = cost_inputs(data, design)
    net = dict(coal=.45, gas=.55 if thermal_mode == "net55" else .58)
    thermal = None if thermal_mode == "disabled" else ThermalVintages(
        new_gross_efficiencies={t: e/costs.reference_net_fractions[t] for t, e in net.items()},
        decision_start_year=decision_start_year, evidence="docs/sources/q2_thermal_vintages.md")
    d, s, p, boundary, assumptions, source_paths = scope_inputs(data, design, parameters, recovery_share=.5)
    policy, cells, tax, prices, actual, _ = policy_inputs(d, s, cash_fraction=1, gas_price_factor=1,
        new_support=True, authority_multiple=authority)
    offer_changes = apply_solar_duration(policy)
    m = ThermalNationalModel(d, s, p, 2014, revenue_policy=policy, operating_boundary=boundary, detail=True,
        generation_costs=costs, fuel_prices=fuel_prices, thermal_vintages=thermal,
        renewable_vintages=RenewableVintages(new_project_cf={t: parameters["new_"+t+"_cf"] for t in ("wind", "solar")},
                                            evidence="docs/sources/q2_revenue_recalibration.md") if include_vintages else None,
        bioenergy=bio_inputs(d, config, parameters) if include_bio else None,
        annual_exposure=AnnualExposure(**config["generator_annual_exposure"]))
    add_initial_support(m, actual)
    initial_changes = apply_solar_duration(m.revenue_policy)
    changes = []
    for year in range(2015, end_year+1):
        if year >= 2021:
            changes.extend(apply_announced_lifetime_limits(m, zone="lower"))
        m.run(year)
    assumptions.update(portfolio_audit="renewables_and_thermal_joint_incremental_profit",
        policy_duration_changes=offer_changes+initial_changes,
        commitment_authority_multiple_of_current_budget=authority,
        annual_exposure=m.annual_exposure.__dict__, extra_free_cash_or_assets=False,
        thermal_mode=thermal_mode, thermal_decision_start_year=decision_start_year,
        thermal_reference_net_efficiencies=net if thermal else None,
        thermal_reference_net_fractions=costs.reference_net_fractions,
        thermal_new_gross_efficiencies=thermal.new_gross_efficiencies if thermal else None,
        thermal_within_technology_dispatch="common utilisation; exposure-weighted harmonic efficiency",
        thermal_history_scope="technical-reference sensitivity, not observed annual national new-plant efficiency",
        initial_thermal_fleet_and_pipeline="original efficiencies retained; no free retrofit",
        nonpower_identification="original fixed-efficiency residual identification unchanged",
        thermal_costs="same previously reviewed forward technical-cost assumptions; not historical observations",
        fuel_price_scope="conditional_shared_market_proxy" if fuel_prices else "original_reference")
    source_paths += ["data/raw/q2_solar_entitlement/ndrc_solar_2013_1638.html",
        "data/raw/q2_solar_entitlement/source_manifest.json", "src/energy_model/q2_solar_entitlement.py",
        "src/energy_model/q2_portfolio.py", "src/energy_model/q2_fuel_prices.py",
        "src/energy_model/q2_thermal_vintages.py", "scripts/q2_corrected_factory.py",
        "scripts/q2_fuel_price_factory.py", "scripts/q2_thermal_factory.py",
        "docs/sources/q2_thermal_vintages.md", *history_sources]
    return m, assumptions, prices, changes, source_paths
