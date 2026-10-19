"""Freeze v10: a bounded latent PV queue jointly with deployment constraints.

The opening queue is a research hypothesis, not a recovered project inventory.
The zero-queue subgrid is exactly v9; observations and rate bounds stay frozen.
"""
from copy import deepcopy
import json
from math import isfinite
from pathlib import Path

import run_q2_historical_candidate as history
from energy_model.q2.io import dump, sha

ROOT = history.ROOT
QUEUE_MULTIPLIERS = (0, 1, 2)


def with_pv_queue(model, multiplier):
    if type(multiplier) not in (int, float) or not isfinite(multiplier) or multiplier not in QUEUE_MULTIPLIERS:
        raise ValueError('PV queue multiplier must belong to the frozen 0/1/2 grid')
    result = deepcopy(model)
    if multiplier == 0:
        return result
    if result['start_year'] != 2014:
        raise ValueError('Latent queue schedule is specific to the 2014 initialization')
    identity = 'opening_queue:latent_solar_2013'
    if any(p['id'] == identity for p in result['initial_projects']):
        raise ValueError('Latent PV queue already initialized')
    option = next(o for o in result['investment_options'] if o['id'] == 'solar_build')
    group = next(g for g in result['investment_groups'] if g['id'] == 'solar_construction')
    if option['component'] != 'solar_power' or option['known_year'] > 2014:
        raise ValueError('Opening reconstruction cannot use the 2015 new-PV technology')
    quantity = multiplier * group['annual_installation_floor']
    cost = quantity * option['capex_per_unit']
    remaining = cost / 2
    owner = next(a for a in result['agents'] if a['id'] == option['owner'])
    if quantity <= 0 or cost <= 0 or remaining > owner['cash']:
        raise ValueError('Latent queue requires positive scale and available opening cash')
    result['initial_projects'].append(dict(
        id=identity, option=option['id'], owner=option['owner'], kind=option['kind'],
        component=option['component'], quantity=quantity, applied_year=2013,
        online_year=2015, lead_years=2, cost=cost, remaining_cost=remaining,
        state='building', replaces=None, construction_fractions=[0.5, 0.5],
        fixed_om_per_unit=option['fixed_om_per_unit'], replacement_units=0.,
        state_basis='latent_initialization_hypothesis_not_observed_project',
        schedule_basis='assumed_2013_application_2015_commissioning_half_cost_unpaid',
        cost_basis='inherited_old_PV_reference_not_actual_project_budget',
        information_limitation='2014 retrospective state reconstruction; not a replay of a documented 2013 decision'))
    owner['cash'] -= remaining
    result['other_accounts']['escrow'] += remaining
    return result


def build():
    _, data = history.load_frozen(ROOT / 'workflow/q2_candidates/v9/manifest.json')
    originals = data['structural_models']
    models = {}
    descriptions = {}
    for multiplier in QUEUE_MULTIPLIERS:
        for structure, model in originals.items():
            name = structure if multiplier == 0 else f'{structure}_pvqueue_{multiplier}'
            models[name] = with_pv_queue(model, multiplier)
            descriptions[name] = dict(deployment_structure=structure, queue_multiplier=multiplier,
                                      initial_PV_queue_MW=multiplier * 8170.)
    data['structural_models'] = models
    # Keep model and first486 trials byte/number equivalent to v9.
    data['experiment'].update(
        structural_alternatives=list(models),
        selection='2015-2021 loss only; 3 latent queue states x 2 deployment structures x 3 existing rules x 81 wind/PV rate pairs. Exact ties retain declared trial order.',
        development_information='V1-v9 holdout already seen. This is an exploratory initial-state/deployment identification diagnostic, not fresh validation. Other fitted parameters, observations, thresholds and rate bounds stay frozen.')
    data['initialization']['latent_pv_queue_v10'] = dict(
        hypotheses=descriptions, added_fitted_dimensions=1, maximum_total_training_cases=1458,
        control_is_entire_v9_subgrid=True, queue_scale_MW=8170.,
        scale_basis='Inherited 2014 annual-additions reference; not an observation or upper bound for an uncommissioned queue',
        timetable='2013 application, two-year uniform spending, half unpaid at initialization, 2015 commissioning; all hypothetical',
        technology='Inherited old solar_power only; never the source first available in 2015',
        cash='Reallocate outstanding commitment from generator cash to escrow; do not add money',
        prior_cost='The already-spent half is a sunk pre-start outlay; not a model-period cash transaction',
        boundaries='2014 reference stock retained exactly; its end-year/start-state approximation is inherited. The prior queue is not assumed observed at either boundary.',
        no_source_for_actual_queue=True, new_future_information=False)
    data['assumptions'].append(dict(id='V10A01', topic='Latent opening PV construction pipeline',
        status='explicit_research_assumption_not_observation',
        statement='The limited nominal-tariff episode left physical paths unchanged because the assumed deployment limit already bound. Test a missing opening pipeline at 0/1/2 times the inherited 8170MW additions scale, not a measured prior or credible interval. Jointly refit both wind/PV rates and both deployment structures on training only. Prior projects use old PV technology and a hypothetical two-year schedule, not 2015 technology retrospectively. This tests an initial-state mechanism, not actual PV project dates, subsidy eligibility or policy causality. Cash is conserved by reserving half the modeled cost. Queue-size selection is a fitted latent state and increases model flexibility; boundary optima or better fit cannot establish a real queue or national admission.'))
    return data


def freeze():
    parent, _ = history.load_frozen(ROOT / 'workflow/q2_candidates/v9/manifest.json')
    data = build()
    artifacts = dict(parent['source_artifacts'])
    for relative in ('workflow/q2_candidates/v9/manifest.json',
                     'outputs/q2/historical_candidate_v9/training_trials.json',
                     'outputs/q2/nominal_policy_episode/summary.json'):
        artifacts[relative] = sha(ROOT / relative)
    directory = ROOT / 'workflow/q2_candidates/v10'
    if directory.exists():
        for name, value in data.items():
            if json.loads((directory / (name + '.json')).read_text(encoding='utf-8')) != value:
                raise ValueError('Frozen v10 differs; use a new version')
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        if manifest['source_artifacts'] != artifacts or manifest['builder_sha256'] != sha(Path(__file__)):
            raise ValueError('Frozen v10 builder or sources changed')
        return 'Existing v10 reproduced exactly'
    directory.mkdir(parents=True)
    for name, value in data.items():
        dump(directory / (name + '.json'), value)
    dump(directory / 'manifest.json', dict(version=10, owner='p2/yx', scope=parent['scope'],
        national_admission=False, frozen_before_first_fit=True, previous_holdout_already_seen=True,
        builder_sha256=sha(Path(__file__)),
        inputs={name: dict(path=(directory / (name + '.json')).relative_to(ROOT).as_posix(),
                           sha256=sha(directory / (name + '.json'))) for name in data},
        source_artifacts=artifacts,
        admission_limitation='Latent initial PV pipeline is hypothetical. All existing service, accounting, policy, current-state and net-CO2 admission gaps remain.'))
    return 'Frozen v10:1458 training cases, including the complete486-case v9 control'


if __name__ == '__main__':
    print(freeze())
