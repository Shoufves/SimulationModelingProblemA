"""Freeze v2 cost-only versus distinct-new-cohort PV mapping before training.

This follow-up was designed after v1's already-seen holdout; it is exploratory,
not a fresh blind test. Nuclear statuses remain evidence, not invented projects.
"""
import json
from copy import deepcopy
from pathlib import Path

import build_q2_historical_candidate as base
from energy_model.q2.io import dump, local_path, sha, verify_source_records

ROOT = base.ROOT


def references():
    review = json.loads((ROOT / 'data/catalog/q2_mapping_2014_review.json').read_text(encoding='utf-8'))
    if review['decision'] != 'scoped_2014_mapping_reference_not_national_model':
        raise ValueError('Mapping reference review missing')
    if not review['checks'] or not all(c['passed'] is True and c['evidence'] for c in review['checks']):
        raise ValueError('Mapping reference review unresolved')
    for item in review['fingerprints']:
        if sha(local_path(ROOT, item['path'])) != item['sha256']:
            raise ValueError('Mapping reference changed: ' + item['path'])
    verify_source_records(ROOT, review['source_records'])
    return json.loads((ROOT / 'data/catalog/q2_mapping_2014_transcription.json').read_text(encoding='utf-8')), review


def build():
    data = base.build()
    ref, review = references()
    solar = {r['id']: r['value'] for r in ref['solar']}
    deflators = ref['deflator']['values']
    conversion = deflators['2008'] / deflators['2014'] / 1000
    # Three prespecified price hypotheses span the printed typical range. Its
    # arithmetic midpoint is a research node, not a published country mean.
    costs = [solar['pv_typical_low'], (solar['pv_typical_low'] + solar['pv_typical_high']) / 2,
             solar['pv_typical_high']]
    model = data['model']
    opening = next(p for p in model['operation']['processes'] if p['id'] == 'solar_power')
    new = deepcopy(opening)
    new['id'] = 'solar_new_power'
    new['availability'] = [0., 2 * solar['pv_new_project_cf'], 2 * solar['pv_new_project_cf'], 0.]
    model['operation']['processes'].append(new)
    old_option = next(o for o in model['investment_options'] if o['id'] == 'solar_build')
    option = deepcopy(old_option)
    option.update(id='solar_new_build', component=new['id'], known_year=2016,
                  capex_per_unit=costs[1] * conversion, expected_utilisation=solar['pv_new_project_cf'])
    # Conservative next-full-year information convention for a2015 publication.
    # Existing2010 option remains available; it is not retroactively repriced.
    model['investment_options'].append(option)
    next(a for a in model['agents'] if a['id'] == 'generation')['initial_margins'][option['id']] = 0.
    model['cost_decline'][option['id']] = model['cost_decline']['solar_build']
    # No opening asset is invented for this new project vintage. Once it is
    # commissioned, expected returns learn from its own cohort's dispatch.
    for definition in data['definitions']:
        for terms in (definition['numerator'], definition['denominator'] or []):
            for term in terms:
                if 'solar_power' in term.get('ids', []) and 'solar_new_power' not in term['ids']:
                    term['ids'].append('solar_new_power')
    structures = {'updated_cost_only': deepcopy(model), 'new_project_cohort': deepcopy(model)}
    cost_only = structures['updated_cost_only']
    next(p for p in cost_only['operation']['processes'] if p['id'] == new['id'])['availability'] = list(opening['availability'])
    next(o for o in cost_only['investment_options'] if o['id'] == option['id'])['expected_utilisation'] = old_option['expected_utilisation']
    data['structural_models'] = structures
    data['experiment']['structural_alternatives'] = list(structures)
    data['experiment']['parameters'].append({'id': 'solar_capex_million_USD2008_per_MW',
        'grid': [v * conversion for v in costs], 'bounds': [costs[0] * conversion, costs[-1] * conversion],
        'paths': [['investment_options', len(model['investment_options']) - 1, 'capex_per_unit']]})
    data['experiment'].update(maximum_evaluations=81,
        selection='Minimum2015-2021 training loss over2 frozen structures x3 rules x81vectors; selected structure/rule/vector fixed before2022-2024 evaluation.',
        development_information='V1 holdout was already seen before this version was designed. This is exploratory follow-up, not independent validation.',
        source_publication_convention='IRENA2015 cost/CF enters decisions from2016. Revised price index used for retrospective constant-unit normalization only.')
    data['assumptions'].extend([
        {'id': 'V2A01', 'topic': 'Price-year normalization', 'status': 'explicit_research_assumption_not_observation',
         'statement': f'IRENA typical installed-cost interval1320-3090USD2014/kW rebased by US GDP deflator D2008/D2014={conversion * 1000:.16g}. General price conversion, not Chinese technology inflation. Midpoint2205 is an assumed grid node. Original2008USD prices and all other technology samples retained.'},
        {'id': 'V2A02', 'topic': 'PV cohort mapping', 'status': 'explicit_research_assumption_not_observation',
         'statement': 'New utility-PV project process uses indicative17% availability with assumed daytime shape, preserving opening fleet at its2014 ratio. It is not observed hourly availability; no inferred national utility/distributed split. Comparison variant retains old availability while updating new-project cost only. IRENA total installed cost used as a fully funded project-cost proxy; financing/cost-definition equivalence remains unreviewed.'},
        {'id': 'V2A03', 'topic': 'Unresolved queue and scale', 'status': 'explicit_research_assumption_not_observation',
         'statement': 'Twelve NNSA unit statuses are reviewed separately but unknown rated capacities, stock overlap, remaining time and funds prevent physical queue admission. Empty initial queue persists as diagnostic assumption. Installation limits and20x ceiling remain v1 assumptions; new option has its own limit, so combined-vintage competition is an explicit limitation rather than certified construction capacity.'}])
    data['initialization']['new_PV_mapping'] = {'currency_conversion': conversion, 'price_nodes_USD2014_per_kW': costs,
        'availability_cf': solar['pv_new_project_cf'], 'decision_available_from': 2016,
        'opening_solar_unchanged': True, 'new_opening_capacity_MW': 0., 'nuclear_queue_admitted': False}
    data['acceptance'] = json.loads((ROOT / 'workflow/q2_acceptance.json').read_text(encoding='utf-8'))
    return data


