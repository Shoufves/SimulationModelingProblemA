"""Archive and verify a primary research explanation of Chinese coal entry."""
from datetime import datetime,timezone
from hashlib import sha256
from pathlib import Path
from urllib.request import Request,urlopen
import json
import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT/"data/raw/q2_investor_behavior"
URL = "https://www.nber.org/system/files/working_papers/w25437/w25437.pdf"


def main():
    FOLDER.mkdir(parents=True,exist_ok=True)
    original = FOLDER/"nber_25437_2019.pdf"
    manifest = FOLDER/"source_manifest.json"
    old = json.loads(manifest.read_text("utf-8"))[0] if manifest.exists() else None
    if not original.exists():
        with urlopen(Request(URL,headers={"User-Agent":"Mozilla/5.0"}),timeout=30) as response:
            raw = response.read()
        if not raw.startswith(b"%PDF") or len(raw)<10000:
            raise ValueError("Invalid research original")
        original.write_bytes(raw)
    digest = sha256(original.read_bytes()).hexdigest()
    if old and digest != old["sha256"]:
        raise ValueError("Original research changed")
    with pdfplumber.open(original) as pdf:
        texts = [p.extract_text() or "" for p in pdf.pages]
    checks = {1:["WHY HAS CHINA OVERINVESTED IN COAL POWER?","Mengjia Ren","Lee G. Branstetter","January 2019"],
        2:["2013 to 2016","approval authority"],7:["equal share dispatch"],
        12:["business-stealing","if his firm did not"],13:["private investments tend to be excessive","firm therefore selects capacity"]}
    for page,phrases in checks.items():
        if any(p not in texts[page-1] for p in phrases):
            raise ValueError("Research page anchor changed: "+str(page))
    (FOLDER/"nber_25437_2019.txt").write_text("\n\n".join(texts),"utf-8")
    row = dict(id="nber_25437_2019",title="Why Has China Overinvested in Coal Power?",
        authors=["Mengjia Ren","Lee G. Branstetter","Brian K. Kovak","Daniel E. Armanios","Jiahai Yuan"],
        publisher="National Bureau of Economic Research",publication_date="2019-01",url=URL,
        path=original.relative_to(ROOT).as_posix(),sha256=digest,
        retrieved_at=old["retrieved_at"] if old else datetime.now(timezone.utc).isoformat(),
        status="original_working_paper_verified_not_peer_reviewed",
        scope="2013-2016 coal entry mechanism evidence, not future dispatch law or national parameter admission")
    manifest.write_text(json.dumps([row],ensure_ascii=False,indent=2)+"\n","utf-8")
    evidence = dict(source=row["path"],source_sha256=digest,pdf_pages=len(texts),verified_page_anchors=checks,
        interpretation="Private entrant profitability can differ from aggregate industry or social profitability. Equal-share output and regulated prices are historical mechanisms discussed by authors.",
        model_use="Justifies comparing investor objectives; no numerical calibration or guaranteed generation quota imported.",
        limits=["Working paper and historical selected policy episode, not official statistics",
                "Does not establish equal-share dispatch for all technologies or all years",
                "Our candidate LP accounts for own added capacity reducing utilisation; paper simplifies that belief",
                "Our sector financing pool does not reproduce paper firm-level ownership or administrative approval costs"])
    (FOLDER/"evidence.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n","utf-8")
    print(json.dumps(dict(pdf_pages=len(texts),verified_pages=list(checks),sha256=digest)))


if __name__=="__main__":
    main()
