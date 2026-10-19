"""Four paired deployment structures with frozen v7 training-selected behavior.

This does not reselect on holdout. Includes annual frontier snapshots, realized
utilization and approved/queued capacity to diagnose investment feedback.
"""
import argparse
import json
from pathlib import Path

import run_q2_historical_candidate as history
from run_q2_solar_ablation import constraint_rows
from energy_model.q2.io import csvout, dump, local_path, sha

ROOT = history.ROOT


def technology_rows(model, result):
    rows = []
    for operation in result['operations']:
        year, op, solved = operation['year'], operation['input'], operation['result']
        for process in op['processes']:
            identity = process['id']
            options = [o['id'] for o in model['investment_options'] if o['kind']=='process' and o['component']==identity]
            generated = sum(r['value']*r['annual_weight'] for r in solved['flows'] if r['kind']=='process' and r['id']==identity)
            h = sum(a*b for a,b in zip(op['hours'],op['annual_weights']))
            potential = sum(process['capacity_mw']*a*h*w for a,h,w in zip(process['availability'],op['hours'],op['annual_weights']))
            approvals = sum(a['approved_units'] for a in result['actions'] if a['year']==year and a.get('option') in options and 'approved_units' in a)
            pending = sum(p['quantity'] for p in result['projects'] if p['year']==year and p['kind']=='process' and p['component']==identity and p['state']=='building')
            rows.append({'year':year,'process':identity,'operating_capacity_MW':process['capacity_mw'],
                'activity_MWh':generated,'availability_limited_potential_MWh':potential,
                'realized_capacity_factor':generated/(process['capacity_mw']*h) if process['capacity_mw']>0 else None,
                'unutilized_available_fraction':max(0.,1-generated/potential) if potential>0 else None,
                'approved_capacity_MW':approvals,'closing_queue_MW':pending,
                'boundary':'Process activity and model availability; unused potential is not measured renewable curtailment.'})
    return rows


def execute(output_relative):
    binding_path = ROOT/'workflow/q2_candidates/v7_ablation.json'
    binding = json.loads(binding_path.read_text(encoding='utf-8'))
    for item in binding['bindings'].values():
        if sha(local_path(ROOT,item['path'])) != item['sha256']:
            raise ValueError('Frozen v7 ablation binding changed')
    manifest_path = local_path(ROOT,binding['bindings']['manifest']['path'])
    manifest, data = history.load_frozen(manifest_path)
    selected = json.loads(local_path(ROOT,binding['bindings']['training_selection']['path']).read_text(encoding='utf-8'))['selected']
    if selected['status']!='valid' or data['experiment']['parameters']:
        raise ValueError('Expected valid fixed-parameter v7 selection')
    out = local_path(ROOT,output_relative)
    if not out.is_relative_to((ROOT/'outputs/q2').resolve()) or out==(ROOT/'outputs/q2').resolve() or out.exists():
        raise ValueError('Use a new child of outputs/q2')
    out.mkdir(parents=True)
    dump(out/'attempt.json',{'status':'running','national_acceptance':False})
    try:
        constraints, metrics, quality, technology = [], [], [], []
        for name in data['experiment']['structural_alternatives']:
            model = history.rule_model(data['structural_models'][name],selected['rule'])
            result = history.EnergyModel(model).run()
            values = history.metric_rows(result,data['definitions'])
            fit = history.compare(data['observations'],values,data['experiment']['targets'],data['experiment']['windows'])
            baselines = history.baseline_comparisons(data['observations'],data['experiment']['targets'],data['experiment']['windows'])
            check = history.historical_quality({'history_fit':fit,'baselines':baselines},data['experiment']['targets'],data['acceptance']['historical_quality'],data['experiment']['windows'])
            dump(out/(name+'.json'),{'rule':selected['rule'],'result':result,'historical_quality':check})
            constraints.extend({'structure':name,**r} for r in constraint_rows(model,result))
            metrics.extend({'structure':name,**r} for r in values)
            quality.extend({'structure':name,**r} for r in check['targets'])
            technology.extend({'structure':name,**r} for r in technology_rows(model,result))
        for name, rows in [('constraint_usage',constraints),('metrics',metrics),('quality',quality),('technology_activity',technology)]:
            csvout(out/(name+'.csv'),rows)
        dump(out/'summary.json',{'scope':'v7_fixed_rule_deployment_factorial_diagnostic',
            'rule':selected['rule'],'structures':data['experiment']['structural_alternatives'],
            'national_acceptance':False,'interpretation':'Finite technology frontiers are an explicit alternative to an unverified common cap; unused model potential is not observed curtailment. No holdout selection.'})
        dump(out/'run_manifest.json',{'status':'ablation_executed','bindings':binding['bindings'],
            'code_hashes':{p.relative_to(ROOT).as_posix():sha(p) for p in
                [Path(__file__),ROOT/'scripts/run_q2_solar_ablation.py',ROOT/'scripts/run_q2_historical_candidate.py',*sorted((ROOT/'src/energy_model/q2').glob('*.py'))]},
            'outputs':{p.name:sha(p) for p in sorted(out.iterdir()) if p.name!='attempt.json'},
            'national_acceptance':False})
        dump(out/'attempt.json',{'status':'ablation_executed','national_acceptance':False})
        print('Four paired trajectories;44annual constraints;technology activity and queues retained')
        return 0
    except Exception as exc:
        dump(out/'attempt.json',{'status':'failed','reason':str(exc),'national_acceptance':False})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    raise SystemExit(execute(args.output_dir))
