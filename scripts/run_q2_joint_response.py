"""Frozen, training-only joint response fit; never grants national admission.

Retains the v10 selected opening queue and all original scientific boundaries.
Four continuous parameters replace sequential coarse-grid choices. Common
construction/connection envelopes are compared as hypotheses, not observations.
"""
import argparse
from copy import deepcopy
import json
from math import sqrt
from pathlib import Path

import numpy as np
from scipy.optimize import least_squares

import run_q2_historical_candidate as history
from energy_model.q2.io import csvout, dump, local_path, sha
from run_q2_deployment_ablation import technology_rows
from run_q2_solar_ablation import constraint_rows

ROOT = history.ROOT


def envelope_model(model, elasticity):
    """Use current GDP only; this is a hypothetical capacity index, not policy."""
    result = deepcopy(model)
    if elasticity is None:
        for policy in result['policies']:
            policy['deployment_limit_rules'] = {
                'construction': 'technology_frontiers', 'connection': 'technology_frontiers'}
        return result
    original = deepcopy(result['policies'])
    policies = []
    index = 1.0
    for year in range(result['start_year'], result['end_year'] + 1):
        if year > result['start_year']:
            index *= 1 + result['gdp_growth'][str(year)]
        visible = [p for p in original if max(p['known_year'], p['effective_year']) <= year]
        policy = deepcopy(max(visible, key=lambda p: (p['effective_year'], p['known_year'])))
        policy.pop('deployment_limit_rules', None)
        policy.update(id=f'research_GDP_envelope_{elasticity}_{year}',
                      known_year=year, effective_year=year)
        for key in ('construction_units_limit', 'connection_limit'):
            policy[key] *= index ** elasticity
        policies.append(policy)
    result['policies'] = policies
    return result


def freeze():
    parent = ROOT / 'workflow/q2_candidates/v10/manifest.json'
    _, data = history.load_frozen(parent)
    selection_path = ROOT / 'outputs/q2/historical_candidate_v10/training_selection.json'
    selected = json.loads(selection_path.read_text(encoding='utf-8'))['selected']
    parameters = deepcopy(data['experiment']['parameters'])
    for fuel in ('oil', 'gas'):
        parameters.append(dict(id=f'{fuel}_residual_elasticity', bounds=[0.0, 2.0],
            paths=[['demand_drivers', f'{fuel}_residual', 'gdp_elasticity']]))
    initial = dict(selected['parameters'], oil_residual_elasticity=0.5,
                   gas_residual_elasticity=2.0)
    config = dict(version=12, scope='historical_aggregate_candidate_not_admitted',
        national_acceptance=False, previous_holdout_already_seen=True,
        parent=dict(path=parent.relative_to(ROOT).as_posix(), sha256=sha(parent)),
        parent_selection=dict(path=selection_path.relative_to(ROOT).as_posix(), sha256=sha(selection_path)),
        opening_structure=selected['structure'], parameters=parameters, initial=initial,
        envelopes={'fixed_150GW': 0.0, 'GDP_proportional': 1.0,
                   'GDP_squared': 2.0, 'technology_frontiers': None},
        rules=['adaptive_margin', 'instant_margin'],
        optimizer=dict(method='trf', max_nfev=40, diff_step=1e-4,
                       ftol=1e-7, xtol=1e-7, gtol=1e-7),
        controls=['exact_v10_selected', 'no_investment'],
        selection='Minimum original weighted 2015-2021 loss, including exact controls; exact ties use execution order.',
        limitations=[
            'GDP-indexed common capacity is an explicit research hypothesis, not observed construction or grid capacity.',
            'Four jointly fitted parameters retain prior bounds; other inherited choices and latent PV opening queue remain fixed.',
            'Only one deterministic starting point per structure/rule; local optimizer is not a global optimum.',
            'All eight original targets, weights, scales and acceptance thresholds are unchanged.',
            'No current-state or national physical-accounting admission follows from numerical improvement.'])
    path = ROOT / 'workflow/q2_candidates/v12_joint_response.json'
    if path.exists():
        if json.loads(path.read_text(encoding='utf-8')) != config:
            raise ValueError('Frozen protocol differs; use another version')
    else:
        dump(path, config)
    return path


