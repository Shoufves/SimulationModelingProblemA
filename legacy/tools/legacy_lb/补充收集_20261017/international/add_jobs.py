import json
from pathlib import Path
p=Path(__file__).resolve().parent
a=json.loads((p/'jobs.json').read_text(encoding='utf-8')); b=json.loads((p/'extras.json').read_text(encoding='utf-8'))
d={x['id']:x for x in a};d.update({x['id']:x for x in b})
(p/'jobs.json').write_text(json.dumps(list(d.values()),ensure_ascii=False,indent=2),encoding='utf-8')
