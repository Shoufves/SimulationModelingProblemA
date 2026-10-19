"""Freeze v5: separate fuel demand responses and an observed gas-input ablation.

Sequential exploratory search, not new blind validation or national admission.
Neither CEADs totals nor its post2014 sheets are calibration targets here.
"""
import csv
import json
from copy import deepcopy
from pathlib import Path

import build_q2_historical_candidate as base
from energy_model.q2.io import dump, local_path, sha, verify_source_records
from energy_model.q2.experiments import parameterize

ROOT = base.ROOT


def load_parent():
    parent = json.loads((ROOT/'workflow/q2_candidates/v4/manifest.json').read_text(encoding='utf-8'))
    for relative, expected in parent['source_artifacts'].items():
        if sha(local_path(ROOT,relative)) != expected:
            raise ValueError('Parent source changed: ' + relative)
    data = {}
    for name,binding in parent['inputs'].items():
        path = local_path(ROOT,binding['path'])
        if sha(path) != binding['sha256']: raise ValueError('Frozen parent changed: ' + name)
        data[name] = json.loads(path.read_text(encoding='utf-8'))
    selection = json.loads((ROOT/'outputs/q2/historical_candidate_v4/training_selection.json').read_text(encoding='utf-8'))['selected']
    model = parameterize(data['structural_models'][selection['structure']],
                         data['experiment']['parameters'],selection['parameters'])
    return data,model,parent,selection


def references():
    review = json.loads((ROOT/'data/catalog/q2_national_balance_review.json').read_text(encoding='utf-8'))
    if review['decision'] != 'scoped_2014_national_balance_reference_with_unresolved_discrepancies':
        raise ValueError('National balance reference not reviewed')
    if not review['checks'] or not all(c['passed'] and c['evidence'] for c in review['checks']):
        raise ValueError('National balance checks unresolved')
    for r in review['fingerprints']:
        if sha(local_path(ROOT,r['path'])) != r['sha256']: raise ValueError('National balance reference changed')
    verify_source_records(ROOT,review['source_records'])
    checks = json.loads((ROOT/'data/processed/q2/national_balance_2014_checks.json').read_text(encoding='utf-8'))
    for name,expected in checks['outputs'].items():
        if sha(ROOT/'data/processed/q2'/name) != expected: raise ValueError('Extracted national balance changed')
    with (ROOT/'data/processed/q2/national_balance_2014_reference.csv').open(encoding='utf-8-sig',newline='') as f:
        cells = {r['source_cell']:r for r in csv.DictReader(f)}
    row = cells['R54']
    if (row['year'],row['carrier'],row['unit_as_published'],row['account']) != ('2014','Natural Gas','108 cu.m','Thermal Power'):
        raise ValueError('Gas source year, unit or role changed')
    factors = {r['fuel']:r for r in base.rows('fuel_reference.csv')}
    factor = factors['natural_gas']
    if factor['physical_unit'] != '10^4 m3': raise ValueError('Gas volume unit changed')
    fuel_input = float(row['value']) * 10000 * float(factor['NCV_MWh_per_physical_unit'])
    if fuel_input <= 0: raise ValueError('Missing or invalid gas-power fuel reference')
    return fuel_input,review


