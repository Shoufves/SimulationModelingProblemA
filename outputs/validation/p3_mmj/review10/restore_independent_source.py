"""Restore saved independent-run bytes; this does not execute a new experiment."""
import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def inside(root, relative):
    value = (root / relative).resolve()
    if not value.is_relative_to(root.resolve()):
        raise ValueError('Path outside evidence root: ' + relative)
    return value

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default='outputs/q3/pr15_review10_restored')
    args = parser.parse_args()
    target = (ROOT / args.output_dir).resolve()
    latest = target.parent / (target.name + '.latest-attempt.json')
    if target.parent != (ROOT / 'outputs/q3').resolve() or target.exists() or latest.exists():
        raise ValueError('Use an unused direct child of outputs/q3')
    inventory = json.loads((HERE / 'independent_source_inventory.json').read_text(encoding='utf-8'))
    reference = inside(ROOT, inventory['reference_output'])
    if sha(reference / 'run_manifest.json') != inventory['reference_manifest_sha256']:
        raise ValueError('Original reference manifest changed')
    sources = []
    for name, item in inventory['files'].items():
        base = reference if item['storage'] == 'reference' else HERE / 'independent_source_delta'
        source = inside(base, name)
        inside(target, name)
        if sha(source) != item['sha256']:
            raise ValueError('Saved evidence changed: ' + name)
        sources.append((name, source, item['sha256']))
    saved_latest = HERE / 'independent_latest_attempt.json'
    if sha(saved_latest) != inventory['latest_attempt_sha256']:
        raise ValueError('Saved latest attempt changed')
    target.mkdir()
    for name, source, expected in sources:
        dest = inside(target, name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(source.read_bytes())
        if sha(dest) != expected:
            raise ValueError('Restored bytes differ: ' + name)
    latest.write_bytes(saved_latest.read_bytes())
    print(json.dumps(dict(status='restored_saved_run_bytes', output=str(target),
        run_id=inventory['run_id'], files=len(sources), new_experiment_executed=False)))

if __name__ == '__main__':
    main()
