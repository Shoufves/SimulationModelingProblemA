"""Export the pinned PR14 portable tree without merging or changing its files."""
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[1]
REF = '1b8f465783afe7505c8d4e65ec43ada18c311daf'
DEST = ROOT / 'tmp/n2/pr14'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    review=json.loads((ROOT/'data/catalog/n2_input_review.json').read_text('utf-8'))
    if review['baseline_commit']!=REF or review['allowed_use']!='conditional_yearly_q3_research' or review['raw_originals_reverified']:
        raise ValueError('Wrong new-use review or evidence scope')
    manifest = json.loads(subprocess.check_output(
        ['git', 'show', REF+':data/processed/q2_delivery/manifest.json'], cwd=ROOT))
    paths = ['src', 'scripts', 'data/processed/q2_delivery']
    paths += [p for p in manifest['code_sha256']
              if not any(p == d or p.startswith(d+'/') for d in paths)]
    blob = subprocess.check_output(['git', 'archive', REF, '--', *paths], cwd=ROOT)
    DEST.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(blob)) as archive:
        archive.extractall(DEST, filter='data')
    for name, expected in manifest['code_sha256'].items():
        if sha(DEST / name) != expected:
            raise ValueError('Pinned upstream code mismatch: '+name)
    if sha(DEST/'data/processed/q2_delivery/manifest.json')!=review['manifest_sha256']:
        raise ValueError('Export does not match the reviewed new-use input snapshot')
    for name, key in [('parsed_inputs.json','inputs_sha256'), ('q2_design.json','design_sha256')]:
        if sha(DEST/'data/processed/q2_delivery'/name) != manifest[key]:
            raise ValueError('Pinned upstream input mismatch: '+name)
    receipt = dict(commit=REF, exported_paths=paths, mode=manifest['mode'],
                   code_files_verified=len(manifest['code_sha256']),
                   manifest_sha256=sha(DEST/'data/processed/q2_delivery/manifest.json'),
                   raw_originals_reverified=False,
                   new_use_review_sha256=sha(ROOT/'data/catalog/n2_input_review.json'))
    (DEST.parent/'baseline_export.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    prepare()
