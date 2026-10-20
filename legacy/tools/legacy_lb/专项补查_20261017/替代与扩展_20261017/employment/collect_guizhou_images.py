import sys,json,re,concurrent.futures
from pathlib import Path
from urllib.parse import urljoin
BASE=Path(__file__).resolve().parent
ROOT=BASE.parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from collect import fetch
html=(BASE/'originals/guizhou.html').read_text(encoding='utf-8')
urls=re.findall(r'<img[^>]+src=["\']([^"\']+)',html,re.I)
urls=[u for u in urls if 'W020250324' in u and '_ORIGIN.jpg' in u]
jobs=[dict(id=f'GUIZHOU_IMAGE_{i}',url=urljoin('http://stjj.guizhou.gov.cn/tjsj/tjfbyjd/202503/t20250321_87235597.html',u),file=f'{BASE.relative_to(ROOT).as_posix()}/originals/guizhou_page_{i:02}.jpg',title='贵州五经普整套公报扫描页',publication_date='2025-03-21') for i,u in enumerate(urls[:20])]
with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool: entries=list(pool.map(fetch,jobs))
(BASE/'sources_guizhou_images.json').write_text(json.dumps(entries,ensure_ascii=False,indent=2),encoding='utf-8')
for e in entries: print(e['id'],e['status'],e.get('bytes',e.get('error')))
