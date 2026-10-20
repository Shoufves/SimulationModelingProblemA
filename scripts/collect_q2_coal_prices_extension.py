"""Archive additional official CTCI tables; never fill missing monthly observations."""
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "data/raw/q2_coal_prices_extension"
BASE = "https://nyj.guizhou.gov.cn/zwgk/xxgkml/zdlyxx/"
# A comparison table maps its two price cells to current/prior months, not to January/February.
SOURCES = [
    ("guizhou_2016_01_10", BASE+"tjsj/201704/t20170427_27677552.html", 2016, list(range(1, 11)), "official_repost"),
    ("guizhou_2016_11_comparison", BASE+"tjsj/201704/t20170427_27677555.html", 2016, [11, 10], "official_repost"),
    ("guizhou_2017_01_comparison", BASE+"tjsj/201704/t20170427_27677565.html", 2017, [1, 12], "official_repost"),
    ("guizhou_2017_01_06", BASE+"tjsj/201707/t20170717_27820313.html", 2017, list(range(1, 7)), "official_repost"),
    ("guizhou_2017_full", BASE+"tjsj/201801/t20180116_28119450.html", 2017, list(range(1, 13)), "official_repost"),
    ("guizhou_2018_full", BASE+"tjsj/201902/t20190202_28721873.html", 2018, list(range(1, 13)), "official_repost"),
    ("guizhou_2019_01_07", BASE+"yxxt/201910/t20191023_28881137.html", 2019, list(range(1, 8)), "official_repost"),
    ("guizhou_2019_full", BASE+"yxxt/202001/t20200123_44770637.html", 2019, list(range(1, 13)), "official_repost"),
    ("cctd_2020_01_comparison", "https://www.cctd.com.cn/show-46-199445-1.html", 2020, [1, 12], "industry_repost"),
]


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.rows, self.text = {}, [], []
        self.row = self.cell = None
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta" and "name" in attrs:
            self.meta[attrs["name"]] = attrs.get("content", "")
        if tag in ("script", "style"):
            self.hidden += 1
        if tag == "tr":
            self.row = []
        if tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, text):
        if not self.hidden:
            self.text.append(text)
        if self.cell is not None:
            self.cell.append(text)

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
    known = {r["id"]: r for r in json.loads(manifest_path.read_text("utf-8"))} if manifest_path.exists() else {}
    manifest, rows, overlaps = [], [], []
    unique = {}
    old = json.loads((ROOT / "data/raw/q2_coal_prices/evidence.json").read_text("utf-8"))
    previous = {(r["year"], r["month"]): r for r in old["deduplicated_national_months"] if r["value"] is not None}
    for key, url, year, months, authority in SOURCES:
        path = FOLDER / (key + ".html")
        if not path.exists():
            with urlopen(Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=45) as response:
                body = response.read()
            if len(body) < 3000:
                raise ValueError("Incomplete source: "+key)
            path.write_bytes(body)
        raw = path.read_bytes()
        digest = sha256(raw).hexdigest()
        if key in known and digest != known[key]["sha256"]:
            raise ValueError("Changed original: "+key)
        parser = Page()
        encoding = "gb18030" if authority == "industry_repost" else "utf-8"
        parser.feed(raw.decode(encoding))
        text = " ".join(parser.text)
        national = [r for r in parser.rows if r and re.sub(r"\s+", "", r[0]) == "全国"]
        if len(national) != 1:
            raise ValueError("Expected one national row: "+key)
        cells = national[0][1:]
        comparison = "comparison" in key
        if comparison:
            if len(cells) != 4 or not all(w in text for w in ("本期", "上期", "元/吨")):
                raise ValueError("Invalid comparison table: "+key)
            cells = cells[:2]
        else:
            flat = "".join("".join(r) for r in parser.rows)
            if len(cells) != len(months) or not all(f"{year}年{m:02d}月" in flat for m in months):
                raise ValueError("Invalid month headers: "+key)
        body_dates = re.findall(r"发布日期\s*[：:]\s*(\d{4}[/-]\d{1,2}[/-]\d{1,2})", text)
        published = parser.meta.get("PubDate")
        if authority == "industry_repost":
            found = re.search(r"2020-02-25\s+\d\d:\d\d(?::\d\d)?", text)
            if not found:
                raise ValueError("Industry repost publication date absent")
            published = found.group()
        record = dict(id=key, url=url, path=path.relative_to(ROOT).as_posix(), sha256=digest,
                      publisher="贵州省能源局" if authority == "official_repost" else "中国煤炭市场网",
                      authority=authority, original_publisher="国家发展改革委",
                      title=parser.meta.get("ArticleTitle") or re.search(r"<title>(.*?)</title>", raw.decode(encoding), re.S | re.I).group(1).strip(),
                      content_source=parser.meta.get("ContentSource") or "国家发改委 (visible repost source label)",
                      encoding=encoding, published_datetime=published,
                      original_table_release_dates=sorted(set(body_dates)),
                      retrieved_at=known.get(key, {}).get("retrieved_at", datetime.now(timezone.utc).isoformat()),
                      tax_basis="not explicit in this source; unknown", model_admission=False)
        manifest.append(record)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", "utf-8")
        (FOLDER / (key+".txt")).write_text(text, "utf-8")
        for i, (month, cell) in enumerate(zip(months, cells)):
            observation_year = year - 1 if comparison and month == 12 and months[0] == 1 else year
            value = float(cell)
            row = dict(year=observation_year, month=month, value=value,
                       unit="nominal_CNY_per_tonne_5000kcal_kg_delivered; VAT_basis_unverified",
                       source=record["path"], source_sha256=digest,
                       locator="全国 row, "+(("本期" if i == 0 else "上期") if comparison else f"{year}年{month:02d}月 column"),
                       published_datetime=published, original_table_release_dates=record["original_table_release_dates"])
            identity = observation_year, month
            for origin, pool in (("extension", unique), ("previous_archive", previous)):
                if identity in pool:
                    if pool[identity]["value"] != value:
                        raise ValueError("Conflicting overlap: "+str(identity))
                    overlaps.append(dict(year=identity[0], month=month, value=value, agrees=True, compared_with=origin))
            unique.setdefault(identity, row)
            rows.append(row)
    missing = [dict(year=y, month=m, value=None, missing_reason="not_acquired_in_extension")
               for y in range(2016, 2025) for m in range(1, 13) if (y, m) not in unique and (y, m) not in previous]
    complete = [y for y in range(2016, 2025) if all((y, m) in unique or (y, m) in previous for m in range(1, 13))]
    means = {str(y): sum((unique.get((y, m)) or previous[(y, m)])["value"] for m in range(1, 13))/12 for y in complete}
    evidence = dict(status="additional_originals_extracted_not_model_admitted", rows=rows,
                    deduplicated_national_months=list(unique.values()), verified_overlaps=overlaps,
                    complete_years_combining_previous_archive=complete,
                    annual_simple_means_combining_previous_archive=means,
                    annual_mean_scope="arithmetic mean of monthly indices, not annual procurement-volume-weighted price",
                    missing_months_combining_previous_archive=missing,
                    heat_kcal_kg=5000, heat_mwh_per_tonne=5.815,
                    definition_source="data/raw/q2_coal_prices/guizhou_index_method.html",
                    monthly_weight="provincial plant coal arrival tonnage; monitored coverage excludes Tibet",
                    tax_basis="not explicit in acquired primary methodology/tables; unknown",
                    tax_research="Some mineral-right appraisal reports describe CTCI as tax-inclusive delivered price, but this is not an index issuer statement and has not been admitted as tax-basis verification.",
                    model_admission=False, common_market_sensitivity_only=True,
                    blocked_uses=["industrial coal price observation", "tax-exclusive fuel price", "CECI splice as same index",
                                  "missing month as zero", "incomplete-year mean as annual price", "6000kcal same-tonne price"])
    (FOLDER / "evidence.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+"\n", "utf-8")
    print(json.dumps(dict(sources=len(manifest), national_months=len(unique), overlaps=len(overlaps),
                         complete_years=complete, means=means), ensure_ascii=False))


if __name__ == "__main__":
    main()
