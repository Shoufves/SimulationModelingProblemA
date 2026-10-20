"""Verify Q2 integration without rewriting historical Q1/Q3/N2 receipts."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from run_q2_pr14 import load, save, sha, within, verify_payload, stage_runtime, verify_latest

BASE = 'dba50210dcf0636e9b54e4137077ae710070eb2e'
OUT = ROOT/'outputs/q2_pr14_review'


def run_check(name, arguments, cwd=ROOT, env=None):
    start = time.perf_counter()
    with (OUT/(name+'.log')).open('w', encoding='utf-8') as log:
        result = subprocess.run([sys.executable, '-B', '-X', 'utf8', *arguments],
                                cwd=cwd, stdout=log, stderr=subprocess.STDOUT, env=env)
    record = dict(passed=result.returncode==0, exit_code=result.returncode, seconds=time.perf_counter()-start,
                  command=arguments, log=name+'.log')
    print(name, record['passed'], flush=True)
    return record


def protected_files():
    # Compare all old scientific/data/evidence bytes. Do not read restricted
    # data, even for hashes. Only the named navigation/entry edits are allowed.
    allowed = {'.gitattributes', 'run.py', 'README.md', 'WORKFLOW.md', 'docs/RUNNING.md',
               'docs/DATA_GUIDE.md', 'docs/IMPLEMENTATION_ROADMAP.md', 'docs/ROUND_LOG.md',
               '.gitignore', 'data/catalog/datasets_unified.csv'}
    rows = subprocess.check_output(['git','ls-tree','-rzl',BASE], cwd=ROOT).split(b'\0')
    errors=[]; checked=0; protected={}; restricted=[]
    for item in rows:
        if not item:continue
        meta, rawpath=item.split(b'\t',1)
        _, kind, oid, size=meta.decode().split()
        path=rawpath.decode('utf-8')
        if kind!='blob' or path in allowed:continue
        current=ROOT/path
        if path.startswith('data/restricted/'):
            restricted.append(dict(path=path, size_unchanged=current.is_file() and current.stat().st_size==int(size), content_read=False))
            if not restricted[-1]['size_unchanged']:errors.append(path)
            continue
        if not current.is_file():errors.append(path);continue
        content=current.read_bytes()
        actual=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
        checked+=1
        if actual!=oid:errors.append(path)
        if path.startswith(('src/','scripts/','workflow/')):protected[path]=oid
    record=dict(passed=not errors, base=BASE, checked_files=checked, mismatches=errors,
                allowed_navigation_and_q2_entry_edits=sorted(allowed),
                restricted_metadata_only=restricted, unchanged_code_and_config_blobs=protected)
    save(OUT/'preservation.json',record)
    return dict(passed=record['passed'], checked_files=checked, mismatches=errors)


def q3_paths():
    from run_q3 import preflight, TransitionModel, baseline_check
    c,data,design,theta,_=preflight(ROOT/'workflow/q3_inputs.json')
    with (ROOT/'outputs/q3/p3_yx/scenario_paths.csv').open(encoding='utf-8',newline='') as stream:
        old=list(csv.DictReader(stream))
    failures=[]; cases=[]; fields=0
    for scenario in ('S0','SP','ST'):
        model=TransitionModel(data,design,theta,c,scenario=scenario).run(2060)
        expected=[r for r in old if r['scenario']==scenario]
        if len(model.paths)!=len(expected):raise ValueError('Q3 path length changed')
        max_error=0.
        for actual,ref in zip(model.paths,expected):
            if set(actual)!=(set(ref)-{'scenario'}):raise ValueError('Q3 path fields changed')
            for key,value in actual.items():
                if isinstance(value,(int,float)):
                    previous=float(ref[key]);delta=abs(value-previous)
                    tol=(c['acceptance']['cash_absolute_tolerance_cny'] if 'residual' in key and 'cny' in key else
                         c['acceptance']['absolute_numeric_tolerance']+c['acceptance']['relative_numeric_tolerance']*max(1,abs(value),abs(previous)))
                    fields+=1;max_error=max(max_error,delta)
                    if delta>tol:failures.append(dict(scenario=scenario,year=actual['year'],field=key,difference=delta,tolerance=tol))
                elif str(value)!=ref[key]:failures.append(dict(scenario=scenario,field=key))
        cases.append(dict(scenario=scenario,years=len(model.paths),max_absolute_difference=max_error))
        if scenario=='S0':baseline_check(model.paths,c)
    result=dict(passed=not failures,cases=cases,numeric_fields=fields,failures=failures,
                statement='Recomputed full 2025-2060 S0/SP/ST with the unchanged accepted Q3 model; H01/H02/policy full batches were not rerun.')
    save(OUT/'q3_path_regression.json',result)
    return result


def accept_results():
    checks=load(OUT/'checks.json')
    receipt=verify_latest(ROOT/'outputs/q2_pr14/integrated')
    preservation=protected_files()
    tests=load(OUT/'tests.json')
    n2=load(OUT/'n2_research_tests.json')
    q3=load(OUT/'q3_path_regression.json')
    latest=load(ROOT/'outputs/q2_pr14/integrated/latest.json')
    attempt=ROOT/'outputs/q2_pr14/integrated'/latest['attempt']
    verification=load(attempt/'verification.json')
    differences=[d for r in verification['results'] for d in r['reference_comparison']['differences']]
    passed=(checks['passed'] and preservation['passed'] and tests['passed'] and n2['passed'] and q3['passed']
            and receipt['full_q2_delivery'] and len(receipt['cases'])==24)
    clean=load(OUT/'clean_delivery.json') if (OUT/'clean_delivery.json').exists() else None
    if clean is not None:
        passed=passed and clean['passed'] and clean['input_hashes']==receipt['input_hashes']
    result=dict(passed=bool(passed),upstream_commit=receipt['upstream_commit'],base=BASE,
        q2_cases=len(receipt['cases']),q2_numeric_fields=sum(r['reference_comparison']['numeric_fields'] for r in verification['results']),
        q2_max_reference_difference=max((d['absolute_difference'] for d in differences),default=0),
        q2_reference_comparison='Unchanged upstream per-field tolerances; see each difference and bound',
        repository_tests=tests['tests'],n2_tests=n2['tests'],upstream_runner_tests_log='upstream_runner_tests.log',
        q3_path_regression=q3,protected_old_files=preservation['checked_files'],
        clean_directory_reproduction=(None if clean is None else dict(passed=clean['passed'],cases=clean['cases'],
            no_git_directory=clean['no_git_directory'],pythonhashseed=clean['pythonhashseed'])),
        historical_training_rerun=False,raw_originals_reverified=False,
        q1_recomputed=False,full_q3_experiment_batch_rerun=False,n2_77_paths_rerun=False,
        scientific_thresholds_all_passed=False,team_approval_granted=False,
        evidence_hashes={p.name:sha(p) for p in OUT.iterdir() if p.is_file() and p.name!='acceptance.json'},
        q2_receipt_sha256=sha(attempt/'integration.json'),checker_sha256=sha(Path(__file__)))
    save(OUT/'acceptance.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('evidence_hashes','q3_path_regression')},ensure_ascii=False,indent=2))
    return int(not passed)


def main():
    p=argparse.ArgumentParser();p.add_argument('--q3-only',action='store_true')
    p.add_argument('--verify-results',action='store_true');args=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    if args.verify_results:return accept_results()
    if args.q3_only:
        result=q3_paths();print(json.dumps(result,ensure_ascii=False));return int(not result['passed'])
    # These shared tools overwrite their own current receipts; preserve the old
    # tracked evidence and place this task's new receipts under its own folder.
    saved={}
    for folder in ('outputs/validation','outputs/workflow'):
        for path in (ROOT/folder).rglob('*'):
            if path.is_file():saved[path]=path.read_bytes()
    checks={}
    stage=None
    try:
        checks['tests']=run_check('tests',['run.py','test'])
        shutil.copyfile(ROOT/'outputs/validation/tests.json',OUT/'tests.json')
        checks['audit']=run_check('audit',['run.py','audit'])
        shutil.copyfile(ROOT/'outputs/validation/workspace_audit.json',OUT/'workspace_audit.json')
        checks['formal_inputs']=run_check('formal_inputs',['scripts/workflow_status.py','--check-formal-inputs'])
        checks['key_scan']=run_check('key_scan',['scripts/scan_google_keys.py'])
        checks['q3_paths']=run_check('q3_paths',['scripts/check_q2_pr14_integration.py','--q3-only'])
        # N2 remains a separately pinned scientific dependency, with its own
        # unchanged 22-test suite and preservation checks.
        checks['n2']=run_check('n2',['scripts/check_n2_implementation.py','--output','tmp/q2_integration/n2_check'])
        for name in ('research_tests.json','research_tests.log'):
            source=ROOT/'tmp/q2_integration/n2_check'/name
            if source.exists():shutil.copyfile(source,OUT/('n2_'+name))
        review,_=verify_payload()
        stage=stage_runtime(ROOT/'tmp/q2_pr14'/('tests_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')),review)
        (stage/'tmp').mkdir(exist_ok=True)
        checks['upstream_runner_tests']=run_check('upstream_runner_tests',
            ['-m','unittest','discover','-s',str(stage/'tests'),'-p','test_q2_delivery_runners.py'],cwd=stage)
    finally:
        for path,content in saved.items():path.write_bytes(content)
        if stage is not None and stage.exists():shutil.rmtree(within(stage,ROOT/'tmp/q2_pr14'))
    checks['preservation']=protected_files()
    save(OUT/'checks.json',dict(passed=all(r['passed'] for r in checks.values()),checks=checks,
                              q2_24_cases_receipt='See outputs/q2_pr14/integrated/latest.json'))
    if not all(r['passed'] for r in checks.values()):return 1
    return accept_results()


if __name__=='__main__':raise SystemExit(main())
