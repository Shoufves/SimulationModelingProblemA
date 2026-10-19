"""Training-only joint demand/deployment fit with explicit approval alternatives."""
import argparse
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

import run_q2_joint_response as joint
from energy_model.q2.io import csvout, dump, local_path, sha

ROOT = joint.ROOT
history = joint.history


def candidate_model(base, envelope, allocation, rule):
    model = history.rule_model(joint.envelope_model(base, envelope), rule)
    for policy in model['policies']:
        policy['approval_allocation'] = allocation
    return model


def freeze():
    old_path = ROOT / 'workflow/q2_candidates/v12_joint_response.json'
    old = json.loads(old_path.read_text(encoding='utf-8'))
    parameters = deepcopy(old['parameters'])
    parameters += [dict(id='coal_residual_intensity_improvement', bounds=[0., .03],
        paths=[['demand_drivers', 'coal_residual', 'annual_intensity_improvement']]),
        dict(id='electricity_elasticity', bounds=[.7, 1.3], paths=[
            ['demand_drivers', name, 'gdp_elasticity'] for name in ('industrial_electricity', 'other_electricity')])]
    selected = json.loads((ROOT / 'outputs/q2/historical_candidate_v12/training_selection.json').read_text(encoding='utf-8'))['selected']
    protocol = dict(version=13, scope='historical_aggregate_candidate_not_admitted',
        national_acceptance=False, previous_holdout_already_seen=True,
        bindings=[dict(path=p, sha256=sha(ROOT / p)) for p in (
            'workflow/q2_candidates/v12_joint_response.json',
            'workflow/q2_candidates/v10/manifest.json',
            'outputs/q2/historical_candidate_v12/selected_model.json',
            'outputs/q2/historical_candidate_v12/training_selection.json',
            'outputs/q2/historical_candidate_v12/result.json')],
        parameters=parameters,
        initial=dict(selected['parameters'], coal_residual_intensity_improvement=.01,
                     electricity_elasticity=.85),
        envelopes={'fixed_150GW': 0., 'GDP_proportional': 1., 'technology_frontiers': None},
        allocations=['benefit_priority', 'proportional_requests'],
        rules=['adaptive_margin', 'instant_margin'],
        optimizer=dict(method='trf', max_nfev=40, ftol=1e-7, xtol=1e-7, gtol=1e-7),
        normalized_jacobian_step=.0001, equivalent_training_loss_tolerance=.001,
        controls=['exact_v12_selected', 'no_investment'],
        selection='Minimum original weighted2015-2021 loss including exact control; ties use execution order. Persist selection before any holdout evaluation.',
        parameter_basis=[
            'The firstfour bounds, all eight target scales/weights and quality thresholds are unchanged.',
            'Electricity elasticity reuses the v1-v4 declared0.7-1.3 bound instead of fixing the previous minimum0.7.',
            'Coal residual statistical intensity0-3percent/year is a new explicit research range, not measured equipment efficiency. Training overprediction of coal,totalenergy andCO2 motivates testing it; all other fuel residual intensities stayzero.',
            'Proportional requests is an approval-order alternative allowed byfinal D3. It is not a claim about actual national allocation. Existing cash,queue,group and physical limits remain.',
            'Defaultbenefit allocation remains an exact control. No2024reset, data rescaling, added observed future capacity, changed carbon coefficient or relaxed acceptance.',
            'This is exploratory development after the holdout was already seen; no claim of fresh validation. One deterministic start per group does not establish a global optimum.'])
    path = ROOT / 'workflow/q2_candidates/v13_allocation.json'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != protocol:
            raise ValueError('Frozen v13 protocol differs')
    else:
        dump(path, protocol)
    return path


def bounded_jacobian(fun, x, step):
    """Fixed normalized one-sided steps, including coordinates near zero bounds."""
    centre = fun(x)
    columns = []
    for i in range(len(x)):
        shifted = x.copy()
        shifted[i] += step if x[i] + step <= 1. else -step
        columns.append((fun(shifted) - centre) / (shifted[i] - x[i]))
    return np.column_stack(columns)


