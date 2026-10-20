"""Fetch MOF final-account tables, then extract explicitly named renewable levy rows.

Run with --download once (network needed); ordinary reruns use frozen HTML only.
No third-party packages. Output remains research evidence, not a model input.
"""
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urljoin
from urllib.request import urlopen, Request
import csv
import hashlib
import json
import re
import sys
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
INDEXES = {
    2014: "2014czys", 2015: "2015js", 2016: "2016js", 2017: "qgczjs",
    2018: "2018czjs", 2019: "2019qgczjs", 2020: "2020zyjs",
    2021: "2021zyjs", 2022: "2022zyjs", 2023: "2023zyjs", 2024: "2024zyjs",
}
KINDS = {"national_revenue": "全国政府性基金收入决算表",
         "central_revenue": "中央政府性基金收入决算表",
         "national_expenditure": "全国政府性基金支出决算表",
         "central_expenditure": "中央政府性基金支出决算表"}


def clean(s):
    return re.sub(r"\s+", "", s.replace("\xa0", " "))


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links, self.rows, self.text = [], [], []
        self.href = None
        self.linktext = []
        self.row = None
        self.cell = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
            self.linktext = []
        if tag == "tr":
            self.row = []
        if tag in ("td", "th") and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        self.text.append(data)
        if self.href is not None:
            self.linktext.append(data)
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.href is not None:
            self.links.append((self.href, clean("".join(self.linktext))))
            self.href = None
        if tag in ("td", "th") and self.cell is not None:
            self.row.append(clean("".join(self.cell)))
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def read_page(path):
    data = path.read_bytes()
    for enc in ("utf-8", "gb18030"):
        try:
            return Page(data.decode(enc))
        except UnicodeDecodeError:
            pass
    raise ValueError(f"Unknown encoding: {path}")


def download(url, path):
    if path.exists():
        return
    req = Request(url, headers={"User-Agent": "Mozilla/5.0 research archival"})
    with urlopen(req, timeout=60) as response:
        path.write_bytes(response.read())
    print("saved", path.name, flush=True)


def main():
    online = "--download" in sys.argv
    manifest = []
    extracted = []
    audit_tables = []
    for year, folder in INDEXES.items():
        index_url = f"https://yss.mof.gov.cn/{folder}/"
        index_path = ROOT / f"mof_{year}_index.html"
        if online:
            download(index_url, index_path)
        index = read_page(index_path)
        for kind, phrase in KINDS.items():
            candidates = sorted(set(urljoin(index_url, href) for href, text in index.links
                                    if f"{year}年{phrase}" in text))
            locator_index_path, locator_index_url = index_path, index_url
            if not candidates:
                locator_index_url = index_url + "index_1.htm"
                locator_index_path = ROOT / f"mof_{year}_index_1.html"
                if online:
                    download(locator_index_url, locator_index_path)
                extra_index = read_page(locator_index_path)
                candidates = sorted(set(urljoin(index_url, href) for href, text in extra_index.links
                                        if f"{year}年{phrase}" in text))
            if len(candidates) != 1:
                raise ValueError((year, kind, candidates))
            url = candidates[0]
            path = ROOT / f"mof_{year}_{kind}.html"
            if online:
                download(url, path)
            page = read_page(path)
            audit_tables.append({"source_file": path.name, "url": url,
                                 "rows": page.rows})
            alltext = clean("".join(page.text))
            assert f"{year}年{phrase}" in alltext, path
            assert "单位：亿元" in alltext, path
            headers = [(i, r) for i, r in enumerate(page.rows, 1)
                       if "预算数" in r and "决算数" in r]
            assert len(headers) == 1, (path, headers)
            header_i, header = headers[0]
            target = "可再生能源电价附加收入"
            found = [(i, r) for i, r in enumerate(page.rows, 1)
                     if r and target in r[0] and len(r[0]) < 70]
            assert len(found) <= 1, (path, found)
            status = "exact_row_found" if found else "not_separately_disclosed_in_table"
            row_i, row = found[0] if found else ("", [])
            if row:
                assert len(row) == len(header), (path, header, row)
            date_match = re.search(r"发布日期[：:]?(\d{4}年\d{2}月\d{2}日)", alltext)
            record = {
                "year": year, "scope": kind.split("_")[0],
                "measure": kind.split("_")[1], "status": status, "unit": "亿元",
                "budget": row[header.index("预算数")] if row else "",
                "actual": row[header.index("决算数")] if row else "",
                "row_label": row[0] if row else "",
                "row_ordinal_1based": row_i,
                "header_ordinal_1based": header_i, "header": header, "raw_row": row,
                "source_file": path.name, "url": url,
            }
            extracted.append(record)
            manifest.append({
                "source_file": path.name, "url": url,
                "fetched_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "title": f"{year}年{phrase}", "publication_date": date_match[1] if date_match else None,
                "scope": record["scope"], "measure": record["measure"],
                "unit": "亿元", "extraction_status": status,
                "locator": f"HTML tr[{row_i}] / header tr[{header_i}]" if row else f"all {len(page.rows)} HTML tr; no exact target row",
                "index_url": locator_index_url, "index_file": locator_index_path.name,
                "index_sha256": hashlib.sha256(locator_index_path.read_bytes()).hexdigest(),
            })
    (ROOT / "extracted_rows.json").write_text(json.dumps(extracted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "source_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "normalized_tables.json").write_text(json.dumps(audit_tables, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    columns = ["year", "scope", "measure", "status", "unit", "budget", "actual",
               "row_label", "row_ordinal_1based", "source_file", "url"]
    with (ROOT / "annual_renewable_levy.csv").open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(extracted)
    note_records = []
    for year in (2022, 2023):
        index_url = f"https://yss.mof.gov.cn/{INDEXES[year]}/"
        page = read_page(ROOT / f"mof_{year}_index.html")
        links = [(urljoin(index_url, href), text) for href, text in page.links
                 if f"关于{year}年中央政府性基金收支决算" in text]
        assert len(links) == 1, (year, links)
        url, title = links[0]
        path = ROOT / f"mof_{year}_central_notes.html"
        if online:
            download(url, path)
        page = read_page(path)
        text = clean("".join(page.text))
        start = text.index("中央政府性基金收入预算数为")
        end = text.index("各项基金管理制度", start)
        note_records.append({
            "year": year, "scope": "all_central_government_managed_funds",
            "url": url, "source_file": path.name, "title": title,
            "fetched_utc": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "locator": "body opening paragraph, starts 中央政府性基金收入预算数为",
            "opening_accounting_paragraph": text[start:end],
            "renewable_energy_term_present": "可再生能源" in text,
            "use_limit": "Aggregate central funds; no attribution of transfers or carryovers to renewable levy."
        })
    (ROOT / "central_notes_anchors.json").write_text(
        json.dumps(note_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in extracted:
        print(row["year"], row["scope"], row["measure"], row["budget"], row["actual"], row["status"])


if __name__ == "__main__":
    main()
