import csv,json,sys,hashlib,shutil,re
from pathlib import Path
BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from collect import TextParser,decode
manifest=json.loads((BASE/'sources_employment.json').read_text(encoding='utf-8'))
old=json.loads((ROOT/'专项补查_20261017/household_employment/sources_household_employment.json').read_text(encoding='utf-8'))
for e in old:
 if e['id'] in ['SX_CENSUS_2023','SX_CENSUS_TABLE32'] or e.get('geography')=='内蒙古':
  e=dict(e); src=ROOT/e['file']; dst=BASE/'originals'/src.name
  shutil.copy2(src,dst); e['file']=dst.relative_to(ROOT).as_posix()
  manifest.append(e)
for e in manifest:
 p=ROOT/e['file']
 if p.exists():
  data=p.read_bytes()
  e.update(status='saved',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
  e.pop('error',None)
  if p.suffix=='.html':
   parser=TextParser();parser.feed(decode(data))
   p.with_suffix('.txt').write_text(re.sub(r'\n\s*\n+','\n',''.join(parser.parts)),encoding='utf-8')
manifest+=json.loads((BASE/'sources_guizhou_images.json').read_text(encoding='utf-8'))
by_id={e['id']:e for e in manifest}
nmg=next(e for e in manifest if e.get('geography')=='内蒙古')
rows=[
 ('全国','NATIONAL','1.0','万个','277.2','万人','表3-2','全国汇总；保留原表舍入精度'),
 ('山西','SX_CENSUS_2023','3000','个','93.27','万人','表3-2','原图人工核验'),
 ('内蒙古',nmg['id'],'1077','个','19.9','万人','表3-2','自治区全域；玉泉区政府转载，原发布2025-03-18，转载2025-05-21'),
 ('陕西','SHAANXI','1051','个','19.78','万人','表3-2','HTML原表'),
 ('山东','SHANDONG','213','个','15.9','万人','表3-2','原图人工核验；正文上标1不得拼接到总企业数'),
 ('河南','HENAN','470','个','229369','人','表3-2','原图人工核验'),
 ('黑龙江','HEILONGJIANG','490','个','147045','人','表3-2','HTML原表'),
 ('云南','YUNNAN','525','个','76506','人','表3-2','网页发布2025-02-18；正文署期2025-02-17；系统证书下载'),
 ('新疆','XINJIANG','289','个','4.81','万人','表3-1','原文称全疆；公报未明确单列兵团，合并兵团数据前应另核范围'),
 ('贵州','GUIZHOU','899','个','212727','人','表3-2；整套扫描第13页（文件序号12）','正文署期2025-03-20；网页发布2025-03-21；人工核图'),
]
columns=['region','source_id','statistical_period','industry','industry_code','definition','enterprise_value_original','enterprise_unit_original','enterprise_count_converted','employment_value_original','employment_unit_original','employment_persons_converted','employment_10k_persons','table','publication_date','source_url','source_file','notes']
records=[]
for region,sid,n,nu,v,vu,table,note in rows:
 e=by_id[sid]; persons=float(v)*(10000 if vu=='万人' else 1)
 records.append(dict(zip(columns,[region,sid,'2023-12-31','煤炭开采和洗选业','06','工业企业法人单位从业人员；年末存量',n,nu,int(float(n)*(10000 if nu=='万个' else 1)),v,vu,int(round(persons)),f'{persons/10000:.4f}'.rstrip('0').rstrip('.'),table,e['publication_date'],e['url'],e['file'],note])))
with (BASE/'煤炭采洗就业_2023年末_分省扩展.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,columns);w.writeheader();w.writerows(records)
(BASE/'sources_employment.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
lines=['# 来源与原件清单','','|来源ID|地区/标题|原件|字节|SHA256|','|---|---|---|---:|---|']
for e in manifest: lines.append(f"|{e['id']}|{e.get('geography',e['title'])}|{e['file']}|{e.get('bytes','')}|{e.get('sha256','')}|")
(BASE/'01_来源清单.md').write_text('\n'.join(lines),encoding='utf-8')
print('CSV rows',len(records),'sources',len(manifest),'saved',sum(e['status']=='saved' for e in manifest))
for r in records: print(r['region'],r['employment_value_original'],r['employment_unit_original'])
