"""Freeze v8: documented 2016-2018 nuclear non-issuance in annual approvals.

The documented correction is mandatory in this version. The old unconditioned
model is a paired diagnostic control, not a candidate for overriding evidence.
"""
from copy import deepcopy
import json
from pathlib import Path

import run_q2_historical_candidate as history
from energy_model.q2.io import dump, local_path, sha, verify_source_records

ROOT=history.ROOT
REVIEW='data/catalog/q2_nuclear_nonissuance_2016_2018_review.json'


def reference():
    review=json.loads((ROOT/REVIEW).read_text(encoding='utf-8'))
    if (review['decision']!='scoped_realized_nuclear_nonissuance_2016_2018' or
            not review['checks'] or not all(c['passed'] is True and c['evidence'] for c in review['checks']) or
            review['period']!=[2016,2018] or review['reported_construction_permits_issued']!=0):
        raise ValueError('Nuclear non-issuance has not passed scoped review')
    for r in review['fingerprints']:
        if sha(local_path(ROOT,r['path']))!=r['sha256']:
            raise ValueError('Nuclear non-issuance original changed')
    verify_source_records(ROOT,review['source_records'])
    return review


def load_parent():
    manifest,data=history.load_frozen(ROOT/'workflow/q2_candidates/v7/manifest.json')
    selected=json.loads((ROOT/'outputs/q2/historical_candidate_v7/training_selection.json').read_text(encoding='utf-8'))['selected']
    if selected['status']!='valid' or data['experiment']['parameters']:
        raise ValueError('Expected fixed-parameter selected v7 parent')
    return manifest,data,selected


def build():
    _,data,selected=load_parent()
    reference()
    model=deepcopy(data['structural_models'][selected['structure']])
    if model.get('approval_blocks'):
        raise ValueError('Parent unexpectedly contains administrative blocks')
    model['approval_blocks']=[dict(id=f'nuclear_no_issuance_{year}',year=year,option='nuclear_build',
        basis='realized_administrative_outcome',evidence=REVIEW+'#physical41-printed36-section6.1')
        for year in (2016,2017,2018)]
    data['model']=deepcopy(model)
    data['structural_models']={'observed_nuclear_nonissuance':model}
    data['experiment'].update(parameters=[],maximum_evaluations=1,
        structural_alternatives=list(data['structural_models']),
        selection='Mandatory source correction; compare3existing behavior rules on2015-2021only with fixed inherited parameters. Oldunconditioned control is paired separately and cannot override the reviewedzeroissuance.',
        development_information='V1-V7holdout already seen. CNS8explicit2016-2018zeroissuance is retrospective administrative evidence, not an announced2016moratorium or future information visible to investors. Unknownother years retain previous hypotheses, not newly certified permits.')
    data['initialization']['nuclear_nonissuance_v8']={
        'inherited_v7_training_selection':selected,'opening_assets_and_queue_unchanged':True,
        'blocked_approval_years':[2016,2017,2018],'source_report_date':'2019-08',
        'mapping':'Year-local realized government outcomes; no new generic nuclear commitment in these3years. Existing queue construction/commissioning unchanged.',
        'new_numeric_parameters':0,'full_nuclear_calendar_admitted':False}
    data['assumptions'].append(dict(id='V8A01',topic='Observed administrative non-issuance',
        status='reviewed_event_with_explicit_replay_mapping',
        statement='CNS8section6.1(physical41/printed36) explicitly reports no construction permit issued2016-2018. Replay these realized year-endgovernment outcomes only when each year arrives. Firms retain prior price/margin/lead-time assumptions and do not foresee later blocks. This conditions a historical counterfactual, does not establish a policycause or retrospectivepublication as contemporaneous actorinformation. Existing2014queue unaffected; nofuturecompletionobservations used. Generic2014/2015andpost2018nuclearapproval assumptions remain unresolved; the eight2015capacities are not yet a discrete-plant decision model.'))
    return data


def freeze():
    parent,_,_=load_parent()
    data=build();review=reference()
    artifacts=dict(parent['source_artifacts'])
    artifacts.update({r['path']:r['sha256'] for r in review['fingerprints']})
    for relative in (REVIEW,'workflow/q2_candidates/v7/manifest.json',
                     'outputs/q2/historical_candidate_v7/training_selection.json'):
        artifacts[relative]=sha(ROOT/relative)
    directory=ROOT/'workflow/q2_candidates/v8'
    if directory.exists():
        for name,document in data.items():
            if json.loads((directory/(name+'.json')).read_text(encoding='utf-8'))!=document:
                raise ValueError('Frozen v8 differs; use a new version')
        if json.loads((directory/'manifest.json').read_text(encoding='utf-8'))['source_artifacts']!=artifacts:
            raise ValueError('Frozen v8 sources changed')
        return 'Existing v8 reproduced exactly'
    directory.mkdir(parents=True)
    for name,document in data.items():dump(directory/(name+'.json'),document)
    dump(directory/'manifest.json',dict(version=8,owner='p2/yx',scope=parent['scope'],national_admission=False,
        frozen_before_first_fit=True,previous_holdout_already_seen=True,builder_sha256=sha(Path(__file__)),
        inputs={name:dict(path=(directory/(name+'.json')).relative_to(ROOT).as_posix(),
                         sha256=sha(directory/(name+'.json'))) for name in data},source_artifacts=artifacts,
        admission_limitation='Partial observed nuclearapproval replay; otherpermit years, physicalfuel/service mapping and nationalforecast remain unresolved.'))
    return 'Frozen v8:3training cases, zero new numeric parameters; paired oldcontrol separate'


if __name__=='__main__':print(freeze())
