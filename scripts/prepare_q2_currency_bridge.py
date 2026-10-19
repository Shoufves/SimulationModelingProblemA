"""Reviewed retrospective annual CNY-to-real-2008-USD accounting factors.

Annual-average official exchange rates and US general GDP deflators are an
explicit research normalization, not Chinese sector inflation, transaction FX,
VAT removal or contemporaneously known forecasts. No model contract is awarded.
"""
import argparse
import json
from math import isfinite
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from energy_model.q2.io import csvout, dump, local_path, sha, verify_source_records


def series(document, indicator, country, first, last):
    header, records = document
    if header['page'] != 1 or header['pages'] != 1 or header['total'] != len(records):
        raise ValueError('Incomplete or paginated WDI response')
    selected = {}
    for record in records:
        if record['indicator']['id'] != indicator:
            continue
        if record['countryiso3code'] != country:
            raise ValueError('Unexpected country in selected indicator')
        year = int(record['date'])
        if not first <= year <= last:
            continue
        value = record['value']
        if year in selected or type(value) not in (int, float) or not isfinite(value) or value <= 0:
            raise ValueError('Duplicate, missing or nonpositive currency observation')
        selected[year] = value
    if set(selected) != set(range(first, last + 1)):
        raise ValueError('Currency reference years missing; no forward filling')
    return selected


def conversion_factors(exchange_rate, deflator, base_year=2008):
    if base_year not in deflator or set(exchange_rate) != set(deflator):
        raise ValueError('Matched annual exchange/deflator years and base year required')
    rows = []
    for year in sorted(exchange_rate):
        fx, index = exchange_rate[year], deflator[year]
        if any(type(v) not in (int, float) or not isfinite(v) or v <= 0 for v in (fx, index, deflator[base_year])):
            raise ValueError('Finite positive conversion inputs required')
        factor = deflator[base_year] / index / fx
        rows.append(dict(year=year, CNY_per_USD_period_average=fx, US_GDP_deflator=index,
                         US_GDP_deflator_base=deflator[base_year], base_year=base_year,
                         USD2008_per_CNY_nominal=factor,
                         million_USD2008_per_CNY_nominal=factor / 1e6,
                         tariff_CNY_per_kWh_to_million_USD2008_per_MWh=factor / 1000,
                         method='Divide by annual CNY/USD; multiply D2008/Dyear; kWh-to-MWh and million currency separately.',
                         tax_treatment='unchanged; no VAT removal',
                         information_scope='retrospective annual accounting; not a forecast visible to agents'))
    return rows


def prepare(root=ROOT, output_relative='data/processed/q2'):
    review_path = root / 'data/catalog/q2_currency_bridge_review.json'
    review = json.loads(review_path.read_text(encoding='utf-8'))
    if (review['decision'] != 'scoped_retrospective_currency_reference' or not review['checks'] or
            not all(r['passed'] is True and r['evidence'] for r in review['checks'])):
        raise ValueError('Currency normalization not substantively reviewed')
    verify_source_records(root, review['source_records'])
    registry = {s['id']: s for s in json.loads((root / 'data/catalog/q2_sources.json').read_text(encoding='utf-8'))}
    documents = {}
    for role, identifier in review['roles'].items():
        if identifier not in {r['id'] for r in review['source_records']}:
            raise ValueError('Currency role references an unreviewed source')
        documents[role] = json.loads(local_path(root, registry[identifier]['path']).read_text(encoding='utf-8'))
    fx = series(documents['china_fx'], 'PA.NUS.FCRF', 'CHN', 2008, 2024)
    deflator = series(documents['us_deflator'], 'NY.GDP.DEFL.ZS', 'USA', 2008, 2024)
    legacy = series(documents['legacy_deflator'], 'NY.GDP.DEFL.ZS', 'USA', 2008, 2014)
    if documents['china_fx'][0]['lastupdated'] != review['dataset_updated'] or documents['us_deflator'][0]['lastupdated'] != review['dataset_updated']:
        raise ValueError('Unreviewed WDI dataset revision')
    if any(deflator[y] != value for y, value in legacy.items()):
        raise ValueError('Overlapping legacy deflator values differ; retain both vintages')
    for role, identifier in [('fx_definition', 'PA.NUS.FCRF'), ('deflator_definition', 'NY.GDP.DEFL.ZS')]:
        meta = documents[role]
        if meta[0]['total'] != 1 or len(meta[1]) != 1 or meta[1][0]['id'] != identifier:
            raise ValueError('Indicator definition mismatch')
    rows = conversion_factors(fx, deflator)
    sources = {role: dict(id=identifier, path=registry[identifier]['path'], sha256=registry[identifier]['sha256'])
               for role, identifier in review['roles'].items()}
    for row in rows:
        row.update(dataset_updated=review['dataset_updated'], original_sources=sources,
                   admission='scoped_reference_not_model_price_path')
    out = local_path(root, output_relative)
    out.mkdir(parents=True, exist_ok=True)
    csvout(out / 'currency_bridge_2008_2024.csv', rows)
    checks = dict(decision=review['decision'], years=17, overlapping_legacy_deflator_years=7,
        overlapping_values_exact=True, dataset_updated=review['dataset_updated'],
        review_sha256=sha(review_path), historical_model_changed=False, national_model_admission=False,
        future_path_supplied=False, uses_revised_historical_data=True,
        limitations=['Annual-average FX is not a project transaction rate.',
                     'US general GDP deflator is an accounting assumption, not Chinese technology inflation.',
                     'All source tax bases are retained; these factors do not harmonize VAT.',
                     'Future realized FX/deflators may not enter historical investment expectations.',
                     'No current/2060 forecast, project eligibility or national policy weights supplied.'])
    dump(out / 'currency_bridge_checks.json', checks)
    return checks


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default='data/processed/q2')
    print(json.dumps(prepare(output_relative=parser.parse_args().output_dir), ensure_ascii=False, indent=2))
