"""Freeze v7 finite technology-frontier versus common-bottleneck hypotheses.

No new numeric cap, fitted parameter or future observation is introduced. The
150GW common limits remain explicit controls; removing either alone cannot remove
the other. This is an exploratory structural test, not national input admission.
"""
import json
from copy import deepcopy
from pathlib import Path

import run_q2_historical_candidate as history
from energy_model.q2.io import dump, sha

ROOT = history.ROOT


def load_parent():
    parent, data = history.load_frozen(ROOT/'workflow/q2_candidates/v6/manifest.json')
    selection_path = ROOT/'outputs/q2/historical_candidate_v6/training_selection.json'
    binding = json.loads((ROOT/'workflow/q2_candidates/v6_sensitivity.json').read_text(encoding='utf-8'))['bindings']['training_selection']
    if sha(selection_path) != binding['sha256']:
        raise ValueError('Frozen v6 training selection changed')
    selection = json.loads(selection_path.read_text(encoding='utf-8'))['selected']
    if selection['status'] != 'valid' or data['experiment']['parameters']:
        raise ValueError('Expected fixed-parameter v6 parent')
    return parent, data, selection


def build():
    _, data, selected = load_parent()
    parent_model = data['structural_models'][selected['structure']]
    models = {}
    # Ties prefer the inherited structure; all hypotheses declared before fitting.
    for name, construction, connection in (
            ('v6_control', False, False), ('construction_frontiers_only', True, False),
            ('connection_frontiers_only', False, True), ('technology_frontiers', True, True)):
        model = deepcopy(parent_model)
        if construction or connection:
            for policy in model['policies']:
                policy['deployment_limit_rules'] = {
                    'construction': 'technology_frontiers' if construction else 'fixed_global',
                    'connection': 'technology_frontiers' if connection else 'fixed_global'}
        models[name] = model
    data['model'] = deepcopy(models['v6_control'])
    data['structural_models'] = models
    data['experiment'].update(parameters=[], maximum_evaluations=1,
        structural_alternatives=list(models),
        selection='Four frozen deployment structures x three existing behavior rules, inherited fixed parameter vector. Select minimum2015-2021loss; exact ties prefer listed control. No new numeric cap or parameter search.',
        development_information='V1-v6 holdout already seen. V6 constraint logs identified simultaneous binding of assumed150GW construction and connection. This is an exploratory structural ablation, not new independent validation or tuning of a larger cap.')
    data['initialization']['deployment_v7'] = {
        'inherited_v6_training_selection': selected,
        'changed_opening_state': False, 'new_numeric_parameters': 0,
        'rule': 'Finite annual frontier=max(existing floor,existing rate*productive commissioned group stock), limited by remaining total headroom; count each shared group once. Ungrouped technologies retain existing finite individual limits. Only currently known/permitted options contribute.',
        'connection_boundary': 'Sum of technical connection requirements is a redundant envelope, not observed grid security/line capacity. Actual grid finance, delays and geographical constraints remain unresolved.'}
    data['assumptions'].append({'id':'V7A01','topic':'Common versus technology-specific deployment limits',
        'status':'explicit_research_assumption_not_observation',
        'statement':'Compare the inherited constant150GW common construction/connection limits with finite sums of existing technology-frontier limits. Wind/PV cohort shared ceilings and stock rates, thermal/hydro/nuclear limits, money, permit dates, queues, costs, demand and observation targets are unchanged. No claim that national grid connections are unconstrained: the technology-only case is an alternative hypothesis that requires real-world calibration. Earlier150GW statements remain applicable to the control and fixed sides of factorial variants.'})
    return data


def freeze():
    parent, _, _ = load_parent()
    data = build()
    artifacts = dict(parent['source_artifacts'])
    for relative in ('workflow/q2_candidates/v6/manifest.json', 'workflow/q2_candidates/v6_sensitivity.json',
                     'outputs/q2/historical_candidate_v6/training_selection.json'):
        artifacts[relative] = sha(ROOT/relative)
    directory = ROOT/'workflow/q2_candidates/v7'
    if directory.exists():
        for name, document in data.items():
            if json.loads((directory/(name+'.json')).read_text(encoding='utf-8')) != document:
                raise ValueError('Frozen v7 differs; use a new version')
        if json.loads((directory/'manifest.json').read_text(encoding='utf-8'))['source_artifacts'] != artifacts:
            raise ValueError('Frozen v7 references changed')
        return 'Existing v7 reproduced exactly'
    directory.mkdir(parents=True)
    for name, document in data.items(): dump(directory/(name+'.json'), document)
    dump(directory/'manifest.json', {'version':7, 'owner':'p2/yx', 'scope':parent['scope'],
        'national_admission':False, 'frozen_before_first_fit':True, 'previous_holdout_already_seen':True,
        'builder_sha256':sha(Path(__file__)),
        'inputs':{name:{'path':(directory/(name+'.json')).relative_to(ROOT).as_posix(),
                       'sha256':sha(directory/(name+'.json'))} for name in data},
        'source_artifacts':artifacts,
        'admission_limitation':'Deployment bottleneck hypothesis diagnostic only. Prices, service/equipment state, accounting and permit gaps remain.'})
    return 'Frozen v7:12training cases, zero new numeric parameters'


if __name__ == '__main__': print(freeze())
