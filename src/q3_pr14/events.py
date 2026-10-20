"""Continuous conditional events on a common paid-asset snapshot.

Daily rolling dispatch has identical 24-hour information in every arm. Initial
stocks are carried across days, never annualised or cyclic. Six-hour ramps in
the inherited model exceed full nameplate changes, including day boundaries.
"""
from copy import deepcopy
from hashlib import sha256
import json

from energy_model.q2_national import EF
from .dispatch import operate_national
from .services import service_key
from energy_model.q2_operations import Q2Error


def fingerprint(value):
    return sha256(json.dumps(value,sort_keys=True,allow_nan=False).encode()).hexdigest()


def severity(day, start, duration, recovery):
    if day < start or day >= start+duration+recovery:
        return 0.0
    if day < start+duration:
        return 1.0
    return (start+duration+recovery-day)/(recovery+1)


def service_metrics(demands, event_end, config):
    """Never sum incompatible service units; aggregate devices of one service."""
    h=config['event']['hours_per_period']
    tol=config['acceptance']
    grouped={}
    for row in demands:
        key=(service_key(row),row['period'])
        v=grouped.setdefault(key,[0.0,0.0])
        v[0]+=row['requested_service_mwh'];v[1]+=row['unmet_service_mwh']
    result=[]
    for sector in sorted({k[0] for k in grouped}):
        seq=[(t,*grouped[sector,t]) for s,t in sorted(grouped) if s==sector]
        unmet=[u>max(tol['shortage_absolute_mwh'],q*tol['shortage_relative']) for _,q,u in seq]
        longest=current=0
        for bad in unmet:
            current=current+h if bad else 0
            longest=max(longest,current)
        requested=sum(q for _,q,u in seq);u=sum(u for _,q,u in seq)
        need=config['event']['recovery_consecutive_periods']
        recovery=None
        for i,(t,q,value) in enumerate(seq):
            if t*h>=event_end and i+need<=len(seq) and not any(unmet[i:i+need]):
                recovery=t*h-event_end;break
        result.append(dict(service=sector,unit='MWh useful service (within-service only)',
            requested=requested,unmet=u,loss_fraction=u/requested if requested else None,
            longest_interruption_hours=longest,recovery_hours=recovery,
            recovery_status='recovered' if recovery is not None else 'right_censored_not_recovered',
            end_interrupted=unmet[-1],zero_demand=requested==0))
    return result


