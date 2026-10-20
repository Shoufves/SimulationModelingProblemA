"""Run the separately labelled fixed-project ablation against PR14."""
import hashlib
import json
from pathlib import Path
import sys
import run_n2_research as runner
from transition_research.fixed_pipeline import activate
from transition_research.anchored import RULES


if __name__=='__main__':
    runner.activate=activate;runner.RULES=RULES
    try:runner.main()
    finally:
        folder=runner.ROOT/sys.argv[sys.argv.index('--output')+1]
        path=folder/'provenance.json'
        if path.exists():
            value=json.loads(path.read_text('utf-8'))
            for name in ['src/transition_research/anchored.py','src/transition_research/fixed_pipeline.py','scripts/run_n2_fixed.py']:
                blob=(runner.ROOT/name).read_bytes();value['files'][name]=hashlib.sha256(blob).hexdigest()
                (folder/Path(name).name).write_bytes(blob)
            value['scope']='fixed_committed_generation_infrastructure; demand_devices_remain_endogenous'
            path.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
