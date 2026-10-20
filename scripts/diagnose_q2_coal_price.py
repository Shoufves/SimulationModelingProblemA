"""Compare a published early coal-price anchor with the model's fixed reference.

Accounting sensitivity only: fixed generation, no rerun or investment response.
Tax endpoints are assumptions while the acquired index tax basis is unresolved.
"""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from q2_corrected_factory import preflight
from review_q2_revenue_candidate import review


def main():
    run = ROOT / sys.argv[1]
    if not run.resolve().is_relative_to(ROOT / "outputs/q2_revenue_recalibration"):
        raise ValueError("Expected a historical experiment")
    review(run)
    case = json.loads((run / "authority_25_full.json").read_text("utf-8"))
    sources = json.loads((run / "results.json").read_text("utf-8"))["source_sha256"]
    folder = ROOT / "data/raw/q2_coal_prices"
    evidence = json.loads((folder / "evidence.json").read_text("utf-8"))
    manifest = json.loads((folder / "source_manifest.json").read_text("utf-8"))
    for item in manifest:
        if hashlib.sha256((ROOT / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise ValueError("Changed official coal-price original")
        sources[item["path"]] = item["sha256"]
    data, design, _ = preflight()
    year = 2015
    quoted = evidence["annual_simple_means"][str(year)]
    deflator = data[2024, "cpi"] / data[year, "cpi"]
    original_price = next(r['price_cny_per_mwh'] for r in case['behavior']
                          if r['year']==year and r['actor']=='coal' and r['kind']=='offer')
    operation = next(r for r in case['finance'] if r['year']==year and r['actor']=='coal'
                     and r['kind']=='generator_operation')
    fuel = operation['fuel_bill_cny'] / original_price
    exposure = operation['operating_exposure_mw_year']
    proposal = next(r for r in case['behavior'] if r['year']==year and r['actor']=='coal'
                    and r['kind']=='investment_proposal')
    rows = []
    for assumed_vat in (0, .17):
        price = quoted / evidence['heat_mwh_per_tonne'] * deflator / (1+assumed_vat)
        saving = fuel * (original_price-price)
        rows.append(dict(assumed_vat=assumed_vat, tax_status="sensitivity_assumption_not_verified_index_tax",
            price_real_2024_cny_per_fuel_mwh=price, reference_price_real_2024=original_price,
            fuel_bill_change_cny=-saving, operating_margin_change_cny_per_mw_year=saving/exposure,
            unchanged_operating_margin_cny_per_mw_year=operation['cash_delta_cny']/exposure,
            price_only_operating_margin_cny_per_mw_year=(operation['cash_delta_cny']+saving)/exposure,
            existing_learned_project_margin_cny_per_mw_year=proposal['expected_new_project_margin_cny_per_mw']))
    for path in (Path(__file__), folder/'evidence.json', folder/'source_manifest.json',
                 ROOT/'scripts/collect_q2_coal_prices.py', run/'authority_25_full.json', run/'results.json'):
        sources[path.relative_to(ROOT).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    output = dict(created_at=datetime.now(timezone.utc).isoformat(), source_sha256=sources,
        year=year, same_generation_and_exposure=True, actual_model_rerun=False,
        formula="price=index_month_arithmetic_mean/5.815*CPI2024/CPI2015/(1+assumed_vat); delta_margin=fuel_MWh*(old-new)/operating_MW_year",
        caveat="Reported margins are fixed-output accounting sensitivities, not dynamically learned NPV, dispatch changes or validated investment responses.",
        annual_index_not_volume_weighted=True, tax_basis_unverified=True, rows=rows,
        scientific_acceptance=False)
    target = ROOT/'outputs/validation/coal_price_accounting_diagnostic_20261020.json'
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n','utf-8')
    print(json.dumps(rows,ensure_ascii=False))


if __name__ == '__main__':
    main()
