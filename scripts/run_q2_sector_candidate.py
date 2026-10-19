"""Train sector responses on 2015-2021; preserve exact controls and all failures."""
import argparse
from copy import deepcopy
from itertools import product
import json
from math import fsum, prod
from pathlib import Path

import build_q2_sector_candidate as builder
import run_q2_historical_candidate as history
from run_q2_nonenergy_episode import initial_checks, require_close, flow_totals
from energy_model.q2.io import csvout, dump, local_path, sha
from energy_model.q2.operations import OperationError

ROOT = history.ROOT


def model_for_trial(data, trial):
    name = trial['structure']
    if trial['kind'] == 'unchanged_v10_control':
        return deepcopy(data['control_models'][name])
    if trial['kind'] != 'sector_response':
        raise ValueError('Unknown sector trial kind')
    return history.parameterize(data['structural_models'][name], data['experiment']['parameters'], trial['parameters'])


def train(data):
    experiment = data['experiment']
    if experiment['windows'] != {'train':[2015,2021], 'already_seen_holdout':[2022,2024]}:
        raise ValueError('Frozen historical windows changed')
    names = experiment['structural_alternatives']
    if len(set(names)) != len(names) or set(names) != set(data['control_models']) or set(names) != set(data['structural_models']):
        raise ValueError('Missing/duplicate sector structures or parent controls')
    parameters = experiment['parameters']
    grid = list(product(*(p['grid'] for p in parameters)))
    if len(names)*(len(grid)+1) > experiment['maximum_evaluations']:
        raise ValueError('Frozen sector search budget exceeded')
    observations = [r for r in data['observations'] if 2015 <= r['year'] <= 2021]
    trials = []
    specifications = [dict(structure=s, kind='unchanged_v10_control', parameters={}) for s in names]
    specifications += [dict(structure=s, kind='sector_response', parameters=dict(zip([p['id'] for p in parameters],values)))
                       for s in names for values in grid]
    for spec in specifications:
        trial = dict(trial=len(trials), **spec)
        model = model_for_trial(data,trial)
        model['end_year'] = 2021
        try:
            result = history.EnergyModel(model).run()
            fit = history.compare(observations, history.metric_rows(result,data['definitions']),
                                  experiment['targets'],experiment['windows'])
            loss, parts = history.loss(fit,experiment['targets'])
            if trial['kind']=='unchanged_v10_control':
                require_close(loss,data['initialization']['parent_training_winners'][trial['structure']]['loss'],
                              'Unchanged v10 training loss')
            trial.update(status='valid',loss=loss,parts=parts)
        except (ValueError,OperationError) as exc:
            trial.update(status='failed',loss=None,exception=type(exc).__name__,reason=str(exc))
        trials.append(trial)
        if len(trials)%126==0:
            print(json.dumps(dict(executed=len(trials), valid=sum(r['status']=='valid' for r in trials))),flush=True)
    return trials


def winners(trials, structures):
    result = {}
    for name in structures:
        valid = [t for t in trials if t['structure']==name and t['status']=='valid']
        if not valid:
            raise ValueError('No valid candidate for '+name)
        result[name] = min(valid,key=lambda t:(t['loss'],t['trial']))
    return result


def sector_accounts(name,model,result,mappings):
    rows = []
    for operation in result['operations']:
        year, op = operation['year'],operation['input']
        totals = flow_totals(operation)
        policy = next(r['policy'] for r in result['information'] if r['year']==year)
        gdp = prod(1+model['gdp_growth'][str(y)] for y in range(model['start_year']+1,year+1))
        for item in mappings:
            identity = item['id']
            service = next(s for s in op['services'] if s['id']==identity)
            requested = fsum(v*w for v,w in zip(service['demand'],op['annual_weights']))
            expected = item['input_MWh_LHV'] * gdp**model['demand_drivers'][identity]['gdp_elasticity']
            demand_error = require_close(requested,expected,'Sector GDP demand')
            supplied = totals['device',identity+'_device']
            unmet = operation['result']['service_shortfalls'][identity]
            supply_error = require_close(supplied+unmet,requested,'Sector supplied plus unmet')
            purchases = [r for r in result['cash'] if r['year']==year and
                         r['reference']=='device:'+identity+'_device' and r['reason']=='end_use_purchase']
            paid = fsum(r['amount'] for r in purchases)
            cash_error = require_close(paid,supplied*policy['node_prices'][item['carrier']],'Sector fuel payment')
            if any(r['payer']!=item['owner'] or r['payee']!='clearing' for r in purchases):
                raise ValueError('Sector fuel paid by wrong account')
            rows.append(dict(case=name,year=year,sector=item['sector'],carrier=item['carrier'],
                demand_MWh=requested,delivered_MWh=supplied,unmet_MWh=unmet,
                demand_residual_MWh=demand_error,supply_residual_MWh=supply_error,
                fuel_payment_million_USD2008=paid,cash_residual=cash_error,
                useful_service_quantity=None,measured_device_efficiency=None,
                scope='Delivered final-energy proxy only; GDP response fitted on training years.'))
    return rows


