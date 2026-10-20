"""Run the unchanged PR14 Q2 delivery in an isolated, hash-verified process.

Only orchestration is new. This entry reruns 24 cases from PR14's extracted
inputs; it neither retrains history nor claims to revalidate the original PDFs.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = '1b8f465783afe7505c8d4e65ec43ada18c311daf'
REVIEW = 'data/catalog/q2_pr14_integration_review.json'
CONFIG = 'workflow/q2_pr14_integration.json'
OWNER = 'q2_pr14_integration_v1'


def load(path):
    return json.loads(Path(path).read_text('utf-8'))


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name+'.writing')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', 'utf-8')
    temporary.replace(path)


def within(path, parent):
    path, parent = Path(path).resolve(), Path(parent).resolve()
    if not path.is_relative_to(parent):
        raise ValueError('Path outside allowed directory: '+str(path))
    return path


def output_folder(value):
    path = (ROOT/value).resolve()
    allowed = (ROOT/'outputs/q2_pr14', ROOT/'tmp/q2_integration')
    if not any(path.is_relative_to(p.resolve()) and path != p.resolve() for p in allowed):
        raise ValueError('Output must be a subdirectory of outputs/q2_pr14 or tmp/q2_integration')
    if path.exists() and any(path.iterdir()):
        marker = path/'owner.json'
        if not marker.is_file() or load(marker) != {'owner': OWNER}:
            raise ValueError('Refusing to write an unowned output directory')
    path.mkdir(parents=True, exist_ok=True)
    save(path/'owner.json', {'owner': OWNER})
    return path


def verify_payload():
    config = load(ROOT/CONFIG)
    if config['upstream_commit'] != UPSTREAM or config['review_sha256'] != sha(ROOT/REVIEW):
        raise ValueError('Changed integration review or upstream commit')
    review = load(ROOT/REVIEW)
    if review['upstream_commit'] != UPSTREAM or review['scientific_code_modified'] or review['raw_originals_reverified']:
        raise ValueError('Unsupported source/evidence claim')
    names = set()
    for row in review['files']:
        path = within(ROOT/row['path'], ROOT)
        if row['path'] in names or path.is_relative_to(ROOT/'data/restricted'):
            raise ValueError('Duplicate or forbidden payload path')
        names.add(row['path'])
        if sha(path) != row['sha256']:
            raise ValueError('Changed imported PR14 file: '+row['path'])
        if row['role'] == 'runtime' and row['path'] != 'vendor/q2_pr14/'+row['upstream_path']:
            raise ValueError('Unexpected runtime relocation')
    manifest = load(ROOT/'data/processed/q2_delivery/manifest.json')
    mapped = {r['upstream_path']: r for r in review['files']}
    for path, digest in manifest['code_sha256'].items():
        if path not in mapped or mapped[path]['sha256'] != digest or mapped[path]['role'] != 'runtime':
            raise ValueError('PR14 model code is not fully preserved: '+path)
    cases = [s['name'] for s in load(ROOT/'data/processed/q2_delivery/q2_design.json')['scenarios']]
    if len(cases) != 24 or len(set(cases)) != 24 or cases != config['cases']:
        raise ValueError('Question 2 case set changed')
    return review, cases


def stage_runtime(destination, review):
    """Ordinary copies, never hard links or imports into Q1/Q3's interpreter."""
    destination = within(destination, ROOT/'tmp/q2_pr14')
    destination.mkdir(parents=True, exist_ok=False)
    for row in review['files']:
        rel = row['upstream_path']
        if row['role'] != 'runtime' and not rel.startswith('data/processed/q2_delivery/'):
            continue
        target = within(destination/rel, destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT/row['path'], target)
        if sha(target) != row['sha256']:
            raise ValueError('Runtime copy mismatch: '+rel)
    return destination


def current_hashes(review):
    result = {r['path']: sha(ROOT/r['path']) for r in review['files']}
    for path in (REVIEW, CONFIG, 'run.py', 'scripts/run_q2_pr14.py'):
        result[path] = sha(ROOT/path)
    return result


