"""Reproduce the three paper questions without changing frozen scientific code.

AI-assisted organization: OpenAI Codex, 2026-10-20. Model release date was not
available in the session. This wrapper only restores paths and launches code.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def contained(root, name):
    path = (root / name).resolve()
    if path == root.resolve() or not path.is_relative_to(root.resolve()):
        raise ValueError('Path outside allowed directory: ' + str(name))
    return path


def restore_runtime():
    spec = json.loads((ROOT / 'data/workspace_manifest.json').read_text('utf-8'))
    bundle = ROOT / 'data/reproduction_contract.zip'
    if sha(bundle) != spec['bundle_sha256']:
        raise ValueError('Changed frozen reproduction contract')
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    stage = ROOT / 'legacy/.runs' / stamp
    stage.mkdir(parents=True, exist_ok=False)
    with ZipFile(bundle) as archive:
        for name, record in spec['runtime'].items():
            target = contained(stage, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if record['storage'] == 'active':
                source = contained(ROOT, name)
                if sha(source) != record['sha256']:
                    raise ValueError('Changed retained input/code/result: ' + name)
                shutil.copyfile(source, target)
            elif record['storage'] == 'bundle':
                target.write_bytes(archive.read(name))
            else:
                raise ValueError('Unknown storage: ' + record['storage'])
            if sha(target) != record['sha256']:
                raise ValueError('Restored file differs: ' + name)
    return stage


def verify(stage):
    # Use the original receipts and validators in a fresh interpreter. The
    # historical run.py is restored too, so no old code hash is re-authorized.
    code = """
import sys
from pathlib import Path
sys.path.insert(0, 'scripts')
import run_q3_pr14 as q3
import run_q2_pr14 as q2
q3.preflight()
q2.verify_latest(Path('outputs/q2_pr14/integrated'))
q3.verify_latest(Path('outputs/q3_pr14/current'))
folder = Path('outputs/q1/pr14_aligned')
receipt = q3.load(folder / 'alignment_manifest.json')
assert receipt['status'] == 'passed'
for name, expected in receipt['outputs'].items():
    assert q3.sha(folder / name) == expected, name
for name, expected in receipt['input_hashes'].items():
    assert q3.sha(Path(name)) == expected, name
print('PASS: Q1/Q2/Q3 original input, code and result hashes; original Q2/Q3 receipts.')
"""
    return subprocess.call([sys.executable, '-B', '-X', 'utf8', '-c', code], cwd=stage)


def history_command(relative):
    # The frozen Q1 program asks Git only for run provenance. A restored export
    # has no checkout identity; keep the scientific source bytes unchanged and
    # record unknown Git metadata explicitly in the newly generated receipt.
    code = """
import json
from pathlib import Path
import sys
sys.path.insert(0, 'scripts')
import build_q1 as q1
def exported_git(*args):
    if args not in (('rev-parse', 'HEAD'), ('status', '--porcelain')):
        raise ValueError('Unexpected Git operation in exported Q1 runtime')
    return None
q1.git = exported_git
result = q1.run(sys.argv[1])
if result == 0:
    folder = Path(sys.argv[1])
    manifest = folder / 'run_manifest.json'
    receipt = json.loads(manifest.read_text('utf-8'))
    receipt.update(git_sha=None, git_dirty=None, git_status=None,
                   git_metadata_available=False,
                   provenance_note='Frozen exported runtime; Git identity and cleanliness are unknown.')
    q1.dump(manifest, receipt)
    latest = folder.parent / (folder.name + '.latest-attempt.json')
    attempt = json.loads(latest.read_text('utf-8'))
    attempt['manifest_sha256'] = q1.sha(manifest)
    q1.dump(latest, attempt)
raise SystemExit(result)
"""
    return [sys.executable, '-B', '-X', 'utf8', '-c', code, relative]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('verify', 'q1', 'q1-history', 'q2', 'q3'))
    parser.add_argument('--output-dir', help='New directory under outputs/ or legacy/; existing paths are refused')
    parser.add_argument('--smoke', action='store_true', help='Q3 baseline and four event checks only')
    parser.add_argument('--only', nargs='+', help='Q2 case names; omitted means all 24 cases')
    parser.add_argument('--end-year', type=int, default=2060, help='Q2 end year')
    args = parser.parse_args()
    if args.smoke and args.command != 'q3':
        parser.error('--smoke is only available for q3')
    if (args.only or args.end_year != 2060) and args.command != 'q2':
        parser.error('--only and --end-year are only available for q2')
    if args.command == 'verify' and args.output_dir:
        parser.error('verify does not create a result directory')
    destination = None
    if args.command != 'verify':
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        destination = contained(ROOT, args.output_dir or 'outputs/reproduced/' + args.command + '/' + stamp)
        if not any(destination.is_relative_to(ROOT / p) for p in ('outputs', 'legacy')):
            parser.error('Output must stay inside outputs/ or legacy/')
        if destination.exists():
            parser.error('Choose a new output directory; retained results are immutable')
    stage = restore_runtime()
    print('Frozen runtime restored:', stage, flush=True)
    if args.command == 'verify':
        return verify(stage)
    entry, relative = {
        'q1': ('build_q1_pr14.py', 'outputs/q1/paper_reproduction'),
        'q1-history': ('build_q1.py', 'outputs/q1/paper_history'),
        'q2': ('run_q2_pr14.py', 'outputs/q2_pr14/paper_reproduction'),
        'q3': ('run_q3_pr14.py', 'outputs/q3_pr14/paper_reproduction'),
    }[args.command]
    command = [sys.executable, '-B', '-X', 'utf8', str(stage / 'scripts' / entry), '--output-dir', relative]
    if args.command == 'q1-history':
        command = history_command(relative)
    if args.smoke:
        command.append('--smoke')
    if args.command == 'q2':
        command += ['--end-year', str(args.end_year)]
        if args.only:
            command += ['--only', *args.only]
    result = subprocess.call(command, cwd=stage)
    source = stage / relative
    if result == 0 and source.is_dir():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        print('Reproduced results:', destination, flush=True)
    else:
        print('Reproduction failed; diagnostic files retained at:', stage, file=sys.stderr)
    return result


if __name__ == '__main__':
    raise SystemExit(main())
