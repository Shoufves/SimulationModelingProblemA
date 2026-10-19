"""Freeze v6 solar information-date/ceiling ablations; no new fitted parameters.

Previously seen holdout stays exploratory. Resource potential is a conservative
aggregate mapping hypothesis, not observed deployment or national admission.
"""
import json
from copy import deepcopy
from pathlib import Path

import run_q2_historical_candidate as history
from energy_model.q2.io import dump, local_path, sha, verify_source_records

ROOT = history.ROOT


def load_parent():
    parent, data = history.load_frozen(ROOT/'workflow/q2_candidates/v5/manifest.json')
    selection = json.loads((ROOT/'outputs/q2/historical_candidate_v5/training_selection.json').read_text(encoding='utf-8'))['selected']
    if selection['status'] != 'valid':
        raise ValueError('Valid parent training selection required')
    model = history.parameterize(data['structural_models'][selection['structure']],
                                 data['experiment']['parameters'], selection['parameters'])
    return data, model, parent, selection


def references():
    review = json.loads((ROOT/'data/catalog/q2_solar_timing_ceiling_review.json').read_text(encoding='utf-8'))
    if review['decision'] != 'scoped_solar_information_time_and_resource_ceiling_diagnostic':
        raise ValueError('Solar mapping not reviewed')
    if not review['checks'] or not all(c['passed'] is True and c['evidence'] for c in review['checks']):
        raise ValueError('Solar reference checks unresolved')
    for item in review['fingerprints']:
        if sha(local_path(ROOT,item['path'])) != item['sha256']:
            raise ValueError('Solar reference changed: '+item['path'])
    verify_source_records(ROOT,review['source_records'])
    ref = json.loads((ROOT/'data/catalog/q2_solar_timing_ceiling_transcription.json').read_text(encoding='utf-8'))
    source = ref['resource_reference']
    if (source['unit'],source['geography']) != ('GWe','China'):
        raise ValueError('Resource unit or geography mismatch')
    ceiling = source['utility_pv_technical_potential'] * 1000
    if ceiling <= 0 or ceiling != source['model_ceiling_MW']:
        raise ValueError('Resource ceiling conversion mismatch')
    if ref['cost2014_publication']['published_month'] != '2015-01':
        raise ValueError('Source availability date changed')
    return ref, review


def build():
    data, parent_model, _, selection = load_parent()
    ref, _ = references()
    # Order is declared before evaluating results. Exact training ties prefer
    # the documented correction, not a ceiling chosen on holdout outcomes.
    settings = [('date_and_resource_ceiling',True,True),
                ('date_only',True,False),('resource_ceiling_only',False,True),
                ('v5_control',False,False)]
    models = {}
    for name, dated, resource in settings:
        model = deepcopy(parent_model)
        if dated:
            next(o for o in model['investment_options'] if o['id']=='solar_new_build')['known_year'] = 2015
        if resource:
            ceiling = ref['resource_reference']['model_ceiling_MW']
            group = next(g for g in model['investment_groups'] if g['id']=='solar_construction')
            group['maximum_total_units'] = ceiling
            for option in model['investment_options']:
                if option.get('investment_group') == group['id']:
                    option['maximum_total_units'] = ceiling
        models[name] = model
    data['model'] = deepcopy(models['date_and_resource_ceiling'])
    data['structural_models'] = models
    data['experiment'].update(parameters=[], maximum_evaluations=1,
        structural_alternatives=list(models),
        selection='Four frozen source-mapping structures x three existing behavior rules, one fixed inherited parameter vector. Minimum2015-2021 loss; exact ties use declared structure/rule order. No new parameter search.',
        source_publication_convention='IRENA2014cost report published January2015: available for end-year2015 decision in corrected variants; no2014 hindsight. REmap potential published November2014. Control deliberately retains prior2016delay.',
        development_information='V1-v5 holdout already seen; sequential source/mapping correction, not blind validation. All fitted demand, capex, adjustment, construction-rate and queue choices frozen from prior training. Resource correction appears first for deterministic training ties, before any evaluation.')
    data['initialization']['solar_v6_mapping'] = {
        'inherited_v5_training_selection':selection,
        'corrected_decision_available_from':2015,
        'resource_ceiling_MW':ref['resource_reference']['model_ceiling_MW'],
        'opening_stock_and_generation_unchanged':True,
        'annual_construction_and_connection_unchanged':True,
        'earlier_2012_cost_reference_used':False}
    data['assumptions'].extend([
        {'id':'V6A01','topic':'Information date correction','status':'source_based_mapping_correction',
         'statement':'A January2015 report is available at the2015end-year decision. New projects still commission at least one year later. The2014cost price year, selected cost node,17%new-cohortCF, decline path and opening fleet remain unchanged. Older assumptions describing2016visibility are retained as version history and superseded only in date-corrected variants.'},
        {'id':'V6A02','topic':'Resource versus deployment bound','status':'explicit_research_assumption_not_observation',
         'statement':'IRENA2014Table13/CNREC2012 reports2200GWe utility and500GWe rooftop technical potential. Corrected variants bound both modeled PV vintages together by2200000MW, counting mixed openingPV against the utility figure as a conservative aggregate hypothesis. Rooftop500GW is not added. This is neither observed economic potential nor an annual construction, financing or access allowance. Old20xbound retained only as the factorial control.'},
        {'id':'V6A03','topic':'Unresolved annual constraints','status':'explicit_research_assumption_not_observation',
         'statement':'Shared stock-scaled construction hypothesis, global150GW/year construction/connection, finance, nuclear queue, permit assumptions, constant prices, fuel residuals and four-block chronology remain unchanged. Fixing a total-resource ceiling cannot validate those assumptions or create national S0 acceptance. Earlier2012cost/CF is registered but unused.'}])
    return data


def freeze():
    data = build()
    _,_,parent,_ = load_parent()
    _,review = references()
    artifacts = dict(parent['source_artifacts'])
    artifacts.update({r['path']:r['sha256'] for r in review['fingerprints']})
    for relative in ('data/catalog/q2_solar_timing_ceiling_review.json',
                     'outputs/q2/historical_candidate_v5/training_selection.json',
                     'workflow/q2_candidates/v5/manifest.json'):
        artifacts[relative] = sha(ROOT/relative)
    directory = ROOT/'workflow/q2_candidates/v6'
    if directory.exists():
        for name,document in data.items():
            if json.loads((directory/(name+'.json')).read_text(encoding='utf-8')) != document:
                raise ValueError('Frozen v6 differs; use a new version')
        if json.loads((directory/'manifest.json').read_text(encoding='utf-8'))['source_artifacts'] != artifacts:
            raise ValueError('Frozen v6 references changed')
        return 'Existing v6 reproduced exactly'
    directory.mkdir(parents=True)
    for name,document in data.items(): dump(directory/(name+'.json'),document)
    dump(directory/'manifest.json',{'version':6,'owner':'p2/yx','scope':parent['scope'],
        'national_admission':False,'frozen_before_first_fit':True,'previous_holdout_already_seen':True,
        'builder_sha256':sha(Path(__file__)),
        'inputs':{name:{'path':(directory/(name+'.json')).relative_to(ROOT).as_posix(),
                       'sha256':sha(directory/(name+'.json'))} for name in data},
        'source_artifacts':artifacts,
        'admission_limitation':'Source-timing and conservative resource-ceiling ablation; annual deployment, financial, service and accounting gaps remain.'})
    return 'Frozen v6:12 training cases, zero new fitted parameters'


if __name__ == '__main__':
    print(freeze())