def training_residuals(model, data):
    config = deepcopy(model)
    config['end_year'] = 2021
    observations = [r for r in data['observations'] if 2015 <= r['year'] <= 2021]
    experiment = data['experiment']
    result = history.EnergyModel(config).run()
    rows = history.compare(observations, history.metric_rows(result, data['definitions']),
                           experiment['targets'], experiment['windows'])
    residuals = []
    for target in experiment['targets']:
        values = [r for r in rows if r['indicator'] == target['id'] and r['status'] == 'compared']
        if len(values) != 7:
            raise ValueError('All seven training years required for each original target')
        residuals.extend(r['normalized_residual'] * sqrt(target['weight'] / len(values)) for r in values)
    value, _ = history.loss(rows, experiment['targets'])
    if abs(sum(x*x for x in residuals) - value) > 1e-12:
        raise ValueError('Optimizer residuals differ from original scientific loss')
    return np.asarray(residuals)


def execute(config_relative, output_relative):
    path = local_path(ROOT, config_relative)
    protocol = json.loads(path.read_text(encoding='utf-8'))
    for key in ('parent', 'parent_selection'):
        binding = protocol[key]
        if sha(local_path(ROOT, binding['path'])) != binding['sha256']:
            raise ValueError('Frozen parent changed')
    _, data = history.load_frozen(local_path(ROOT, protocol['parent']['path']))
    selected_parent = json.loads(local_path(ROOT, protocol['parent_selection']['path']).read_text(encoding='utf-8'))['selected']
    parameters = protocol['parameters']
    base = data['structural_models'][protocol['opening_structure']]
    original = history.parameterize(history.rule_model(base, selected_parent['rule']),
                                   data['experiment']['parameters'], selected_parent['parameters'])
    out = local_path(ROOT, output_relative)
    if out.exists() or not out.is_relative_to((ROOT / 'outputs/q2').resolve()) or out == ROOT / 'outputs/q2':
        raise ValueError('Use a fresh outputs/q2 child directory')
    out.mkdir(parents=True)
    dump(out / 'attempt.json', dict(status='running', national_acceptance=False))
    trials, candidates, optimizers = [], [], []
    journal = out / 'training_trials.jsonl'

    def evaluate(model, description):
        try:
            residuals = training_residuals(model, data)
            trial = dict(trial=len(trials), **description, status='valid',
                         loss=float(residuals @ residuals))
        except Exception as exc:
            trial = dict(trial=len(trials), **description, status='failed',
                         reason=str(exc), exception=type(exc).__name__)
            with journal.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(trial, ensure_ascii=False) + '\n')
            trials.append(trial)
            raise
        trials.append(trial)
        with journal.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(trial, ensure_ascii=False) + '\n')
        return residuals, trial

    try:
        for name, model in [('exact_v10_selected', original),
                            ('no_investment', history.rule_model(original, 'no_investment'))]:
            _, trial = evaluate(model, dict(case=name, rule=name, parameters={}))
            candidates.append((trial, model))
        if abs(candidates[0][0]['loss'] - selected_parent['loss']) > 1e-12:
            raise ValueError('Exact original control failed reproduction')
        lower = np.array([p['bounds'][0] for p in parameters])
        upper = np.array([p['bounds'][1] for p in parameters])
        # Normalize all coordinates to [0,1] for finite differences and trust region.
        start = (np.array([protocol['initial'][p['id']] for p in parameters]) - lower) / (upper-lower)
        for name, exponent in protocol['envelopes'].items():
            for rule in protocol['rules']:
                model = history.rule_model(envelope_model(base, exponent), rule)
                candidate_models = []

                def objective(x):
                    values = dict(zip([p['id'] for p in parameters], (lower+x*(upper-lower)).tolist()))
                    current = history.parameterize(model, parameters, values)
                    residuals, trial = evaluate(current, dict(case=name, rule=rule, parameters=values))
                    candidate_models.append((trial, values))
                    return residuals

                result = least_squares(objective, start, bounds=(np.zeros(len(start)), np.ones(len(start))),
                                       **protocol['optimizer'])
                best, values = min(candidate_models, key=lambda pair: (pair[0]['loss'], pair[0]['trial']))
                candidates.append((best, history.parameterize(model, parameters, values)))
                record = dict(case=name, rule=rule, success=bool(result.success), status=int(result.status),
                              message=str(result.message), nfev=int(result.nfev),
                              actual_training_executions=len(candidate_models), best=best)
                optimizers.append(record)
                dump(out / 'optimizer_status.json', optimizers)
                print(json.dumps(record), flush=True)
        selected, model = min(candidates, key=lambda pair: (pair[0]['loss'], pair[0]['trial']))
        # Persist irreversible selection before opening the holdout path.
        dump(out / 'training_selection.json', dict(selected=selected,
            candidate_winners=[r for r, _ in candidates], selection_information=protocol['selection']))
        dump(out / 'selected_model.json', model)
        result = history.EnergyModel(model).run()
        metrics = history.metric_rows(result, data['definitions'])
        experiment = data['experiment']
        fit = history.compare(data['observations'], metrics, experiment['targets'], experiment['windows'])
        if abs(history.loss(fit, experiment['targets'])[0] - selected['loss']) > 1e-12:
            raise ValueError('Training prefix changed when evaluating holdout')
        baselines = history.baseline_comparisons(data['observations'], experiment['targets'], experiment['windows'])
        quality = history.historical_quality(dict(history_fit=fit, baselines=baselines),
            experiment['targets'], data['acceptance']['historical_quality'], experiment['windows'])
        dump(out / 'historical_quality.json', quality)
        dump(out / 'result.json', result)
        for name, rows in [('history_fit', fit), ('metrics', metrics), ('history_baselines', baselines),
                           ('constraint_usage', constraint_rows(model, result)),
                           ('technology_activity', technology_rows(model, result))]:
            csvout(out / (name + '.csv'), rows)
        history.write_figure(out, fit)
        summary = dict(status='diagnostic_executed', training_executions=len(trials),
            previous_cumulative_executions=5745, cumulative_executions=5745+len(trials),
            selected=selected, numeric_quality_passed=quality['passed'],
            failed_indicators=[r['indicator'] for r in quality['targets'] if not r['passed']],
            national_acceptance=False, previous_holdout_already_seen=True)
        dump(out / 'summary.json', summary)
        code = [Path(__file__), ROOT / 'scripts/run_q2_historical_candidate.py',
                ROOT / 'scripts/run_q2_deployment_ablation.py', ROOT / 'scripts/run_q2_solar_ablation.py',
                *sorted((ROOT / 'src/energy_model/q2').glob('*.py'))]
        dump(out / 'run_manifest.json', dict(protocol=dict(path=config_relative, sha256=sha(path)),
            code_hashes={p.relative_to(ROOT).as_posix(): sha(p) for p in code},
            outputs={p.name: sha(p) for p in sorted(out.iterdir()) if p.name != 'attempt.json'},
            national_acceptance=False))
        dump(out / 'attempt.json', summary)
        print(json.dumps(summary), flush=True)
        return 0
    except Exception as exc:
        dump(out / 'attempt.json', dict(status='failed', reason=str(exc), national_acceptance=False))
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--config', default='workflow/q2_candidates/v12_joint_response.json')
    parser.add_argument('--output-dir')
    args = parser.parse_args()
    if args.freeze:
        print(freeze())
    elif args.output_dir:
        raise SystemExit(execute(args.config, args.output_dir))
    else:
        parser.error('--freeze or --output-dir required')