def run_event(snapshot, config, scenario='S0', *, gas_offset=0, frozen_gas=None,
              channel_share=None, diagnostics=(), cost_factor=1.0):
    e=config['event'];n=4;h=e['hours_per_period']
    if h!=6 or e['days']<=0 or e['recovery_days']<0 or e['duration_days']<1:
        raise Q2Error('invalid_input','Invalid event calendar')
    if scenario not in ('S0','SG','SW','SGW'):
        raise Q2Error('invalid_input','Unknown paired event')
    channel=e['channel_a_share'] if channel_share is None else channel_share
    if not 0<=channel<=1 or e['gas_start_day']+gas_offset<e['warmup_days']:
        raise Q2Error('invalid_input','Invalid source share or prehistory')
    if frozen_gas is not None and len(frozen_gas)!=e['days']*n:
        raise Q2Error('invalid_input','Frozen response schedule length differs')
    base=deepcopy(snapshot['operation']);opening=fingerprint(base)
    stocks={f:p['initial_mwh'] for f,p in base['fuels'].items()}
    soc=base['storage']['initial_mwh']
    extra_soc={k:p['initial_mwh'] for k,p in base.get('additional_storage',{}).items()}
    rows={k:[] for k in ('fuel','generation','demand','storage','additional_storage','recoveries','balances','stages','sources')}
    total_cost=total_carbon=max_residual=0.0
    for day in range(e['days']):
        op=deepcopy(base);op.update(annual_repeats=1,cyclic=False)
        op['storage']['initial_mwh']=soc
        op['storage']['terminal_rule']='free'
        for name,p in op.get('additional_storage',{}).items():
            p.update(initial_mwh=extra_soc[name],terminal_rule='free')
        for fuel,p in op['fuels'].items():p['initial_mwh']=stocks[fuel]
        gas=severity(day,e['gas_start_day']+gas_offset,e['duration_days'],e['recovery_days']) if scenario in ('SG','SGW') else 0
        weather=severity(day,e['weather_start_day'],e['duration_days'],e['recovery_days']) if scenario in ('SW','SGW') else 0
        # Reallocate an explicitly paid contract's share; total import capacity
        # before a shock stays fixed. Other sources and domestic capacity unchanged.
        exposed=max(0,channel-snapshot.get('diversified_fraction',0))
        for t in range(n):
            imp=base['fuels']['gas']['import_mw'][t]
            a=imp*exposed*(1-gas*e['gas_loss_fraction']);other=imp*(1-exposed)
            op['fuels']['gas']['import_mw'][t]=a+other
            rows['sources'].append(dict(day=day,period=day*n+t,source='hypothetical_A',
                available_mw=a,other_import_mw=other,domestic_mw=op['fuels']['gas']['domestic_mw'][t]))
        for tech in ('wind','solar'):
            op['plants'][tech]['availability']=[v*(1-weather*(1-e[tech+'_factor'])) for v in base['plants'][tech]['availability']]
        op['plants']['hydro']['window_energy_budget_mwh']*=1-weather*(1-e['hydro_factor'])
        if frozen_gas is not None:
            p=op['plants']['gas'];cap=p['capacity_mw']
            p['availability']=[min(v,max(0,frozen_gas[day*n+t])/(h*cap)) if cap else 0 for t,v in enumerate(p['availability'])]
        delta=config['search']['diagnostic_fraction']
        if 'grid' in diagnostics:op['grid']['power_mw']*=1+delta
        if 'storage' in diagnostics:
            op['storage']['power_mw']*=1+delta;op['storage']['energy_mwh']*=1+delta
        if 'withdrawal' in diagnostics:op['fuels']['gas']['withdrawal_mw']*=1+delta
        # Budgets are daily flow allowances. Paid-device stock is fixed; no
        # resetting cash/inventory to make frozen or stressed cases feasible.
        result=operate_national(op)
        max_residual=max(max_residual,result['max_residual'])
        total_cost+=result['resource_cost']
        for r in result['fuel']:
            material=sum(x['input_mwh'] for x in result['demand'] if x['sector']=='nonenergy_feedstock' and x['carrier']==r['fuel'] and x['period']==r['period'])
            r['nonenergy_mwh']=material
            # PR14 also has recovered heat and recovered electricity carriers;
            # their upstream fuel emissions are already counted once.
            if material:
                r['combustion_co2_t']-=material*EF[r['fuel']]
            total_carbon+=r['combustion_co2_t']
            if r['fuel']=='gas':
                source=rows['sources'][day*n+r['period']]
                available=source['available_mw']+source['other_import_mw']
                r['channel_a_import_mwh']=r['import_mwh']*source['available_mw']/available if available else 0
                r['other_import_mwh']=r['import_mwh']-r['channel_a_import_mwh']
        for kind in ('fuel','generation','demand','storage','additional_storage','recoveries','balances','stages'):
            rows[kind].extend(dict(r,day=day,period=day*n+r['period']) if 'period' in r else dict(r,day=day) for r in result[kind])
        stocks={f:next(r['closing_mwh'] for r in reversed(result['fuel']) if r['fuel']==f) for f in stocks}
        soc=result['storage'][-1]['closing_mwh']
        for name in extra_soc:
            extra_soc[name]=next(r['closing_mwh'] for r in reversed(result['additional_storage']) if r['store']==name)
    end=max(e['gas_start_day']+gas_offset if scenario in ('SG','SGW') else e['weather_start_day'],
            e['weather_start_day'] if scenario in ('SW','SGW') else e['gas_start_day']+gas_offset)
    metrics=service_metrics(rows['demand'],(end+e['duration_days']+e['recovery_days'])*24,config)
    # Account for finite initial inventory consumed and the terminal inventory.
    stock_cost=sum((p['initial_mwh']-stocks[f])*p['domestic_cost_per_mwh'] for f,p in base['fuels'].items())
    stock_cost+=(base['storage']['initial_mwh']-soc)*snapshot['electricity_value']
    stock_cost+=sum((base['additional_storage'][k]['initial_mwh']-v)*snapshot['electricity_value'] for k,v in extra_soc.items())
    return dict(scenario=scenario,gas_offset=gas_offset,channel_share=channel,
        snapshot_hash=opening,metrics=metrics,rows=rows,resource_cost_cny=total_cost+stock_cost,
        purchased_resource_cost_cny=total_cost,stock_value_adjustment_cny=stock_cost,
        combustion_co2_t=total_carbon,max_residual=max_residual,
        gas_min_inventory_mwh=min(r['closing_mwh'] for r in rows['fuel'] if r['fuel']=='gas'),
        storage_min_mwh=min(r['closing_mwh'] for r in rows['storage']),
        gas_response=[r['output_mwh'] for r in rows['generation'] if r['plant']=='gas'],
        terminal_stocks=stocks,terminal_soc=soc,terminal_additional_soc=extra_soc,status='solved')


def interaction(arms):
    by={s:{m['service']:m for m in a['metrics']} for s,a in arms.items()}
    return {service:by['SGW'][service]['unmet']-by['SG'][service]['unmet']-
            by['SW'][service]['unmet']+by['S0'][service]['unmet'] for service in by['S0']}
