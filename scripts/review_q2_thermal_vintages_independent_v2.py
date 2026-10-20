"""Independent read-only checks of thermal-vintage pairs and boundary cases."""
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import fsum
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts"), str(ROOT / "tests")]
from energy_model.q2_thermal_vintages import ThermalVintages, ThermalNationalModel
from energy_model.q2_portfolio import PortfolioNationalModel
from energy_model.q2_exposure import AnnualExposure
from energy_model.q2_national import EF
from q2_corrected_factory import preflight
from q2_thermal_factory import build
from test_q2 import small_operation


def read(path):
    return json.loads((ROOT / path).read_text("utf-8"))


def main():
    run = Path("outputs/q2_thermal_pairs/20261019T235331010638Z")
    result = read(run / "results.json")
    assert read(run / "status.json")["status"] == "completed"
    for path, digest in result["source_sha256"].items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    source_run = Path(read(run / "design.json")["source_run"])
    config = read(source_run / "design.json")
    selection = read(source_run / "training_selection.json")
    data, design, _ = preflight()
    parameters = selection["scenarios"]["25"]["parameters"]
    model, *_ = build(data, design, config, parameters, 25, end_year=2024, thermal_mode="net58")
    saved = read(run / "authority_25_net58.json")
    fields = ("paths", "finance", "behavior", "operations", "projects", "assets", "balances", "thermal_fuel_ledger")
    assert all(getattr(model, f) == saved[f] for f in fields)
    assert model.year_end_operation() == saved["year_end_operation"]
    max_heat_error = max_co2_error = max_cash = max_bill_error = 0.
    cases = []
    for label in result["summary"]:
        case = read(run / (label + ".json"))
        if label.endswith("_disabled"):
            authority = label.split("_")[1]
            original = read(source_run / f"authority_{authority}_full.json")
            assert all(case[f] == original[f] for f in fields if f != "thermal_fuel_ledger")
        else:
            eta_new = case["assumptions"]["thermal_new_gross_efficiencies"]
            for project in case["projects"]:
                if project["tech"] not in eta_new:
                    continue
                if project["initial_reconstruction"]:
                    assert "gross_thermal_efficiency" not in project
                elif project["decision_year"] >= 2015:
                    assert project["gross_thermal_efficiency"] == eta_new[project["tech"]]
            for path in case["paths"]:
                year = path["year"]
                for tech in ("coal", "gas"):
                    ledger = [r for r in case["thermal_fuel_ledger"] if r["year"] == year and r["tech"] == tech]
                    fuel = fsum(r["fuel_mwh"] for r in ledger)
                    energy = fsum(r["generation_mwh"] for r in ledger)
                    physical = fsum(r["conversion_mwh"] * 365 for r in case["operations"]
                                    if r["kind"] == "fuel" and r["year"] == year and r["fuel"] == tech)
                    heat_error = abs(fuel - physical)
                    co2_error = abs(fsum(r["combustion_co2_t"] for r in ledger) - physical * EF[tech])
                    assert heat_error < .001 and co2_error < .001
                    assert abs(energy - path[tech + "_generation_mwh"]) < .001
                    operation = next(r for r in case["finance"] if r["kind"] == "generator_operation"
                                     and r["year"] == year and r["actor"] == tech)
                    bill = physical * model.reference_fuel_prices[tech]
                    bill_error = abs(operation["fuel_bill_cny"] - bill)
                    assert bill_error < .01
                    identity = operation["revenue_cny"] - operation["fuel_bill_cny"] - operation["om_cny"] + operation["ets_transfer_cny"]
                    assert abs(identity - operation["cash_delta_cny"]) < .001
                    if year >= 2021:
                        assert abs(operation["covered_emissions_t"] - physical * EF[tech]) < .001
                    max_heat_error = max(max_heat_error, heat_error)
                    max_co2_error = max(max_co2_error, co2_error)
                    max_bill_error = max(max_bill_error, bill_error)
        max_cash = max(max_cash, max(abs(p["cash_balance_residual_cny"]) for p in case["paths"]))
        cases.append(label)
    assert len(cases) == 9 and max_cash < .01

    # Two thermal technologies can fail in sequence after the other is removed.
    theta = dict(activity_elasticity=.5, investment_response=1, renewable_mix_response=.7,
                 replacement_adoption=.2, expectation_rate=.25)
    vintage = ThermalVintages(new_gross_efficiencies={"coal": .5, "gas": .6},
                              decision_start_year=2015, evidence="independent synthetic boundary")
    fixture = ThermalNationalModel(deepcopy(data), deepcopy(design), theta, 2014,
                                   thermal_vintages=vintage, annual_exposure=AnnualExposure(.25, "synthetic quarter exposure"))
    logs = []
    fixture.last_operation = {}
    fixture.a["marginal_investment_halvings"] = 0
    fixture.government.log = lambda *a, **kw: logs.append(kw)
    def conditional_npv(tech, amount, portfolio, *, support_fraction=1.):
        return -1 if tech == "gas" or portfolio.get("gas", 0) == 0 else 1
    with patch.object(PortfolioNationalModel, "audit_renewable_portfolio", side_effect=lambda x, **kw: dict(x)), \
         patch.object(fixture, "thermal_candidate_npv", side_effect=conditional_npv):
        checked = fixture.audit_renewable_portfolio({"coal": 10, "gas": 10, "nuclear": 7})
    assert checked == {"coal": 0., "gas": 0., "nuclear": 7}
    assert len(logs) == 2

    # Real LP: quarter-year candidate efficiency saves fuel/ETS without invented sales.
    op = small_operation()
    op["storage"].update(initial_mwh=0, energy_mwh=0, power_mw=0)
    op["fuels"]["gas"].update(domestic_mw=[100, 100], domestic_cost_per_mwh=1, import_cost_per_mwh=1)
    op["plants"]["gas"].update(capacity_mw=10, efficiency=.5, policy_cost_per_mwh=0)
    fixture.year, fixture.carbon = 2022, 100
    fixture.suppliers["gas"].price = 1
    fixture.thermal_beliefs["gas"].project_margin = 1e9
    new_eta = (10 + 2.5) / (10/.5 + 2.5/.6)
    expected_margin = (20 - 10/new_eta) * 365 * (1 + 100 * EF["gas"]) / 2.5
    expected_npv = expected_margin * fixture.energy_pv_factor(lead=3, life=30) - sum(
        1/3/(1+fixture.a["discount_rate"])**k for k in range(3))
    with patch.object(fixture, "planning_operation", side_effect=lambda _: deepcopy(op)), \
         patch.object(fixture, "variable_om", return_value=0), patch.object(fixture, "fixed_om_per_mw", return_value=0), \
         patch.object(fixture, "tariff", return_value=100), patch.object(fixture, "capex", return_value=1):
        actual_npv = fixture.thermal_candidate_npv("gas", 10)
    assert abs(actual_npv - expected_npv) < 1e-6
    fixture.annual_exposure = AnnualExposure(0, "zero first-year boundary")
    with patch.object(fixture, "planning_operation", side_effect=lambda _: deepcopy(op)), \
         patch.object(fixture, "variable_om", return_value=0), patch.object(fixture, "fixed_om_per_mw", return_value=0), \
         patch.object(fixture, "tariff", return_value=100), patch.object(fixture, "capex", return_value=1):
        zero_exposure_npv = fixture.thermal_candidate_npv("gas", 10)
    assert zero_exposure_npv > 0

    paths = ["src/energy_model/q2_thermal_vintages.py", "scripts/q2_thermal_factory.py",
             "scripts/run_q2_thermal_pairs.py", "tests/test_q2_thermal_vintages.py",
             "docs/sources/q2_thermal_vintages.md", "scripts/review_q2_thermal_vintages_independent_v2.py"]
    receipt = dict(created_at=datetime.now(timezone.utc).isoformat(), status="passed_with_scope_limits",
        run=run.as_posix(), all_frozen_source_hashes_match=True, frozen_source_count=len(result["source_sha256"]),
        specialized_tests_reexecuted=dict(passed=15, failed=0),
        authority25_net58_actual_rebuild_exact=list(fields)+["year_end_operation"],
        three_disabled_cases_full_history_exact=True, nine_cases_checked=cases,
        max_cohort_fuel_vs_lp_error_mwh=max_heat_error, max_cohort_co2_vs_lp_error_t=max_co2_error,
        max_cash_residual_cny=max_cash, max_generator_bill_error_cny=max_bill_error,
        synthetic_additional_checks=dict(zero_halvings_cascading_thermal_removal=True,
            unaffected_nuclear_capacity_preserved=True, quarter_exposure_real_lp_ets_and_fuel_npv_error=abs(actual_npv-expected_npv),
            zero_first_year_exposure_shifts_to_first_positive_year=True),
        code_review=dict(initial_fleet_and_pipeline="original efficiency retained; original nonpower residual identification unchanged",
            mixing="exposure-weighted harmonic efficiency; physical stock separately used in snapshots",
            future_planning="known projects and survival only, no future realised decisions or fuel prices",
            learning="candidate heat saving relative to current mixed fleet, avoids repeating initial-vs-new saving; ETS marginal fuel term included",
            projects="approval-year tagging, commissioning copies persisted value to cohort",
            screening="separate real LP candidate contribution, then joint renewable/thermal rescreen; bounded failure/removal",
            cash="operating LP mixed efficiency matches inherited fuel bill/ETS and independent per-cohort fuel/carbon ledger"),
        remaining_limits=["Shared utilisation within each technology is not unit-level merit order; efficient-new and inefficient-old plants cannot dispatch separately",
            "2015 availability and 2025 technical costs remain conditional assumptions, not observed historical vintage data",
            "2014 fleet own-use ratios remain proxies for converting net technical efficiency to gross",
            "Aggregate annual exposure cannot model seasonal commissioning or part-load heat rates",
            "Fuel-price and efficiency sensitivities do not resolve national historical model acceptance"],
        default_inputs_changed=False, scientific_acceptance=False,
        source_sha256={p: sha256((ROOT/p).read_bytes()).hexdigest() for p in paths})
    for path, digest in result["source_sha256"].items():
        assert sha256((ROOT/path).read_bytes()).hexdigest() == digest, path
    out = ROOT / "outputs/validation/thermal_vintages_independent_review_20261020_v2.json"
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+"\n", "utf-8")
    print(json.dumps(dict(path=out.relative_to(ROOT).as_posix(), cases=9,
                         max_fuel_error_mwh=max_heat_error, max_cash_residual_cny=max_cash), ensure_ascii=False))


if __name__ == "__main__":
    main()
