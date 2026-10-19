"""Frozen multi-target calibration and paired deterministic scenario experiments.

Grid search never evaluates holdout loss while choosing parameters. Published
inventory targets require a separate boundary-matched metric specification.
"""
from copy import deepcopy
from itertools import product
from math import fsum, isfinite

from .annual import EnergyModel
from .operations import OperationError


def assign(document, path, value):
    if not isinstance(path,list) or not path:
        raise ValueError('Parameter path must be a nonempty list')
    node=document
    for key in path[:-1]:
        node=node[key]
    if path[-1] not in node if isinstance(node,dict) else not 0 <= path[-1] < len(node):
        raise ValueError('Cannot invent a parameter path')
    node[path[-1]]=value


def parameterize(model, parameters, values):
    out=deepcopy(model)
    for p in parameters:
        value=values[p['id']]
        if not isfinite(value) or not p['bounds'][0] <= value <= p['bounds'][1]:
            raise ValueError('Parameter outside frozen bounds')
        for path in p['paths']:
            assign(out,path,value)
    return out


def metric_rows(result, definitions):
    """Explicit linear accounting/ratios; no eval and no implicit unit conversion."""
    if not definitions or len({d['id'] for d in definitions})!=len(definitions):
        raise ValueError('Unique nonempty metric definitions required')
    rows=[]
    for annual in result['annual']:
        year=annual['year']
        matches=[o for o in result['operations'] if o['year']==year]
        if len(matches)!=1:
            raise ValueError('Each annual metric requires exactly one operation ledger')
        operation=matches[0]['result']
        assets=[a for a in result['assets'] if a['year']==year and a['state']=='operating']
        def total(terms):
            if not terms:
                raise ValueError('Empty metric terms cannot represent observed zero')
            value=0.
            for term in terms:
                if not isfinite(term['coefficient']):
                    raise ValueError('Nonfinite metric coefficient')
                if term['kind']=='annual':
                    amount=annual[term['field']]
                elif term['kind']=='flow':
                    present={r['id'] for r in operation['flows'] if r['kind']==term['flow_kind']}
                    if not term['ids'] or len(set(term['ids']))!=len(term['ids']) or not set(term['ids'])<=present:
                        raise ValueError('Metric references absent or duplicate flow components')
                    amount=sum(r['value']*r['annual_weight'] for r in operation['flows']
                               if r['kind']==term['flow_kind'] and r['id'] in term['ids'])
                elif term['kind']=='capacity':
                    collections={'source':'sources','process':'processes','device':'devices','store':'stores'}
                    collection=collections.get(term['asset_kind'])
                    if collection is None:
                        raise ValueError('Unknown metric asset kind')
                    present={c['id'] for c in matches[0]['input'][collection]}
                    if not term['ids'] or len(set(term['ids']))!=len(term['ids']) or not set(term['ids'])<=present:
                        raise ValueError('Metric references absent or duplicate capacity components')
                    amount=sum(a['quantity'] for a in assets if a['component'] in term['ids'] and a['kind']==term['asset_kind'])
                else:
                    raise ValueError('Unknown metric accounting term')
                if type(amount) not in (int,float) or not isfinite(amount):
                    raise ValueError('Metric requires finite numeric accounting amounts')
                value+=amount*term['coefficient']
            return value
        for definition in definitions:
            numerator=total(definition['numerator'])
            denominator=total(definition['denominator']) if definition['denominator'] is not None else 1.
            value=numerator/denominator if denominator!=0 else None
            rows.append({'year':year,'indicator':definition['id'],'value':value,
                         'unit':definition['unit'],'boundary':definition['boundary']})
    return rows


def compare(observations, simulated, targets, windows):
    lookup={(r['year'],r['indicator']):r for r in simulated}
    if len(lookup)!=len(simulated):
        raise ValueError('Duplicate model metric')
    target_map={t['id']:t for t in targets}
    rows=[]
    seen=set()
    for obs in observations:
        if obs['indicator'] not in target_map:
            continue
        key=obs['year'],obs['indicator']
        if key in seen:
            raise ValueError('Same observation counted twice')
        seen.add(key)
        if windows['train'][0] <= obs['year'] <= windows['train'][1]:
            window='train'
        elif windows['already_seen_holdout'][0] <= obs['year'] <= windows['already_seen_holdout'][1]:
            window='already_seen_holdout'
        else:
            continue
        sim=lookup.get(key)
        if obs['value'] is None:
            rows.append({**obs,'window':window,'simulated':None,'residual':None,'status':'missing_observation'})
            continue
        if sim is None or sim['value'] is None:
            raise ValueError(f'Missing simulated target {key}')
        if sim['unit']!=obs['unit'] or sim['boundary']!=obs['boundary']:
            raise ValueError(f'Unreconciled target boundary/unit {key}')
        if not isfinite(obs['value']) or not isfinite(sim['value']):
            raise ValueError('Nonfinite fit target')
        residual=sim['value']-obs['value']
        rows.append({**obs,'window':window,'simulated':sim['value'],'residual':residual,
                     'normalized_residual':residual/target_map[obs['indicator']]['scale'],
                     'status':'compared'})
    return rows


