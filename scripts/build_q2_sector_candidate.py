"""Freeze a sector-resolved final-energy diagnostic, preserving unresolved uses.

Nine reported APEC sector/carrier groups partition the existing fuel residuals.
These are delivered-final-energy proxies, NOT measured useful heat or mobility.
The parent effective CO2 formula is retained solely for numerical comparability.
"""
from copy import deepcopy
from decimal import Decimal
import json
from math import fsum, isfinite
from pathlib import Path

import run_q2_historical_candidate as history
from run_q2_joint_deployment_comparison import training_winners
from prepare_q2_apec_balance import parse_table, TOP_COLUMNS, value
from energy_model.q2.io import dump, local_path, sha, verify_source_records

ROOT = history.ROOT
DIRECTORY = 'workflow/q2_candidates/v11'
REVIEW = 'data/catalog/q2_sector_partition_review.json'
PRODUCTS = {'coal': ('1. Coal', '2. Coal products'),
            'oil': ('6. Crude oil & NGL', '7. Petroleum products'), 'gas': ('8. Gas',)}
SECTORS = {'industry': ('14. Industry sector', 'industrial'),
           'transport': ('15. Transport sector', 'transport'),
           'other': ('16. Other sector', 'buildings')}
MWH_PER_KTOE = Decimal('11630')


def extract_sectors(table):
    if not table or any(not r or len(r) != len(table[0]) for r in table):
        raise ValueError('Rectangular sector table required')
    labels = table[0]
    if len(set(labels)) != len(labels) or len({r[0] for r in table[1:]}) != len(table)-1:
        raise ValueError('Duplicate sector row/column')
    rows = {r[0]: (i, r) for i, r in enumerate(table[1:], 1)}
    if not {r[0] for r in SECTORS.values()} <= rows.keys():
        raise ValueError('Required sector rows missing')
    if not {'19. Total', *(p for products in PRODUCTS.values() for p in products)} <= set(labels):
        raise ValueError('Required carrier columns missing')
    items, controls = [], []
    for sector, (flow, owner) in SECTORS.items():
        index, row = rows[flow]
        reported = [value(row[c]) for c in TOP_COLUMNS if value(row[c]) is not None]
        total = value(row[labels.index('19. Total')])
        if total is None or total <= 0 or any(v < 0 for v in reported):
            raise ValueError('Positive sector control and nonnegative final energy required')
        lo = sum(max(Decimal(0), v-Decimal('.5')) for v in reported)
        hi = sum(v+Decimal('.5') for v in reported)
        missing_lo = max(Decimal(0), total-Decimal('.5')-hi)
        missing_hi = total+Decimal('.5')-lo
        if missing_hi < missing_lo:
            raise ValueError('Sector control violates printed rounding bounds')
        controls.append(dict(sector=sector, total_ktoe=float(total), reported_top_sum_ktoe=float(sum(reported)),
            missing_top_cells=len(TOP_COLUMNS)-len(reported), joint_missing_lower_ktoe=float(missing_lo),
            joint_missing_upper_ktoe=float(missing_hi),
            assumption='Nonnegative inputs; nearest integer rounding. One joint interval per sector, not per missing cell.'))
        for carrier, products in PRODUCTS.items():
            cells, missing = [], []
            for name in products:
                col = labels.index(name)
                token, amount = row[col], value(row[col])
                reference = dict(flow=flow, product=name, tsv_line=index+3, column=col+1, raw_token=token)
                if amount is None:
                    missing.append(reference)
                else:
                    cells.append(dict(**reference, value_ktoe=float(amount)))
            amount = sum(Decimal(c['raw_token']) for c in cells)
            if amount <= 0:
                raise ValueError('Each of nine sector/carrier groups requires reported positive input')
            items.append(dict(id='final_' + sector + '_' + carrier, sector=sector, owner=owner, carrier=carrier,
                cells=cells, unresolved_product_cells=missing, value_ktoe=float(amount),
                input_MWh_LHV=float(amount*MWH_PER_KTOE),
                meaning='Reported delivered final energy, not useful heat/mobility or equipment stock'))
    return items, controls