def freeze():
    directory = ROOT / 'workflow/q2_candidates/v2r1'
    documents = build()
    _, review = references()
    parent = json.loads((ROOT / 'workflow/q2_candidates/v1/manifest.json').read_text(encoding='utf-8'))
    artifacts = dict(parent['source_artifacts'])
    artifacts.update({r['path']: r['sha256'] for r in review['fingerprints']})
    rp = 'data/catalog/q2_mapping_2014_review.json'
    artifacts[rp] = sha(ROOT / rp)
    if directory.exists():
        for name, document in documents.items():
            if json.loads((directory / (name + '.json')).read_text(encoding='utf-8')) != document:
                raise ValueError('Frozen v2 differs; use a new version')
        if json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))['source_artifacts'] != artifacts:
            raise ValueError('Frozen v2 references changed')
        return 'Existing v2 reproduced exactly; no files changed'
    directory.mkdir(parents=True)
    for name, document in documents.items():
        dump(directory / (name + '.json'), document)
    dump(directory / 'manifest.json', {'version': 2, 'revision': 'r1_metric_alias_fix', 'owner': 'p2/yx', 'scope': parent['scope'],
         'national_admission': False, 'frozen_before_first_fit': True,
         'previous_holdout_already_seen': True, 'builder_sha256': sha(Path(__file__)),
         'inputs': {name: {'path': (directory / (name + '.json')).relative_to(ROOT).as_posix(),
                           'sha256': sha(directory / (name + '.json'))} for name in documents},
         'source_artifacts': artifacts,
         'admission_limitation': 'Exploratory cost/cohort ablation; original accounting, demand, queue and policy gaps remain.'})
    return 'Frozen v2:486 training cases; no national admission'


if __name__ == '__main__':
    print(freeze())