def loss(rows, targets, window='train'):
    parts=[]
    for target in targets:
        data=[r for r in rows if r['indicator']==target['id'] and r['window']==window and r['status']=='compared']
        if not data:
            raise ValueError(f'No comparable {window} data for {target["id"]}')
        scale,weight=target['scale'],target['weight']
        if not isfinite(scale) or scale<=0 or not isfinite(weight) or weight<=0:
            raise ValueError('Positive frozen scales and weights required')
        mse=sum((r['residual']/scale)**2 for r in data)/len(data)
        parts.append({'indicator':target['id'],'n':len(data),'scale':scale,'weight':weight,
                      'normalized_mse':mse,'weighted_loss':weight*mse})
    return sum(p['weighted_loss'] for p in parts),parts


def calibration(model, definitions, observations, experiment):
    windows=experiment['windows']; parameters=experiment['parameters']; targets=experiment['targets']
    if windows!={'train':[2015,2021],'already_seen_holdout':[2022,2024]}:
        raise ValueError('Official historical windows changed')
    if model['start_year']>2015 or model['end_year']<2024:
        raise ValueError('Historical state must precede training and include holdout')
    if len({t['id'] for t in targets})!=len(targets) or len({p['id'] for p in parameters})!=len(parameters):
        raise ValueError('Duplicate target or parameter')
    if {t['family'] for t in targets}!={'energy_consumption','primary_mix','capacity_or_generation','co2'}:
        raise ValueError('All four historical target families required')
    if len(parameters)>4 or not parameters:
        raise ValueError('Small identifiable calibration requires one to four parameters')
    for p in parameters:
        if not p['grid'] or len(set(p['grid']))!=len(p['grid']):
            raise ValueError('Empty or repeated grid candidate')
    candidates=list(product(*(p['grid'] for p in parameters)))
    if len(candidates)>experiment['maximum_evaluations']:
        raise ValueError('Frozen search budget exceeded')
    train_obs=[o for o in observations if windows['train'][0]<=o['year']<=windows['train'][1]]
    trials=[]
    for index,combination in enumerate(candidates):
        values=dict(zip([p['id'] for p in parameters],combination))
        config=parameterize(model,parameters,values)
        config['end_year']=windows['train'][1]
        try:
            result=EnergyModel(config).run()
            rows=compare(train_obs,metric_rows(result,definitions),targets,windows)
            value,parts=loss(rows,targets)
            trials.append({'trial':index,'parameters':values,'loss':value,'parts':parts,'status':'valid'})
        except (OperationError,ValueError) as exc:
            trials.append({'trial':index,'parameters':values,'loss':None,'status':'failed','reason':str(exc)})
    valid=[t for t in trials if t['status']=='valid']
    if not valid:
        raise ValueError('Every frozen calibration candidate failed')
    best=min(valid,key=lambda t:(t['loss'],t['trial']))
    final_model=parameterize(model,parameters,best['parameters'])
    final=EnergyModel(final_model).run()
    rows=compare(observations,metric_rows(final,definitions),targets,windows)
    holdout_loss,holdout_parts=loss(rows,targets,'already_seen_holdout')
    equivalent=[t['parameters'] for t in valid if t['loss']<=best['loss']+experiment['equivalent_loss_absolute_tolerance']]
    baselines=baseline_comparisons(observations,targets,windows)
    return {'best_parameters':best['parameters'],'training_loss':best['loss'],'holdout_loss':holdout_loss,
            'holdout_parts':holdout_parts,'trials':trials,'equivalent_candidates':equivalent,
            'history_fit':rows,'baselines':baselines,'simulation':final,
            'interpretation':'Already-seen holdout; conditional on declared historical drivers; grid optimum only'}