def source_reference():
    ap = json.loads((ROOT/'data/catalog/q2_apec_balance_review.json').read_text(encoding='utf-8'))
    table = parse_table((ROOT/ap['ktoe_export']).read_text(encoding='utf-8-sig'), 'Unit:KTOE', ap)
    return extract_sectors(table)


def reviewed_reference():
    review = json.loads((ROOT/REVIEW).read_text(encoding='utf-8'))
    if (review['decision'] != 'limited_sector_final_energy_partition_hypothesis' or
            review['national_admission'] is not False or not review['checks'] or
            not all(c['passed'] is True and c['evidence'] for c in review['checks'])):
        raise ValueError('Sector partition lacks scoped substantive review')
    for item in review['fingerprints']:
        if sha(local_path(ROOT, item['path'])) != item['sha256']:
            raise ValueError('Reviewed sector reference changed')
    verify_source_records(ROOT, review['source_records'])
    items, controls = source_reference()
    return review, items, controls


def partition(model, items):
    """Retain each carrier's residual growth and proxy CO2; carve only known inputs."""
    if (len(items) != 9 or len({i['id'] for i in items}) != 9 or
            {(i['sector'], i['carrier']) for i in items} != {(s,c) for s in SECTORS for c in PRODUCTS}):
        raise ValueError('Nine unique sector/carrier groups required')
    if model['start_year'] != 2014:
        raise ValueError('Sector reference year is 2014')
    result = deepcopy(model)
    op = result['operation']
    if any(s['id'].startswith('final_') for s in op['services']):
        raise ValueError('Sector partition already applied')
    mappings = []
    for carrier in PRODUCTS:
        service = next(s for s in op['services'] if s['id'] == carrier+'_residual')
        device = next(d for d in op['devices'] if d['service'] == service['id'])
        if device['node'] != carrier or device['service_per_mwh'] != 1.:
            raise ValueError('Partition requires one-to-one parent fuel accounting')
        old_assets = [a for a in result['assets'] if a['kind']=='device' and a['component']==device['id']]
        if len(old_assets)!=1 or old_assets[0]['quantity']!=1. or old_assets[0]['fixed_om_per_unit']!=0.:
            raise ValueError('Reviewed parent device must have one normalized opening unit and zero fixed cost')
        selected = [i for i in items if i['carrier']==carrier]
        if any(type(i['input_MWh_LHV']) not in (int,float) or not isfinite(i['input_MWh_LHV']) or
               i['input_MWh_LHV'] <= 0 or i['owner'] != SECTORS[i['sector']][1] for i in selected):
            raise ValueError('Invalid sector amount or accounting owner')
        opening = fsum(d*w for d,w in zip(service['demand'],op['annual_weights']))
        final = fsum(i['input_MWh_LHV'] for i in selected)
        if not 0 < final < opening:
            raise ValueError('Reported sector inputs exceed inherited residual; no rescaling')
        before, base = list(service['demand']), deepcopy(device)
        service['demand'] = [d*(1-final/opening) for d in before]
        service['unit'] = 'MWh_LHV_unresolved_conversion_own_use_material_and_source_bridge_proxy'
        device['input_capacity_mw'] *= 1-final/opening
        for item in selected:
            fraction, identity = item['input_MWh_LHV']/opening, item['id']
            op['services'].append(dict(id=identity, demand=[d*fraction for d in before],
                unit='MWh_LHV_reported_sector_final_energy_proxy', priority=service['priority'],
                shortfall_weight=service['shortfall_weight']))
            new_device = deepcopy(base)
            new_device.update(id=identity+'_device', service=identity, input_capacity_mw=base['input_capacity_mw']*fraction)
            op['devices'].append(new_device)
            result['assets'].append(dict(id=identity+'_opening', owner=item['owner'], kind='device',
                component=new_device['id'], quantity=1., online_year=2014, state='operating', fixed_om_per_unit=0.))
            # Same-carrier growth is the classification control. Experiment paths
            # explicitly replace these nine elasticities by three sector responses.
            result['demand_drivers'][identity] = deepcopy(result['demand_drivers'][service['id']])
            for policy in result['policies']:
                policy['service_prices'][identity] = policy['service_prices'][service['id']]
            mappings.append(dict(**item, inherited_residual_MWh=opening,
                fraction_of_inherited_residual=fraction, remaining_unresolved_MWh=opening-final,
                carbon_coefficient_role='Unchanged parent effective accounting coefficient, not a measured combustion factor'))
    return result, mappings


