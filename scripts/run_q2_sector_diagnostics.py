"""Expose every structure's rejected training-best sector model and account for it.

The overall selected model remains the v10 control. These six diagnostic paths
are selected using training loss only and never replace that winner on holdout.
"""
import argparse
import json
from pathlib import Path

import run_q2_sector_candidate as sector
from energy_model.q2.io import csvout, dump, local_path, sha

ROOT=sector.ROOT
CONFIG='workflow/q2_candidates/v11_sector_diagnostics.json'


def execute(output_relative):
    config=json.loads((ROOT/CONFIG).read_text(encoding='utf-8'))
    for binding in config['bindings'].values():
        if sha(local_path(ROOT,binding['path']))!=binding['sha256']:
            raise ValueError('Frozen sector diagnostic input changed')
    if config['scope']!='rejected_sector_model_diagnostics' or config['national_acceptance'] is not False:
        raise ValueError('Rejected sector diagnostic scope required')
    _,data=sector.history.load_frozen(local_path(ROOT,config['bindings']['manifest']['path']))
    trials=json.loads(local_path(ROOT,config['bindings']['trials']['path']).read_text(encoding='utf-8'))
    selected=sector.winners([r for r in trials if r['kind']=='sector_response'],data['experiment']['structural_alternatives'])
    if selected!=config['training_only_selections']:
        raise ValueError('Rejected sector diagnostic selection changed')
    out=local_path(ROOT,output_relative)
    if not out.is_relative_to((ROOT/'outputs/q2').resolve()) or out==(ROOT/'outputs/q2').resolve() or out.exists():
        raise ValueError('Use a fresh outputs/q2 child directory')
    out.mkdir(parents=True)
    dump(out/'attempt.json',dict(status='running',national_acceptance=False))
    try:
        accounts,metrics,quality,parts,comparisons=[],[],[],[],[]
        for name,trial in selected.items():
            model=sector.model_for_trial(data,trial)
            result=sector.history.EnergyModel(model).run()
            values=sector.history.metric_rows(result,data['definitions'])
            fit=sector.history.compare(data['observations'],values,data['experiment']['targets'],data['experiment']['windows'])
            loss,loss_parts=sector.history.loss(fit,data['experiment']['targets'])
            sector.require_close(loss,trial['loss'],'Rejected model training prefix')
            baseline=sector.history.baseline_comparisons(data['observations'],data['experiment']['targets'],data['experiment']['windows'])
            check=sector.history.historical_quality({'history_fit':fit,'baselines':baseline},data['experiment']['targets'],
                data['acceptance']['historical_quality'],data['experiment']['windows'])
            parent=data['initialization']['parent_training_winners'][name]
            for row in loss_parts:
                before=next(p for p in parent['parts'] if p['indicator']==row['indicator'])
                parts.append(dict(structure=name,**row,parent_weighted_loss=before['weighted_loss'],
                                  change_in_weighted_training_loss=row['weighted_loss']-before['weighted_loss']))
            accounts.extend(sector.sector_accounts(name,model,result,data['initialization']['sector_mappings']))
            metrics.extend(dict(structure=name,**r) for r in values)
            quality.extend(dict(structure=name,**r) for r in check['targets'])
            dump(out/(name+'.json'),dict(training_selection=trial,result=result,historical_quality=check,
                 selected_overall=False,national_acceptance=False))
            comparisons.append(dict(structure=name,training_loss=loss,parent_training_loss=parent['loss'],
                increase=loss-parent['loss'],parameters=trial['parameters'],
                failed_numeric_targets=[r['indicator'] for r in check['targets'] if not r['passed']],
                selected_overall=False))
        for name,rows in [('sector_accounts',accounts),('metrics',metrics),('quality',quality),('loss_decomposition',parts)]:
            csvout(out/(name+'.csv'),rows)
        dump(out/'summary.json',dict(scope=config['scope'],cases=6,comparisons=comparisons,sector_account_rows=len(accounts),
            all_losses_worse_than_parent=all(r['increase']>0 for r in comparisons),national_acceptance=False,
            interpretation='All six sector responses selected on training, including rejected ones. No switching to a lower holdout error model; useful services and true carbon boundary remain unresolved.'))
        code=[Path(__file__),ROOT/'scripts/run_q2_sector_candidate.py',ROOT/'scripts/build_q2_sector_candidate.py',
              ROOT/'scripts/run_q2_nonenergy_episode.py',ROOT/'scripts/build_q2_nonenergy_episode.py',
              ROOT/'scripts/run_q2_joint_deployment_comparison.py',ROOT/'scripts/run_q2_historical_candidate.py',
              ROOT/'scripts/run_q2_deployment_ablation.py',ROOT/'scripts/run_q2_solar_ablation.py',ROOT/'scripts/prepare_q2_apec_balance.py',
              *sorted((ROOT/'src/energy_model/q2').glob('*.py'))]
        dump(out/'run_manifest.json',dict(config_path=CONFIG,config_sha256=sha(ROOT/CONFIG),bindings=config['bindings'],
            code_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in code},
            outputs={p.name:sha(p) for p in sorted(out.iterdir()) if p.name!='attempt.json'},national_acceptance=False))
        dump(out/'attempt.json',dict(status='rejected_sector_diagnostics_executed',national_acceptance=False))
        print('Six rejected training-best sector paths;594sector fuel/cash accounts reconciled')
        return 0
    except Exception as exc:
        dump(out/'attempt.json',dict(status='failed',reason=str(exc),national_acceptance=False))
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True)
    raise SystemExit(execute(parser.parse_args().output_dir))
