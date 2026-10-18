"""Explicit one-time Q1 input review snapshot; not called by run.py q1.

Review reasoning is recorded in docs/solutions/p1-lb-input-review.md.
Changing hashes alone does not constitute review or expand the original contracts.
"""
from pathlib import Path
import csv
import hashlib
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from energy_model.q1 import COST_ASSUMPTIONS, review_snapshot
from prepare_q1_cost_parameters import prepare as prepare_cost_parameters

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ('reviewed2024', 'data/processed/q1/reviewed_2024_additions.csv', 'C1/L2 revision: NDC preliminary 2024 share; storage report published 2025 describing 2021-2024; figure/text precision and regional subsets kept separate; see p1-lb-review-response.md'),
    ('national', 'data/processed/unified/nbs_history.csv', 'Primary same-vintage history; table-image checks; original units and dedup identity retained'),
    ('products', 'data/processed/nbs_products_annual.csv', 'National product rows; physical tonnes/volume separate from standard coal'),
    ('balance', 'data/processed/nbs_balance_checkpoints.csv', '2015/2020/2022/2023 table 9-3 to 9-6; preserve published residuals'),
    ('province', 'data/processed/nbs_province_demand.csv', '31 provinces at selected years; no interpolated regional panel'),
    ('region_generation', 'data/processed/q1/province_generation_2024.csv', '31 province rows visually transcribed from same-base table 9-19'),
    ('regional_resources', 'data/processed/q1/regional_resource_top3.csv', 'Top three published provinces per coal/gas/hydro product visually identified on full table 9-19; selected nine cells, not complete province panel'),
    ('renewables', 'data/processed/nea_renewables_2024_2025.csv', 'Annual official technology snapshots; PV versus solar and hydro definitions separated'),
    ('snapshots', 'data/processed/fuel_storage_hydrogen_snapshots.csv', '2024 gas/hydrogen and 2025 storage snapshots; no mixed-year initial state'),
    ('carbon', 'data/processed/china_co2_gcb_annual.csv', 'Territorial fossil and industry inventory estimate; excludes land-use and removals'),
    ('research', 'data/processed/china_energy_research_annual.csv', 'Research supplementary history; no splice into NBS primary-energy accounting'),
    ('costs', 'data/processed/technology_accounting_parameters.csv', 'IRENA 2024 China published LCOE/CAPEX; mmj baf1975 reviewed wind CAPEX 856/1520 reused for common-financing conditional costs; lifetime and financing boundaries retained'),
    ('cost_comparison', 'data/processed/q1/iea_comparable_costs.csv', '2020 report projected cases with 2018 price year; matched discount/CF groups; not current actual costs'),
    ('prices', 'data/processed/q1/prices_reviewed.csv', 'Archive/PDF vintages and definition segments retained; mixed Europe 2015 and coal 2022 excluded from returns; coal replacement effective February 2022; Europe 2024 anomalous cell excluded; see p1-lb-review-response.md'),
    ('renewable_regions', 'data/processed/q1/renewable_regions.csv', 'NEA original DOC tables 1-5: consumption responsibility shares, wind/PV grid-region utilization and hydro basins; not capacity factors'),
    ('technology_regions', 'data/processed/q1/technology_region_capacities.csv', 'PV 32 reporting areas including separate XPCC; nuclear 8 operating provinces and same-source total; original images visually checked'),
    ('context', 'data/processed/q1/additional_context.csv', 'Hydro and biomass multiyear costs, 2024 hydrogen December prices and regional shares, NEA gas benchmark snapshot, UHV annual flows, combustion reference factors and supplementary industry estimates; no silent year/scope splice'),
    ('pipeline', 'data/processed/lb/trade_alternatives/pipeline_gas_china_2024.csv', 'Same EI sheet and GCV unit; country versus regional bucket classification'),
    ('lng', 'data/processed/lb/trade_alternatives/lng_china_2024.csv', 'Same EI sheet and GCV unit; origin and total rows separated'),
    ('coal_trade', 'data/processed/lb/trade_alternatives/coal_china_2024_EJ.csv', 'Same EI coal energy table; no conversion to tonnes'),
    ('irena_capacity', 'data/processed/lb/base/irena/china_capacity_2016_2025.csv', 'Independent compilation of technical capacity; original flags and categories retained'),
    ('cost_method', 'data/processed/q1/cost_method_parameters.csv', 'mmj baf1975: China 2024 onshore/offshore O&M, new-project CF and economic life; published assumptions, not operating-fleet observations; see p1-yx-integration.md'),
    ('official2024', 'data/observations/energy_official_communique_2024.json', 'Retain existing S13 admitted scope; independent 2024 release only'),
]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    cost_checks = prepare_cost_parameters(ROOT)
    registry = json.loads((ROOT/'data/catalog/sources_unified.json').read_text(encoding='utf-8'))
    sources = {s['source_key']: s for s in registry}
    ordered_files = [r for r in FILES if r[0] != 'cost_method'] + [r for r in FILES if r[0] == 'cost_method']
    inputs, used = [], set()
    for label, path, review in ordered_files:
        p = ROOT/path
        if p.suffix == '.csv':
            with p.open(encoding='utf-8-sig') as stream: rows = list(csv.DictReader(stream))
            if label == 'costs': rows = [r for r in rows if r['source_id']=='IRENA_COST_2024_PDF']
            if label == 'prices':
                if any(r['status'] not in ('archived_reference','reviewed_release') for r in rows):raise ValueError('Unreviewed price')
            raw_keys = set(r.get('source_key') or r.get('source_id') for r in rows)
        else:
            raw_keys = {'mmj:S13'}
            doc=json.loads(p.read_text(encoding='utf-8'))
            rows=[dict(year=doc['year'],unit=r['unit'],status=doc['status']) for r in doc['observations']]
        mapping = {}
        for key in sorted(raw_keys):
            if key in sources:
                chosen = sources[key]
            else:
                candidates = [s for s in registry if s['original_source_id']==key and s.get('canonical_path') and (ROOT/s['canonical_path']).is_file()]
                candidates.sort(key=lambda s: (s['namespace']!='yx', s['source_key']))
                if not candidates: raise ValueError(f'No available original for {label}/{key}')
                chosen = candidates[0]
            mapping[key] = chosen['source_key']; used.add(chosen['source_key'])
        inputs.append(dict(id=label,path=path,sha256=sha(p),source_map=mapping,review=review,
                           years=sorted({int(r['year']) for r in rows}),
                           units=sorted({r.get('unit','MW') for r in rows}),
                           evidence_status=sorted({r.get('source_status',r.get('status','published_compilation')) for r in rows}),
                           allowed_use='Q1 descriptive assessment only',blocked_use='national ABM calibration/initialization without further review'))
    pinned_sources = {}
    for key in sorted(used):
        s = sources[key]
        paths = []
        if s.get('canonical_path') and (ROOT/s['canonical_path']).is_file():paths.append(s['canonical_path'])
        for e in s.get('evidence_files',[]):
            path = e if isinstance(e,str) else e.get('path') or e.get('canonical_path')
            if path and (ROOT/path).is_file():paths.append(path)
        if not paths: raise ValueError(f'No source artifact: {key}')
        pinned_sources[key] = dict(title=s['title'],publisher=s['publisher'],url=s['url'],
                                   artifacts=[dict(path=p,sha256=sha(ROOT/p)) for p in sorted(set(paths))])
    config = dict(schema_version=1,review_date='2026-10-18',base_sha='7a65d068d19eea2f7dd8161a618a3ad8d66f98b8',
                  geography='China mainland; research-source geography separately labelled',comparison_years=[2015,2024],
                  inputs=inputs,sources=pinned_sources,
                  decisions={'missing':'never zero fill','conflicts':'retain separate vintages','score':'no composite score',
                             'price_window':[2015,2024],'volatility_ddof':1,'new_external_inputs':True,
                             'additional_review':'docs/solutions/p1-lb-additional-review.md',
                             'shared_input_status':'lb and mmj candidates passed yx local technical review; original PRs not formally approved or merged as checked 2026-10-18; integrated PR requires mmj and lb approval of the same final SHA and shared-input-use confirmation; not formal model admission',
                             'wind_cost_assumptions':COST_ASSUMPTIONS})
    # Reuse lb's substantive review only for unchanged bytes, sources and uses.
    prior = json.loads((ROOT/'data/catalog/q1_input_review.json').read_text(encoding='utf-8'))
    prior_config = json.loads((ROOT/'workflow/q1_inputs.json').read_text(encoding='utf-8'))
    inherited = [r for r in inputs if r['id'] != 'cost_method']
    prior_inputs = [dict(r) for r in prior['inputs'] if r['id'] != 'cost_method']
    # The sole inherited-use extension is mmj's already-reviewed wind CAPEX use.
    for row in prior_inputs:
        if row['id'] == 'costs' and row['review'] == 'Only IRENA 2024 China LCOE rows for Q1; lifetime and financing scope reviewed':
            row['review'] = next(r['review'] for r in inherited if r['id'] == 'costs')
    reviewed_sources = prior.get('reviewed_snapshot', {}).get('sources', prior_config['sources'])
    if inherited != prior_inputs or pinned_sources != reviewed_sources:
        raise ValueError('Inherited lb inputs/sources differ from reviewed scope; substantive re-review required')
    checks = [dict(check='lb_reviewed_bytes_sources_and_non_cost_uses_unchanged', passed=True)] + cost_checks
    review = dict(scope='lb reviewed inputs plus mmj cost increment; no original contract replacement',
        review_document='docs/solutions/p1-yx-integration.md', config='workflow/q1_inputs.json',
        base_sha=config['base_sha'], inputs=inputs, checks=checks,
        reviewed_snapshot=review_snapshot(inputs, pinned_sources))
    review_path = ROOT/'data/catalog/q1_input_review.json'
    review_path.write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    config['evidence_review'] = dict(path='data/catalog/q1_input_review.json', sha256=sha(review_path))
    (ROOT/'workflow/q1_inputs.json').write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f'Recorded {len(inputs)} Q1 input files and {len(pinned_sources)} original sources')

if __name__=='__main__': main()