def execute(config_relative, output_relative):
    config_path = local_path(ROOT, config_relative)
    protocol = json.loads(config_path.read_text(encoding='utf-8'))
    for b in protocol['bindings']:
        if sha(local_path(ROOT, b['path'])) != b['sha256']:
            raise ValueError('Frozen v13 input changed: ' + b['path'])
    _, data = history.load_frozen(ROOT / 'workflow/q2_candidates/v10/manifest.json')
    old_protocol = json.loads((ROOT / 'workflow/q2_candidates/v12_joint_response.json').read_text(encoding='utf-8'))
    base = data['structural_models'][old_protocol['opening_structure']]
    parent = json.loads((ROOT / 'outputs/q2/historical_candidate_v12/selected_model.json').read_text(encoding='utf-8'))
    expected = json.loads((ROOT / 'outputs/q2/historical_candidate_v12/training_selection.json').read_text(encoding='utf-8'))['selected']
    out = local_path(ROOT, output_relative)
    if out.exists() or not out.is_relative_to((ROOT / 'outputs/q2').resolve()) or out == ROOT / 'outputs/q2':
        raise ValueError('Use a fresh outputs/q2 child directory')
    out.mkdir(parents=True)
    dump(out / 'attempt.json', dict(status='running', national_acceptance=False))
    trials, candidates, optimizers = [], [], []
    params = protocol['parameters']
    lower = np.array([p['bounds'][0] for p in params])
    upper = np.array([p['bounds'][1] for p in params])
    initial = (np.array([protocol['initial'][p['id']] for p in params]) - lower) / (upper - lower)

    def evaluate(model, description):
        try:
            residuals = joint.training_residuals(model, data)
            trial = dict(trial=len(trials), **description, status='valid', loss=float(residuals @ residuals))
        except Exception as exc:
            trial = dict(trial=len(trials), **description, status='failed', reason=str(exc))
            with (out / 'training_trials.jsonl').open('a', encoding='utf-8') as f:
                f.write(json.dumps(trial) + '\n')
            trials.append(trial)
            raise
        trials.append(trial)
        with (out / 'training_trials.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(trial) + '\n')
        return residuals, trial

    try:
        original_result = history.EnergyModel(parent).run()
        retained_result = json.loads((ROOT / 'outputs/q2/historical_candidate_v12/result.json').read_text(encoding='utf-8'))
        if original_result != retained_result:
            raise ValueError('Default allocation changed the complete v12 ledger')
        dump(out / 'legacy_control.json', dict(full_v12_ledger_equal=True))
        for name, model in [('exact_v12_selected', parent), ('no_investment', history.rule_model(parent, 'no_investment'))]:
            _, trial = evaluate(model, dict(case=name, rule=name, parameters={}))
            candidates.append((trial, model))
        if abs(candidates[0][0]['loss'] - expected['loss']) > 1e-12:
            raise ValueError('V12 training control changed')
        for envelope, exponent in protocol['envelopes'].items():
            for allocation in protocol['allocations']:
                for rule in protocol['rules']:
                    label = envelope + '__' + allocation
                    model = candidate_model(base, exponent, allocation, rule)
                    executed, cache = [], {}

                    def objective(x):
                        # Avoid rerunning a point just to obtain the centre of its Jacobian.
                        key = tuple(x)
                        if key not in cache:
                            values = dict(zip([p['id'] for p in params], (lower + x * (upper - lower)).tolist()))
                            current = history.parameterize(model, params, values)
                            residuals, trial = evaluate(current, dict(case=label, rule=rule, parameters=values))
                            executed.append((trial, values))
                            cache[key] = residuals
                        return cache[key]

                    result = least_squares(objective, initial, bounds=(np.zeros(len(params)), np.ones(len(params))),
                        jac=lambda x: bounded_jacobian(objective, x, protocol['normalized_jacobian_step']),
                        **protocol['optimizer'])
                    best, values = min(executed, key=lambda pair: (pair[0]['loss'], pair[0]['trial']))
                    candidates.append((best, history.parameterize(model, params, values)))
                    record = dict(case=label, rule=rule, success=bool(result.success), status=int(result.status),
                        message=str(result.message), actual_executions=len(executed), best=best)
                    optimizers.append(record)
                    dump(out / 'optimizer_status.json', optimizers)
                    print(json.dumps(record), flush=True)
        selected, model = min(candidates, key=lambda pair: (pair[0]['loss'], pair[0]['trial']))
        dump(out / 'training_selection.json', dict(selected=selected,
            candidate_winners=[r for r, _ in candidates], selection_information=protocol['selection']))
        dump(out / 'selected_model.json', model)
        result = history.EnergyModel(model).run()
        metrics = history.metric_rows(result, data['definitions'])
        experiment = data['experiment']
        fit = history.compare(data['observations'], metrics, experiment['targets'], experiment['windows'])
        if abs(history.loss(fit, experiment['targets'])[0] - selected['loss']) > 1e-12:
            raise ValueError('Training prefix changed at holdout evaluation')
        baselines = history.baseline_comparisons(data['observations'], experiment['targets'], experiment['windows'])
        quality = history.historical_quality(dict(history_fit=fit, baselines=baselines), experiment['targets'],
            data['acceptance']['historical_quality'], experiment['windows'])
        dump(out / 'historical_quality.json', quality)
        dump(out / 'result.json', result)
        equivalent = []
        for trial, candidate in candidates:
            if trial['loss'] - selected['loss'] <= protocol['equivalent_training_loss_tolerance']:
                equivalent.append(dict(trial=trial, model=candidate))
        dump(out / 'equivalent_training_candidates.json', equivalent)
        for name, rows in [('history_fit', fit), ('metrics', metrics), ('history_baselines', baselines),
                          ('constraint_usage', joint.constraint_rows(model, result)),
                          ('technology_activity', joint.technology_rows(model, result))]:
            csvout(out / (name + '.csv'), rows)
        history.write_figure(out, fit)
        summary = dict(status='diagnostic_executed', selected=selected,
            training_executions=len(trials), previous_cumulative_executions=5995,
            cumulative_executions=5995 + len(trials), numeric_quality_passed=quality['passed'],
            failed_indicators=[r['indicator'] for r in quality['targets'] if not r['passed']],
            equivalent_candidate_count=len(equivalent), full_v12_ledger_equal=True,
            national_acceptance=False, previous_holdout_already_seen=True)
        dump(out / 'summary.json', summary)
        code = [Path(__file__), ROOT / 'scripts/run_q2_joint_response.py',
            ROOT / 'scripts/run_q2_historical_candidate.py', ROOT / 'scripts/run_q2_deployment_ablation.py',
            ROOT / 'scripts/run_q2_solar_ablation.py', *sorted((ROOT / 'src/energy_model/q2').glob('*.py'))]
        dump(out / 'run_manifest.json', dict(protocol=dict(path=config_relative, sha256=sha(config_path)),
            code_hashes={p.relative_to(ROOT).as_posix(): sha(p) for p in code},
            outputs={p.name: sha(p) for p in sorted(out.iterdir()) if p.name != 'attempt.json'}, national_acceptance=False))
        dump(out / 'attempt.json', summary)
        print(json.dumps(summary), flush=True)
        return 0
    except Exception as exc:
        dump(out / 'attempt.json', dict(status='failed', reason=str(exc), national_acceptance=False))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--config', default='workflow/q2_candidates/v13_allocation.json')
    parser.add_argument('--output-dir')
    args = parser.parse_args()
    if args.freeze:
        print(freeze())
    elif args.output_dir:
        raise SystemExit(execute(args.config, args.output_dir))
    else:
        parser.error('--freeze or --output-dir required')