def baseline_comparisons(observations,targets,windows):
    rows=[]
    for target in targets:
        train=sorted([r for r in observations if r['indicator']==target['id'] and r['value'] is not None
                      and windows['train'][0]<=r['year']<=windows['train'][1]],key=lambda r:r['year'])
        if len(train)<2:
            raise ValueError('Too few training years for baselines')
        # Closed-form two-coefficient OLS avoids BLAS-dependent final-bit
        # differences across otherwise identical NumPy versions/environments.
        x=[r['year']-train[0]['year'] for r in train];y=[r['value'] for r in train]
        mean_x=fsum(x)/len(x);mean_y=fsum(y)/len(y)
        denominator=fsum((v-mean_x)**2 for v in x)
        if denominator==0:
            raise ValueError('Distinct training years required for trend baseline')
        slope=fsum((a-mean_x)*(b-mean_y) for a,b in zip(x,y))/denominator
        intercept=mean_y-slope*mean_x
        for obs in observations:
            if obs['indicator']!=target['id'] or obs['value'] is None or not windows['already_seen_holdout'][0]<=obs['year']<=windows['already_seen_holdout'][1]:
                continue
            for method,value in [('last_training_observation',train[-1]['value']),
                                 ('training_linear_trend',float(intercept+slope*(obs['year']-train[0]['year'])))]:
                rows.append({'year':obs['year'],'indicator':target['id'],'method':method,'observed':obs['value'],
                             'simulated':value,'residual':value-obs['value'],'unit':obs['unit'],
                             'boundary':obs['boundary'],'window':'already_seen_holdout'})
    return rows


def sensitivity(model, definitions, factors):
    if {f['id'] for f in factors}!={'gdp_growth','technology_cost_decline','carbon_price'}:
        raise ValueError('GDP, technology cost and carbon price factors required')
    rows=[]
    for index,levels in enumerate(product(*(f['values'] for f in factors))):
        changed=deepcopy(model)
        setting={f['id']:v for f,v in zip(factors,levels)}
        for f,value in zip(factors,levels):
            if not f['rationale'] or not f['source_or_assumption']:
                raise ValueError('Sensitivity range lacks justification')
            for path in f['paths']:
                assign(changed,path,value)
        try:
            result=EnergyModel(changed).run()
            for row in metric_rows(result,definitions):
                rows.append({'case':index,**setting,**row,'status':'optimal'})
        except (OperationError,ValueError) as exc:
            rows.append({'case':index,**setting,'year':None,'indicator':None,'value':None,'status':'failed','reason':str(exc)})
    return rows


def peak_assessment(year_values, minimum_following_years, maximum_rebound_fraction, minimum_final_decline_fraction):
    years=sorted(year_values)
    if not years or years!=list(range(years[0],years[-1]+1)):
        raise ValueError('Peak assessment requires a continuous annual path')
    if any(v is None or not isfinite(v) or v<0 for v in year_values.values()):
        raise ValueError('Peak assessment requires finite nonnegative gross CO2')
    if type(minimum_following_years) is not int or minimum_following_years<1:
        raise ValueError('Positive persistence horizon required')
    if not 0<=maximum_rebound_fraction<1 or not 0<minimum_final_decline_fraction<1:
        raise ValueError('Invalid fixed peak criteria')
    maximum=max(year_values.values())
    last_peak=max(y for y in years if year_values[y]==maximum)
    if maximum==0:
        return {'status':'zero_emissions_path','peak_year':None,'peak_value':0.}
    if years[-1]-last_peak<minimum_following_years:
        return {'status':'insufficient_following_years','peak_year':None,'peak_value':maximum,'candidate_year':last_peak}
    # Following years must remain below the peak and finish materially lower.
    stable=all(year_values[y]<=maximum*(1+maximum_rebound_fraction) for y in years if y>last_peak)
    decline=year_values[years[-1]]<=maximum*(1-minimum_final_decline_fraction)
    return {'status':'sustained_peak' if stable and decline else 'no_sustained_decline',
            'peak_year':last_peak if stable and decline else None,'peak_value':maximum,'candidate_year':last_peak}


def net_co2(energy_gross, captured, nonenergy_positive, net_removals, *, common_boundary):
    if not common_boundary:
        raise ValueError('No reviewed common gross/removal boundary')
    values=[energy_gross,captured,nonenergy_positive,net_removals]
    if any(v is None or not isfinite(v) or v<0 for v in values) or captured>energy_gross:
        raise ValueError('Missing or invalid national CO2 input')
    positive=energy_gross-captured+nonenergy_positive
    return {'positive_co2':positive,'net_removals':net_removals,'net_co2':positive-net_removals,
            'neutralization_ratio':net_removals/positive if positive else None,
            'ratio_status':'defined' if positive else 'zero_positive_emissions'}
