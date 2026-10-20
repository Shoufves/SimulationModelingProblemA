"""Verify fresh supplementary diagnostics; optionally execute all engineering gates."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

from audit_q1_q3_research import ROOT, BASE, read, dump, sha, unchanged_baseline

OUT = ROOT/'outputs/research_audit/verification'


def gate_input_hashes():
    files = {ROOT/'run.py'}
    for folder in ('src','scripts','tests'):
        files.update((ROOT/folder).rglob('*.py'))
    files.update(ROOT.glob('requirements*.txt'))
    files.update((ROOT/'workflow').glob('*.json'))
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted(files)}


def collect_checks(reused_test=None):
    """Run real commands, save evidence, then restore pre-run tracked gate outputs."""
    before = gate_input_hashes()
    if reused_test is not None and (not reused_test['passed'] or reused_test['input_hashes'] != before):
        raise ValueError('Test record does not match current gate inputs')
    tracked = subprocess.check_output(['git','ls-files','-z','outputs/validation','outputs/workflow'],cwd=ROOT)
    saved = {name.decode('utf-8'):(ROOT/name.decode('utf-8')).read_bytes() for name in tracked.split(b'\0') if name}
    jobs = [('tests',['run.py','test']),('audit',['run.py','audit']),
        ('formal_inputs',['scripts/workflow_status.py','--check-formal-inputs']),
        ('key_scan',['scripts/scan_google_keys.py'])]
    receipts = {}
    try:
        for label,args in jobs:
            if label=='tests' and reused_test is not None:
                receipts[label] = reused_test['command_record']
                continue
            command = [sys.executable,'-B','-X','utf8',*args]
            with (OUT/(label+'.log')).open('wb') as stream:
                completed = subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
            receipts[label] = dict(command=['python','-B','-X','utf8',*args],exit_code=completed.returncode,
                log_sha256=sha(OUT/(label+'.log')))
            if completed.returncode:
                raise ValueError('Engineering gate failed: '+label)
            if label=='tests':
                dump(OUT/'tests.json',read(ROOT/'outputs/validation/tests.json'))
            elif label=='audit':
                dump(OUT/'workspace_audit.json',read(ROOT/'outputs/validation/workspace_audit.json'))
            elif label=='formal_inputs':
                dump(OUT/'formal_inputs.json',read(ROOT/'outputs/workflow/status.json')['formal_input_check'])
            elif label=='key_scan':
                dump(OUT/'key_scan.json',read(OUT/'key_scan.log'))
        if before != gate_input_hashes():
            raise ValueError('Gate input changed during execution')
        dump(OUT/'gates.json',dict(passed=True,input_hashes=before,commands=receipts,
            summary_hashes={name:sha(OUT/name) for name in ('tests.json','workspace_audit.json','formal_inputs.json','key_scan.json')},
            execution_scope='Actual full tests and engineering gates; no fresh full Q2/Q3 simulation claimed'))
    except Exception as exc:
        dump(OUT/'gates.json',dict(passed=False,error=str(exc),commands=receipts))
        raise
    finally:
        for name,content in saved.items():
            (ROOT/name).write_bytes(content)


def check_manifest(path):
    manifest = read(path/'run_manifest.json')
    if not manifest['passed']:
        raise ValueError('Incomplete diagnostics: '+str(path))
    if set(manifest['outputs']) != {'q1_source_exposure.json','q3_effectiveness.json',
            'unchanged_baseline.json','text_metrics.json','evidence_checks.json'}:
        raise ValueError('Unexpected/missing diagnostic outputs')
    for field in ('code_hashes','input_hashes'):
        for name,expected in manifest[field].items():
            if sha(ROOT/name) != expected:
                raise ValueError('Stale diagnostic input: '+name)
    for name,expected in manifest['outputs'].items():
        if sha(path/name) != expected:
            raise ValueError('Changed diagnostic output: '+name)
    return manifest


def verify():
    primary = ROOT/'outputs/research_audit/q1_q3'
    second = ROOT/'outputs/research_audit/q1_q3_reproduction'
    first = check_manifest(primary);repeat = check_manifest(second)
    if first['code_hashes'] != repeat['code_hashes'] or first['input_hashes'] != repeat['input_hashes']:
        raise ValueError('Independent runs used different inputs')
    same = {name:first['outputs'][name]==repeat['outputs'][name] for name in first['outputs']}
    if not all(same.values()):
        raise ValueError('Independent diagnostic outputs differ')
    gates = read(OUT/'gates.json')
    if not gates['passed'] or gates['input_hashes'] != gate_input_hashes():
        raise ValueError('Missing or stale engineering gates')
    for name,expected in gates['summary_hashes'].items():
        if sha(OUT/name) != expected:
            raise ValueError('Engineering summary changed: '+name)
    for name,record in gates['commands'].items():
        if record['exit_code'] or sha(OUT/(name+'.log')) != record['log_sha256']:
            raise ValueError('Gate log mismatch: '+name)
    tests = read(OUT/'tests.json')
    if not tests['passed'] or tests['skipped'] or tests['errors'] or tests['failures']:
        raise ValueError('Tests did not pass without skips')
    if not read(OUT/'workspace_audit.json')['passed'] or not read(OUT/'formal_inputs.json')['passed']:
        raise ValueError('Audit or formal inputs failed')
    if not read(OUT/'key_scan.json')['working_tree']['passed']:
        raise ValueError('Key scan failed')
    protected = unchanged_baseline()
    references = read(ROOT/'docs/research/q1-q3-literature.json')['references']
    registered = {r['id'] for r in references}
    if len(registered)!=len(references) or any(not r.get('verification') or not r.get('read_scope') for r in references):
        raise ValueError('Unverified/duplicate bibliographic registration')
    import re
    for p in (ROOT/'docs/paper').glob('q[13]-*.md'):
        cited=set(re.findall(r'\bL\d{2}\b',p.read_text(encoding='utf-8')))
        if not cited<=registered:
            raise ValueError('Unregistered literature reference')
    docs = [*sorted((ROOT/'docs/research').glob('*')),*sorted((ROOT/'docs/paper').glob('q[13]-*.md')),
        ROOT/'README.md',ROOT/'docs/RUNNING.md']
    result = dict(technical_passed=True,status='technical_passed_human_review_pending',base=BASE,
        tests=tests['tests'],test_errors=tests['errors'],test_skips=tests['skipped'],
        identical_diagnostic_files=same,protected_scientific_files=len(protected),
        verified_numerical_claim_groups=len(read(primary/'evidence_checks.json')['claims']),
        literature_records=len(references),literature_check='Bibliographic/abstract review as individually scoped; not an exhaustive novelty certificate',
        diagnostics_manifest_sha256=sha(primary/'run_manifest.json'),
        reproduction_manifest_sha256=sha(second/'run_manifest.json'),gates_sha256=sha(OUT/'gates.json'),
        document_hashes={p.relative_to(ROOT).as_posix():sha(p) for p in docs if p.is_file()},
        formal_aigc_detector_percent=None,true_ai_authorship_percent=None,external_plagiarism_percent=None,
        human_validation='pending_actual_signatures',team_approved=False,
        novelty_conclusion='Application-level explanatory increments; no new algorithm or universal performance gain demonstrated',
        scope='Fresh supplementary analysis twice; original scientific code/inputs/outputs unchanged. Prior full Q1/Q2/Q3 reproduction evidence reused, not rerun here.')
    dump(OUT/'acceptance.json',result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-checks',action='store_true')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    dump(OUT/'acceptance.json',dict(technical_passed=False,status='running'))
    try:
        if args.run_checks:
            collect_checks()
        result=verify()
    except Exception as exc:
        result=dict(technical_passed=False,status='failed',error=type(exc).__name__+': '+str(exc))
        dump(OUT/'acceptance.json',result)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result['technical_passed'] else 1


if __name__=='__main__':
    raise SystemExit(main())
