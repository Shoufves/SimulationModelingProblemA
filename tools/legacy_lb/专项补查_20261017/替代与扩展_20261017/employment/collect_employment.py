import sys,json,concurrent.futures
from pathlib import Path
BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from collect import fetch
PREFIX=BASE.relative_to(ROOT).as_posix()
jobs=[
 dict(id='NATIONAL',geography='全国',publication_date='2024-12-26',url='https://www.stats.gov.cn/sj/zxfb/202412/t20241226_1957895.html',name='national.html'),
 dict(id='SHAANXI',geography='陕西',publication_date='2025-03-17',url='https://tjj.shaanxi.gov.cn/tjsj/ndsj/tjgb/qs_444/202503/t20250317_3462798.html',name='shaanxi.html'),
 dict(id='SHANDONG',geography='山东',publication_date='2025-04-10',url='http://tjj.shandong.gov.cn/art/2025/4/10/art_6293_10317362.html',name='shandong.html'),
 dict(id='SHANDONG_TABLE32',geography='山东',publication_date='2025-04-10',url='http://tjj.shandong.gov.cn/picture/-1/4ccc319535c8428fbb75756a228a75a4.png',name='shandong_table32.png'),
]
extra=BASE/'extra_jobs.json'
if extra.exists(): jobs+=json.loads(extra.read_text(encoding='utf-8'))
for j in jobs:
 j.update(file=f"{PREFIX}/originals/{j.pop('name')}",statistical_period='2023年末',title=f"{j['geography']}第五次全国经济普查公报（第三号）",definition='工业企业法人单位从业人员；煤炭开采和洗选业')
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
 entries=list(pool.map(fetch,jobs))
for e in entries: print(e['id'],e['status'],e.get('bytes',e.get('error')),flush=True)
(BASE/'sources_employment.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
