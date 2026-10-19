"""APEC residential-oil conditional heat mapping and replacement valuation.

Eligible heat fractions and capital-cost offers are hypotheses, never fitted
observations. This episode does not claim a national heating fleet or S0.
"""
import argparse
from copy import deepcopy
import json
from math import fsum
from pathlib import Path

import run_q2_historical_candidate as history
from prepare_q2_apec_balance import parse_table
from prepare_q2_end_use import prepare
from energy_model.q2.finance import project_value
from energy_model.q2.io import csvout, dump, local_path, sha, verify_source_records

ROOT = history.ROOT
SERVICE = 'residential_oil_low_temperature_heat_hypothesis'
PROTOCOL = 'workflow/q2_candidates/residential_heat_episode_v2.json'


def residential_oil_reference():
    review = json.loads((ROOT/'data/catalog/q2_apec_balance_review.json').read_text(encoding='utf-8'))
    for binding in review['fingerprints']:
        if sha(local_path(ROOT, binding['path'])) != binding['sha256']:
            raise ValueError('APEC source changed')
    verify_source_records(ROOT, review['source_records'])
    table = parse_table((ROOT/review['ktoe_export']).read_text(encoding='utf-8-sig'), 'Unit:KTOE', review)
    rows = [r for r in table[1:] if r[0]=='16.2 Residential']
    if len(rows)!=1:
        raise ValueError('Unique residential row required')
    column = table[0].index('7. Petroleum products')
    token = rows[0][column]
    if token!='26375':
        raise ValueError('Reviewed residential petroleum input changed')
    return dict(flow=rows[0][0], product=table[0][column], raw_token=token,
                value_ktoe=26375., input_MWh_LHV=26375.*11630,
                boundary='APEC China005 2014 residential petroleum final-energy input; heating fraction unknown')


def split_residential(model, fraction, reference, performance):
    if not 0 < fraction <= 1 or model['start_year']!=2014:
        raise ValueError('Explicit bounded 2014 eligible-heat fraction required')
    result = deepcopy(model)
    op = result['operation']
    if any(s['id']==SERVICE for s in op['services']):
        raise ValueError('Residential heat already partitioned')
    original_service = next(s for s in op['services'] if s['id']=='oil_residual')
    original_device = next(d for d in op['devices'] if d['service']=='oil_residual')
    if original_device['service_per_mwh']!=1:
        raise ValueError('Parent residual must be an unconverted final-energy proxy')
    eta = performance['building_oil_boiler']['service_per_MWh_input']
    demand = list(original_service['demand'])
    energy = fsum(v*w for v,w in zip(demand,op['annual_weights']))
    eligible = reference['input_MWh_LHV']*fraction
    share = eligible/energy
    if not 0<share<1:
        raise ValueError('Eligible input exceeds residual; no rescaling')
    capacity = original_device['input_capacity_mw']*share
    original_service['demand'] = [v*(1-share) for v in demand]
    original_device['input_capacity_mw'] *= 1-share
    op['services'].append(dict(id=SERVICE, demand=[v*share*eta for v in demand],
        unit='MWh_heat_service_conditional_low_temperature', priority=original_service['priority'],
        shortfall_weight=original_service['shortfall_weight']/eta))
    boiler = deepcopy(original_device)
    boiler.update(id='residential_oil_boiler', service=SERVICE, input_capacity_mw=capacity, service_per_mwh=eta)
    op['devices'].append(boiler)
    result['assets'].append(dict(id='residential_oil_boiler_opening', owner='buildings', kind='device',
        component=boiler['id'], quantity=1., online_year=2014, state='operating', fixed_om_per_unit=0.))
    result['demand_drivers'][SERVICE] = deepcopy(result['demand_drivers']['oil_residual'])
    for policy in result['policies']:
        policy['service_prices'][SERVICE] = policy['service_prices']['oil_residual']/eta
    return result, dict(eligible_fraction_assumption=fraction, eligible_fuel_input_MWh=eligible,
        useful_heat_MWh=eligible*eta, initial_input_capacity_MW=capacity,
        initial_rated_heat_MW=capacity*eta, boiler_efficiency_reference=eta,
        inherited_spare_capacity_is_not_observed_fleet=True)


