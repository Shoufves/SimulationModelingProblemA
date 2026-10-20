"""Preserve an official settlement-delay report; no tariff values inferred."""
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'data/raw/q2_settlement_review'
URL = 'https://zfxxgk.nea.gov.cn/2020-07/27/c_139254469.htm'


class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    path = DEST / 'nea_2019_special_supervision.html'
    manifest = DEST / 'source_manifest.json'
    if path.exists():
        raw = path.read_bytes()
        if not manifest.exists():
            raise ValueError('Existing original has no acquisition record')
        record = json.loads(manifest.read_text('utf-8'))['sources'][0]
        if hashlib.sha256(raw).hexdigest() != record['sha256']:
            raise ValueError('Saved original changed')
    else:
        request = urllib.request.Request(URL, headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
        record = dict(id='nea_2019_settlement_delays', url=URL,
            path=path.relative_to(ROOT).as_posix(), publisher='国家能源局',
            published_on='2020-07-27', retrieved_at=datetime.now(timezone.utc).isoformat(),
            sha256=hashlib.sha256(raw).hexdigest(),
            notes='Qualitative settlement-delay evidence only; not a national gas price or cash collection ratio',
            admitted=False)
    parser = TextExtractor()
    parser.feed(raw.decode('utf-8'))
    text = '\n'.join(parser.parts)
    anchors = ['2019年重点专项监管报告', '电费结算和补贴发放不及时',
               '承兑汇票比例偏高', '月度支付购电费与应付购电费存在差异', '差额在年底核对清算']
    for anchor in anchors:
        if anchor not in text:
            raise ValueError('Missing source anchor: '+anchor)
    if not path.exists():
        path.write_bytes(raw)
        manifest.write_text(json.dumps({'sources':[record]},ensure_ascii=False,indent=2)+'\n','utf-8')
    start = text.index('（九）电费结算和补贴发放不及时')
    end = text.index('（十）',start)
    evidence = dict(source_sha256=record['sha256'], section='二（九）、专栏9第26—28项',
        excerpt=text[start:end], model_use='Motivate accrued/cash distinction; no numerical calibration',
        missing=['2019—2024 national gas electricity price', 'national energy-payment collection ratio',
                 'national delay distribution', 'capacity-income inclusion in NEA sales revenue'],
        price_search_result='Focused search and official archive inspection did not retrieve a replacement national tariff table; this is not evidence of nonexistence')
    (DEST/'evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n','utf-8')
    print(json.dumps({'original':record['path'],'sha256':record['sha256'],'numeric_observations_added':0},ensure_ascii=False))


if __name__ == '__main__':
    main()
