"""Download public sources, preserve originals and record provenance. Python stdlib only."""
import argparse, concurrent.futures, csv, hashlib, json, re, sys, time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.request import Request, urlopen
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]

class TextParser(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.skip=0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style'): self.skip+=1
        if tag in ('p','div','tr','br','h1','h2','h3','li'): self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script','style'): self.skip=max(0,self.skip-1)
    def handle_data(self, data):
        if not self.skip: self.parts.append(data)

def decode(data):
    for enc in ('utf-8-sig','gb18030','utf-16'):
        try: return data.decode(enc)
        except UnicodeError: pass
    return data.decode('utf-8',errors='replace')

def fetch(job):
    entry=dict(job); entry['retrieved_at']=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'); entry['status']='failed'
    path=ROOT/job['file']; path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.stat().st_size>0 and not job.get('refresh'):
        data=path.read_bytes(); entry.update(status='saved',bytes=len(data),sha256=hashlib.sha256(data).hexdigest()); return entry
    try:
        request=Request(job['url'],headers={'User-Agent':'Mozilla/5.0 (public academic data collection)','Accept':'*/*'})
        with urlopen(request, timeout=55) as response:
            data=response.read(); entry['final_url']=response.url; entry['content_type']=response.headers.get('Content-Type','')
        if not data: raise ValueError('Empty response')
        if path.suffix.lower()=='.pdf' and not data.startswith(b'%PDF'): raise ValueError('Response is not PDF')
        if path.suffix.lower()=='.xlsx' and not data.startswith(b'PK'): raise ValueError('Response is not XLSX')
        if path.suffix.lower()=='.csv' and b'<html' in data[:1000].lower(): raise ValueError('HTML instead of CSV')
        path.write_bytes(data)
        if path.suffix.lower() in ('.html','.htm'):
            parser=TextParser(); parser.feed(decode(data)); text=re.sub(r'\n\s*\n+', '\n', ''.join(parser.parts)); path.with_suffix('.txt').write_text(text,encoding='utf-8')
        entry.update(status='saved',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
    except Exception as exc: entry['error']=str(exc)
    return entry

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('jobs'); args=ap.parse_args()
    jobs=json.loads(Path(args.jobs).read_text(encoding='utf-8-sig'))
    manifest=ROOT/'sources.json'; entries=json.loads(manifest.read_text(encoding='utf-8')) if manifest.exists() else []
    by_id={r['id']:r for r in entries}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        for entry in pool.map(fetch,jobs):
            by_id[entry['id']]=entry; print(entry['id'],entry['status'],entry.get('bytes',entry.get('error')),flush=True)
    manifest.write_text(json.dumps(list(by_id.values()),ensure_ascii=False,indent=2),encoding='utf-8')
    columns=['id','title','agency','category','coverage','url','file','status','retrieved_at','bytes','sha256','notes','error']
    with (ROOT/'资料来源目录.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,columns,extrasaction='ignore'); writer.writeheader(); writer.writerows(by_id.values())

if __name__=='__main__': main()
