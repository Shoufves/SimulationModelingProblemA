"""Offline Google API key scan; prints locations only, including ZIP members.

Use --history to also inspect blobs reachable from local Git refs. This does
not contact Google, validate credentials, or change files/history.
"""
from pathlib import Path
import argparse
import io
import json
import re
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(rb"AIza[0-9A-Za-z_-]{35}")


def scan_bytes(data, location, findings, stats, depth=0):
    stats['payloads_scanned'] += 1
    matches = list(PATTERN.finditer(data))
    if matches:
        findings.append(dict(path=location, count=len(matches),
                             lines=[data[:m.start()].count(b'\n') + 1 for m in matches]))
    if data.startswith((b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08')):
        if depth >= 8:
            raise ValueError('ZIP nesting exceeds scan limit: ' + location)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            for entry in archive.infolist():
                if not entry.is_dir():
                    stats['zip_members_scanned'] += 1
                    scan_bytes(archive.read(entry), location + '!' + entry.filename,
                               findings, stats, depth + 1)


def scan_workspace(root=ROOT):
    findings, errors = [], []
    stats = dict(files_scanned=0, payloads_scanned=0, zip_members_scanned=0)
    for path in sorted(root.rglob('*')):
        if not path.is_file() or '.git' in path.relative_to(root).parts:
            continue
        relative = path.relative_to(root).as_posix()
        try:
            stats['files_scanned'] += 1
            scan_bytes(path.read_bytes(), relative, findings, stats)
        except Exception as exc:
            errors.append(dict(path=relative, error=type(exc).__name__))
    return dict(scope='working tree including hidden files and ZIP members; .git excluded',
                pattern='Google API key format only; not an exhaustive credential audit',
                passed=not findings and not errors, findings=findings, errors=errors, **stats)


def scan_history(root=ROOT):
    listing = subprocess.check_output(['git', '-C', str(root), 'rev-list', '--objects', '--all'])
    entries = [line.split(b' ', 1) for line in listing.splitlines()]
    findings, errors = [], []
    stats = dict(blobs_scanned=0, payloads_scanned=0, zip_members_scanned=0)
    process = subprocess.Popen(['git', '-C', str(root), 'cat-file', '--batch'],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for parts in entries:
            oid = parts[0]
            process.stdin.write(oid + b'\n')
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3:
                raise ValueError('Invalid Git object response')
            data = process.stdout.read(int(header[2]))
            process.stdout.read(1)
            if header[1] != b'blob':
                continue
            stats['blobs_scanned'] += 1
            name = parts[1].decode('utf-8', 'replace') if len(parts) > 1 else '(unnamed)'
            location = oid.decode() + ':' + name
            try:
                scan_bytes(data, location, findings, stats)
            except Exception as exc:
                errors.append(dict(path=location, error=type(exc).__name__))
    finally:
        process.stdin.close()
        process.wait()
        process.stdout.close()
    return dict(scope='blobs reachable from local Git refs, including ZIP members; no remote query',
                passed=not findings and not errors, findings=findings, errors=errors, **stats)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', action='store_true')
    args = parser.parse_args()
    result = dict(working_tree=scan_workspace())
    if args.history:
        result['git_history'] = scan_history()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(r['passed'] for r in result.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
