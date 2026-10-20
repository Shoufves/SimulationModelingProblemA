"""Streaming comparison across environments; numeric tolerances fixed in config."""
import argparse
import csv
import gzip
from itertools import zip_longest
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_q3 import verify_latest,load,dump,sha


def ledger_rows(folder,kind):
    for path in sorted(folder.glob(kind+'_ledgers*.jsonl.gz')):
        with gzip.open(path,'rt',encoding='utf-8') as f:
            for line in f:yield json.loads(line)


def compare(left,right):
    a=verify_latest(left);b=verify_latest(right);c=load(left/'frozen_config.json')
    errors=[];count=0;max_relative=0;compared=[]
    def visit(x,y,path=''):
        nonlocal count,max_relative
        if len(errors)>=20:return
        if isinstance(x,bool) or isinstance(y,bool):
            if type(x)!=type(y) or x!=y:errors.append(path+' boolean')
        elif isinstance(x,(int,float)) and isinstance(y,(int,float)):
            count+=1;scale=max(1,abs(x),abs(y));error=abs(x-y)
            if not(math.isfinite(x) and math.isfinite(y)):errors.append(path+' nonfinite');return
            bound=c['acceptance']['absolute_numeric_tolerance']+c['acceptance']['relative_numeric_tolerance']*scale
            if 'residual' in path and 'cny' in path:bound=max(bound,c['acceptance']['cash_absolute_tolerance_cny'])
            if 'residual' in path and 'cny' not in path:bound=max(bound,c['acceptance']['physical_residual_mwh'])
            if error>bound:errors.append(dict(path=path,left=x,right=y,error=error,bound=bound))
            if 'residual' not in path:max_relative=max(max_relative,error/scale)
        elif isinstance(x,dict) and isinstance(y,dict):
            if set(x)!=set(y):errors.append(path+' dictionary keys');return
            for key in x:visit(x[key],y[key],path+'/'+str(key))
        elif isinstance(x,list) and isinstance(y,list):
            if len(x)!=len(y):errors.append(path+' list length');return
            for i,(u,v) in enumerate(zip(x,y)):visit(u,v,path+'/'+str(i))
        elif isinstance(x,str) and isinstance(y,str) and x!=y:
            try:u,v=json.loads(x),json.loads(y)
            except (ValueError,TypeError):errors.append(path+' text differs');return
            visit(u,v,path)
        elif x!=y:errors.append(path+' value differs')
    for kind in ('annual','event'):
        cases=0
        for i,(x,y) in enumerate(zip_longest(ledger_rows(left,kind),ledger_rows(right,kind))):
            visit(x,y,kind+'/'+str(i));cases+=1
            if cases%40==0:print(f'compare {kind} {cases}',flush=True)
        compared.append(dict(kind=kind,records=cases))
    names={n for n in a['outputs'] if not n.endswith(('.gz','.png'))}
    other={n for n in b['outputs'] if not n.endswith(('.gz','.png'))}
    if names!=other:errors.append('scientific output file set differs')
    for name in sorted(names&other):
        if name.endswith('.json'):visit(load(left/name),load(right/name),name)
        elif name.endswith('.csv'):
            with (left/name).open(encoding='utf-8',newline='') as f,(right/name).open(encoding='utf-8',newline='') as g:
                for i,(x,y) in enumerate(zip_longest(csv.DictReader(f),csv.DictReader(g))):visit(x,y,f'{name}/{i}')
        elif (left/name).read_bytes()!=(right/name).read_bytes():errors.append(name+' nonnumeric artifact differs')
    return dict(passed=not errors,status='matched_with_frozen_tolerances' if not errors else 'failed',
        left_run=a['run_id'],right_run=b['run_id'],left_python=a['python'],right_python=b['python'],
        left_manifest=sha(left/'run_manifest.json'),right_manifest=sha(right/'run_manifest.json'),
        numeric_values_compared=count,max_nonresidual_relative_difference=max_relative,ledgers=compared,
        errors=errors,config_tolerances=c['acceptance'],checker_sha256=sha(Path(__file__)),
        statement='Cross-environment numerical reproduction, not a byte-identity claim; image bytes are excluded.')


def main():
    p=argparse.ArgumentParser();p.add_argument('--left',default='outputs/q3/p3_yx');p.add_argument('--right',default='outputs/q3/p3_yx_reproduction');args=p.parse_args()
    out=ROOT/'outputs/q3_review';out.mkdir(exist_ok=True)
    dump(out/'reproduction.json',dict(passed=False,status='running'))
    try:result=compare(ROOT/args.left,ROOT/args.right)
    except Exception as exc:result=dict(passed=False,status='failed',error=str(exc))
    dump(out/'reproduction.json',result);print(json.dumps(result,ensure_ascii=False))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
