"""Paired v7/v8 paths under the v8 training-selected rule, with queue tracing."""
import argparse
import json
from pathlib import Path

import run_q2_historical_candidate as history
from run_q2_deployment_ablation import technology_rows
from run_q2_solar_ablation import constraint_rows
from energy_model.q2.io import csvout, dump, local_path, sha

ROOT=history.ROOT


def execute(output_relative):
    binding=json.loads((ROOT/'workflow/q2_candidates/v8_ablation.json').read_text(encoding='utf-8'))
    for r in binding['bindings'].values():
        if sha(local_path(ROOT,r['path']))!=r['sha256']:raise ValueError('Frozen v8 comparison binding changed')
    _,before=history.load_frozen(local_path(ROOT,binding['bindings']['parent_manifest']['path']))
    _,after=history.load_frozen(local_path(ROOT,binding['bindings']['manifest']['path']))
    prior=json.loads(local_path(ROOT,binding['bindings']['parent_selection']['path']).read_text(encoding='utf-8'))['selected']
    selected=json.loads(local_path(ROOT,binding['bindings']['selection']['path']).read_text(encoding='utf-8'))['selected']
    if after['experiment']['parameters']:raise ValueError('Paired comparison expects fixed inherited parameters')
    models={'unconditioned_v7_control':before['structural_models'][prior['structure']],
            'observed_nuclear_nonissuance':after['structural_models'][selected['structure']]}
    out=local_path(ROOT,output_relative)
    if not out.is_relative_to((ROOT/'outputs/q2').resolve()) or out==(ROOT/'outputs/q2').resolve() or out.exists():
        raise ValueError('Use a fresh outputs/q2 child directory')
    out.mkdir(parents=True);dump(out/'attempt.json',dict(status='running',national_acceptance=False))
    try:
        metrics,quality,technology,constraints,approvals=[],[],[],[],[]
        for name,config in models.items():
            model=history.rule_model(config,selected['rule'])
            result=history.EnergyModel(model).run()
            values=history.metric_rows(result,after['definitions'])
            fit=history.compare(after['observations'],values,after['experiment']['targets'],after['experiment']['windows'])
            baselines=history.baseline_comparisons(after['observations'],after['experiment']['targets'],after['experiment']['windows'])
            check=history.historical_quality({'history_fit':fit,'baselines':baselines},after['experiment']['targets'],after['acceptance']['historical_quality'],after['experiment']['windows'])
            dump(out/(name+'.json'),dict(rule=selected['rule'],result=result,historical_quality=check))
            metrics.extend(dict(structure=name,**r) for r in values)
            quality.extend(dict(structure=name,**r) for r in check['targets'])
            technology.extend(dict(structure=name,**r) for r in technology_rows(model,result))
            constraints.extend(dict(structure=name,**r) for r in constraint_rows(model,result))
            for year in range(model['start_year'],model['end_year']+1):
                actions=[a for a in result['actions'] if a['year']==year and a.get('option')=='nuclear_build']
                approvals.append(dict(structure=name,year=year,
                    documented_no_issuance=year in (2016,2017,2018),
                    observed_block_applied=any(e['year']==year for e in model.get('approval_blocks',[])),
                    model_approved_MW=sum(a.get('approved_units',0) for a in actions),
                    explicitly_rejected_request_MW=sum(a.get('requested_units',0) for a in actions if a.get('reason')=='realized_administrative_nonissuance'),
                    closing_model_nuclear_queue_MW=sum(p['quantity'] for p in result['projects'] if p['year']==year and p['component']=='nuclear_power' and p['state']=='building'),
                    information_basis='Retrospective observed year-local outcome; other years retain unresolved prior hypotheses.'))
        for name,rows in [('metrics',metrics),('quality',quality),('technology_activity',technology),
                          ('constraint_usage',constraints),('nuclear_approvals',approvals)]:
            csvout(out/(name+'.csv'),rows)
        dump(out/'summary.json',dict(scope='v8_fixed_rule_observed_approval_replay_diagnostic',
            rule=selected['rule'],structures=list(models),national_acceptance=False,
            interpretation='Observed2016-2018zeroissuance conditions government decisions only; preservedexistingqueue. Not a causal policy estimate, foresightmodel, complete permitcalendar or nationalS0. Control cannot overrule documentedfacts.'))
        dump(out/'run_manifest.json',dict(status='ablation_executed',bindings=binding['bindings'],
            code_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in [Path(__file__),ROOT/'scripts/run_q2_deployment_ablation.py',
                ROOT/'scripts/run_q2_solar_ablation.py',ROOT/'scripts/run_q2_historical_candidate.py',*sorted((ROOT/'src/energy_model/q2').glob('*.py'))]},
            outputs={p.name:sha(p) for p in sorted(out.iterdir()) if p.name!='attempt.json'},national_acceptance=False))
        dump(out/'attempt.json',dict(status='ablation_executed',national_acceptance=False))
        print('Two paired trajectories;22annual nuclearapproval and constraint records')
        return 0
    except Exception as exc:
        dump(out/'attempt.json',dict(status='failed',reason=str(exc),national_acceptance=False));raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output-dir',required=True)
    raise SystemExit(execute(parser.parse_args().output_dir))
