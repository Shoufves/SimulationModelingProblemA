"""Freeze v4: reviewed2014 nuclear queue with explicit schedule/cash hypotheses."""
import csv
import json
from copy import deepcopy
from pathlib import Path

import build_q2_capacity_candidate as previous
from energy_model.q2.io import dump, local_path, sha, verify_source_records

ROOT = previous.ROOT


def queue_references():
    review = json.loads((ROOT / 'data/catalog/q2_nuclear_queue_review.json').read_text(encoding='utf-8'))
    if review['decision'] != 'scoped_2014_nuclear_queue_reference' or not all(c['passed'] and c['evidence'] for c in review['checks']):
        raise ValueError('Queue reference review unresolved')
    for item in review['fingerprints']:
        if sha(local_path(ROOT, item['path'])) != item['sha256']:
            raise ValueError('Queue reference changed: ' + item['path'])
    verify_source_records(ROOT, review['source_records'])
    with (ROOT / 'data/processed/q2/nuclear_queue_2014_reference.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.DictReader(f))
    if len(rows) != 26 or sum(float(r['capacity_MW']) for r in rows) != 28450:
        raise ValueError('Queue reference counts changed')
    if any(r['online_year'] or r['remaining_years'] or r['remaining_cost'] for r in rows):
        raise ValueError('Future timing or funding cannot masquerade as reference observation')
    return rows, review


def with_queue(model, rows, delay):
    c = deepcopy(model)
    option = next(o for o in c['investment_options'] if o['id'] == 'nuclear_build')
    # These durations are assumptions linked to verified2014 states; none is
    # an observed future commissioning date. The whole family is frozen.
    durations = {'near_completion':1, 'testing':2, 'installation':3,
                 'first_of_kind_delayed':4, 'civil':5}
    for row in rows:
        applied = int(row['construction_start_month'][:4])
        online = 2014 + durations[row['diagnostic_stage']] + delay
        lead = online - applied
        fractions = [1. / lead] * lead
        quantity = float(row['capacity_MW'])
        cost = quantity * option['capex_per_unit']
        remaining = cost * sum(f for i, f in enumerate(fractions) if applied + i >= c['start_year'])
        c['initial_projects'].append({'id':'opening_queue:' + row['id'], 'option':option['id'],
            'owner':option['owner'], 'kind':option['kind'], 'component':option['component'],
            'quantity':quantity, 'applied_year':applied, 'online_year':online, 'lead_years':lead,
            'cost':cost, 'remaining_cost':remaining, 'state':'building', 'replaces':None,
            'construction_fractions':fractions, 'fixed_om_per_unit':option['fixed_om_per_unit'], 'replacement_units':0.,
            'reference_unit':row['id'], 'schedule_basis':'assumed_stage_duration_plus_common_delay',
            'cost_basis':'IEA2010_nuclear_sample_proxy_uniform_construction_spending_not_observed_project_budget'})
    reserved = sum(p['remaining_cost'] for p in c['initial_projects'])
    next(a for a in c['agents'] if a['id'] == option['owner'])['cash'] -= reserved
    c['other_accounts']['escrow'] += reserved
    return c


def build():
    data = previous.build()
    rows, _ = queue_references()
    # Inherit only the earlier training-selected construction hypothesis.
    # Previous holdout results are never read by this builder.
    selection = json.loads((ROOT / 'outputs/q2/historical_candidate_v3/training_selection.json').read_text(encoding='utf-8'))
    structure = selection['selected']['structure']
    model = data['structural_models'][structure]
    models = {'empty_queue_control':deepcopy(model)}
    for name, delay in [('stage_schedule',0), ('stage_plus_one_year',1), ('stage_plus_two_years',2)]:
        models[name] = with_queue(model, rows, delay)
    data['model'] = models['stage_schedule']
    data['structural_models'] = models
    data['experiment']['structural_alternatives'] = list(models)
    data['experiment']['selection'] = 'Minimum2015-2021 loss over4 frozen initial-queue hypotheses x3 rules x81vectors; construction hypothesis inherited from v3 training only.'
    data['experiment']['development_information'] = 'Exploratory iteration after v1-v3 already-seen holdout; no independent validation claim. Sequential structure selection is additional model search and must not be hidden by counting only four grid parameters.'
    data['initialization']['nuclear_queue_reconstruction'] = {
        'source_units':26, 'source_capacity_MW':28450, 'inherited_construction_hypothesis':structure,
        'remaining_years_by_stage':{'near_completion':1, 'testing':2, 'installation':3, 'first_of_kind_delayed':4, 'civil':5},
        'additional_delays_years':[0,1,2], 'no_queue_control':True,
        'source_dates':'2014year-end status and historical construction-start month only',
        'cost':'Same existing representative nuclear sample in million2008USD; not actual project budget',
        'funding':'Uniform annual construction-cost hypothesis from start year through year before modeled online; unpaid balance fully escrowed from opening generator cash',
        'status':'explicit_diagnostic_reconstruction_not_national_initial_state_admission'}
    data['assumptions'].append({'id':'V4A01','topic':'Initial nuclear queue and cash',
        'status':'explicit_research_assumption_not_observation',
        'statement':'This variant supersedes earlier empty-queue limitation for three schedule hypotheses, retaining empty control.26matched units28450MW from NEA2014year-end table;20MWNEA/NBS opening-stock difference not rescaled. Remaining years1/2/3/4/5 by reviewed stage and common delays0/1/2 are assumptions, not actual future completion or operating permits. Uniform construction spending, generic sample capex, inherited nuclear dispatch ratio, year-step full-year operation and fixed financing remain reduced-model assumptions.2014 is initialization replay, not independently validated operation; never claim these2015 publications were contemporaneous2014 investment information.'})
    return data


def freeze():
    data = build()
    _, review = queue_references()
    directory = ROOT / 'workflow/q2_candidates/v4'
    parent = json.loads((ROOT / 'workflow/q2_candidates/v3/manifest.json').read_text(encoding='utf-8'))
    artifacts = dict(parent['source_artifacts'])
    artifacts.update({r['path']:r['sha256'] for r in review['fingerprints']})
    for relative in ('data/catalog/q2_nuclear_queue_review.json', 'data/processed/q2/nuclear_queue_2014_reference.csv',
                     'outputs/q2/historical_candidate_v3/training_selection.json'):
        artifacts[relative] = sha(ROOT / relative)
    if directory.exists():
        for name, document in data.items():
            if json.loads((directory / (name + '.json')).read_text(encoding='utf-8')) != document:
                raise ValueError('Frozen v4 differs; use a new version')
        if json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))['source_artifacts'] != artifacts:
            raise ValueError('Frozen v4 references changed')
        return 'Existing v4 reproduced exactly'
    directory.mkdir(parents=True)
    for name, document in data.items(): dump(directory / (name + '.json'), document)
    dump(directory / 'manifest.json', {'version':4, 'owner':'p2/yx', 'scope':parent['scope'],
        'national_admission':False, 'frozen_before_first_fit':True, 'previous_holdout_already_seen':True,
        'builder_sha256':sha(Path(__file__)),
        'inputs':{name:{'path':(directory / (name + '.json')).relative_to(ROOT).as_posix(),
                        'sha256':sha(directory / (name + '.json'))} for name in data},
        'source_artifacts':artifacts,
        'admission_limitation':'Verified queue identities/capacities; assumed schedule/funding; unresolved national accounting/demand/policy boundary.'})
    return 'Frozen v4:972 training cases'


if __name__ == '__main__': print(freeze())
