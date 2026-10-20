"""Q3's frozen experiment design on the exact PR14 Q2 factory and parameters."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import time
from types import MethodType

from q3_pr14_runtime import ROOT, decode, build_snapshot, activate_forward, compare_reference
from run_q2_pr14 import verify_payload, load, sha, save
from q3_pr14.transition import TransitionModel, annual_metrics
from q3_pr14.events import run_event
import run_q3 as protocol

CONFIG = 'workflow/q3_pr14_inputs.json'


def preflight():
    review, _ = verify_payload()
    binding = load(ROOT/CONFIG)
    for path, digest in binding['inherited_files'].items():
        if sha(ROOT/path) != digest:
            raise ValueError('Changed inherited experiment/input: '+path)
    if binding['upstream_commit'] != review['upstream_commit']:
        raise ValueError('Different Q2 base')
    admission = load(ROOT/binding['review'])
    if sha(ROOT/binding['review']) != binding['review_sha256'] or admission['team_approved']:
        raise ValueError('Changed review or unsupported team approval')
    if set(admission['allowed_uses']) != {'q1_classification_handoff', 'q3_same_model_scenarios', 'h01', 'h02', 'bounded_policy_search'}:
        raise ValueError('Missing scoped input use review')
    config = load(ROOT/'workflow/q3_inputs.json')
    config.update(experiment_version='q3-pr14-aligned-v1', model_base=binding['upstream_commit'])
    return config


def make_model(config, spec):
    record = decode(load(ROOT/'data/processed/q2_delivery/parsed_inputs.json')['net58/25'])
    model, _, _ = build_snapshot(record, 25, {})
    s0 = next(s for s in load(ROOT/'data/processed/q2_delivery/q2_design.json')['scenarios'] if s['name']=='S0')
    activate_forward(model, record['config'], s0, end_year=spec.get('end_year',2060))
    model.__class__ = TransitionModel
    model.configure(config, scenario=spec.get('scenario','S0'), h01=spec.get('h01'),
                    policy=spec.get('policy',()), cost_multiplier=spec.get('cost_multiplier',1),
                    fixed_pipeline=spec.get('fixed_pipeline',False))
    # Mesa stores the bound user step during construction; changing the class
    # alone would silently omit every Q3 policy/retirement decision.
    model._user_step = MethodType(TransitionModel.step, model)
    return model


def calculate_annual(payload):
    config, _, _, _, spec = payload
    model = make_model(config, spec).run(spec.get('end_year',2060))
    return dict(spec=spec, metrics=annual_metrics(model), ledger=protocol.ledger(model), snapshots=model.snapshots)


def baseline_check(paths, config):
    expected = load(ROOT/'data/processed/q2_delivery/reference_paths/S0.json')['paths']
    # Only explicitly named extension bookkeeping may be omitted. Missing or
    # unexpected Q2 fields fail, including nonnumeric fields and every year.
    additions = {'q3_public_commitment_cny','q3_public_budget_cny','q3_extra_resource_cost_cny',
                 'q3_early_retired_mw','q3_managed_natural_retired_mw'}
    actual = [{k:v for k,v in r.items() if k not in additions} for r in paths]
    report = compare_reference(actual, expected)
    if not report['passed']:
        raise ValueError('PR14 baseline regression: '+str(report['failures'][:5]))
    return report


def report(out, summary, comparisons, h02, tradeoffs, diagnostic):
    # Retain the familiar result tables, then replace legacy provenance and
    # conclusions that are no longer assertions about this model version.
    original_report(out, summary, comparisons, h02, tradeoffs, diagnostic)
    path = out/'report.md'
    text = path.read_text('utf-8').replace(protocol.BASE, '1b8f465783afe7505c8d4e65ec43ada18c311daf')
    text = text.replace('run.py q3 --config workflow/q3_inputs.json --output-dir outputs/q3/p3_yx',
                        'scripts/run_q3_pr14.py --output-dir outputs/q3_pr14/reproduction')
    text = text.replace('Issue12', 'PR14 aligned')
    intro = ('本版由PR14观测尺度2024初态、同一校准参数及同一年度运行模型出发；S0逐字段通过问题2参考路径比较。'
             '不重新训练历史，不将2022—2024已接触评估称为盲测。旧Q3结果保留在outputs/q3/p3_yx，仅属于旧模型。\n\n'
             '年度资源费保留未折现口径供旧Q3筛选，另见年度路径可按Q2折现率换算；事件资源费为12天范围，不能相加。'
             '非能源煤、油、气原料分别作为服务；电池与抽蓄各自连续结转SOC及终值。'
             'S0已有缺供时仍使用原5%/15%硬门槛，不用相对改善替代可行性。\n\n')
    path.write_text(intro+text, 'utf-8')


original_report = protocol.report
protocol.calculate_annual = calculate_annual
protocol.baseline_check = baseline_check
protocol.run_event = run_event
protocol.report = report


def hashes():
    paths = [ROOT/CONFIG, ROOT/'scripts/run_q3_pr14.py', ROOT/'scripts/q3_pr14_runtime.py', ROOT/'scripts/run_q3.py']
    paths += sorted((ROOT/'src/q3_pr14').glob('*.py'))
    binding = load(ROOT/CONFIG)
    paths += [ROOT/binding['review']]
    review, _ = verify_payload()
    paths += [ROOT/r['path'] for r in review['files']]
    paths += [ROOT/p for p in binding['inherited_files']]
    return {p.relative_to(ROOT).as_posix():sha(p) for p in paths}


def verify_latest(folder):
    folder = Path(folder).resolve()
    latest = load(folder/'latest.json')
    attempt = (folder/latest['attempt']).resolve()
    if latest['status'] != 'passed' or not attempt.is_relative_to(folder/'attempts'):
        raise ValueError('Latest Q3 attempt is not a valid success')
    manifest = load(attempt/'manifest.json')
    if sha(attempt/'manifest.json') != latest['manifest_sha256'] or manifest['status'] != 'passed':
        raise ValueError('Changed Q3 receipt')
    preflight()
    if manifest['input_hashes'] != hashes():
        raise ValueError('Q3 input or code changed')
    for name,digest in manifest['outputs'].items():
        path = (attempt/name).resolve()
        if not path.is_relative_to(attempt) or sha(path) != digest:
            raise ValueError('Changed output '+name)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',default='outputs/q3_pr14/current')
    parser.add_argument('--smoke',action='store_true')
    args = parser.parse_args(argv)
    folder = (ROOT/args.output_dir).resolve()
    if not any(folder.is_relative_to(ROOT/p) and folder != ROOT/p for p in ('outputs/q3_pr14','tmp/q3_pr14')):
        parser.error('Output must be a subdirectory of outputs/q3_pr14 or tmp/q3_pr14')
    folder.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out = folder/'attempts'/run_id
    out.mkdir(parents=True)
    latest = dict(status='running',attempt=out.relative_to(folder).as_posix())
    save(folder/'latest.json', latest)
    started=time.perf_counter()
    manifest=dict(status='running',smoke=args.smoke,team_approved=False,raw_originals_reverified=False)
    try:
        config=preflight()
        manifest.update(input_hashes=hashes(),dependencies={k:importlib.metadata.version(k) for k in ('numpy','scipy','mesa','matplotlib')})
        save(out/'frozen_config.json',config)
        if args.smoke:
            result=calculate_annual((config,None,None,None,dict(id='S0')))
            save(out/'baseline_regression.json',baseline_check(result['ledger']['paths'],config))
            save(out/'S0_metrics.json',result['metrics'])
            save(out/'S0_paths.json',result['ledger']['paths'])
            for scenario in ('S0','SG','SW','SGW'):
                event=run_event(result['snapshots'][2030],config,scenario)
                save(out/(scenario+'_event.json'),event)
            manifest['status']='passed_smoke'
        else:
            manifest['coverage']=protocol.run(config,None,None,None,out)
            manifest['status']='passed'
    except Exception as exc:
        manifest.update(status='failed',error_type=type(exc).__name__,error=str(exc))
        import traceback
        traceback.print_exc()
    finally:
        manifest['elapsed_seconds']=time.perf_counter()-started
        manifest['outputs']={p.name:sha(p) for p in sorted(out.iterdir()) if p.name!='manifest.json'}
        save(out/'manifest.json',manifest)
        latest.update(status=manifest['status'],manifest_sha256=sha(out/'manifest.json'))
        save(folder/'latest.json',latest)
    print(json.dumps(dict(status=manifest['status'],seconds=manifest['elapsed_seconds'],output=str(out)),ensure_ascii=False),flush=True)
    return 0 if manifest['status'].startswith('passed') else 1


if __name__=='__main__':
    raise SystemExit(main())
