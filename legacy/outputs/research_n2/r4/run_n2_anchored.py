"""Execute the R4 refinement with the same PR14 experiment harness."""
import hashlib
import json
from pathlib import Path
import sys
import run_n2_research as runner
from transition_research.anchored import activate,RULES


if __name__=='__main__':
    runner.activate=activate
    runner.RULES=RULES
    try:
        runner.main()
    finally:
        if '--output' in sys.argv:
            folder=runner.ROOT/sys.argv[sys.argv.index('--output')+1]
            path=folder/'provenance.json'
            if path.exists():
                value=json.loads(path.read_text('utf-8'))
                for name in ['src/transition_research/anchored.py','scripts/run_n2_anchored.py']:
                    blob=(runner.ROOT/name).read_bytes()
                    value['files'][name]=hashlib.sha256(blob).hexdigest()
                    (folder/Path(name).name).write_bytes(blob)
                path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
