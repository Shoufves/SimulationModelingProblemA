"""Offline, scoped historical policy terms; never fabricates national contracts."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from energy_model.q2.io import csvout,local_path,sha,verify_source_records


def prepare(root=ROOT):
    review=json.loads((root/'data/catalog/q2_policy_review.json').read_text(encoding='utf-8'))
    if review['decision']!='scoped_historical_policy_reference' or not review['checks'] or not all(c['passed'] is True and c['evidence'] for c in review['checks']):
        raise ValueError('Historical policy reference not reviewed')
    for item in review['fingerprints']:
        if sha(local_path(root,item['path']))!=item['sha256']:
            raise ValueError('Historical policy fingerprint mismatch: '+item['path'])
    verify_source_records(root,review['source_records'])
    document=json.loads((root/'data/catalog/q2_policy_transcription.json').read_text(encoding='utf-8'))
    records=document['records']
    if not records or len({r['id'] for r in records})!=len(records):
        raise ValueError('Duplicate or empty historical policy identities')
    registry=json.loads((root/'data/catalog/q2_sources.json').read_text(encoding='utf-8'))
    sources={r['id']:r for r in registry}
    bound={b['id'] for b in review['source_records']}
    rows=[]
    for r in records:
        if not r['source_ids'] or not set(r['source_ids'])<=bound:
            raise ValueError('Policy source outside reviewed records')
        rows.append({**r,'price_CNY_nominal_per_MWh':r['price']*1000,
                     'transformation':'kWh to MWh only; no tax removal, inflation adjustment, annual aggregation or national averaging',
                     'originals':[{'source_id':s,'path':sources[s]['path'],'sha256':sources[s]['sha256']} for s in r['source_ids']],
                     'admission':'scoped_policy_reference_not_model_contract'})
    out=root/'data/processed/q2/policy_reference.csv';out.parent.mkdir(exist_ok=True)
    csvout(out,rows)
    return {'records':len(rows),'output':out.relative_to(root).as_posix(),'sha256':sha(out),'national_policy_mapping_complete':False}


if __name__=='__main__':print(json.dumps(prepare(),ensure_ascii=False,indent=2))