def add_offer(model, mapping, performance, utilisation_rule, cost_multiplier):
    """Cost offers straddle current-operation break-even; not market quotations."""
    result = deepcopy(model)
    result['mechanisms']['replacement'] = True
    cop = performance['building_heat_pump']['service_per_MWh_input']
    hp = dict(id='residential_heat_pump', node='electricity', service=SERVICE,
        service_per_mwh=cop, input_capacity_mw=1/cop, resource_cost_per_mwh=0.,
        gross_co2_t_per_mwh=0., liability_co2_t_per_mwh=0.)
    result['operation']['devices'].append(hp)
    result['assets'].append(dict(id='residential_heat_pump_opening', owner='buildings', kind='device',
        component=hp['id'], quantity=0., online_year=2014, state='operating', fixed_om_per_unit=0.))
    option = dict(id='residential_heat_upgrade', owner='buildings', kind='device', component=hp['id'],
        capex_per_unit=1., annual_installation_units=.05*mapping['initial_rated_heat_MW'],
        maximum_total_units=mapping['initial_rated_heat_MW'], fixed_om_per_unit=0., discount_rate=.05,
        economic_life=20., expected_utilisation=1., replacement_ratio=1/mapping['initial_rated_heat_MW'],
        connection_per_unit=1/cop, subsidy_per_unit=0., lead_years=1, construction_fractions=[1.],
        expected_terminal_value_per_unit=0., funding_convention='fully_funded_nonremunerated_escrow',
        known_year=2014, permit_known_year=2014, permit_effective_year=2014, cost_reference_year=2014,
        replaces='residential_oil_boiler_opening', device_utilisation_rule='replaced_device_observed')
    result['investment_options'].append(option)
    result['cost_decline'][option['id']] = 0.
    next(a for a in result['agents'] if a['id']=='buildings')['initial_margins'][option['id']] = 0.
    initial = deepcopy(model)
    initial['end_year']=2014
    operation = history.EnergyModel(initial).run()['operations'][0]['result']
    valuation_model = history.EnergyModel(result)
    margin = valuation_model.margin_per_unit(option, hp, valuation_model.visible_policy(), operation)
    capex = project_value(option, 0., margin)['investment_npv']
    if capex<=0:
        raise ValueError('No positive break-even capital cost under frozen initial prices')
    option['capex_per_unit']=capex*cost_multiplier
    option['device_utilisation_rule']=utilisation_rule
    return result, dict(observed_utilisation=valuation_model.expected_activity(option | {
        'device_utilisation_rule':'replaced_device_observed'}, hp, operation)[1],
        initial_annual_margin_per_MW_heat=margin, break_even_capex_million_USD2008_per_MW_heat=capex,
        hypothetical_offer_multiplier=cost_multiplier, hypothetical_capex=option['capex_per_unit'],
        cost_is_not_an_observation=True)


def freeze():
    performance = {r['id']:r for r in prepare()}
    reference = residential_oil_reference()
    binding_paths = ['outputs/q2/historical_candidate_v12/selected_model.json',
        'workflow/q2_candidates/v10/definitions.json', 'data/catalog/q2_apec_balance_review.json',
        'data/catalog/q2_end_use_review.json', 'data/processed/q2/end_use_reference.csv']
    protocol = dict(version=2, scope='real_input_conditional_service_mapping_not_national',
        national_acceptance=False, fitted_parameters=0, eligible_fractions=[.05,.10,.20],
        utilisation_rules=['declared','replaced_device_observed'], capital_offer_multipliers=[.5,1.5],
        reference=reference, performance=performance,
        bindings={p:sha(ROOT/p) for p in binding_paths},
        assumptions=[
            '5/10/20 percent of reported residential petroleum is assumed eligible low-temperature oil heating; actual fraction unknown.',
            'REmap85percent boiler andCOP3.5 are prospective performance references, assumed for the scoped conversion, not observed2014equipment.',
            'Existing residual spare input capacity is partitioned, not re-estimated; it is not an observed boiler fleet.',
            'Conditional heat service and its bookkeeping price are rescaled inversely so classification preserves fuel input and aggregate service revenue.',
            'Capital offers are0.5/1.5 times initial observed-usage break-even, not observedCAPEX. Lifetime20years,5percentdiscount,1yearlead,zeroO&M/terminalvalue are diagnostic assumptions.',
            'Installation5percent of opening rated thermalcapacity peryear; shared construction proxy counts1MWheat as1constructionunit. Electrical connection counts1/COP. Not a reviewed national crew or grid limit.',
            'No source costs from2030, no newcalibration, no futurepolicy or actualreplacementfraction inferred.',
            'Replacement mechanism is explicitly enabled only in offer cases; parent has no replacement offers and keeps its original switch.',
            'Electricity carbon remains at generation, heat-pumpdevicehaszero onsitecarbon. Parent effectivecarbonproxy retained; no full national emissions claim.'])
    path = ROOT/PROTOCOL
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != protocol:
            raise ValueError('Frozen episode changed; use a new version')
    else:
        dump(path, protocol)
    return path