def verify_latest(folder):
    """A later failure invalidates earlier successes; check inputs and outputs."""
    folder = Path(folder).resolve()
    latest = load(folder/'latest.json')
    if latest['status'] != 'passed':
        raise ValueError('Latest Q2 attempt did not pass')
    attempt = within(folder/latest['attempt'], folder/'attempts')
    receipt = load(attempt/'integration.json')
    if receipt['status'] != 'passed' or sha(attempt/'integration.json') != latest['receipt_sha256']:
        raise ValueError('Changed or unsuccessful run receipt')
    review, _ = verify_payload()
    if receipt['input_hashes'] != current_hashes(review):
        raise ValueError('Code or inputs changed since the run')
    for name, digest in receipt['result_hashes'].items():
        if sha(within(attempt/name, attempt)) != digest:
            raise ValueError('Changed run result: '+name)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default='outputs/q2_pr14/integrated')
    parser.add_argument('--only', nargs='+')
    parser.add_argument('--end-year', type=int, default=2060)
    args = parser.parse_args(argv)
    # Own the new attempt before input checks: a bad new request cannot leave a
    # previous success looking like the result of that request.
    folder = output_folder(args.output_dir)
    attempt_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    attempt = within(folder/'attempts'/attempt_id, folder)
    attempt.mkdir(parents=True)
    latest = dict(status='running', attempt='attempts/'+attempt_id)
    save(folder/'latest.json', latest)
    receipt = dict(status='running', upstream_commit=UPSTREAM, end_year=args.end_year,
                   raw_originals_reverified=False, historical_training_rerun=False,
                   scientific_thresholds_all_passed=False, team_approval_granted=False)
    save(attempt/'integration.json', receipt)
    stage = None
    try:
        if not 2025 <= args.end_year <= 2060:
            raise ValueError('--end-year must be within 2025..2060')
        review, cases = verify_payload()
        selected = cases if args.only is None else args.only
        if len(set(selected)) != len(selected) or not selected or set(selected)-set(cases):
            raise ValueError('Unknown, duplicate or empty Q2 cases')
        receipt.update(cases=selected, full_q2_delivery=set(selected)==set(cases) and args.end_year==2060,
                       input_hashes=current_hashes(review))
        parent = ROOT/'tmp/q2_pr14'
        parent.mkdir(parents=True, exist_ok=True)
        stage = stage_runtime(parent/attempt_id, review)
        command = [sys.executable, '-I', '-B', '-X', 'utf8', str(stage/'scripts/run_q2_portable.py'),
                   '--verify-reference', '--end-year', str(args.end_year), '--only', *selected]
        environment = dict(os.environ)
        for key in ('PYTHONPATH', 'PYTHONHOME'):
            environment.pop(key, None)
        with (attempt/'execution.log').open('w', encoding='utf-8') as log:
            process = subprocess.Popen(command, cwd=stage, env=environment, stdout=subprocess.PIPE,
                                       stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace')
            for line in process.stdout:
                log.write(line); log.flush(); print(line, end='', flush=True)
            code = process.wait()
        receipt['process_exit_code'] = code
        outputs = list((stage/'outputs/q2_portable').glob('*'))
        if len(outputs) == 1:
            for path in outputs[0].iterdir():
                if path.is_file():
                    shutil.copyfile(path, attempt/path.name)
        if code != 0:
            raise RuntimeError('PR14 runner failed; see execution.log and verification.json')
        verified = load(attempt/'verification.json')
        if (verified['status'] != 'passed' or verified['cases'] != len(selected)
                or {r['name'] for r in verified['results']} != set(selected)
                or not all(r['reference_comparison']['passed'] for r in verified['results'])):
            raise ValueError('Incomplete or failed upstream verification')
        for name in selected:
            case = load(attempt/(name+'.json'))
            if [r['year'] for r in case['paths']] != list(range(2025, args.end_year+1)):
                raise ValueError('Missing or duplicate annual path: '+name)
        # Recheck immutable source after execution as well as before it.
        verify_payload()
        if current_hashes(review) != receipt['input_hashes']:
            raise ValueError('Inputs changed during execution')
        receipt.update(status='passed', evidence_mode=load(ROOT/'data/processed/q2_delivery/manifest.json')['mode'],
                       result_hashes={p.name: sha(p) for p in attempt.iterdir() if p.is_file() and p.name != 'integration.json'})
        save(attempt/'integration.json', receipt)
        save(folder/'latest.json', dict(latest, status='passed', receipt_sha256=sha(attempt/'integration.json')))
        print('Q2 PR14 integration passed:', attempt.relative_to(ROOT), flush=True)
        return 0
    except Exception as exc:
        receipt.update(status='failed', error=str(exc))
        save(attempt/'integration.json', receipt)
        save(folder/'latest.json', dict(latest, status='failed', receipt_sha256=sha(attempt/'integration.json')))
        print('Q2 PR14 integration failed:', exc, file=sys.stderr, flush=True)
        return 1
    finally:
        if stage is not None and stage.exists():
            # Both endpoints are resolved inside the dedicated staging root.
            # All scientific evidence/logs were copied to the owned attempt.
            shutil.rmtree(within(stage, ROOT/'tmp/q2_pr14'))


if __name__ == '__main__':
    raise SystemExit(main())
