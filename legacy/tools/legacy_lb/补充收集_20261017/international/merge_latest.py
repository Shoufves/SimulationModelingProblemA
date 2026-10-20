import json
from pathlib import Path
p=Path(__file__).resolve().parent
j=json.loads((p/'jobs.json').read_text(encoding='utf-8')); d={x['id']:x for x in j}
for x in json.loads((p/'latest_jobs.json').read_text(encoding='utf-8')):d[x['id']]=x
d['MOFCOM_CBAM']['publication_date']='2026-07（按PDF封面）'
d['MOFCOM_CBAM']['agency']='商务部外贸发展事务局（商务部网站托管）'
d['MOFCOM_CBAM']['notes']+='；URL目录202511与正文2026年7月不一致，以正文版本标记'
d['EIA_CHOKEPOINTS_2026']['notes']+='；HTML仅壳页面，正文已在Chrome阅读；定量使用同页官方XLSX附件'
(p/'jobs.json').write_text(json.dumps(list(d.values()),ensure_ascii=False,indent=2),encoding='utf-8')
