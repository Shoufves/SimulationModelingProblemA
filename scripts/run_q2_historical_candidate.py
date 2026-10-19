"""Execute frozen, nonadmitted real-data historical diagnostics, entirely offline.

Choose parameters AND the behavior rule on 2015-2021 only. Evaluate the selected
candidate on the already-seen 2022-2024 holdout once, without changing thresholds.
Every failed trial is retained. Even a numerically passing proxy is not admission.
"""
import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from copy import deepcopy
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from energy_model.q2.annual import EnergyModel
from energy_model.q2.experiments import baseline_comparisons, compare, loss, metric_rows, parameterize
from energy_model.q2.io import csvout, dump, local_path, sha
from energy_model.q2.operations import OperationError
from energy_model.q2.quality import historical_quality


def load_frozen(path):
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest['scope'] != 'historical_aggregate_candidate_not_admitted' or manifest['national_admission'] is not False:
        raise ValueError('This diagnostic runner cannot execute or grant national admission')
    for relative, expected in manifest['source_artifacts'].items():
        if sha(local_path(ROOT, relative)) != expected:
            raise ValueError('Frozen reference changed: ' + relative)
    data = {}
    for key, binding in manifest['inputs'].items():
        file = local_path(ROOT, binding['path'])
        if sha(file) != binding['sha256']:
            raise ValueError('Frozen candidate input changed: ' + key)
        data[key] = json.loads(file.read_text(encoding='utf-8'))
    if data['model']['scope'] != manifest['scope']:
        raise ValueError('Candidate model scope changed')
    return manifest, data


def rule_model(model, rule):
    config = deepcopy(model)
    if rule == 'instant_margin':
        config['behavior']['expectation_update'] = 1.
    elif rule == 'no_investment':
        config['mechanisms']['investment'] = False
    elif rule != 'adaptive_margin':
        raise ValueError('Unknown frozen behavior alternative')
    return config


def train_candidates(data):
    experiment = data['experiment']
    windows = experiment['windows']
    if windows != {'train': [2015, 2021], 'already_seen_holdout': [2022, 2024]}:
        raise ValueError('Historical windows changed')
    parameters = experiment['parameters']
    grid = list(product(*(p['grid'] for p in parameters)))
    if len(grid) > experiment['maximum_evaluations']:
        raise ValueError('Frozen training budget exceeded')
    observations = [o for o in data['observations'] if 2015 <= o['year'] <= 2021]
    trials = []
    structures = experiment.get('structural_alternatives', [None])
    if structures != [None] and (len(set(structures)) != len(structures) or
                                set(structures) != set(data.get('structural_models', {}))):
        raise ValueError('Frozen structural alternatives missing or duplicated')
    for structure, rule in product(structures, experiment['rule_alternatives']):
        for combination in grid:
            values = dict(zip([p['id'] for p in parameters], combination))
            source_model = data['model'] if structure is None else data['structural_models'][structure]
            config = parameterize(rule_model(source_model, rule), parameters, values)
            config['end_year'] = 2021
            trial = {'trial': len(trials), 'rule': rule, 'parameters': values}
            if structure is not None:
                trial['structure'] = structure
            try:
                result = EnergyModel(config).run()
                rows = compare(observations, metric_rows(result, data['definitions']), experiment['targets'], windows)
                value, parts = loss(rows, experiment['targets'])
                trial.update(status='valid', loss=value, parts=parts)
            except (OperationError, ValueError) as exc:
                trial.update(status='failed', loss=None, reason=str(exc), exception=type(exc).__name__)
            trials.append(trial)
        current = [r for r in trials if r['rule'] == rule and r.get('structure') == structure]
        valid = [r for r in current if r['status'] == 'valid']
        print(json.dumps({'rule': rule, **({'structure': structure} if structure is not None else {}),
                          'valid': len(valid), 'failed': len(current) - len(valid),
                          'best_training_loss': min((r['loss'] for r in valid), default=None)}), flush=True)
    return trials


def write_figure(out, fit):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams['svg.hashsalt'] = 'q2-real-historical-candidate-v1'
    names = list(dict.fromkeys(r['indicator'] for r in fit))
    figure, axes = plt.subplots(4, 2, figsize=(12, 12), constrained_layout=True)
    for identity, axis in zip(names, axes.flat):
        selected = sorted([r for r in fit if r['indicator'] == identity], key=lambda r: r['year'])
        axis.plot([r['year'] for r in selected], [r['value'] for r in selected], label='Observed target')
        axis.plot([r['year'] for r in selected], [r['simulated'] for r in selected], label='Reduced model proxy')
        axis.axvline(2021.5, color='gray', linestyle='--')
        axis.set_title(identity); axis.set_ylabel(selected[0]['unit']); axis.legend(fontsize=8)
    figure.suptitle('Real historical targets / nonadmitted aggregate candidate — no national forecast')
    figure.savefig(out / 'historical_fit.svg', metadata={'Date': None})
    figure.savefig(out / 'historical_fit.png', dpi=150)
    plt.close(figure)


