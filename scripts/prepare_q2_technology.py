"""Offline extraction of visually checked IEA reference parameters; no auto-admission."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from energy_model.q2.io import csvout, local_path, sha


def prepare(root=ROOT):
    review = json.loads((root/'data/catalog/q2_technology_review.json').read_text(encoding='utf-8'))
    if review['decision'] != 'scoped_reference_parameters_only' or not all(c['passed'] for c in review['checks']):
        raise ValueError('Technology reference review absent or unresolved')
    for item in review['fingerprints']:
        if sha(local_path(root, item['path'])) != item['sha256']:
            raise ValueError('Technology review fingerprint mismatch: '+item['path'])
    source = json.loads((root/'data/catalog/q2_technology_transcription.json').read_text(encoding='utf-8'))
    if sha(local_path(root, source['source_path'])) != source['source_sha256']:
        raise ValueError('Technology original changed')
    records = source['records']
    if len({r['id'] for r in records}) != len(records):
        raise ValueError('Duplicate technology parameter')
    exchange = next(r['value'] for r in records if r['id']=='china:exchange_rate_2018')
    rows = []
    for record in records:
        value, unit, transform = record['value'], record['unit'], 'identity'
        if unit == '%':
            value /= 100.; unit = 'fraction'; transform = 'percent / 100'
        elif unit == 'USD_2018/kWe_AC':
            value *= exchange*1000.; unit = 'CNY_2018/MWe_AC'
            transform = 'USD_2018/kWe_AC * reported 6.62 CNY_2018/USD_2018 * 1000 kW/MW'
        rows.append({**record, 'normalized_value': value, 'normalized_unit': unit, 'transformation': transform,
                     'source_key': source['source_key'], 'source_path': source['source_path'],
                     'source_sha256': source['source_sha256'], 'publication_year': source['publication_year'],
                     'price_year': source['price_year'], 'projection_commission_year':source['projection_commission_year'],
                     'annual_decision_available_from':source['annual_decision_available_from'],
                     'admission':'scoped_reference_only_not_complete_model_admission'})
    out = root/'data/processed/q2/technology_reference.csv'
    out.parent.mkdir(parents=True, exist_ok=True)
    csvout(out, rows)
    return {'rows':len(rows), 'output':out.relative_to(root).as_posix(), 'sha256':sha(out)}


if __name__ == '__main__':
    print(json.dumps(prepare(), ensure_ascii=False, indent=2))
