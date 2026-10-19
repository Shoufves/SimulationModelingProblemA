"""Freeze v9: jointly calibrate separate wind/PV frontiers under both bottlenecks.

V7 tested a structural change at inherited, confounded rates. V9 keeps the
original zero-to-two multiplier bounds and evaluates separate technology rates
on a declared quarter-step grid. No holdout targets enter construction or choice.
"""
from copy import deepcopy
import json
from pathlib import Path

import run_q2_historical_candidate as history
from energy_model.q2.io import dump, sha

ROOT=history.ROOT


def load_parent():
    parent,data=history.load_frozen(ROOT/'workflow/q2_candidates/v8/manifest.json')
    selected=json.loads((ROOT/'outputs/q2/historical_candidate_v8/training_selection.json').read_text(encoding='utf-8'))['selected']
    if selected['status']!='valid' or data['experiment']['parameters']:
        raise ValueError('Expected valid fixed-parameter v8 parent')
    return parent,data,selected


def build():
    _,data,selected=load_parent()
    base=deepcopy(data['structural_models'][selected['structure']])
    models={'shared_construction_connection':deepcopy(base),
            'technology_frontiers':deepcopy(base)}
    for p in models['technology_frontiers']['policies']:
        p['deployment_limit_rules']={'construction':'technology_frontiers','connection':'technology_frontiers'}
    multipliers=[i/4 for i in range(9)]
    parameters=[];rates={}
    for technology in ('wind','solar'):
        index=next(i for i,g in enumerate(base['investment_groups']) if g['id']==technology+'_construction')
        group=base['investment_groups'][index]
        stock=sum(a['quantity'] for a in base['assets'] if a['state']=='operating' and
                  a['kind']==group['kind'] and a['component'] in group['components'])
        reference=group['annual_installation_floor']/stock
        if reference<=0:raise ValueError('Positive reviewed opening-stock/additions scale required')
        grid=[m*reference for m in multipliers]
        parameters.append(dict(id=technology+'_stock_expansion_rate',grid=grid,bounds=[min(grid),max(grid)],
                               paths=[['investment_groups',index,'stock_expansion_rate']]))
        rates[technology]=dict(base_rate=reference,multipliers=multipliers,
                               opening_MW=stock,annual_floor_MW=group['annual_installation_floor'])
    data['model']=deepcopy(models['shared_construction_connection'])
    data['structural_models']=models
    data['experiment'].update(parameters=parameters,maximum_evaluations=81,
        structural_alternatives=list(models),
        selection='Joint2015-2021loss over2deploymentstructures x3existingrules x81wind/PVratepairs. Bounds retainoriginal0-to-2times2014additions/stock; independentquarter-step multipliers. Exactties use declaredtrialorder. No holdoutselection.',
        development_information='V1-V8holdout already seen; exploratory jointstructure/rate correction. V3usedonecommon multiplier; V7removedboth commoncaps at inheriteddouble rates and didnotrecalibrate. V9testsseparatewind/PVrates jointly with both constraintstructures. Otherfitparametersremain frozen;notglobaloptimumorindependentvalidation.')
    data['initialization']['joint_deployment_v9']=dict(inherited_v8_training_selection=selected,
        changed_opening_state=False,calibrated_rates=rates,new_fitted_dimensions=2,
        inherited_fuel_responses_and_prices=True,maximum_total_training_cases=486,
        calibration_not_measured_manufacturing_capacity=True)
    data['assumptions'].append(dict(id='V9A01',topic='Joint technology-rate and bottleneck calibration',
        status='explicit_research_assumption_not_observation',
        statement='Separatewind/PVannualstockexpansionrates span0-to-2times2014observedadditions/openingstock, quarter-step multipliergrid. These are calibratedeffective deploymentresponses, not manufacturing/gridcapacityobservations. Sharedannualfloor, totalceilings, cash, permitblocks, leadtimes, prices, costtrends, fuelresponses andobservations remain unchanged. Technologyfrontiers retainfinite group/option limits; common150GWcase remains as structuralcontrol. V7inherited-rate overexpansion didnotestablish joint-modelfailure. New81ratepairs perrule/structure count toward totalexploratorysearch; historicalholdout is alreadyseen.'))
    return data


def freeze():
    parent,_,_=load_parent();data=build();artifacts=dict(parent['source_artifacts'])
    for rel in ('workflow/q2_candidates/v8/manifest.json','outputs/q2/historical_candidate_v8/training_selection.json'):
        artifacts[rel]=sha(ROOT/rel)
    directory=ROOT/'workflow/q2_candidates/v9'
    if directory.exists():
        for name,value in data.items():
            if json.loads((directory/(name+'.json')).read_text(encoding='utf-8'))!=value:
                raise ValueError('Frozen v9 differs; use a new version')
        if json.loads((directory/'manifest.json').read_text(encoding='utf-8'))['source_artifacts']!=artifacts:
            raise ValueError('Frozen v9 sources changed')
        return 'Existing v9 reproduced exactly'
    directory.mkdir(parents=True)
    for name,value in data.items():dump(directory/(name+'.json'),value)
    dump(directory/'manifest.json',dict(version=9,owner='p2/yx',scope=parent['scope'],national_admission=False,
        frozen_before_first_fit=True,previous_holdout_already_seen=True,builder_sha256=sha(Path(__file__)),
        inputs={name:dict(path=(directory/(name+'.json')).relative_to(ROOT).as_posix(),sha256=sha(directory/(name+'.json'))) for name in data},
        source_artifacts=artifacts,admission_limitation='Jointdeployment calibration diagnostic; fuel/service/price/cohort and nationalphysicalaccounting gaps remain.'))
    return 'Frozen v9:486training cases;2independenttechnology-rate dimensions;originalbounds retained'


if __name__=='__main__':print(freeze())