def execute(manifest_path, output_path):
    started = time.perf_counter()
    manifest_file = local_path(ROOT, manifest_path)
    out = local_path(ROOT, output_path)
    if not out.is_relative_to((ROOT / 'outputs/q2').resolve()) or out == (ROOT / 'outputs/q2').resolve():
        raise ValueError('Diagnostic output must be a child of outputs/q2')
    if out.exists():
        raise ValueError('Use a new diagnostic directory; previous scientific evidence must remain intact')
    # Validate before creating a result directory. A bad fingerprint never
    # produces a successful-looking old or empty scientific output.
    manifest, data = load_frozen(manifest_file)
    out.mkdir(parents=True)
    dump(out / 'attempt.json', {'status': 'running', 'national_acceptance': False})
    try:
        trials = train_candidates(data)
        dump(out / 'training_trials.json', trials)
        valid = [t for t in trials if t['status'] == 'valid']
        if not valid:
            raise ValueError('All frozen real-data candidates failed; see training_trials.json')
        selected = min(valid, key=lambda t: (t['loss'], t['trial']))
        experiment = data['experiment']
        # The selected parameter vector and rule are immutable from here on.
        dump(out / 'training_selection.json', {'selected': selected,
             'equivalent_candidates': [t for t in valid if t['loss'] <= selected['loss'] + experiment['equivalent_loss_absolute_tolerance']],
             'selection_information': 'Only 2015-2021 target residuals; rules frozen before fitting'})
        source_model = (data['structural_models'][selected['structure']] if 'structure' in selected else data['model'])
        model = parameterize(rule_model(source_model, selected['rule']), experiment['parameters'], selected['parameters'])
        result = EnergyModel(model).run()
        simulated = metric_rows(result, data['definitions'])
        fit = compare(data['observations'], simulated, experiment['targets'], experiment['windows'])
        baselines = baseline_comparisons(data['observations'], experiment['targets'], experiment['windows'])
        quality = historical_quality({'history_fit': fit, 'baselines': baselines}, experiment['targets'],
                                     data['acceptance']['historical_quality'], experiment['windows'])
        quality['national_acceptance'] = False
        quality['interpretation'] = 'Numeric diagnostic only: unreviewed proxy equivalence and explicit structural gaps still prevent national acceptance.'
        dump(out / 'historical_quality.json', quality)
        csvout(out / 'history_fit.csv', fit)
        csvout(out / 'history_baselines.csv', baselines)
        csvout(out / 'annual_path.csv', result['annual'])
        csvout(out / 'metrics.csv', simulated)
        for name in ('assets', 'actions', 'cash', 'information'):
            csvout(out / (name + '.csv'), result[name])
        dump(out / 'projects.json', result['projects'])
        dump(out / 'operations.json', result['operations'])
        write_figure(out, fit)
        rule_summary = []
        for structure, rule in product(experiment.get('structural_alternatives', [None]), experiment['rule_alternatives']):
            candidates = [t for t in valid if t['rule'] == rule and t.get('structure') == structure]
            best = min(candidates, key=lambda t: (t['loss'], t['trial'])) if candidates else None
            rule_summary.append({'rule': rule, **({'structure': structure} if structure is not None else {}),
                                 'valid_trials': len(candidates),
                                 'best_training_loss': best['loss'] if best else None,
                                 'best_parameters': best['parameters'] if best else None})
        csvout(out / 'rule_comparison.csv', rule_summary)
        rows = '\n'.join(f"| {r['indicator']} | {r['holdout_mape']:.2%} | {r['rmse_ratio_to_persistence']:.3f} | {'通过' if r['passed'] else '未通过'} |"
                         for r in quality['targets'])
        failed = [r['indicator'] for r in quality['targets'] if not r['passed']]
        (out / 'report.md').write_text(
            f"# 全国历史聚合候选 v{manifest['version']}：实测目标诊断，未准入\n\n"
            '此结果使用真实 NBS/GCB 历史观测和明确研究假设。它不是合成目标恢复，也不是全国问题二验收通过。'
            '初态、统计桥接、残余消费服务、年龄/队列和历史政策仍有实质缺口，详见冻结的 assumptions.json。\n\n'
            f"实际执行 {len(trials)} 次训练候选，{len(valid)} 次成功。三个规则均先按2015—2021训练误差比较；"
            + (f"结构对照为 `{selected['structure']}`。设计本轮时已看过前序版本留出，属于探索性修正，不是新的盲测。"
               if 'structure' in selected else '') +
            f"选中 `{selected['rule']}` / `{selected['parameters']}`，训练损失 {selected['loss']:.6g}。"
            '随后固定规则与参数，运行2022—2024已接触留出；没有按留出改变阈值或再次选参。\n\n'
            '| 指标 | 留出MAPE | RMSE/持平基线 | 数值门槛 |\n|---|---:|---:|---|\n' + rows + '\n\n'
            f"未通过项：{', '.join(failed) if failed else '无数值失败，但语义与结构仍未准入'}。\n\n"
            '容量、总量与能源结构分别计算，不能用总量误差掩盖技术路径错误。参考价格、现存设备年龄和初始队列的简化'
            '属于待检验假设；训练/留出失败并不证明某项实际政策失效。'
            '本候选不输出2030/2060预测、不计算全国中和率；正式入口的六组准入缺口继续有效。\n\n'
            '![真实历史目标与聚合代理比较](historical_fit.svg)\n', encoding='utf-8')
        scientific = {p.name: sha(p) for p in sorted(out.iterdir()) if p.name != 'attempt.json'}
        code = [Path(__file__), ROOT / 'scripts/build_q2_historical_candidate.py',
                *sorted((ROOT / 'src/energy_model/q2').glob('*.py'))]
        if manifest['version'] >= 2:
            code.append(ROOT / 'scripts/build_q2_mapping_candidate.py')
        if manifest['version'] >= 3:
            code.append(ROOT / 'scripts/build_q2_capacity_candidate.py')
        if manifest['version'] >= 4:
            code.extend([ROOT / 'scripts/build_q2_queue_candidate.py', ROOT / 'scripts/prepare_q2_nuclear_queue.py'])
        if manifest['version'] >= 5:
            code.extend([ROOT / 'scripts/build_q2_fuel_candidate.py', ROOT / 'scripts/prepare_q2_national_balance.py'])
        if manifest['version'] >= 6:
            code.append(ROOT / 'scripts/build_q2_solar_candidate.py')
        if manifest['version'] >= 7:
            code.append(ROOT / 'scripts/build_q2_deployment_candidate.py')
        if manifest['version'] >= 8:
            code.append(ROOT / 'scripts/build_q2_permit_candidate.py')
        if manifest['version'] >= 9:
            code.append(ROOT / 'scripts/build_q2_joint_deployment_candidate.py')
        if manifest['version'] >= 10:
            code.append(ROOT / 'scripts/build_q2_pv_queue_candidate.py')
        import matplotlib.ft2font
        # A copied snapshot can reproduce scientific results without a.git
        # checkout. Do not borrow an ancestor repository's identity silently.
        git_root = subprocess.run(['git', 'rev-parse', '--show-toplevel'], cwd=ROOT,
                                  text=True, capture_output=True)
        own_checkout = git_root.returncode == 0 and Path(git_root.stdout.strip()).resolve() == ROOT.resolve()
        git_sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() if own_checkout else None
        git_dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True)) if own_checkout else None
        dump(out / 'run_manifest.json', {'owner': 'p2/yx', 'scope': manifest['scope'],
             'status': 'diagnostic_executed', 'numeric_quality_passed': quality['passed'], 'national_acceptance': False,
             'config_path': manifest_path, 'config_sha256': sha(manifest_file),
             'command': ['python', '-B', '-X', 'utf8', 'scripts/run_q2_historical_candidate.py',
                         '--manifest', manifest_path, '--output-dir', output_path],
             'seconds': time.perf_counter() - started,
             'git_sha': git_sha, 'git_dirty': git_dirty,
             'python': sys.version, 'platform': platform.platform(),
             'dependencies': {n: importlib.metadata.version(n) for n in ('mesa', 'numpy', 'scipy', 'matplotlib', 'pillow')},
             'freetype_version': matplotlib.ft2font.__freetype_version__,
             'code_hashes': {p.relative_to(ROOT).as_posix(): sha(p) for p in code}, 'scientific_outputs': scientific})
        dump(out / 'attempt.json', {'status': 'diagnostic_executed', 'numeric_quality_passed': quality['passed'],
                                   'national_acceptance': False})
        print(json.dumps({'status': 'diagnostic_executed', 'numeric_quality_passed': quality['passed'],
                          'failed_indicators': failed, 'national_acceptance': False}), flush=True)
        return 0
    except Exception as exc:
        dump(out / 'attempt.json', {'status': 'failed', 'exception': type(exc).__name__, 'reason': str(exc),
                                   'national_acceptance': False})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', default='workflow/q2_candidates/v1/manifest.json')
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    raise SystemExit(execute(args.manifest, args.output_dir))
