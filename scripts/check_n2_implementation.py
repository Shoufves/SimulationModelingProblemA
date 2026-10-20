"""Machine receipt for isolated PR14 research tests and original-asset preservation."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
BASE='d0c234313509f159f1c449a2372c35686ce9cb15'


def main():
    out=ROOT/'tmp/n2';out.mkdir(parents=True,exist_ok=True)
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests/research'))
    start=time.perf_counter()
    with (out/'research_tests.log').open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    protected=['src/energy_model','只读工作区','data/sources.json','data/evidence_reviews.json',
        'workflow/model_inputs.json','workflow/q3_inputs.json','outputs/q1','outputs/q2','outputs/q3']
    changes=subprocess.check_output(['git','diff','--name-only',BASE,'--',*protected],cwd=ROOT,text=True,encoding='utf-8').splitlines()
    files=['tests/research/test_pr14_retirement.py','tests/research/test_research_comparisons.py',
        'src/transition_research/retirement.py','src/transition_research/anchored.py','src/transition_research/current_information.py']
    receipt=dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        passed=result.wasSuccessful() and not changes,seconds=time.perf_counter()-start,
        protected_scientific_files_changed=changes,preservation_base=BASE,python=sys.version,
        hashes={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in files})
    (out/'research_tests.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt,ensure_ascii=False,indent=2))
    if not receipt['passed']:
        print((out/'research_tests.log').read_text('utf-8'));return 1
    return 0


if __name__=='__main__':raise SystemExit(main())
