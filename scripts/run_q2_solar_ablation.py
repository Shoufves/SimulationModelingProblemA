"""Report frozen v6 factorial contrasts and physical deployment constraint usage.

Uses the v6 training-selected rule for all four structures. Holdout differences
are diagnostics only, never another selection step. Full ledgers are retained.
"""
import argparse
import json
from pathlib import Path

import run_q2_historical_candidate as history
from energy_model.q2.io import csvout, dump, local_path, sha

ROOT=history.ROOT


def constraint_rows(model, result):
    rows=[]
    options={o['id']:o for o in model['investment_options']}
    solar=next(g for g in model['investment_groups'] if g['id']=='solar_construction')
    for information in result['information']:
        year,policy=information['year'],information['policy']
        approvals=[a for a in result['actions'] if a['year']==year and 'approved_units' in a]
        total=sum(a['approved_units'] for a in approvals)
        connection=sum(a['approved_units']*options[a['option']]['connection_per_unit'] for a in approvals)
        stock=sum(a['quantity'] for a in result['assets'] if a['year']==year and a['state']!='retired'
                  and a['component'] in solar['components'] and a['kind']==solar['kind'])
        queue=sum(p['quantity'] for p in result['projects'] if p['year']==year and p['state']=='building'
                  and p['component'] in solar['components'] and p['kind']==solar['kind'])
        rows.append({'year':year,'approved_units_total':total,
            'construction_limit':policy['construction_units_limit'],
            'construction_slack':policy['construction_units_limit']-total,
            'connection_used':connection,'connection_limit':policy['connection_limit'],
            'connection_slack':policy['connection_limit']-connection,
            'solar_installed_MW':stock,'solar_pending_MW':queue,
            'solar_total_ceiling_MW':solar['maximum_total_units'],
            'solar_headroom_after_approval_MW':solar['maximum_total_units']-stock-queue,
            'solar_approved_MW':sum(a['approved_units'] for a in approvals
                                   if options[a['option']].get('investment_group')==solar['id']),
            'wind_approved_MW':sum(a['approved_units'] for a in approvals if a['option']=='wind_build')})
    return rows


def execute(output_relative):
    manifest_path=ROOT/'workflow/q2_candidates/v6/manifest.json'
    manifest,data=history.load_frozen(manifest_path)
    selection_path=ROOT/'outputs/q2/historical_candidate_v6/training_selection.json'
    binding_path=ROOT/'workflow/q2_candidates/v6_sensitivity.json'
    bindings=json.loads(binding_path.read_text(encoding='utf-8'))['bindings']
    for path,key in ((manifest_path,'manifest'),(selection_path,'training_selection')):
        if path!=local_path(ROOT,bindings[key]['path']) or sha(path)!=bindings[key]['sha256']:
            raise ValueError('Frozen v6 manifest or selection changed')
    selected=json.loads(selection_path.read_text(encoding='utf-8'))['selected']
    if selected['status']!='valid' or data['experiment']['parameters']:
        raise ValueError('Expected valid fixed-parameter v6 selection')
    out=local_path(ROOT,output_relative)
    if not out.is_relative_to((ROOT/'outputs/q2').resolve()) or out==(ROOT/'outputs/q2').resolve() or out.exists():
        raise ValueError('Use a new child of outputs/q2')
    out.mkdir(parents=True)
    dump(out/'attempt.json',{'status':'running','national_acceptance':False})
    try:
        constraints,metrics,quality=[],[],[]
        for name in data['experiment']['structural_alternatives']:
            model=history.rule_model(data['structural_models'][name],selected['rule'])
            result=history.EnergyModel(model).run()
            values=history.metric_rows(result,data['definitions'])
            fit=history.compare(data['observations'],values,data['experiment']['targets'],data['experiment']['windows'])
            baselines=history.baseline_comparisons(data['observations'],data['experiment']['targets'],data['experiment']['windows'])
            check=history.historical_quality({'history_fit':fit,'baselines':baselines},data['experiment']['targets'],
                                             data['acceptance']['historical_quality'],data['experiment']['windows'])
            dump(out/(name+'.json'),{'rule':selected['rule'],'result':result,'historical_quality':check})
            constraints.extend({'structure':name,**r} for r in constraint_rows(model,result))
            metrics.extend({'structure':name,**r} for r in values)
            quality.extend({'structure':name,**r} for r in check['targets'])
        csvout(out/'constraint_usage.csv',constraints)
        csvout(out/'metrics.csv',metrics)
        csvout(out/'quality.csv',quality)
        dump(out/'summary.json',{'scope':'v6_fixed_rule_factorial_diagnostic','rule':selected['rule'],
            'structures':data['experiment']['structural_alternatives'],'national_acceptance':False,
            'interpretation':'Exhausted budget is not proof of its real-world value or an LP shadow price. No holdout selection. Physical ledgers and annual cash remain available for all four contrasts.'})
        dump(out/'run_manifest.json',{'status':'ablation_executed',
            'bindings':{str(p.relative_to(ROOT).as_posix()):sha(p) for p in [manifest_path,selection_path,binding_path]},
            'code_hashes':{p.relative_to(ROOT).as_posix():sha(p) for p in
                [Path(__file__),ROOT/'scripts/run_q2_historical_candidate.py',*sorted((ROOT/'src/energy_model/q2').glob('*.py'))]},
            'outputs':{p.name:sha(p) for p in sorted(out.iterdir()) if p.name!='attempt.json'},
            'national_acceptance':False})
        dump(out/'attempt.json',{'status':'ablation_executed','national_acceptance':False})
        print('Four paired trajectories;44annual constraint records; no national acceptance')
        return 0
    except Exception as exc:
        dump(out/'attempt.json',{'status':'failed','reason':str(exc),'national_acceptance':False})
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True)
    args=parser.parse_args()
    raise SystemExit(execute(args.output_dir))
