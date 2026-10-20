"""Independent saved-case review of project allocations, cash and old controls."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import fsum
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = Path("outputs/q2_project_competition_pairs/20261020T000557617231Z")


def read(path):
    return json.loads((ROOT / path).read_text("utf-8"))


def close(a, b, errors, key):
    error = abs(a - b)
    errors[key] = max(errors.get(key, 0.), error)
    assert error <= max(.01, abs(b) * 1e-12), (key, a, b)


def main():
    assert read(RUN / "status.json")["status"] == "completed"
    results = read(RUN / "results.json")
    hashes = results["source_sha256"]
    for path, digest in hashes.items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    assert len(results["summary"]) == 12
    errors, owners, projects = {}, [], []
    for name in results["summary"]:
        case = read(RUN / (name + ".json"))
        mode, _, authority, perspective = name.split("_")
        for annual in case["paths"]:
            assert abs(annual["cash_balance_residual_cny"]) < .01
        if perspective == "owner":
            old = read(Path("outputs/q2_thermal_pairs/20261019T235331010638Z") / f"authority_{authority}_{mode}.json")
            for field in ("paths", "finance", "behavior", "operations", "projects", "assets", "balances",
                          "thermal_fuel_ledger", "year_end_operation"):
                assert case[field] == old[field], (name, field)
            assert not case["project_operation_accounts"] and not case["project_forecasts"]
            owners.append(name)
            continue
        for annual in case["paths"]:
            year = annual["year"]
            for tech in ("coal", "gas", "wind", "solar"):
                rows = [r for r in case["project_operation_accounts"] if r["year"] == year and r["tech"] == tech]
                assert rows
                operation = next(r for r in case["finance"] if r["year"] == year
                                 and r["kind"] == "generator_operation" and r["actor"] == tech)
                for field in ("revenue_cny", "fuel_bill_cny", "om_cny", "ets_transfer_cny"):
                    close(fsum(r[field] for r in rows), operation[field], errors, field)
                close(fsum(r["generation_mwh"] for r in rows), annual[tech + "_generation_mwh"], errors, "generation_mwh")
                close(fsum(r["operating_profit_before_support_cny"] for r in rows),
                      operation["cash_delta_cny"], errors, "operating_profit_cny")
                for row in rows:
                    close(row["revenue_cny"] - row["fuel_bill_cny"] - row["om_cny"] + row["ets_transfer_cny"],
                          row["operating_profit_before_support_cny"], errors, "individual_profit_identity_cny")
                if tech in ("coal", "gas"):
                    physical = fsum(r["conversion_mwh"] * 365 for r in case["operations"]
                                    if r["year"] == year and r["kind"] == "fuel" and r["fuel"] == tech)
                    close(fsum(r["fuel_mwh"] for r in rows), physical, errors, "fuel_mwh")
            subsidy = [r for r in case["finance"] if r["year"] == year and r["kind"] == "subsidy_cash_transfer"]
            close(fsum(r["cash_delta_cny"] for r in subsidy), 0, errors, "subsidy_cash_transfer_cny")
        for row in case["project_forecasts"]:
            close(row["candidate_generation_mwh"] + row["incumbent_generation_mwh"],
                  row["total_same_technology_generation_mwh"], errors, "forecast_sales_partition_mwh")
            close(row["candidate_operating_mw_year"] * row["annualised_project_hours"],
                  row["candidate_generation_mwh"], errors, "forecast_candidate_meter_mwh")
            assert 0 <= row["annualised_project_hours"] <= 8760
            if row["tech"] in ("coal", "gas"):
                close(row["candidate_generation_mwh"] / row["candidate_gross_efficiency"],
                      row["candidate_fuel_mwh"], errors, "forecast_candidate_fuel_mwh")
        ineligible = {p["id"] for p in case["projects"] if p.get("support_eligible") is False}
        for year in case["fund_history"]:
            for payment in year["payments"]:
                assert payment["project"] not in ineligible or payment["paid_cny"] == 0
        projects.append(name)
    assert len(owners) == len(projects) == 6
    receipt = dict(created_at=datetime.now(timezone.utc).isoformat(), status="passed_with_scope_limits",
        run=RUN.as_posix(), all_frozen_source_hashes_match=True, frozen_source_count=len(hashes),
        six_owner_cases_exact_old_controls=owners, six_project_cases_allocation_and_cash_checked=projects,
        max_absolute_errors=errors, merchant_cohorts_receive_no_subsidy=True,
        no_parameter_search_or_evaluation_based_selection=results["new_parameter_selection"] is False,
        limits=["Common thermal utilisation and renewable curtailment remain aggregate approximations",
                "Representative financing pool does not establish independent firm ownership or bankruptcy",
                "Saved subsidy payments verify cash and ineligible exclusions; eligible lifetime metering remains implemented by previously reviewed revenue adapter"],
        default_inputs_changed=False, scientific_acceptance=False)
    for path, digest in hashes.items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    out = ROOT / "outputs/validation" / ("project_competition_pairs_independent_review_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({"receipt": out.relative_to(ROOT).as_posix(), "cases": 12, "max_errors": errors}))


if __name__ == "__main__":
    main()
