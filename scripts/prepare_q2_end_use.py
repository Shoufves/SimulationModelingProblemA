"""Extract reviewed REmap end-use reference performance, withholding cost use."""
import json
from math import isfinite
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from energy_model.q2.io import csvout, dump, local_path, sha, verify_source_records


def normalize(record):
    amount = record['performance_value']
    if type(amount) not in (int, float) or not isfinite(amount) or amount <= 0:
        raise ValueError('Positive source performance required')
    unit = record['performance_unit']
    if unit == '%':
        service, factor = 'MWh_heat_service', amount/100
    elif unit == 'MJ/passenger_km':
        service, factor = 'passenger_km', 3600/amount
    else:
        raise ValueError('Unreviewed performance unit')
    return dict(**record, service_unit=service, service_per_MWh_input=factor,
                conversion='value / 100' if unit == '%' else '3600 MJ/MWh / value MJ/passenger_km',
                performance_role='REmap prospective technology assumption; not measured 2014 national stock',
                economic_use_admitted=False)


def prepare(root=ROOT):
    review_path = root/'data/catalog/q2_end_use_review.json'
    review = json.loads(review_path.read_text(encoding='utf-8'))
    if review['decision'] != 'limited_prospective_performance_and_unit_reference' or not all(
            c['passed'] is True and c['evidence'] for c in review['checks']):
        raise ValueError('Substantive end-use reference review required')
    for binding in review['fingerprints']:
        if sha(local_path(root, binding['path'])) != binding['sha256']:
            raise ValueError('Reviewed end-use reference changed')
    verify_source_records(root, review['source_records'])
    source = json.loads((root/'data/catalog/q2_end_use_transcription.json').read_text(encoding='utf-8'))
    if len(source['records']) != 7 or len({r['id'] for r in source['records']}) != 7:
        raise ValueError('Seven unique reviewed end-use technology rows required')
    rows = [dict(**normalize(row), source_id=source['source_id'], source_path=source['source_path'],
                 source_sha256=source['source_sha256'], publication_month=source['publication_month'])
            for row in source['records']]
    out = root/'data/processed/q2'
    out.mkdir(parents=True, exist_ok=True)
    csvout(out/'end_use_reference.csv', rows)
    dump(out/'end_use_reference_checks.json', dict(rows=len(rows), review_sha256=sha(review_path),
        outputs={'end_use_reference.csv': sha(out/'end_use_reference.csv')},
        economic_use_admitted=False, national_admission=False))
    return rows


if __name__ == '__main__':
    print(json.dumps(dict(rows=len(prepare()), national_admission=False)))