def classification_check(name, parent, split):
    rows = []
    for a,b in zip(parent['operations'],split['operations']):
        before,after = flow_totals(a),flow_totals(b)
        residuals = [require_close(after[k],v,'Classification control source/process flow')
                     for k,v in before.items() if k[0] in ('source','process')]
        aa = next(r for r in parent['annual'] if r['year']==a['year'])
        bb = next(r for r in split['annual'] if r['year']==a['year'])
        carbon = require_close(bb['gross_energy_co2_t'],aa['gross_energy_co2_t'],'Unchanged effective carbon proxy')
        cost = require_close(bb['total_resource_cost'],aa['total_resource_cost'],'Classification resource cost')
        cash = require_close(fsum([*bb['agent_cash'].values(),*bb['accounts'].values()]),
                             fsum([*aa['agent_cash'].values(),*aa['accounts'].values()]),'Whole-system money')
        rows.append(dict(structure=name,year=a['year'],max_flow_residual_MWh=max(map(abs,residuals)),
                         proxy_carbon_residual_t=carbon,resource_cost_residual=cost,cash_residual=cash))
    return rows


def execute(output_relative):
    builder.freeze()
    manifest_path = ROOT/builder.DIRECTORY/'manifest.json'
    manifest,data = history.load_frozen(manifest_path)
    if manifest.get('study_kind')!='sector_final_energy_response_training_diagnostic':
        raise ValueError('Wrong frozen study')
    out = local_path(ROOT,output_relative)
    if not out.is_relative_to((ROOT/'outputs/q2').resolve()) or out==(ROOT/'outputs/q2').resolve() or out.exists():
        raise ValueError('Use a fresh outputs/q2 child directory')
    out.mkdir(parents=True)
    dump(out/'attempt.json',dict(status='running',national_acceptance=False))
    try:
        structures = data['experiment']['structural_alternatives']
        classifications,opening = [],[]
        for name in structures:
            original = history.EnergyModel(data['control_models'][name]).run()
            retained = json.loads((ROOT/('outputs/q2/historical_candidate_v10_comparison/'+name+'.json')).read_text(encoding='utf-8'))['result']
            if original!=retained:
                raise ValueError('Exact v10 parent ledger changed: '+name)
            split = history.EnergyModel(data['structural_models'][name]).run()
            classifications.extend(classification_check(name,original,split))
            opening.extend(dict(structure=name,**r) for r in initial_checks(data['control_models'][name],data['structural_models'][name]))
        csvout(out/'classification_controls.csv',classifications)
        csvout(out/'opening_conservation.csv',opening)
        trials = train(data)
        dump(out/'training_trials.json',trials)
        if len(trials)!=756:
            raise ValueError('Full frozen756trial experiment required')
        valid = [t for t in trials if t['status']=='valid']
        if not valid:
            raise ValueError('All sector trials failed')
        selected = min(valid,key=lambda t:(t['loss'],t['trial']))
        best = winners(trials,structures)
        dump(out/'training_selection.json',dict(selected=selected,selected_by_structure=best,
            equivalent_candidates=[t for t in valid if t['loss']<=selected['loss']+data['experiment']['equivalent_loss_absolute_tolerance']],
            selection_information='Training2015-2021only; unchanged parent controls eligible; allholdoutalreadyseen'))
        metrics,quality,accounts,comparison = [],[],[],[]
        overall = None
        for name,trial in best.items():
            model = model_for_trial(data,trial)
            result = history.EnergyModel(model).run()
            values = history.metric_rows(result,data['definitions'])
            fit = history.compare(data['observations'],values,data['experiment']['targets'],data['experiment']['windows'])
            loss,_ = history.loss(fit,data['experiment']['targets'])
            require_close(loss,trial['loss'],'Training-prefix selected replay')
            baselines = history.baseline_comparisons(data['observations'],data['experiment']['targets'],data['experiment']['windows'])
            check = history.historical_quality({'history_fit':fit,'baselines':baselines},data['experiment']['targets'],
                                              data['acceptance']['historical_quality'],data['experiment']['windows'])
            dump(out/(name+'.json'),dict(selection=trial,result=result,historical_quality=check,national_acceptance=False))
            metrics.extend(dict(structure=name,**r) for r in values)
            quality.extend(dict(structure=name,**r) for r in check['targets'])
            if trial['kind']=='sector_response':
                accounts.extend(sector_accounts(name,model,result,data['initialization']['sector_mappings']))
            comparison.append(dict(structure=name,kind=trial['kind'],parameters=trial['parameters'],training_loss=loss,
                parent_training_loss=data['initialization']['parent_training_winners'][name]['loss'],
                selected_overall=trial==selected,failed_numeric_targets=[r['indicator'] for r in check['targets'] if not r['passed']]))
            if trial==selected:
                overall = (model,result,fit,baselines,check)
        for name,rows in [('metrics',metrics),('quality',quality),('structure_comparison',comparison)]:
            csvout(out/(name+'.csv'),rows)
        if accounts:
            csvout(out/'sector_accounts.csv',accounts)
        model,result,fit,baselines,check = overall
        dump(out/'selected_model.json',model)
        dump(out/'selected_result.json',result)
        check['national_acceptance']=False
        dump(out/'historical_quality.json',check)
        csvout(out/'history_fit.csv',fit)
        csvout(out/'history_baselines.csv',baselines)
        history.write_figure(out,fit)
        dump(out/'summary.json',dict(scope='historical_sector_final_energy_diagnostic_not_national',
            training_executions=len(trials),valid_training_executions=len(valid),failed_training_executions=len(trials)-len(valid),
            exact_v10_control_training_executions=6,exact_v10_full_control_ledgers_equal=6,
            same_growth_classification_controls=6,selected=selected,comparison=comparison,
            sector_account_rows=len(accounts),national_acceptance=False,
            reason='Nine source-based final-energy groups with GDP proxies. Unresolved remainder and originaleffectiveCO2account retained. Not measured useful services or a complete carbon boundary; no nationalS0.'))
        code = [Path(__file__), ROOT/'scripts/build_q2_sector_candidate.py',ROOT/'scripts/run_q2_nonenergy_episode.py',
                ROOT/'scripts/build_q2_nonenergy_episode.py',ROOT/'scripts/run_q2_historical_candidate.py',
                ROOT/'scripts/run_q2_joint_deployment_comparison.py',ROOT/'scripts/run_q2_deployment_ablation.py',
                ROOT/'scripts/run_q2_solar_ablation.py',ROOT/'scripts/prepare_q2_apec_balance.py',
                *sorted((ROOT/'src/energy_model/q2').glob('*.py'))]
        dump(out/'run_manifest.json',dict(status='sector_candidate_executed',manifest_path=manifest_path.relative_to(ROOT).as_posix(),
            manifest_sha256=sha(manifest_path),code_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in code},
            outputs={p.name:sha(p) for p in sorted(out.iterdir()) if p.name!='attempt.json'},national_acceptance=False))
        dump(out/'attempt.json',dict(status='sector_candidate_executed',national_acceptance=False))
        print(json.dumps(dict(selected=selected['trial'],loss=selected['loss'],kind=selected['kind'],
            failed_targets=[r['indicator'] for r in check['targets'] if not r['passed']])),flush=True)
        return 0
    except Exception as exc:
        dump(out/'attempt.json',dict(status='failed',reason=str(exc),national_acceptance=False))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True)
    raise SystemExit(execute(parser.parse_args().output_dir))
