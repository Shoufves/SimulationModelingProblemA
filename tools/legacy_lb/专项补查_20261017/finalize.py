from pathlib import Path
import json,csv,hashlib
from collections import Counter
from pypdf import PdfReader
P=Path(__file__).resolve().parent
combined=[]
for folder,manifest in [('ai_trade','sources.json'),('household_employment','sources_household_employment.json')]:
    entries=json.loads((P/folder/manifest).read_text(encoding='utf-8'))
    for r in entries:
        r=dict(r)
        if folder=='ai_trade': f=P/folder/r['file']
        else: f=P.parent/r['file']
        r['file']=str(f.relative_to(P))
        if r['status']=='saved':
            assert f.exists(),f
            b=f.read_bytes()
            assert hashlib.sha256(b).hexdigest()==r['sha256'],f
            if f.suffix=='.pdf':r['verified_pdf_pages']=len(PdfReader(f).pages)
        combined.append(r)
(P/'sources_combined.json').write_text(json.dumps(combined,ensure_ascii=False,indent=2),encoding='utf-8')
cols=['id','title','agency','publication_date','coverage','statistical_period','url','file','status','bytes','sha256','verified_pdf_pages','notes','limitations','error']
with (P/'资料来源目录.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.DictWriter(f,cols,extrasaction='ignore');w.writeheader();w.writerows(combined)
derived=[]
for f in (P/'ai_trade/derived').glob('*.csv'):
    b=f.read_bytes();derived.append(dict(file=str(f.relative_to(P)),bytes=len(b),sha256=hashlib.sha256(b).hexdigest()))
(P/'ai_trade/derived_files_manifest.json').write_text(json.dumps(derived,ensure_ascii=False,indent=2),encoding='utf-8')
summary=dict(status_counts=dict(Counter(r['status'] for r in combined)),saved_bytes=sum(r.get('bytes',0) for r in combined if r['status']=='saved'),checks='All saved source hashes matched; all saved PDFs opened; derived arithmetic checked separately.')
(P/'validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8');print(summary)
