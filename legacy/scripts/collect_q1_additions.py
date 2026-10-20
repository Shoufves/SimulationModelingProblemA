"""Explicit download of immutable public Pink Sheet releases for Q1 review.

Never used by the offline q1 run; no quarantined workbook is overwritten.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,urllib.request
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[1]
BASE='https://thedocs.worldbank.org/en/doc/5d903e848db1d1b83e0ec8f744e55570-0350012021/related/'

def fetch(year):
    url=BASE+f'CMO-Pink-Sheet-January-{year}.pdf'
    path=ROOT/f'data/raw/q1/wb_pink_january_{year}.pdf'
    path.parent.mkdir(parents=True,exist_ok=True)
    manifest=ROOT/'data/raw/q1/retrievals.json'
    existing=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else []
    if path.exists():
        content=path.read_bytes()
        prior=next((r for r in existing if r.get('path')==path.relative_to(ROOT).as_posix()),None)
        if prior is None or prior.get('sha256')!=hashlib.sha256(content).hexdigest():
            raise ValueError('Existing raw file lacks matching acquisition record; review before changing provenance')
        return prior
    else:
        with urllib.request.urlopen(url,timeout=40) as response:
            content=response.read(); final=response.url
        if not content.startswith(b'%PDF'):raise ValueError('Not a PDF')
        path.write_bytes(content)
    return dict(source_id=f'Q1_WB_PINK_JAN_{year}',title=f'World Bank Pink Sheet January {year}',
                publisher='World Bank',url=url,final_url=final,retrieved_at=datetime.now(timezone.utc).isoformat(),
                path=path.relative_to(ROOT).as_posix(),sha256=hashlib.sha256(content).hexdigest(),
                status='downloaded_pending_content_review')

if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=2) as pool:records=list(pool.map(fetch,[2023,2025]))
    dest=ROOT/'data/raw/q1/retrievals.json'
    existing=json.loads(dest.read_text(encoding='utf-8')) if dest.exists() else []
    by_path={r['path']:r for r in records}
    merged=[by_path.pop(r.get('path'),r) for r in existing]
    merged.extend(by_path.values())
    dest.write_text(json.dumps(merged,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(records,ensure_ascii=False))
