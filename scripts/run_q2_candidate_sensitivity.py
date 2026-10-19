"""Paired response diagnostic on a frozen real-data historical candidate.

These are counterfactual2014-2024 paths, not validation forecasts or national S0.
Preserves chronological GDP variation, technology-specific decline and budgets.
"""
import argparse
import json
from copy import deepcopy
from itertools import product
from math import isfinite
from pathlib import Path

import run_q2_historical_candidate as history
from energy_model.q2.io import csvout, digest, dump, local_path, sha

ROOT = history.ROOT


def perturb(model, setting):
    expected = {'gdp_growth_multiplier','cost_decline_multiplier','carbon_price_USD2008_per_t'}
    if set(setting) != expected or any(type(v) not in (int,float) or not isfinite(v) or v<0 for v in setting.values()):
        raise ValueError('Invalid response setting')
    changed = deepcopy(model)
    changed['gdp_growth'] = {y:v*setting['gdp_growth_multiplier'] for y,v in model['gdp_growth'].items()}
    changed['cost_decline'] = {key:v*setting['cost_decline_multiplier'] for key,v in model['cost_decline'].items()}
    if any(v>=1 for v in changed['cost_decline'].values()):
        raise ValueError('Cost decline must remain below one')
    # Candidate currency is million constant2008USD, NOT USD or nominal CNY.
    for policy in changed['policies']:
        policy['carbon_price_per_t'] = setting['carbon_price_USD2008_per_t'] / 1e6
    return changed


