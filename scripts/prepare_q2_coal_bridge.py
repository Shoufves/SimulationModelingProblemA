"""Scoped CEADs/NBS coal bridge; frozen v5/v6 diagnostics remain unchanged."""
import csv
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from energy_model.q2.io import csvout, dump, local_path, sha, verify_source_records


def bridge(cells, nbs, mappings):
    results = []
    for spec in mappings:
        addresses = spec['ceads_cells']
        if not addresses or len(set(addresses)) != len(addresses):
            raise ValueError('Empty or repeated bridge cell')
        terms = [cells[a] for a in addresses]
        target = nbs[(spec['nbs_table'], spec['nbs_account'])]
        if any(t['unit_as_published'] != '104 tn' or not t['value'] for t in terms):
            raise ValueError('Coal bridge missing value or incompatible source unit')
        if target['unit'] != '10^4 t' or not target['value']:
            raise ValueError('Coal bridge missing target or incompatible target unit')
        left = sum((Decimal(t['value']) for t in terms), Decimal(0))
        right = Decimal(target['value'])
        bound = Decimal('.05') * (len(terms) + 1)
        delta = left - right
        if abs(delta) > bound:
            raise ValueError('Coal bridge exceeds source rounding: ' + spec['comparison'])
        results.append({**spec, 'year': 2014, 'unit': '10^4 t',
                        'ceads_value': float(left), 'nbs_value': float(right),
                        'difference_ceads_minus_nbs': float(delta),
                        'rounding_bound': float(bound),
                        'status': 'scoped_aggregate_agreement_within_rounding',
                        'ceads_source_sheet': '2014',
                        'nbs_source_path': target['source_path'],
                        'nbs_source_sha256': target['source_sha256']})
    return results


def prepare(root=ROOT, output_dir=None):
    review = json.loads((root/'data/catalog/q2_coal_bridge_review.json').read_text(encoding='utf-8'))
    if review['decision'] != 'scoped_coal_aggregate_bridge_only':
        raise ValueError('Coal bridge review not admitted')
    if not review['checks'] or not all(c['passed'] and c['evidence'] for c in review['checks']):
        raise ValueError('Coal bridge substantive review missing')
    for item in review['fingerprints']:
        if sha(local_path(root, item['path'])) != item['sha256']:
            raise ValueError('Coal bridge input changed: ' + item['path'])
    verify_source_records(root, review['source_records'])
    with (root/'data/processed/q2/national_balance_2014_reference.csv').open(encoding='utf-8-sig', newline='') as f:
        cells = {r['source_cell']: r for r in csv.DictReader(f)}
    with (root/'data/processed/q2/nbs2014_accounts.csv').open(encoding='utf-8-sig', newline='') as f:
        nbs = {(r['table'], r['account']): r for r in csv.DictReader(f)}
    results = bridge(cells, nbs, review['mappings'])
    out = Path(output_dir) if output_dir else root/'data/processed/q2'
    out.mkdir(parents=True, exist_ok=True)
    csvout(out/'coal_bridge_2014.csv', results)
    summary = {'decision': review['decision'], 'comparisons': len(results),
               'all_within_rounding': True, 'national_initialization_admitted': False,
               'supersedes': 'The raw_coal_power_input discrepancy interpretation only; old records and model outputs retained.',
               'remaining': review['unresolved'],
               'review_sha256': sha(root/'data/catalog/q2_coal_bridge_review.json'),
               'output_sha256': sha(out/'coal_bridge_2014.csv')}
    dump(out/'coal_bridge_2014_checks.json', summary)
    return summary


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(output_dir=args.output_dir), ensure_ascii=False))
