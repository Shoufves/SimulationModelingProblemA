"""Run final current-information screening; preserve all prior research arms."""
import hashlib
import json
from pathlib import Path
import sys
import run_n2_research as runner
from transition_research.current_information import activate
from transition_research.anchored import RULES


if __name__=='__main__':
    runner.activate=activate;runner.RULES=RULES
    try:runner.main()
    finally:
        folder=runner.ROOT/sys.argv[sys.argv.index('--output')+1]
        path=folder/'provenance.json'
        if path.exists():
            for result_path in folder.glob('*__anchored_guard.json'):
                result=json.loads(result_path.read_text('utf-8'))
                result['summary']['forecast_count_unit']='mixed_static_lp_calls_and_rollout_years_not_total_lp_solves'
                result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            summary=folder/'summary.json'
            if summary.exists():
                rows=json.loads(summary.read_text('utf-8'))
                for row in rows:
                    if row['name'].endswith('__anchored_guard'):
                        row['forecast_count_unit']='mixed_static_lp_calls_and_rollout_years_not_total_lp_solves'
                summary.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            value=json.loads(path.read_text('utf-8'))
            for name in ['src/transition_research/anchored.py','src/transition_research/current_information.py','scripts/run_n2_current.py']:
                blob=(runner.ROOT/name).read_bytes();value['files'][name]=hashlib.sha256(blob).hexdigest()
                (folder/Path(name).name).write_bytes(blob)
            value['forecast_information']='current observed GDP growth, fuel price, availability; known technology/lifetime rules; no future realised event or GDP regime'
            path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
