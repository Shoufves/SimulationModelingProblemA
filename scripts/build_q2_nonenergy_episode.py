"""Separate reported 2014 material uses from a diagnostic fuel residual.

This is a cross-source partition hypothesis, not national input admission.
All predeclared responses are retained; no fitting or holdout selection occurs.
"""
from copy import deepcopy
from decimal import Decimal
from itertools import product
import json
from math import fsum, isfinite
from pathlib import Path

import run_q2_historical_candidate as history
from prepare_q2_apec_balance import parse_table, TOP_COLUMNS, value
from energy_model.q2.io import dump, local_path, sha, verify_source_records

ROOT = history.ROOT
REVIEW = 'data/catalog/q2_nonenergy_mapping_review.json'
DIRECTORY = 'workflow/q2_candidates/nonenergy_episode_v2'
MWH_PER_KTOE = Decimal('11630')
PRODUCTS = {'coal': ('1. Coal', '2. Coal products'),
            'oil': ('6. Crude oil & NGL', '7. Petroleum products'),
            'gas': ('8. Gas',)}
SECTORS = {'transformation': ('17.1 Transformation sector', 'fuel'),
           'industry': ('17.2 Industry sector', 'industrial'),
           'transport': ('17.3 Transport sector', 'transport')}


def extract_material_reference(table):
    """Use eight reported cells; preserve unknown cells as a joint bound."""
    if not table or any(not row or len(row) != len(table[0]) for row in table):
        raise ValueError('Rectangular nonempty material table required')
    labels = table[0]
    if len(set(labels)) != len(labels) or len({r[0] for r in table[1:]}) != len(table) - 1:
        raise ValueError('Duplicate material table row or column')
    rows = {r[0]: (index, r) for index, r in enumerate(table[1:], 1)}
    required_rows = {'17. Non-energy use', '17.4 Other sector', *(s[0] for s in SECTORS.values())}
    required_columns = {'19. Total', *(p for products in PRODUCTS.values() for p in products)}
    if not required_rows <= rows.keys() or not required_columns <= set(labels) or len(labels) <= max(TOP_COLUMNS):
        raise ValueError('Required material row or column missing')
    total = value(rows['17. Non-energy use'][1][labels.index('19. Total')])
    if total is None or total <= 0:
        raise ValueError('Positive reported nonenergy control required')
    items, reported, missing = [], [], []
    for sector, (flow, owner) in SECTORS.items():
        index, row = rows[flow]
        for carrier, products in PRODUCTS.items():
            cells = []
            for name in products:
                col = labels.index(name)
                val = value(row[col])
                if val is None:
                    continue
                if val <= 0:
                    raise ValueError('Episode only maps the eight reviewed positive material cells')
                cells.append(dict(flow=flow, product=name, raw_token=row[col],
                                  value_ktoe=float(val), tsv_line=index + 3, column=col + 1))
            if cells:
                quantity = sum(Decimal(c['raw_token']) for c in cells)
                items.append(dict(id='nonenergy_' + sector + '_' + carrier, sector=sector, owner=owner,
                    carrier=carrier, cells=cells, value_ktoe=float(quantity),
                    input_MWh_LHV=float(quantity * MWH_PER_KTOE),
                    use='reported_material_input_not_useful_energy_service'))
    for flow in [s[0] for s in SECTORS.values()] + ['17.4 Other sector']:
        index, row = rows[flow]
        for col in TOP_COLUMNS:
            val = value(row[col])
            if val is None:
                missing.append(dict(flow=flow, product=labels[col], tsv_line=index + 3, column=col + 1))
            elif val < 0:
                raise ValueError('Gross nonenergy input cannot be negative')
            else:
                reported.append(val)
    mapped = sum(Decimal(c['raw_token']) for item in items for c in item['cells'])
    if len(reported) != 8 or len(items) != 5 or mapped != sum(reported):
        raise ValueError('Material reference changed; no silent missing-carrier allocation')
    lower_sum = sum(max(Decimal(0), v - Decimal('.5')) for v in reported)
    upper_sum = sum(v + Decimal('.5') for v in reported)
    missing_lower = max(Decimal(0), total - Decimal('.5') - upper_sum)
    missing_upper = total + Decimal('.5') - lower_sum
    if missing_upper < missing_lower:
        raise ValueError('Material control cannot reconcile even under printed rounding')
    return items, dict(year=2014, geography='APEC_China_code_005', unit='ktoe',
        total_nonenergy_control=float(total), reported_cells=len(reported), mapped_centres_ktoe=float(mapped),
        unresolved_cells=len(missing), missing_cells=missing,
        unassigned_joint_lower_ktoe=float(missing_lower), unassigned_joint_upper_ktoe=float(missing_upper),
        assumption='Nonnegative gross inputs and independent nearest-integer rounding. Joint bound, not one bound per blank. Model maps reported centres only; unknown cells are not imputed zero.',
        national_admission=False)


