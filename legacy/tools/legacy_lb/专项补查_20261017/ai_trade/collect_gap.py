import sys,json,concurrent.futures
from pathlib import Path
P=Path(__file__).resolve().parent
sys.path.insert(0,str(P.parents[1]/'scripts'))
import collect
collect.ROOT=P
jobs=json.loads((P/'jobs.json').read_text(encoding='utf-8'))
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex: results=list(ex.map(collect.fetch,jobs))
(P/'sources.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
for r in results:print(r['id'],r['status'],r.get('bytes',r.get('error')),flush=True)
