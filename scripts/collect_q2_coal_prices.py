"""Archive official delivered-coal index tables without filling absent months."""
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data/raw/q2_coal_prices"
SOURCES = [
    ("guizhou_index_method", "https://nyj.guizhou.gov.cn/zwgk/xxgkml/zdlyxx/tjsj/201704/t20170427_27677544.html", "贵州省能源局（转载指数编制方案）", "2016-10-19", None),
    ("guizhou_ndrc_index_2014", "https://nyj.guizhou.gov.cn/zwgk/xxgkml/zdlyxx/tjsj/201704/t20170427_27677542.html", "贵州省能源局（转载国家发展改革委）", "2016-10-19", 2014),
    ("guizhou_ndrc_index_2015", "https://nyj.guizhou.gov.cn/zwgk/xxgkml/zdlyxx/tjsj/201704/t20170427_27677541.html", "贵州省能源局（转载国家发展改革委）", "2016-10-19", 2015),
    ("guizhou_ndrc_index_2016", "https://nyj.guizhou.gov.cn/zwgk/xxgkml/zdlyxx/tjsj/201704/t20170427_27677540.html", "贵州省能源局（转载国家发展改革委）", "2016-10-19", 2016),
    ("guizhou_ndrc_index_2016_partial", "https://nyj.guizhou.gov.cn/zwgk/xxgkml/zdlyxx/tjsj/201704/t20170427_27677543.html", "贵州省能源局（转载国家发展改革委）", "2016-10-19", 2016),
]


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.text = [], None, None, []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "tr":
            self.row = []
        if tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.hidden = max(0, self.hidden - 1)
        if tag in ("td", "th") and self.cell is not None:
            self.row.append("".join(self.cell).strip())
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def main():
    FOLDER.mkdir(parents=True, exist_ok=True)
    manifest_path = FOLDER / "source_manifest.json"
    old = json.loads(manifest_path.read_text("utf-8")) if manifest_path.exists() else []
    known = {r["id"]: r for r in old}
    rows, records = [], []
    for key, url, publisher, published, year in SOURCES:
        path = FOLDER / (key + ".html")
        if not path.exists():
            with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=35) as response:
                body = response.read()
            if len(body) < 3000:
                raise ValueError("Incomplete official source: " + key)
            path.write_bytes(body)
        digest = sha256(path.read_bytes()).hexdigest()
        if key in known and digest != known[key]["sha256"]:
            raise ValueError("Changed archived source: " + key)
        parsed = Tables()
        parsed.feed(path.read_bytes().decode("utf-8"))
        text = " ".join(parsed.text)
        if year is None:
            if not all(p in text for p in ("5000", "到厂", "西藏除外", "到货量")):
                raise ValueError("Coal index definition missing")
        else:
            national = [r for r in parsed.rows if r and r[0].replace(" ", "") == "全国"]
            if len(national) != 1:
                raise ValueError("Expected exactly one national row")
            if year == 2016 and key.endswith('_2016'):
                if len(national[0]) != 5 or not all(p in text for p in ("2016年9月", "本期", "上期", "元/吨")):
                    raise ValueError("Expected September comparison table")
                values = {9: national[0][1], 8: national[0][2]}
            else:
                if len(national[0]) not in ((10, 13) if year == 2016 else (13,)):
                    raise ValueError("Expected twelve month cells")
                values = dict(enumerate(national[0][1:], 1))
            for month in range(1, 13):
                value = values.get(month, "")
                rows.append(dict(year=year, month=month, value=None if not value else float(value),
                    unit="nominal_CNY_per_tonne_5000kcal_kg_delivered; VAT_basis_unverified",
                    geography="national_index_coverage", missing_reason=("not_present_in_original" if month not in values
                        else "blank_in_original" if not value else None),
                    source=path.relative_to(ROOT).as_posix(), source_sha256=digest,
                    locator=("not present" if month not in values else f"全国 row, {month}月 column" if not key.endswith('_2016') else
                             "全国 row, 本期" if month == 9 else "全国 row, 上期" if month == 8 else "not present")))
        (FOLDER / (key + ".txt")).write_text(text, "utf-8")
        records.append(known.get(key) or dict(id=key, url=url, publisher=publisher,
            published_date=published, observation_year=year, path=path.relative_to(ROOT).as_posix(),
            sha256=digest, retrieved_at=datetime.now(timezone.utc).isoformat(),
            notes="Public official index; unit, heat and tax definitions require separate verified methodology; no default model admission"))
        records[-1].update(published_date=published,
            original_table_release_date="2016-10-14" if key.endswith('_2016') else None,
            notes="Official repost; unit/heat/arrival weighting checked against saved methodology; tax basis unverified; no model admission")
        # Persist acquisition identity even if a later source is unavailable.
        retained = {r['id']:r for r in old}
        retained.update({r['id']:r for r in records})
        manifest_path.write_text(json.dumps(list(retained.values()), ensure_ascii=False, indent=2)+"\n", "utf-8")
    unique = {}
    for row in rows:
        key = row['year'], row['month']
        if key in unique and unique[key]['value'] is not None and row['value'] is not None:
            if unique[key]['value'] != row['value']:
                raise ValueError('Overlapping official monthly indices disagree')
        if key not in unique or unique[key]['value'] is None:
            unique[key] = row
    annual_rows = list(unique.values())
    output = dict(status="official_index_extraction_not_model_admitted", rows=rows,
        deduplicated_national_months=annual_rows,
        complete_years=[y for y in (2014, 2015, 2016) if all(r['value'] is not None for r in annual_rows if r['year']==y)],
        annual_simple_means={str(y): sum(r['value'] for r in annual_rows if r['year']==y)/12
            for y in (2014,2015,2016) if all(r['value'] is not None for r in annual_rows if r['year']==y)},
        annual_mean_scope="arithmetic mean of published monthly indices; not annual procurement-volume weighted price",
        heat_mwh_per_tonne=5000*4.1868/3600,
        monthly_weight="provincial plant coal arrival tonnage; monitored coverage excludes Tibet",
        tax_basis="not explicit in acquired methodology; no tax-exclusive model cost admission",
        blocked_uses=["blank months as zero", "nine-month mean as full-year index",
                      "apply same tonnage price to 6000kcal coal", "equate VAT-inclusive price to tax-exclusive cost",
                      "treat regional/source coverage as a census of all power plants"])
    (FOLDER / "evidence.json").write_text(json.dumps(output, ensure_ascii=False, indent=2)+"\n", "utf-8")
    print(json.dumps({k:v for k,v in output.items() if k not in ("rows", "deduplicated_national_months")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