def references():
    review = json.loads((ROOT / REVIEW).read_text(encoding='utf-8'))
    if (review['decision'] != 'limited_nonenergy_partition_hypothesis' or not review['checks'] or
            not all(c['passed'] is True and c['evidence'] for c in review['checks'])):
        raise ValueError('Material-use mapping not reviewed')
    for item in review['fingerprints']:
        if sha(local_path(ROOT, item['path'])) != item['sha256']:
            raise ValueError('Reviewed material reference changed')
    verify_source_records(ROOT, review['source_records'])
    ap = json.loads((ROOT / 'data/catalog/q2_apec_balance_review.json').read_text(encoding='utf-8'))
    table = parse_table((ROOT / ap['ktoe_export']).read_text(encoding='utf-8-sig'), 'Unit:KTOE', ap)
    items, bounds = extract_material_reference(table)
    return review, items, bounds


def split_material(model, items, elasticities):
    if set(elasticities) != {'coal', 'oil', 'gas'} or any(
            type(v) not in (int, float) or not isfinite(v) or not 0 <= v <= 2 for v in elasticities.values()):
        raise ValueError('Three finite, bounded material response assumptions required')
    result = deepcopy(model)
    if result['start_year'] != 2014:
        raise ValueError('2014 material reference cannot initialize another year')
    op = result['operation']
    if any(s['id'].startswith('nonenergy_') for s in op['services']):
        raise ValueError('Material partition already applied')
    if len({item['id'] for item in items}) != len(items):
        raise ValueError('Duplicate material reference')
    if any(item['carrier'] not in PRODUCTS for item in items):
        raise ValueError('Unmapped material carrier')
    mappings = []
    for carrier in ('coal', 'oil', 'gas'):
        service = next(s for s in op['services'] if s['id'] == carrier + '_residual')
        device = next(d for d in op['devices'] if d['service'] == service['id'])
        if device['node'] != carrier or device['service_per_mwh'] != 1.:
            raise ValueError('Partition requires the declared one-to-one residual input proxy')
        opening = fsum(d * w for d, w in zip(service['demand'], op['annual_weights']))
        selected = [item for item in items if item['carrier'] == carrier]
        material = fsum(item['input_MWh_LHV'] for item in selected)
        if not 0 < material < opening:
            raise ValueError('Material partition exceeds positive inherited fuel residual')
        if any(type(i['input_MWh_LHV']) not in (int, float) or not isfinite(i['input_MWh_LHV']) or
               i['input_MWh_LHV'] <= 0 or i['owner'] not in {a['id'] for a in result['agents']} for i in selected):
            raise ValueError('Invalid material amount or owner')
        base_demand, base_device = list(service['demand']), deepcopy(device)
        share = material / opening
        service['demand'] = [d * (1 - share) for d in base_demand]
        service['unit'] = 'MWh_unresolved_energy_residual_after_reported_material_partition'
        device['input_capacity_mw'] *= 1 - share
        for item in selected:
            fraction = item['input_MWh_LHV'] / opening
            identity = item['id']
            op['services'].append(dict(id=identity, demand=[d * fraction for d in base_demand],
                unit='MWh_LHV_nonenergy_material_content', priority=service['priority'],
                shortfall_weight=service['shortfall_weight']))
            material_device = deepcopy(base_device)
            material_device.update(id=identity + '_device', service=identity,
                input_capacity_mw=base_device['input_capacity_mw'] * fraction,
                gross_co2_t_per_mwh=0., liability_co2_t_per_mwh=0.)
            op['devices'].append(material_device)
            result['assets'].append(dict(id=identity + '_opening', owner=item['owner'], kind='device',
                component=material_device['id'], quantity=1., online_year=2014, state='operating', fixed_om_per_unit=0.))
            result['demand_drivers'][identity] = dict(gdp_elasticity=elasticities[carrier], annual_intensity_improvement=0.)
            for policy in result['policies']:
                policy['service_prices'][identity] = policy['service_prices'][service['id']]
            mappings.append(dict(**item, inherited_residual_service=service['id'],
                inherited_residual_MWh=opening, fraction_of_inherited_residual=fraction,
                material_gdp_elasticity=elasticities[carrier],
                excluded_combustion_proxy_t_per_MWh=base_device['gross_co2_t_per_mwh'],
                industrial_process_release_or_retention='not modeled; no removal credit'))
    return result, mappings


