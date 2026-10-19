"""Independent service, rated capacity, cash and legacy-output checks."""
import json
from math import fsum, isclose
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from energy_model.q2.io import dump,sha


def execute():
    folder=ROOT/'outputs/q2/residential_heat_episode_final'
    read=lambda path:json.loads(path.read_text(encoding='utf-8'))
    summary=read(folder/'summary.json')
    original=read(ROOT/'outputs/q2/historical_candidate_v12/result.json')
    control=read(folder/'v12_control.json')['result']
    if original!=control:
        raise ValueError('Original v12 full ledger changed')
    checks=[]
    maximum_heat_error=maximum_money_error=maximum_queue_error=0.
    for record in summary['records']:
        document=read(folder/(record['case']+'.json'))
        model,result=document['model'],document['result']
        mapping=document['mapping']
        initial_money=fsum(a['cash'] for a in model['agents'])+fsum(model['other_accounts'].values())
        heat_service=next((s for s in model['operation']['services'] if s['id'].startswith('residential_oil_low_')),None)
        activity=1.
        for annual in result['annual']:
            year=annual['year']
            money=fsum(annual['agent_cash'].values())+fsum(annual['accounts'].values())
            maximum_money_error=max(maximum_money_error,abs(money-initial_money))
            if not isclose(money,initial_money,abs_tol=1e-6,rel_tol=1e-8):
                raise ValueError('Whole-system cash not conserved')
            queue=fsum(p['remaining_cost'] for p in result['projects'] if p['year']==year and p['state']=='building')
            maximum_queue_error=max(maximum_queue_error,abs(queue-annual['accounts']['escrow']))
            if not isclose(queue,annual['accounts']['escrow'],abs_tol=1e-6,rel_tol=1e-8):
                raise ValueError('Queue funding differs from escrow')
            if heat_service is None:continue
            driver=model['demand_drivers'][heat_service['id']]
            if year>model['start_year']:
                activity*=(1+model['gdp_growth'][str(year)])**driver['gdp_elasticity']
            requested=fsum(v*w for v,w in zip(heat_service['demand'],model['operation']['annual_weights']))*activity
            requested*=(1-driver['annual_intensity_improvement'])**(year-model['start_year'])
            operation=next(o['result'] for o in result['operations'] if o['year']==year)
            def flow(identity):
                return fsum(r['value']*r['annual_weight'] for r in operation['flows'] if r['kind']=='device' and r['id']==identity)
            oil,electricity=flow('residential_oil_boiler'),flow('residential_heat_pump')
            boiler=next(d for d in model['operation']['devices'] if d['id']=='residential_oil_boiler')
            pump=next((d for d in model['operation']['devices'] if d['id']=='residential_heat_pump'),None)
            heat=oil*boiler['service_per_mwh']+electricity*pump['service_per_mwh'] if pump else oil*boiler['service_per_mwh']
            deficit=annual['service_shortfalls'][heat_service['id']]
            maximum_heat_error=max(maximum_heat_error,abs(heat+deficit-requested))
            if not isclose(heat+deficit,requested,abs_tol=1e-6,rel_tol=1e-8):
                raise ValueError('Delivered heat plus deficit differs from requested service')
            rated=fsum(a['quantity']*next(d['input_capacity_mw']*d['service_per_mwh'] for d in model['operation']['devices'] if d['id']==a['component'])
                for a in result['assets'] if a['year']==year and a['kind']=='device'
                and a['component'] in ('residential_oil_boiler','residential_heat_pump') and a['state']!='retired')
            if not isclose(rated,mapping['initial_rated_heat_MW'],abs_tol=1e-6,rel_tol=1e-8):
                raise ValueError('Replacement created rated service capacity')
            if year==2014 and electricity!=0:
                raise ValueError('New device served demand in application year')
            checks.append(dict(case=record['case'],year=year,requested_heat_MWh=requested,
                delivered_heat_MWh=heat,shortfall_MWh=deficit,rated_capacity_MW_heat=rated,
                heat_balance_error=heat+deficit-requested,cash_error=money-initial_money,
                queue_escrow_error=queue-annual['accounts']['escrow']))
    prior=read(ROOT/'outputs/q2/activity_regressions.json')
    engineering={}
    for name,binding in prior['engineering_files'].items():
        path=ROOT/'outputs/q2/device_mapping_engineering_regression'/name
        actual=sha(path)
        if actual!=binding['original_sha256']:
            raise ValueError('Legacy engineering scientific output changed: '+name)
        engineering[name]=dict(sha256=actual,byte_identical=True)
    dump(ROOT/'outputs/q2/device_mapping_checks.json',dict(
        previous_goal_turn_classification='progress: v12 changed fitted state and provided independent failure evidence',
        all_checks_passed=True,full_v12_ledger_equal=True,checked_service_years=len(checks),
        maximum_heat_balance_error_MWh=maximum_heat_error,maximum_money_error=maximum_money_error,
        maximum_queue_escrow_error=maximum_queue_error,service_year_checks=checks,
        engineering_files=engineering,engineering_identical_count=len(engineering),
        checked_input_hashes={p.name:sha(p) for p in sorted(folder.glob('*.json'))},
        current_code_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in sorted((ROOT/'src/energy_model/q2').glob('*.py'))},
        national_acceptance=False))
    print(json.dumps(dict(service_years=len(checks),engineering_outputs_equal=len(engineering),national_acceptance=False)))


if __name__=='__main__':execute()
