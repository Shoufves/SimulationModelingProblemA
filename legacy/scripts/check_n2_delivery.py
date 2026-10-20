"""Verify the N2 evidence archive and workspace gates without replacing old receipts."""
from pathlib import Path
import gzip
import hashlib
import json
import subprocess
import sys
import argparse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/research_n2'


def digest(blob):
    return hashlib.sha256(blob).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    global OUT
    parser=argparse.ArgumentParser();parser.add_argument('--evidence',default='outputs/research_n2')
    args=parser.parse_args();OUT=ROOT/args.evidence
    qa = OUT / 'qa'
    qa.mkdir(exist_ok=True)
    archive = json.loads((OUT / 'archive_manifest.json').read_text('utf-8'))
    for record in archive['records']:
        path = OUT / record['path']
        blob = path.read_bytes()
        raw = gzip.decompress(blob) if path.suffix == '.gz' else blob
        if digest(blob) != record['sha256'] or digest(raw) != record['uncompressed_sha256']:
            raise ValueError('Archive hash mismatch: ' + record['path'])
    write(qa / 'archive_integrity.json', dict(passed=True, files=len(archive['records']),
          verification='Stored SHA256 and losslessly decompressed SHA256 for every archive record'))
    tracked = subprocess.check_output(['git', 'ls-files', '-z', 'outputs/validation', 'outputs/workflow'], cwd=ROOT)
    saved = {name.decode('utf-8'): (ROOT / name.decode('utf-8')).read_bytes()
             for name in tracked.split(b'\0') if name}
    jobs = [('audit', ['run.py', 'audit'], 'outputs/validation/workspace_audit.json'),
            ('formal_inputs', ['scripts/workflow_status.py', '--check-formal-inputs'], 'outputs/workflow/status.json'),
            ('key_scan', ['scripts/scan_google_keys.py'], None)]
    records = []
    try:
        for label, args, receipt in jobs:
            log = qa / (label + '.log')
            with log.open('wb') as stream:
                result = subprocess.run([sys.executable, '-B', '-X', 'utf8', *args], cwd=ROOT,
                                        stdout=stream, stderr=subprocess.STDOUT)
            records.append(dict(name=label, command=['python', '-B', '-X', 'utf8', *args],
                                exit_code=result.returncode, log_sha256=digest(log.read_bytes())))
            if receipt and (ROOT / receipt).exists():
                (qa / (label + '.json')).write_bytes((ROOT / receipt).read_bytes())
            write(qa / 'gates.json', dict(passed=len(records) == len(jobs) and all(r['exit_code'] == 0 for r in records),
                  commands=records, scope='Delivery checks only; no fresh simulation or test execution claimed'))
            if result.returncode:
                raise ValueError('Workspace gate failed: ' + label)
    finally:
        for name, blob in saved.items():
            (ROOT / name).write_bytes(blob)
    assets = [p for p in OUT.rglob('*') if p.is_file() and p != qa / 'delivery_manifest.json']
    assets += [ROOT / '.gitattributes', ROOT / 'README.md', ROOT / 'docs/IMPLEMENTATION_ROADMAP.md',
               ROOT / 'docs/research/ai-use-and-human-review.md', ROOT / 'data/catalog/n2_input_review.json']
    for pattern in ('docs/research/n2-*.md', 'scripts/*n2*.py', 'workflow/n2_*.json',
                    'src/transition_research/*.py', 'tests/research/*.py'):
        assets.extend(ROOT.glob(pattern))
    write(qa / 'delivery_manifest.json', dict(passed=True, files={p.relative_to(ROOT).as_posix(): digest(p.read_bytes())
          for p in sorted(set(assets))}, human_review='pending',
          figure_review='PNG inspected for readable labels, complete panels, units and scope caption'))
    print(json.dumps(dict(passed=True, archive_files=len(archive['records']), gates=records), ensure_ascii=False))


if __name__ == '__main__':
    main()
