"""Rebuild source-pinned 2024 state and confront the existing historical endpoint.

No observed 2024 data is fed back into training or substituted for a simulation.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from energy_model.q2.current_state import build_state, compare_historical_endpoint, require_complete_state
from energy_model.q2.io import AdmissionError, csvout, dump, local_path, sha


def execute(root=ROOT, output='data/processed/q2'):
    review_path = root / 'data/catalog/q2_current_state_review.json'
    review = json.loads(review_path.read_text(encoding='utf-8'))
    for binding in review['fingerprints']:
        if sha(local_path(root, binding['path'])) != binding['sha256']:
            raise ValueError('Reviewed current-state input changed: ' + binding['path'])
    if review['decision'] != 'partial_state_only_not_national_admission' or not all(
            c['passed'] and c['evidence'] for c in review['checks']):
        raise ValueError('Current-state review does not support this use')
    transcription = json.loads((root / 'data/catalog/q2_current_state_transcription.json').read_text(encoding='utf-8'))
    state, rows = build_state(transcription['observations'])
    state['source_review_sha256'] = sha(review_path)
    by_id = {r['id']: r for r in rows}
    diagnostics = []
    for label in ('total', 'thermal', 'hydro', 'nuclear', 'wind', 'solar'):
        a, b = by_id['NBS:' + label], by_id['NEA:' + label]
        diagnostics.append(dict(check='capacity_vintage_' + label,
            value=a['normalized_value'], reference=b['normalized_value'],
            difference=a['normalized_value'] - b['normalized_value'], unit='MW',
            status='separate_publications_no_splice_or_average'))
    for label in ('thermal', 'hydro', 'nuclear', 'wind', 'solar'):
        # Ratios are an inconsistency diagnostic, never an imputed national stock.
        sample = by_id['RELIABILITY:' + label]['normalized_value']
        coverage = by_id['COVERAGE:' + label]['normalized_value']
        nbs = by_id['NBS:' + label]['normalized_value']
        diagnostics.append(dict(check='reporting_coverage_' + label,
            value=sample / nbs, reference=coverage, difference=sample / nbs - coverage,
            unit='fraction', status='reporting_sample_and_published_coverage_not_national_partition'))
    power, energy = by_id['STORAGE:power'], by_id['STORAGE:energy']
    diagnostics.append(dict(check='new_storage_nameplate_energy_to_power',
        value=energy['normalized_value'] / power['normalized_value'], reference=2.3,
        difference=energy['normalized_value'] / power['normalized_value'] - 2.3,
        unit='h', status='nameplate_ratio_not_available_discharge_duration'))
    model = json.loads((root / review['candidate_model']).read_text(encoding='utf-8'))
    result = json.loads((root / review['candidate_result']).read_text(encoding='utf-8'))
    endpoint = compare_historical_endpoint(state, model, result)
    try:
        require_complete_state(state)
    except AdmissionError as exc:
        rejection = dict(rejected=True, reason=str(exc), unresolved_fields=exc.gaps)
    else:
        raise ValueError('Partial state must not be accepted as complete initialization')
    out = local_path(root, output)
    out.mkdir(parents=True, exist_ok=True)
    dump(out / 'current_state_2024.json', state)
    csvout(out / 'current_state_2024_observations.csv', rows)
    csvout(out / 'current_state_2024_diagnostics.csv', diagnostics)
    csvout(out / 'current_state_2024_endpoint.csv', endpoint)
    checks = dict(status='partial_state_reproduced', observations=len(rows),
        source_review_sha256=sha(review_path), checks=state['checks'],
        national_acceptance=False, initialization_complete=False,
        full_state_rejection=rejection, candidate_endpoint_compared=True,
        historical_model_unchanged=True, calibration_executions_added=0,
        output_hashes={p.name: sha(p) for p in sorted(out.glob('current_state_2024*'))
                      if p.name != 'current_state_2024_checks.json'})
    dump(out / 'current_state_2024_checks.json', checks)
    print(json.dumps({k: checks[k] for k in ('status', 'observations', 'initialization_complete')}))
    return checks


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', default='data/processed/q2')
    args = parser.parse_args()
    execute(output=args.output_dir)
