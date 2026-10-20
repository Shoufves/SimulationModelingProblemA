"""Prepare a reversible paper workspace layout from existing local evidence."""
import csv
import hashlib
import json
from pathlib import Path
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'legacy/organization'


def load(name):
    return json.loads((ROOT / name).read_text('utf-8-sig'))


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', 'utf-8')


keep = set()
runtime = set()


def add(name, run=False):
    path = ROOT / name
    if path.is_file():
        keep.add(name)
        if run:
            runtime.add(name)


def tree(name, run=False, suffixes=None):
    for path in (ROOT / name).rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts:
            if suffixes is None or path.suffix in suffixes:
                add(path.relative_to(ROOT).as_posix(), run)


for name in ('.gitattributes', '.gitignore', 'requirements-data.txt',
             'requirements-q1.txt', 'requirements-q2.txt', 'requirements-q3.txt'):
    add(name, True)
for path in ROOT.glob('*.xlsx'):
    add(path.name, True)
for path in ROOT.glob('*A题.pdf'):
    add(path.name)
for name in ('build_q1_pr14', 'run_q2_pr14', 'run_q3_pr14', 'q3_pr14_runtime',
             'run_q3', 'build_q1', 'prepare_q1_review', 'plot_q1',
             'q1_additional_analysis', 'extract_q1_additions', 'extract_q1_revision',
             'prepare_q1_cost_parameters', 'build_attachments', 'workflow_status'):
    add('scripts/' + name + '.py', True)
for name in ('__init__', 'q1', 'q3_transition', 'q3_events'):
    add('src/energy_model/' + name + '.py', True)
tree('src/q3_pr14', True, {'.py'})
for name in ('workflow/q1_inputs.json', 'workflow/q3_inputs.json',
             'workflow/q3_pr14_inputs.json', 'workflow/q2_pr14_integration.json',
             'workflow/provided_inputs.json'):
    add(name, True)
for name in ('q1_input_review', 'q2_pr14_integration_review',
             'q123_pr14_alignment_review', 'q3_input_review', 'q1_sources'):
    add('data/catalog/' + name + '.json', True)

q1 = load('workflow/q1_inputs.json')
for row in q1['inputs']:
    add(row['path'], True)
for row in q1['sources'].values():
    for artifact in row['artifacts']:
        add(artifact['path'], True)
for row in load('data/catalog/q1_sources.json'):
    add(row['path'], True)
tree('data/processed/q1', True)
tree('data/raw/q1', True)

review = load('data/catalog/q2_pr14_integration_review.json')
for row in review['files']:
    name = row['path']
    runtime.add(name)
    if (name.startswith('data/processed/') or
        (row['role'] == 'runtime' and '/tests/' not in name and
         not Path(name).name.startswith('review_')) or
        name.startswith('outputs/q2_revenue_recalibration/')):
        add(name)

tree('outputs/q1/pr14_aligned', True)
tree('outputs/q2_pr14/integrated', True)
tree('outputs/q3_pr14/current/attempts/20261020T091248608100Z', True)
add('outputs/q3_pr14/current/latest.json', True)
for name in ('annual_common_metrics.csv', 'scenario_service_fractions.csv'):
    add('outputs/q123_alignment/' + name, True)
for name in ('baseline_targets.csv', 'historical_validation.csv', 'q2_summary.csv',
             'sensitivity_summary.csv', 'answer_manifest.json'):
    add('outputs/question2_delivery_20261020/' + name, True)
tree('outputs/question2_delivery_20261020/figures', True, {'.png', '.svg'})
for name in ('source_snapshot.json', 'design.json', 'targets.csv'):
    add('outputs/q2_current_delivery/20261020T004752442611Z/' + name, True)

# The original receipt validators require these exact bytes at historical paths.
runtime.add('run.py')
runtime.add('scripts/review_q1_delivery.py')
runtime.update(load('workflow/q3_pr14_inputs.json')['inherited_files'])
runtime.update(p.relative_to(ROOT).as_posix() for p in
               (ROOT / 'outputs/q1/p1_yx').glob('*') if p.is_file())
for name in ('data/sources.json', 'data/attachment_reviews.json'):
    add(name, True)