def build():
    review, items, controls = reviewed_reference()
    _, parent = history.load_frozen(ROOT/'workflow/q2_candidates/v10/manifest.json')
    trials = json.loads((ROOT/'outputs/q2/historical_candidate_v10/training_trials.json').read_text(encoding='utf-8'))
    structures = parent['experiment']['structural_alternatives']
    winners = training_winners(trials, structures)
    original, split = {}, {}
    for structure in structures:
        best = winners[structure]
        original[structure] = history.parameterize(history.rule_model(parent['structural_models'][structure],best['rule']),
                                                  parent['experiment']['parameters'],best['parameters'])
        split[structure], mappings = partition(original[structure],items)
    selected = json.loads((ROOT/'outputs/q2/historical_candidate_v10/training_selection.json').read_text(encoding='utf-8'))['selected']
    parameters = [dict(id=sector+'_gdp_response', grid=[0.,.5,1.,1.5,2.], bounds=[0.,2.],
        paths=[['demand_drivers',i['id'],'gdp_elasticity'] for i in items if i['sector']==sector]) for sector in SECTORS]
    return dict(model=original[selected['structure']], control_models=original, structural_models=split,
        definitions=parent['definitions'], observations=parent['observations'], acceptance=parent['acceptance'],
        experiment=dict(windows=parent['experiment']['windows'],targets=parent['experiment']['targets'],
            parameters=parameters, structural_alternatives=structures, maximum_evaluations=756,
            equivalent_loss_absolute_tolerance=parent['experiment']['equivalent_loss_absolute_tolerance'],
            selection='2015-2021 only; six exact v10 controls plus125sector response vectors per structure. No holdout feedback.',
            development_information='V10 holdout already seen. Wind/PV rates and behavior rule retained from each v10 training winner; this block-coordinate experiment is not a joint global optimum.',
            carbon_accounting='Unchanged v10 effective CO2 proxy including unresolved uses; not the partial-carbon nonenergy episode. No physical/nonenergy emissions admission follows.'),
        initialization=dict(parent_training_winners=winners, parent_overall_selection=selected,
            sector_mappings=mappings, sector_joint_missing_bounds=controls,
            mapping_assumptions=review['mapping_assumptions'], national_admission=False))


def freeze():
    data = build()
    review, _, _ = reviewed_reference()
    parent = json.loads((ROOT/'workflow/q2_candidates/v10/manifest.json').read_text(encoding='utf-8'))
    artifacts = dict(parent['source_artifacts'])
    artifacts.update({r['path']:r['sha256'] for r in review['fingerprints']})
    artifacts[REVIEW] = sha(ROOT/REVIEW)
    out = ROOT/DIRECTORY
    if out.exists():
        for name, document in data.items():
            if json.loads((out/(name+'.json')).read_text(encoding='utf-8')) != document:
                raise ValueError('Frozen v11 inputs changed; preserve and version the revision')
        manifest = json.loads((out/'manifest.json').read_text(encoding='utf-8'))
        if manifest['source_artifacts'] != artifacts or manifest['builder_sha256'] != sha(Path(__file__)):
            raise ValueError('Frozen v11 source/builder changed')
        return 'Frozen v11 sector candidate reproduced exactly'
    out.mkdir(parents=True)
    for name,document in data.items():
        dump(out/(name+'.json'),document)
    dump(out/'manifest.json',dict(version=11, owner='p2/yx', scope=parent['scope'],
        study_kind='sector_final_energy_response_training_diagnostic', national_admission=False,
        frozen_before_first_run=True, previous_holdout_already_seen=True, builder_sha256=sha(Path(__file__)),
        inputs={name:dict(path=(out/(name+'.json')).relative_to(ROOT).as_posix(),sha256=sha(out/(name+'.json'))) for name in data},
        source_artifacts=artifacts))
    return 'Frozen v11: six parent controls and750sector-response training paths'


if __name__ == '__main__':
    print(freeze())
