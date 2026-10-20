"""Verify relocation against the before-move inventory; never read restricted data."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


inventory = json.loads((HERE / 'inventory.json').read_text('utf-8'))
# Save exact pre-edit Git settings separately; these are the only changed
# original infrastructure files besides the archived README and run.py.
markers = {'.gitignore': b'# Local archived environments, caches and new reproduction staging.',
           '.gitattributes': b'# Organized and archived evidence keeps its original bytes after checkout.'}
for name, marker in markers.items():
    before = (ROOT / name).read_bytes().split(marker)[0]
    expected = next(r['sha256'] for r in inventory if r['original'] == name)
    candidates = (before, before.replace(b'\r\n', b'\n'), before.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
    restored = next((value for value in candidates if hashlib.sha256(value).hexdigest() == expected), None)
    if restored is None:
        raise ValueError('Cannot recover original Git settings: ' + name)
    (HERE / ('original' + name)).write_bytes(restored)
    for row in inventory:
        if row['original'] == name:
            row['destination'] = 'legacy/organization/original' + name

failures = []
for row in inventory:
    path = ROOT / row['destination']
    if not path.is_file() or path.stat().st_size != row['bytes']:
        failures.append({'file': row['original'], 'reason': 'missing/size'})
    elif row['sha256'] is not None and sha(path) != row['sha256']:
        failures.append({'file': row['original'], 'reason': 'sha256'})

(HERE / 'inventory.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + '\n', 'utf-8')
result = dict(passed=not failures, tracked_originals=len(inventory),
              byte_checked=sum(r['sha256'] is not None for r in inventory),
              restricted_metadata_only=sum(r['sha256'] is None for r in inventory), failures=failures)
(HERE / 'preservation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', 'utf-8')
print(json.dumps(result, ensure_ascii=False))
raise SystemExit(0 if result['passed'] else 1)
