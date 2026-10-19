"""Compare deployment structures at their own training-selected rates and rule.

The v8 control retains its complete frozen trajectory. This is a comparison of
jointly fitted models, not a single-factor causal effect or national acceptance.
"""
import argparse
import json
from pathlib import Path

import run_q2_historical_candidate as history
from run_q2_deployment_ablation import technology_rows
from run_q2_solar_ablation import constraint_rows
from energy_model.q2.io import csvout, dump, local_path, sha

ROOT = history.ROOT


def training_winners(trials, structures):
    winners = {}
    for structure in structures:
        valid = [r for r in trials if r.get('structure') == structure and r['status'] == 'valid']
        if not valid:
            raise ValueError('No valid training candidate for ' + structure)
        winners[structure] = min(valid, key=lambda r: (r['loss'], r['trial']))
    return winners


def execute(output_relative, config_relative='workflow/q2_candidates/v9_comparison.json'):
    binding_path = local_path(ROOT, config_relative)
    binding = json.loads(binding_path.read_text(encoding='utf-8'))
    for item in binding['bindings'].values():
        if sha(local_path(ROOT, item['path'])) != item['sha256']:
            raise ValueError('Frozen comparison binding changed: ' + item['path'])
    def read(key):
        return json.loads(local_path(ROOT, binding['bindings'][key]['path']).read_text(encoding='utf-8'))
    _, data = history.load_frozen(local_path(ROOT, binding['bindings']['manifest']['path']))
    _, parent = history.load_frozen(local_path(ROOT, binding['bindings']['parent_manifest']['path']))
    selected = training_winners(read('training_trials'), data['experiment']['structural_alternatives'])
    prior = read('parent_selection')['selected']
    control_name = binding.get('control_name', 'v8_control')
    if control_name in selected:
        raise ValueError('Control name collides with a fitted structure')
    cases = {control_name: (parent, prior), **{name: (data, trial) for name, trial in selected.items()}}
    out = local_path(ROOT, output_relative)
    if not out.is_relative_to((ROOT / 'outputs/q2').resolve()) or out == (ROOT / 'outputs/q2').resolve() or out.exists():
        raise ValueError('Use a fresh outputs/q2 child directory')
    out.mkdir(parents=True)
    dump(out / 'attempt.json', dict(status='running', national_acceptance=False))
    try:
        metrics, quality, technology, constraints, losses = [], [], [], [], []
        for name, (inputs, trial) in cases.items():
            model = history.parameterize(history.rule_model(inputs['structural_models'][trial['structure']], trial['rule']),
                                         inputs['experiment']['parameters'], trial['parameters'])
            result = history.EnergyModel(model).run()
            values = history.metric_rows(result, inputs['definitions'])
            fit = history.compare(inputs['observations'], values, inputs['experiment']['targets'], inputs['experiment']['windows'])
            value, parts = history.loss(fit, inputs['experiment']['targets'])
            if abs(value - trial['loss']) > 1e-12:
                raise ValueError('Training-prefix replay differs from frozen trial')
            baselines = history.baseline_comparisons(inputs['observations'], inputs['experiment']['targets'], inputs['experiment']['windows'])
            check = history.historical_quality({'history_fit': fit, 'baselines': baselines}, inputs['experiment']['targets'],
                                              inputs['acceptance']['historical_quality'], inputs['experiment']['windows'])
            dump(out / (name + '.json'), dict(selection=trial, result=result, historical_quality=check))
            metrics.extend(dict(structure=name, **r) for r in values)
            quality.extend(dict(structure=name, **r) for r in check['targets'])
            losses.extend(dict(structure=name, **r) for r in parts)
            technology.extend(dict(structure=name, **r) for r in technology_rows(model, result))
            constraints.extend(dict(structure=name, **r) for r in constraint_rows(model, result))
        for name, rows in [('metrics', metrics), ('quality', quality), ('training_loss_parts', losses),
                           ('technology_activity', technology), ('constraint_usage', constraints)]:
            csvout(out / (name + '.csv'), rows)
        dump(out / 'summary.json', dict(scope=binding.get('scope', 'v9_joint_structure_rate_comparison'), cases=len(cases),
            selected_by_structure=selected, control=prior, national_acceptance=False,
            interpretation='Each structure uses its own 2015-2021 training-optimal rates and rule on the frozen grid. '
            'All holdout data were already seen. This separates inherited-rate confounding from structural comparison; '
            'it is neither a causal bottleneck estimate nor a global optimum.'))
        paths = [Path(__file__), ROOT / 'scripts/run_q2_historical_candidate.py', ROOT / 'scripts/run_q2_deployment_ablation.py',
                 ROOT / 'scripts/run_q2_solar_ablation.py', *sorted((ROOT / 'src/energy_model/q2').glob('*.py'))]
        dump(out / 'run_manifest.json', dict(status='comparison_executed', bindings=binding['bindings'],
            config_sha256=sha(binding_path), code_hashes={p.relative_to(ROOT).as_posix(): sha(p) for p in paths},
            outputs={p.name: sha(p) for p in sorted(out.iterdir()) if p.name != 'attempt.json'}, national_acceptance=False))
        dump(out / 'attempt.json', dict(status='comparison_executed', national_acceptance=False))
        print(f'{len(cases)} complete trajectories; each training prefix agrees with its frozen selected trial')
        return 0
    except Exception as exc:
        dump(out / 'attempt.json', dict(status='failed', reason=str(exc), national_acceptance=False))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--config', default='workflow/q2_candidates/v9_comparison.json')
    args = parser.parse_args()
    raise SystemExit(execute(args.output_dir, args.config))