def build():
    review, items, bounds = references()
    _, parent = history.load_frozen(ROOT / 'workflow/q2_candidates/v10/manifest.json')
    selected = json.loads((ROOT / 'outputs/q2/historical_candidate_v10/training_selection.json').read_text(encoding='utf-8'))['selected']
    base = history.parameterize(history.rule_model(parent['structural_models'][selected['structure']], selected['rule']),
                                parent['experiment']['parameters'], selected['parameters'])
    models = {'v10_control': deepcopy(base)}
    cases = [dict(id='v10_control', kind='unchanged_parent', material_elasticities=None)]
    inherited = {fuel:base['demand_drivers'][fuel + '_residual']['gdp_elasticity'] for fuel in ('coal', 'oil', 'gas')}
    same, mappings = split_material(base, items, inherited)
    models['same_growth_split'] = same
    cases.append(dict(id='same_growth_split', kind='classification_and_owner_mapping_control', material_elasticities=inherited))
    for values in product((0., 1., 2.), repeat=3):
        elasticities = dict(zip(('coal', 'oil', 'gas'), values))
        name = 'material_response_' + '_'.join(str(int(v)) for v in values)
        models[name], _ = split_material(base, items, elasticities)
        cases.append(dict(id=name, kind='unfitted_conditional_response', material_elasticities=elasticities))
    return dict(model=base, structural_models=models, definitions=parent['definitions'],
        observations=parent['observations'], acceptance=parent['acceptance'],
        experiment=dict(selection='No calibration or case selection; all29predeclared cases retained.',
                        targets=parent['experiment']['targets'], windows=parent['experiment']['windows']),
        initialization=dict(parent_selection=selected, material_mappings=mappings, source_bounds=bounds),
        episode=dict(scope='nonenergy_partition_diagnostic_not_national_history', cases=cases,
            mapping_assumptions=review['mapping_assumptions'], national_acceptance=False,
            carbon_target_comparison_admitted=False,
            reason='Model now excludes declared material from direct energy-combustion proxy. Process oxidation, end-of-life release and full GCB boundary remain unresolved; do not rank models against the old aggregate carbon target.'))


def freeze():
    data = build()
    review, _, _ = references()
    parent = json.loads((ROOT / 'workflow/q2_candidates/v10/manifest.json').read_text(encoding='utf-8'))
    artifacts = dict(parent['source_artifacts'])
    artifacts.update({item['path']:item['sha256'] for item in review['fingerprints']})
    artifacts[REVIEW] = sha(ROOT / REVIEW)
    directory = ROOT / DIRECTORY
    if directory.exists():
        for name, document in data.items():
            if json.loads((directory / (name + '.json')).read_text(encoding='utf-8')) != document:
                raise ValueError('Frozen material episode changed; use a new version')
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['source_artifacts'] != artifacts or manifest['builder_sha256'] != sha(Path(__file__)):
            raise ValueError('Frozen material builder or source changed')
        return 'Existing29case material episode reproduced exactly'
    directory.mkdir(parents=True)
    for name, document in data.items():
        dump(directory / (name + '.json'), document)
    dump(directory / 'manifest.json', dict(version=2, owner='p2/yx',
        scope=parent['scope'], study_kind='fixed_nonenergy_partition_no_calibration',
        national_admission=False, frozen_before_first_run=True, previous_holdout_already_seen=True,
        builder_sha256=sha(Path(__file__)),
        inputs={name:dict(path=(directory / (name + '.json')).relative_to(ROOT).as_posix(),
                         sha256=sha(directory / (name + '.json'))) for name in data},
        source_artifacts=artifacts))
    return 'Frozen29case material episode; no fitting or national admission'


if __name__ == '__main__':
    print(freeze())
