"""Extract a reproducible narrow locator from the saved official HTML."""
from pathlib import Path
from html.parser import HTMLParser
import hashlib
import json

ROOT = Path(__file__).resolve().parent
FILE = ROOT / "nea_20170105_planning_briefing.html"

class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())

raw = FILE.read_bytes()
parser = Text()
parser.feed(raw.decode("utf-8-sig"))
text = "\n".join(parser.parts)
(ROOT / "nea_20170105_planning_briefing.txt").write_text(text, encoding="utf-8")
anchor = "截至2015年底"
start = text.index(anchor)
excerpt = text[max(0,start-90):start+220]
assert all(s in excerpt for s in ("480万千瓦", "250亿千瓦时", "8000万吨"))
manifest = {
    "source_url": "https://www.nea.gov.cn/xwfb/20170105zb1/iframe_text.htm",
    "publisher": "国家能源局",
    "title": "能源发展十三五及可再生能源发展十三五规划发布会文字实录",
    "published": "2017-01-05",
    "retrieved_local_date": "2026-10-20",
    "path": FILE.name,
    "sha256": hashlib.sha256(raw).hexdigest(),
    "bytes": len(raw),
    "locator": "答记者问：垃圾焚烧处理方式；文本锚点“截至2015年底”",
    "scope": "中国截至2015年底垃圾焚烧发电行业；约数；未给化石/生物电量拆分",
    "observations": {
        "capacity_kw": 4800000,
        "annual_generation_kwh": 25000000000,
        "annual_treatment_tonnes": 80000000,
        "all_approximate": True
    },
    "status": "research_classification_evidence_not_production_admitted",
    "previous_catalog_check": "rg over data/raw and data/catalog found no matching URL or the 480/250/8000 triplet",
    "excerpt": excerpt,
}
(ROOT / "source_manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
print(json.dumps(manifest,ensure_ascii=False,indent=2))
