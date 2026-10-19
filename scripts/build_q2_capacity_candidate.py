"""Freeze v3 shared-vintage construction capacity diagnostic, not admission."""
import json
from copy import deepcopy
from pathlib import Path

import build_q2_mapping_candidate as previous
from energy_model.q2.io import dump, sha

ROOT = previous.ROOT


def build():
    data = previous.build()
    # Preserve all four v2 parameter grids. Compare construction hypotheses as
    # explicit structural alternatives; do not estimate more continuous knobs.
    model = deepcopy(data['structural_models']['new_project_cohort'])
    options = {o['id']: o for o in model['investment_options']}
    groups = []
    for tech in ('wind', 'solar'):
        old = options[tech + '_build']
        components = [tech + '_power'] + (['solar_new_power'] if tech == 'solar' else [])
        opening = sum(a['quantity'] for a in model['assets'] if a['component'] in components and a['state'] == 'operating')
        group = {'id': tech + '_construction', 'kind': 'process', 'components': components,
                 'annual_installation_floor': old['annual_installation_units'],
                 'stock_expansion_rate': old['annual_installation_units'] / opening,
                 'maximum_total_units': old['maximum_total_units']}
        groups.append(group)
        for option in model['investment_options']:
            if option['component'] in components:
                option['investment_group'] = group['id']
    model['investment_groups'] = groups
    models = {}
    for name, multiplier in [('fixed_shared_capacity', 0.), ('stock_scaled_capacity', 1.), ('double_stock_rate', 2.)]:
        variant = deepcopy(model)
        for group in variant['investment_groups']:
            group['stock_expansion_rate'] *= multiplier
        models[name] = variant
    data['model'] = models['stock_scaled_capacity']
    data['structural_models'] = models
    data['experiment']['structural_alternatives'] = list(models)
    data['experiment']['selection'] = 'Minimum2015-2021 training loss over3 frozen construction hypotheses x3 rules x81vectors; holdout only after final selection.'
    data['experiment']['development_information'] = 'V1 and v2 already-seen holdout informed diagnosis. This exploratory v3 does not restore independent validation.'
    data['assumptions'].append({'id': 'V3A01', 'topic': 'Shared endogenous construction limits',
        'status': 'explicit_research_assumption_not_observation',
        'statement': 'All solar vintages share one annual limit and total ceiling. Wind and solar annual group limit=max(2014 additions, rate*current productive commissioned group stock). Rate alternatives0,1,2times2014 additions/2014 closing stock are research hypotheses, not observed manufacturer capacity. Queues consume total headroom but do not expand annual productive capacity. Global150GW construction/connection and20times group ceiling remain unchanged. All demand/statistical/queue/policy limitations persist.'})
    return data


def freeze():
    data = build()
    directory = ROOT / 'workflow/q2_candidates/v3'
    parent = json.loads((ROOT / 'workflow/q2_candidates/v2r1/manifest.json').read_text(encoding='utf-8'))
    artifacts = dict(parent['source_artifacts'])
    if directory.exists():
        for name, document in data.items():
            if json.loads((directory / (name + '.json')).read_text(encoding='utf-8')) != document:
                raise ValueError('Frozen v3 differs; use a new version')
        if json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))['source_artifacts'] != artifacts:
            raise ValueError('Frozen v3 references changed')
        return 'Existing v3 reproduced exactly'
    directory.mkdir(parents=True)
    for name, document in data.items():
        dump(directory / (name + '.json'), document)
    dump(directory / 'manifest.json', {'version': 3, 'owner': 'p2/yx', 'scope': parent['scope'],
        'national_admission': False, 'frozen_before_first_fit': True, 'previous_holdout_already_seen': True,
        'builder_sha256': sha(Path(__file__)),
        'inputs': {name: {'path': (directory / (name + '.json')).relative_to(ROOT).as_posix(),
                          'sha256': sha(directory / (name + '.json'))} for name in data},
        'source_artifacts': artifacts, 'admission_limitation': 'Construction-capacity hypothesis diagnostic; not national acceptance.'})
    return 'Frozen v3:729 training cases'


if __name__ == '__main__':
    print(freeze())
