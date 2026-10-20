"""Execute frozen independent conditions in two isolated subprocesses."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import argparse
import hashlib
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser();p.add_argument('--protocol',default='workflow/n2_validation_r3.json');p.add_argument('--output',required=True)
    p.add_argument('--runner',choices=['scripts/run_n2_research.py','scripts/run_n2_anchored.py','scripts/run_n2_current.py'],default='scripts/run_n2_research.py')
    p.add_argument('--workers',type=int,choices=[1,2,4],default=2)
    args=p.parse_args();base=ROOT/args.output;base.mkdir(parents=True,exist_ok=False)
    raw=(ROOT/args.protocol).read_bytes();protocol=json.loads(raw)
    (base/'protocol.json').write_bytes(raw)
    (base/'protocol.sha256').write_text(hashlib.sha256(raw).hexdigest()+'\n',encoding='utf-8')
    work=[]
    for c in protocol['conditions']:
        selected={**protocol,'conditions':[c],'parent_protocol_sha256':hashlib.sha256(raw).hexdigest()}
        path=base/(c['id']+'_protocol.json')
        path.write_text(json.dumps(selected,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        work.append((c['id'],path))
    def run(item):
        name,path=item
        with (base/(name+'.log')).open('w',encoding='utf-8') as log:
            result=subprocess.run([sys.executable,'-B','-X','utf8',args.runner,
                '--protocol',path.relative_to(ROOT).as_posix(),'--output',(base/name).relative_to(ROOT).as_posix()],
                cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        return dict(condition=name,returncode=result.returncode)
    results=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for done in as_completed([pool.submit(run,w) for w in work]):
            result=done.result();results.append(result);print(json.dumps(result),flush=True)
            (base/'execution.json').write_text(json.dumps(results,indent=2)+'\n',encoding='utf-8')
    if any(r['returncode'] for r in results):raise SystemExit(1)


if __name__=='__main__':main()
