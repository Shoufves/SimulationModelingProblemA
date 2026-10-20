"""Check protected base bytes and independently regenerated Q1/Q2 artifacts."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
from run_q3 import BASE, ROOT, dump, load, sha

DEST=ROOT/'outputs/q3_review'

def protected():
    paths=['2026年第二届全国大学生仿真建模应用挑战赛A题.pdf',*[f'附件{i}.xlsx' for i in range(1,5)],
        *[p.relative_to(ROOT).as_posix() for p in (ROOT/'只读工作区').iterdir() if p.is_file()],
        'data/sources.json','data/evidence_reviews.json','workflow/model_inputs.json']
    checks=[]
    for path in paths:
        original=subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT)
        digest=hashlib.sha256(original).hexdigest()
        checks.append(dict(path=path,base_sha256=digest,current_sha256=sha(ROOT/path),unchanged=digest==sha(ROOT/path)))
    result=dict(passed=all(r['unchanged'] for r in checks),base=BASE,checks=checks)
    dump(DEST/'protected_originals.json',result)
    return result

def regression(kind):
    reference=ROOT/('outputs/q1/p1_yx' if kind=='q1' else 'outputs/q2/p2_lb_national')
    fresh=ROOT/f'outputs/{kind}/q3_yx_regression'
    old=load(reference/'run_manifest.json');new=load(fresh/'run_manifest.json')
    errors=[];compared=0;values=0;hashes=[]
    tol=load(ROOT/'workflow/q3_inputs.json')['acceptance']
    def visit(a,b,path):
        nonlocal values
        if len(errors)>=20:return
        if isinstance(a,dict) and isinstance(b,dict):
            if set(a)!=set(b):errors.append(path+' keys');return
            for k in a:visit(a[k],b[k],path+'/'+str(k))
        elif isinstance(a,list) and isinstance(b,list):
            if len(a)!=len(b):errors.append(path+' length');return
            for i,(x,y) in enumerate(zip(a,b)):visit(x,y,path+'/'+str(i))
        elif isinstance(a,(int,float)) and isinstance(b,(int,float)):
            values+=1
            bound=tol['absolute_numeric_tolerance']+tol['relative_numeric_tolerance']*max(1,abs(a),abs(b))
            if 'residual' in path:bound=max(bound,tol['cash_absolute_tolerance_cny'] if 'cny' in path else tol['physical_residual_mwh'])
            if not(math.isfinite(a) and math.isfinite(b)) or abs(a-b)>bound:errors.append(dict(path=path,old=a,new=b,bound=bound))
        elif a!=b:
            if isinstance(a,str) and isinstance(b,str):
                try:x,y=json.loads(a),json.loads(b)
                except (ValueError,TypeError):errors.append(path+' text');return
                visit(x,y,path)
            else:errors.append(path+' value')
    if not new['status'].startswith('success'):errors.append('new run not successful')
    exclusions={'model_snapshot.zip','national_paths.png'} if kind=='q2' else set()
    names={p.name for p in reference.iterdir() if p.is_file()}-{'run_manifest.json'}-exclusions
    for name in sorted(names):
        a,b=reference/name,fresh/name;compared+=1
        ha,hb=sha(a),sha(b);hashes.append(dict(file=name,base=ha,reproduced=hb,byte_identical=ha==hb))
        if ha==hb:continue
        if kind=='q1':errors.append(name+' byte differs');continue
        if a.suffix=='.json':visit(load(a),load(b),name)
        elif a.suffix=='.csv':
            with a.open(encoding='utf-8',newline='') as f,b.open(encoding='utf-8',newline='') as g:visit(list(csv.DictReader(f)),list(csv.DictReader(g)),name)
        else:errors.append(name+' bytes differ')
    shutil.copy2(fresh/'run_manifest.json',DEST/f'{kind}_regression_manifest.json')
    result=dict(passed=not errors,reference=reference.relative_to(ROOT).as_posix(),fresh=fresh.relative_to(ROOT).as_posix(),
        files_compared=compared,numeric_values_compared=values,hashes=hashes,errors=errors,
        excluded={k:'code archive intentionally changed / image source numerical tables compared' for k in exclusions},
        original_manifest_sha256=sha(reference/'run_manifest.json'),fresh_manifest_sha256=sha(fresh/'run_manifest.json'))
    dump(DEST/f'{kind}_regression.json',result)
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--q2',action='store_true');args=p.parse_args();DEST.mkdir(exist_ok=True)
    results={'protected':protected(),'q1':regression('q1')}
    if args.q2:results['q2']=regression('q2')
    print(json.dumps({k:{x:y for x,y in v.items() if x not in ('hashes','checks')} for k,v in results.items()},ensure_ascii=False))
    return 0 if all(r['passed'] for r in results.values()) else 1

if __name__=='__main__':raise SystemExit(main())