def annual_rows(name, model, result):
    rows=[]
    op=model['operation']
    boiler=next((d for d in op['devices'] if d['id']=='residential_oil_boiler'), None)
    if boiler is None:
        # The original control has no residential subaccount. Its unallocated
        # petroleum use must not be exported as a measured zero for that scope.
        return rows
    for entry in result['operations']:
        year=entry['year']; flows=entry['result']['flows']
        def activity(kind, identity):
            return fsum(r['value']*r['annual_weight'] for r in flows if r['kind']==kind and r['id']==identity)
        oil=activity('device','residential_oil_boiler')
        electricity=activity('device','residential_heat_pump')
        pump=next((d for d in op['devices'] if d['id']=='residential_heat_pump'), None)
        pump_heat=electricity*pump['service_per_mwh'] if pump else 0.
        heat=oil*boiler['service_per_mwh']+pump_heat if boiler else None
        decisions=[a for a in result['actions'] if a['year']==year and a.get('option')=='residential_heat_upgrade']
        rows.append(dict(case=name,year=year,reported_scope=SERVICE if boiler else 'unsplit_parent',
            oil_MWh_LHV=oil,electricity_MWh=electricity,delivered_heat_MWh=heat,
            ambient_heat_MWh=pump_heat-electricity,
            approved_MW_heat=fsum(a.get('approved_units',0.) for a in decisions),
            operating_pump_MW_heat=fsum(a['quantity'] for a in result['assets'] if a['year']==year
                and a['component']=='residential_heat_pump' and a['state']=='operating'),
            valuation_utilisation=next((a['valuation_utilisation'] for a in decisions if 'valuation_utilisation' in a),None)))
    return rows


def execute(output_relative):
    path=ROOT/PROTOCOL
    protocol=json.loads(path.read_text(encoding='utf-8'))
    for name,expected in protocol['bindings'].items():
        if sha(ROOT/name)!=expected:
            raise ValueError('Frozen episode binding changed: '+name)
    # Revalidate the new source purpose, not just the protocol hash.
    performance={r['id']:r for r in prepare()}
    reference=residential_oil_reference()
    if performance!=protocol['performance'] or reference!=protocol['reference']:
        raise ValueError('Source extraction differs from frozen episode')
    parent=json.loads((ROOT/'outputs/q2/historical_candidate_v12/selected_model.json').read_text(encoding='utf-8'))
    definitions=json.loads((ROOT/'workflow/q2_candidates/v10/definitions.json').read_text(encoding='utf-8'))
    out=local_path(ROOT,output_relative)
    if out.exists() or not out.is_relative_to((ROOT/'outputs/q2').resolve()) or out==ROOT/'outputs/q2':
        raise ValueError('Use a fresh outputs/q2 child')
    out.mkdir(parents=True)
    dump(out/'attempt.json',dict(status='running',national_acceptance=False))
    try:
        cases={'v12_control':(parent,{})}
        mappings=[]
        for fraction in protocol['eligible_fractions']:
            split,mapping=split_residential(parent,fraction,reference,performance)
            label=f'eligible_{int(fraction*100)}'
            cases[label+'_classification']=(split,mapping)
            mappings.append(mapping)
            for rule in protocol['utilisation_rules']:
                for multiplier in protocol['capital_offer_multipliers']:
                    model,pricing=add_offer(split,mapping,performance,rule,multiplier)
                    cases[f'{label}_{rule}_offer_{multiplier}']=(model,dict(**mapping,**pricing))
        all_rows,metrics,records=[],[],[]
        control=None
        for name,(model,mapping) in cases.items():
            result=history.EnergyModel(model).run()
            values=history.metric_rows(result,definitions)
            if name=='v12_control':
                control=values
            classification_equal=None
            if name.endswith('_classification'):
                classification_equal=all(abs(a['value']-b['value'])<=1e-8*max(1,abs(a['value']))
                    for a,b in zip(control,values))
                if not classification_equal:
                    raise ValueError('Service-unit classification changed parent physical metrics')
            all_rows.extend(annual_rows(name,model,result))
            metrics.extend(dict(case=name,**row) for row in values)
            record=dict(case=name,mapping=mapping,classification_matches_parent=classification_equal,
                        national_acceptance=False)
            dump(out/(name+'.json'),dict(**record,model=model,result=result))
            records.append(record)
        csvout(out/'service_accounts.csv',all_rows)
        csvout(out/'proxy_metrics.csv',metrics)
        summary=dict(status='conditional_service_episode_executed',cases=len(cases),records=records,
            additional_calibration_executions=0,changes_v12_selection=False,national_acceptance=False)
        dump(out/'summary.json',summary)
        code=[Path(__file__),ROOT/'scripts/prepare_q2_end_use.py',ROOT/'scripts/prepare_q2_apec_balance.py',
              ROOT/'scripts/run_q2_historical_candidate.py',*sorted((ROOT/'src/energy_model/q2').glob('*.py'))]
        dump(out/'run_manifest.json',dict(protocol_sha256=sha(path),bindings=protocol['bindings'],
            code_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in code},
            outputs={p.name:sha(p) for p in sorted(out.iterdir()) if p.name!='attempt.json'},national_acceptance=False))
        dump(out/'attempt.json',summary)
        print(json.dumps(dict(cases=len(cases),national_acceptance=False)))
    except Exception as exc:
        dump(out/'attempt.json',dict(status='failed',reason=str(exc),national_acceptance=False))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze',action='store_true')
    parser.add_argument('--output-dir')
    args=parser.parse_args()
    if args.freeze:
        print(freeze())
    elif args.output_dir:
        execute(args.output_dir)
    else:
        parser.error('--freeze or --output-dir required')
