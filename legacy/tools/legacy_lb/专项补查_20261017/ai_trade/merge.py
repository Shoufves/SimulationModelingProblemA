import json
from pathlib import Path
P=Path(__file__).resolve().parent
j={x['id']:x for x in json.loads((P/'jobs.json').read_text(encoding='utf-8'))}
j.update({x['id']:x for x in json.loads((P/'extras.json').read_text(encoding='utf-8'))})
(P/'jobs.json').write_text(json.dumps(list(j.values()),ensure_ascii=False,indent=2),encoding='utf-8')