def build():
    data,model,_,selection = load_parent()
    gas_input, _ = references()
    models = {'capacity_share_control':deepcopy(model),'gas_power_input_reference':deepcopy(model)}
    new = models['gas_power_input_reference']
    total_gas = data['initialization']['primary_fuel_MWh_equivalent']['gas']
    previous_residual = data['initialization']['base_services_MWh']['gas_residual']
    corrected = total_gas - gas_input
    if not 0 < corrected < total_gas: raise ValueError('Invalid gas initialization hypothesis')
    service = next(s for s in new['operation']['services'] if s['id']=='gas_residual')
    service['demand'] = [v * corrected / previous_residual for v in service['demand']]
    # Freeze upstream training choices. Only these three new demand parameters
    # are searched in this round; no holdout or later source sheet is read.
    parameters = [{'id':fuel+'_residual_elasticity','grid':[0.,.5,1.,1.5,2.],
        'bounds':[0.,2.],'paths':[['demand_drivers',fuel+'_residual','gdp_elasticity']]}
        for fuel in ('coal','oil','gas')]
    data['model'] = new
    data['structural_models'] = models
    data['experiment'].update(parameters=parameters,maximum_evaluations=125,
        structural_alternatives=list(models),
        selection='Minimum2015-2021 loss over2 gas-initialization hypotheses x3 expectation rules x125 fuel-response vectors. All previous cost/build/queue/electricity-response choices fixed from v4 training only.',
        development_information='Exploratory sequential model development after v1-v4 holdout was seen. Three additional response parameters on a common broad zero-to-two grid; original upstream search and its uncertainty remain, not a new blind validation or a global joint optimum.')
    data['initialization']['fuel_response_mapping'] = {
        'inherited_training_selection':selection,'gas_thermal_input_MWh_LHV_reference':gas_input,
        'gas_original_reconstructed_residual_MWh':previous_residual,
        'gas_alternative_reconstructed_residual_MWh':corrected,
        'reference_cell':'CEADs5425546.v1,2014!R54=228.2 in10^8m3',
        'heat_value':'WRI2013 default389310MJ/10^4m3; not2014 observed gas quality',
        'status':'cross_source_mapping_hypothesis_not_reconciled_national_balance'}
    data['assumptions'].extend([
        {'id':'V5A01','topic':'Gas power-use mapping','status':'explicit_research_assumption_not_observation',
         'statement':'Alternative changes only initial residual gas demand: NBS2025-vintage2014 gas primary-energy proxy minus CEADs2014 thermal gas physical input converted with WRI default. No CEADs total rescaling, invented gas generation, dispatch floor, efficiency estimate or future actual demand. Source/method mismatch is unresolved; subtraction is a diagnostic bridge hypothesis. Annual optimized gas dispatch may differ from observed initial use, so exact2014 fuel replay is not asserted.'},
        {'id':'V5A02','topic':'Separate demand responses','status':'explicit_research_assumption_not_observation',
         'statement':'Coal/oil/gas residual services each receive independent GDP elasticity on the same0,0.5,1,1.5,2grid. Zero means no GDP response and two is a research upper bound, not empirical prior. This tests the prior shared-elasticity restriction; residuals still are not observed useful services and contain unresolved nonenergy/loss/heat. No claim of endogenous same-service equipment substitution.'},
        {'id':'V5A03','topic':'Sequential search and information','status':'explicit_research_assumption_not_observation',
         'statement':'V4 training-selected queue, construction structure, PV cost, electricity elasticity and investment adjustment are fixed. Additional three-parameter search and previous searches are all disclosed.2017 source is retrospective initial-state evidence, never a dated2014 policy available to agents. Historical acceptance thresholds and holdout remain frozen; no use for S0.'}])
    return data


def freeze():
    data = build()
    _,_,parent,_ = load_parent()
    _,review = references()
    artifacts = dict(parent['source_artifacts'])
    artifacts.update({r['path']:r['sha256'] for r in review['fingerprints']})
    for relative in ('data/catalog/q2_national_balance_review.json',
                     'data/processed/q2/national_balance_2014_reference.csv',
                     'data/processed/q2/national_balance_2014_checks.json',
                     'data/processed/q2/fuel_reference.csv',
                     'outputs/q2/historical_candidate_v4/training_selection.json',
                     'workflow/q2_candidates/v4/manifest.json'):
        artifacts[relative] = sha(ROOT/relative)
    directory = ROOT/'workflow/q2_candidates/v5'
    if directory.exists():
        for name,document in data.items():
            if json.loads((directory/(name+'.json')).read_text(encoding='utf-8')) != document:
                raise ValueError('Frozen v5 differs; use a new version')
        if json.loads((directory/'manifest.json').read_text(encoding='utf-8'))['source_artifacts'] != artifacts:
            raise ValueError('Frozen v5 sources changed')
        return 'Existing v5 reproduced exactly'
    directory.mkdir(parents=True)
    for name,document in data.items(): dump(directory/(name+'.json'),document)
    dump(directory/'manifest.json',{'version':5,'owner':'p2/yx','scope':parent['scope'],
        'national_admission':False,'frozen_before_first_fit':True,'previous_holdout_already_seen':True,
        'builder_sha256':sha(Path(__file__)),
        'inputs':{name:{'path':(directory/(name+'.json')).relative_to(ROOT).as_posix(),
                       'sha256':sha(directory/(name+'.json'))} for name in data},
        'source_artifacts':artifacts,
        'admission_limitation':'Explicit cross-source initial gas hypothesis and additional demand parameters; unresolved physical accounting, substitution, policy and national quality.'})
    return 'Frozen v5:750 training cases'


if __name__ == '__main__': print(freeze())
