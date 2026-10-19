"""Pinned local inputs, semantic admission and attempt-safe result publication."""
import csv
import hashlib
import json
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,
                                     allow_nan=False).encode('utf-8')).hexdigest()


def sha(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def verify_source_records(root, bindings):
    """Pin reviewed registry records without freezing unrelated later additions."""
    if not bindings or len({(b['path'],b['id']) for b in bindings})!=len(bindings):
        raise ValueError('Unique nonempty reviewed source bindings required')
    for binding in bindings:
        registry=json.loads(local_path(root,binding['path']).read_text(encoding='utf-8'))
        matches=[r for r in registry if r.get('id')==binding['id']]
        if len(matches)!=1 or digest(matches[0])!=binding['record_sha256']:
            raise ValueError('Reviewed source record changed or duplicated: '+binding['id'])
        record=matches[0]
        if sha(local_path(root,record['path']))!=record['sha256']:
            raise ValueError('Reviewed source original changed: '+binding['id'])


def local_path(root,relative):
    if not isinstance(relative,str) or Path(relative).is_absolute():
        raise ValueError('Repository-relative input path required')
    path=(root/relative).resolve()
    if not path.is_relative_to(root.resolve()) or 'restricted' in path.relative_to(root.resolve()).parts:
        raise ValueError('Input outside permitted public workspace')
    return path


def dump(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')


def csvout(path,rows):
    if not rows:
        raise ValueError('Required scientific table is empty: '+str(path))
    fields=list(dict.fromkeys(k for r in rows for k in r))
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        writer.writerows({k:json.dumps(v,ensure_ascii=False,sort_keys=True,allow_nan=False) if isinstance(v,(dict,list)) else v
                          for k,v in r.items()} for r in rows)


class AdmissionError(ValueError):
    def __init__(self,message,gaps=None):
        super().__init__(message)
        self.gaps=gaps or []


def load_bundle(root,config):
    scope=config['scope']
    if scope not in {'national_q2','synthetic_engineering_only'}:
        raise AdmissionError('Explicit scientific scope required')
    if config['unresolved_required_inputs']:
        raise AdmissionError('Required national inputs are not yet admitted',config['unresolved_required_inputs'])
    inputs=config['inputs']
    if len({i['id'] for i in inputs})!=len(inputs):
        raise AdmissionError('Duplicate Q2 input identities')
    result={}
    for spec in inputs:
        path=local_path(root,spec['path'])
        if sha(path)!=spec['sha256']:
            raise AdmissionError('Input fingerprint mismatch: '+spec['id'])
        if not spec['purpose'] or not spec['boundary']:
            raise AdmissionError('Input lacks explicit purpose and boundary')
        result[spec['id']]=json.loads(path.read_text(encoding='utf-8'))
    for key in ('model_bundle','experiment','metric_definitions','observations'):
        if key not in result:
            raise AdmissionError('Missing required bundle input: '+key)
    if scope=='national_q2':
        binding=config['evidence_review']
        path=local_path(root,binding['path'])
        if sha(path)!=binding['sha256']:
            raise AdmissionError('Q2 evidence review changed')
        review=json.loads(path.read_text(encoding='utf-8'))
        snapshot={'inputs':inputs,'sources':config['sources'],'assumptions':config['assumptions']}
        if review['reviewed_snapshot_sha256']!=digest(snapshot):
            raise AdmissionError('Input semantics differ from substantive Q2 review')
        if review['scope']!='national_q2' or review['decision']!='admitted' or not review['checks']:
            raise AdmissionError('National model use has not passed substantive review')
        if not all(check['passed'] is True and check['evidence'] for check in review['checks']):
            raise AdmissionError('Unresolved substantive review checks')
        for source in config['sources']:
            if not source['artifacts']:
                raise AdmissionError('Source original absent')
            for artifact in source['artifacts']:
                if sha(local_path(root,artifact['path']))!=artifact['sha256']:
                    raise AdmissionError('Source original changed')
        if any(m['scope']=='synthetic_engineering_only' for m in result['model_bundle'].values()):
            raise AdmissionError('Synthetic model cannot enter national prediction')
    else:
        if any(m['scope']!='synthetic_engineering_only' for m in result['model_bundle'].values()):
            raise AdmissionError('Engineering run mixes scientific scopes')
    return result
