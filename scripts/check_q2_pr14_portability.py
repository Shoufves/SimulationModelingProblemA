"""Reproduce two full Q2 paths from a clean payload, without Git or old tmp."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from run_q2_pr14 import ROOT, CONFIG, REVIEW, verify_payload, sha, load, save


def main():
    review,_=verify_payload()
    destination=ROOT/'tmp/q2_integration'/('clean_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    destination.mkdir(parents=True,exist_ok=False)
    files=[r['path'] for r in review['files']]+[REVIEW,CONFIG,'run.py','scripts/run_q2_pr14.py']
    for rel in files:
        target=destination/rel;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/rel,target)
    environment=dict(os.environ,PYTHONHASHSEED='81739')
    environment.pop('PYTHONPATH',None)
    out=ROOT/'outputs/q2_pr14_review';out.mkdir(parents=True,exist_ok=True)
    command=[sys.executable,'-I','-B','-X','utf8','scripts/run_q2_pr14.py','--only','S0',
             'sensitivity_gdp_growth_delta_1','--output-dir','outputs/q2_pr14/clean_reproduction']
    start=time.perf_counter()
    with (out/'clean_delivery.log').open('w',encoding='utf-8') as stream:
        result=subprocess.run(command,cwd=destination,env=environment,stdout=stream,stderr=subprocess.STDOUT)
    folder=destination/'outputs/q2_pr14/clean_reproduction'
    latest=load(folder/'latest.json');attempt=folder/latest['attempt']
    receipt=load(attempt/'integration.json')
    proof=dict(passed=result.returncode==0 and receipt['status']=='passed',exit_code=result.returncode,
        seconds=time.perf_counter()-start,pythonhashseed=environment['PYTHONHASHSEED'],command=command[5:],
        no_git_directory=not (destination/'.git').exists(),initial_tree_had_no_tmp=True,
        exported_files={p:sha(destination/p) for p in files},cases=receipt.get('cases'),
        full_q2_delivery=receipt.get('full_q2_delivery'),verification=load(attempt/'verification.json'),
        input_hashes=receipt.get('input_hashes'),checker_sha256=sha(Path(__file__)))
    save(out/'clean_delivery.json',proof)
    print(json.dumps({k:v for k,v in proof.items() if k not in ('exported_files','input_hashes','verification')},indent=2))
    return int(not proof['passed'])


if __name__=='__main__':raise SystemExit(main())