# Keep available Q2 provenance; record missing imported originals explicitly.
upstream = load('data/processed/q2_delivery/manifest.json')['original_source_sha256']
missing = []
for name, expected in upstream.items():
    if name.startswith('data/') and 'restricted' not in Path(name).parts:
        path = ROOT / name
        if path.is_file() and digest(path) == expected:
            add(name)
        else:
            missing.append({'path': name, 'expected_sha256': expected,
                            'status': 'missing' if not path.is_file() else 'different_local_version'})

# Documents and execution logs are not writing entry points in the active tree.
keep = {p for p in keep if not p.endswith(('.md', '.log'))}
runtime.update(keep & {p for p in keep if p.startswith(('vendor/', 'scripts/', 'src/'))})
bad = [p for p in runtime if not (ROOT / p).is_file()]
if bad:
    raise RuntimeError('Missing runtime dependency: ' + repr(bad))

bundle = ROOT / 'data/reproduction_contract.zip'
with ZipFile(bundle, 'w', ZIP_DEFLATED, compresslevel=6) as archive:
    for name in sorted(runtime - keep):
        archive.write(ROOT / name, name)
keep.add('data/reproduction_contract.zip')
manifest = {'schema_version': 1, 'basis_commit': 'ddb60bc',
            'purpose': 'Path-only organization; frozen model and evidence bytes unchanged',
            'bundle_sha256': digest(bundle),
            'runtime': {p: {'storage': 'active' if p in keep else 'bundle',
                            'sha256': digest(ROOT / p)} for p in sorted(runtime)},
            'upstream_originals_unavailable_or_different': missing}
save(ROOT / 'data/workspace_manifest.json', manifest)
keep.add('data/workspace_manifest.json')

# Preserve source registries without promoting their optional datasets to inputs.
for name in ('data/catalog/sources_unified.json', 'data/catalog/source_inventory.csv',
             'data/sources.json', 'data/evidence_reviews.json', 'data/attachment_reviews.json'):
    add(name)

# Retain every existing bibliographic field for the sources actually used by Q1.
registries = []
def visit(value, origin):
    if isinstance(value, dict):
        if isinstance(value.get('url'), str):
            registries.append((origin, value))
        for child in value.values():
            visit(child, origin)
    elif isinstance(value, list):
        for child in value:
            visit(child, origin)
for path in (ROOT / 'data/catalog').rglob('*.json'):
    try:
        visit(json.loads(path.read_text('utf-8-sig')), path.relative_to(ROOT).as_posix())
    except (ValueError, UnicodeError):
        pass
with (ROOT / 'data/catalog/source_inventory.csv').open(encoding='utf-8-sig', newline='') as stream:
    registries.extend(('data/catalog/source_inventory.csv', r) for r in csv.DictReader(stream))
references = []
sources = [dict(source_key=k, **v) for k, v in q1['sources'].items()]
sources += [dict(source_key=r['id'], **r) for r in load('data/catalog/q1_sources.json')]
for source in sources:
    matches = [(origin, row) for origin, row in registries if row.get('url') == source['url']]
    dates = sorted({str(v) for _, row in matches for k, v in row.items()
                    if k in ('retrieved_at', 'accessed_at', 'downloaded_at', 'access_date') and v})
    if source.get('retrieved_at'):
        dates.append(source['retrieved_at'])
    references.append(dict(source, recorded_access_dates=sorted(set(dates)),
                           metadata_matches=[{'registry': origin, 'record': row} for origin, row in matches]))
save(ROOT / 'data/references.json', references)
keep.add('data/references.json')

tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
inventory = []
for name in tracked:
    if not name or name.startswith('legacy/'):
        continue
    path = ROOT / name
    restricted = name.startswith('data/restricted/')
    inventory.append({'original': name, 'destination': name if name in keep else 'legacy/' + name,
                      'bytes': path.stat().st_size,
                      'sha256': None if restricted else digest(path),
                      'restricted_metadata_only': restricted})
save(OUT / 'inventory.json', inventory)
save(OUT / 'keep.json', sorted(keep))
print(json.dumps({'active_original_files': len(keep), 'runtime_files': len(runtime),
                  'bundled_dependencies': len(runtime - keep),
                  'bundle_bytes': bundle.stat().st_size, 'tracked_originals': len(inventory),
                  'upstream_original_gaps': len(missing)}, ensure_ascii=False))