def execute(config_relative, output_relative):
    config_path = local_path(ROOT,config_relative)
    config = json.loads(config_path.read_text(encoding='utf-8'))
    if config['scope'] != 'historical_candidate_response_diagnostic_not_national_sensitivity':
        raise ValueError('Explicit historical diagnostic scope required')
    if config['national_acceptance'] is not False or not config['frozen_before_first_run']:
        raise ValueError('Response plan cannot certify national acceptance')
    for binding in config['bindings'].values():
        if sha(local_path(ROOT,binding['path'])) != binding['sha256']:
            raise ValueError('Sensitivity reference fingerprint changed: '+binding['path'])
    _,data = history.load_frozen(local_path(ROOT,config['bindings']['manifest']['path']))
    if data['initialization']['currency'] != 'million_USD_2008':
        raise ValueError('Carbon-price conversion requires million constant2008USD')
    selected = json.loads(local_path(ROOT,config['bindings']['training_selection']['path']).read_text(encoding='utf-8'))['selected']
    baseline = history.parameterize(history.rule_model(data['structural_models'][selected['structure']],selected['rule']),
                                    data['experiment']['parameters'],selected['parameters'])
    if baseline['scope'] != 'historical_aggregate_candidate_not_admitted' or (baseline['start_year'],baseline['end_year'])!=(2014,2024):
        raise ValueError('This frozen response study requires its2014-2024 diagnostic model')
    factors = config['factors']
    if len(factors)!=3 or len({f['id'] for f in factors})!=3:
        raise ValueError('Three unique response factors required')
    if any(not f['rationale'] or not f['assumption'] or f['baseline'] not in f['values'] for f in factors):
        raise ValueError('Factor baseline and rationale required')
    out = local_path(ROOT,output_relative)
    if not out.is_relative_to((ROOT/'outputs/q2').resolve()) or out==(ROOT/'outputs/q2').resolve() or out.exists():
        raise ValueError('Use an unused child of outputs/q2; retain previous experiments')
    out.mkdir(parents=True)
    dump(out/'attempt.json',{'status':'running','national_acceptance':False})
    try:
        trials, annual, metrics, actions = [], [], [], []
        settings=list(product(*(f['values'] for f in factors)))
        if len(settings)!=config['case_count']:raise ValueError('Frozen response budget mismatch')
        for case,levels in enumerate(settings):
            setting=dict(zip([f['id'] for f in factors],levels))
            current=perturb(baseline,setting)
            is_baseline=all(setting[f['id']]==f['baseline'] for f in factors)
            trial={'case':case,**setting,'baseline':is_baseline,'model_sha256':digest(current)}
            try:
                result=history.EnergyModel(current).run()
                for r in result['annual']:annual.append({'case':case,**r})
                for r in history.metric_rows(result,data['definitions']):metrics.append({'case':case,**r})
                for r in result['actions']:actions.append({'case':case,**r})
                # Complete physical/financial ledgers make every case auditable.
                dump(out/f'case_{case:02d}.json',{'setting':setting,'result':result})
                trial.update(status='optimal',maximum_cash_residual=max(abs(r['cash_residual']) for r in result['annual']),
                             initial_cash=sum(a['cash'] for a in current['agents'])+sum(current['other_accounts'].values()),
                             seed=current['seed'])
            except (history.OperationError,ValueError) as exc:
                trial.update(status='failed',exception=type(exc).__name__,reason=str(exc))
            trials.append(trial)
        base_cases=[r for r in trials if r['baseline']]
        if len(base_cases)!=1 or base_cases[0]['status']!='optimal':
            raise ValueError('Paired response baseline failed or ambiguous')
        base_case=base_cases[0]['case']
        if base_cases[0]['model_sha256']!=digest(baseline):
            raise ValueError('Baseline perturbation changed the selected model')
        observed_base={(r['year'],r['indicator']):r for r in metrics if r['case']==base_case}
        paired=[]
        for r in metrics:
            b=observed_base[r['year'],r['indicator']]
            paired.append({**r,'baseline_value':b['value'],'difference':r['value']-b['value'],
                           'relative_change':r['value']/b['value']-1 if b['value'] else None})
        csvout(out/'cases.csv',trials);csvout(out/'annual_paths.csv',annual)
        csvout(out/'paired_metrics.csv',paired);csvout(out/'action_ledger.csv',actions)
        # One-factor endpoints use exactly the baseline levels of other factors.
        one_factor=[]
        for factor in factors:
            ids={r['case'] for r in trials if r['status']=='optimal' and
                 all(r[f['id']]==f['baseline'] for f in factors if f['id']!=factor['id'])}
            for trial in trials:
                if trial['case'] not in ids:continue
                for r in paired:
                    if r['case']==trial['case'] and r['year']==2024:
                        one_factor.append({'factor':factor['id'],'level':trial[factor['id']],**r})
        csvout(out/'one_factor_2024.csv',one_factor)
        failed=[r for r in trials if r['status']=='failed']
        summary={'scope':config['scope'],'cases':len(trials),'valid':len(trials)-len(failed),'failed':failed,
                 'baseline_case':base_case,'national_acceptance':False,
                 'identical_opening_cash':len({r.get('initial_cash') for r in trials if r['status']=='optimal'})==1,
                 'identical_seed':len({r.get('seed') for r in trials if r['status']=='optimal'})==1,
                 'metric_boundaries':'Same unreconciled proxy definitions as v5; no nationwide policy inference.',
                 'assumptions':'Common historical GDP-growth multipliers; relative cost-decline multipliers; uniform real2008USD carbon charges on all modeled fossil liabilities. These ranges/coverage are research scenarios, not historical policy observations.',
                 'not_B6_acceptance':'No2025-2060 baseline, admitted national boundary or empirical uncertainty distribution.'}
        dump(out/'summary.json',summary)
        dump(out/'run_manifest.json',{'config_path':config_relative,'config_sha256':sha(config_path),
             'bindings':config['bindings'],'status':'response_diagnostic_executed',
             'code_hashes':{p.relative_to(ROOT).as_posix():sha(p) for p in
                [Path(__file__),ROOT/'scripts/run_q2_historical_candidate.py',*sorted((ROOT/'src/energy_model/q2').glob('*.py'))]},
             'outputs':{p.name:sha(p) for p in sorted(out.iterdir()) if p.name!='attempt.json'},
             'national_acceptance':False})
        dump(out/'attempt.json',{'status':'response_diagnostic_executed','failed_cases':len(failed),'national_acceptance':False})
        print(json.dumps(summary,ensure_ascii=False));return 0 if not failed else 1
    except Exception as exc:
        dump(out/'attempt.json',{'status':'failed','reason':str(exc),'national_acceptance':False});raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',default='workflow/q2_candidates/v5_sensitivity.json')
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args();raise SystemExit(execute(args.config,args.output_dir))
