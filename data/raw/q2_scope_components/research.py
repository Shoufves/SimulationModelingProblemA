"""Freeze narrowly scoped pumped-storage and waste-carbon primary evidence.

Default operation rebuilds texts/manifests from saved originals. --download
fetches only missing declared originals. Nothing is admitted to production.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import csv
from pathlib import Path
import re
import sys
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
TEXT_REUSE={"cec_2014_reuse":"../q2_capacity_detail/cec2014_portal.txt",
            "nea_2024_reuse":"../q2_capacity_detail/nea_renewable_2024.txt"}
SOURCES = [
    dict(id="hydrochina_2024", file="hydrochina_renewables_2024.pdf",
         url="https://www.eesia.cn/upload/files/2025/5/2fea84d6414c788d.pdf",
         kind="primary_report_original_document_association_host"),
    dict(id="ndrc_2021", file="ndrc_pumped_2021.html",
         url="https://www.ndrc.gov.cn/fzggw/wld/sw/lddt/202206/t20220628_1329040.html",
         kind="official_release"),
    dict(id="nea_2014_regional", file="nea_pumped_2014_regional.html",
         url="https://zfxxgk.nea.gov.cn/auto92/201505/t20150519_1927.htm",
         kind="official_regulatory_report_partial_year_partial_region"),
    dict(id="ma_2024", file="ma_2024_radiocarbon.html",
         url="https://link.springer.com/article/10.1007/s44246-024-00162-9",
         kind="primary_peer_reviewed_research"),
    dict(id="ma_2024_pdf", file="ma_2024_radiocarbon.pdf",
         url="https://link.springer.com/content/pdf/10.1007/s44246-024-00162-9.pdf",
         kind="primary_peer_reviewed_research"),
    dict(id="ma_2024_supplement", file="ma_2024_supplement.docx",
         url="https://media.springernature.com/original/springer-static/esm/art%3A10.1007%2Fs44246-024-00162-9/MediaObjects/44246_2024_162_MOESM1_ESM.docx",
         kind="primary_research_supplement"),
    dict(id="cec_2014_reuse", file="../q2_technology_scope/cec2014_portal.html",
         url="https://chinaenergyportal.org/2014-detailed-electricity-statistics/",
         kind="CEC_unofficial_reprint_existing_original"),
    dict(id="nea_2014_reuse", file="../q2_technology_scope/nea_electricity2014.html",
         url="https://gzb.nea.gov.cn/dtyw/hyxx/202310/t20231023_192081.html",
         kind="official_regional_repost_existing_original"),
    dict(id="nea_2024_reuse", file="../batch1_national/nea_renewable_2024.html",
         url="https://www.nea.gov.cn/20250221/e10f363cabe3458aaf78ba4558970054/c.html",
         kind="official_existing_original"),
]


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.parts, self.links, self.rows = [], [], []
        self.skip = 0
        self.row = self.cell = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag == "tr":
            self.row = []
        if tag in {"td", "th"} and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data.strip())
            if self.cell is not None:
                self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = max(0, self.skip - 1)
        if tag in {"td", "th"} and self.cell is not None:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip())
            self.cell = None
        if tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None


def download(source):
    path = ROOT / source["file"]
    if path.exists():
        return dict(id=source["id"], status="already_saved")
    if path.resolve().parent != ROOT:
        return dict(id=source["id"], status="failed", reason="Reused original missing; no write outside new evidence directory")
    try:
        req = Request(source["url"], headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "text/html,application/pdf,*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with urlopen(req, timeout=25) as response:
            content = response.read()
            final_url = response.url
        if source["file"].endswith(".pdf") and not content.startswith(b"%PDF"):
            raise ValueError("Server did not return a PDF")
        path.write_bytes(content)
        return dict(id=source["id"], status="saved", final_url=final_url)
    except Exception as exc:
        return dict(id=source["id"], status="failed", reason=str(exc))


def main():
    if "--download" in sys.argv:
        with ThreadPoolExecutor(max_workers=5) as executor:
            attempts = list(executor.map(download, SOURCES))
        (ROOT / "retrieval_attempts.json").write_text(
            json.dumps(attempts, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(attempts, ensure_ascii=False, indent=2), flush=True)
    manifest, tables = [], []
    for source in SOURCES:
        path = ROOT / source["file"]
        if not path.exists():
            continue
        entry = dict(source, sha256=sha256(path.read_bytes()).hexdigest(),
                     saved_utc=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat())
        if path.suffix == ".html":
            raw = path.read_bytes()
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                text = raw.decode("gb18030")
            page = Page(text)
            text_value="\n".join(p for p in page.parts if p)+"\n"
            text_file=TEXT_REUSE.get(source["id"],path.stem+".txt")
            target=ROOT/text_file
            if source["id"] in TEXT_REUSE:
                if target.read_text(encoding="utf-8")!=text_value:
                    raise ValueError("Reused extracted text differs from source: "+text_file)
            else:
                target.write_text(text_value,encoding="utf-8")
            entry["text_file"] = text_file
            entry["document_links"] = [link for link in page.links
                                       if re.search(r"\.(pdf|docx?|xlsx?|zip)(?:\?|$)", link)]
            tables.append(dict(id=source["id"], rows=page.rows))
        manifest.append(entry)
    import zipfile
    import xml.etree.ElementTree as ET
    from pypdf import PdfReader
    for source in SOURCES:
        path = ROOT / source["file"]
        if path.exists() and path.suffix == ".pdf":
            reader = PdfReader(path)
            (ROOT / (path.stem + ".txt")).write_text(
                "\n".join(f"\n--- PDF page {i} ---\n{p.extract_text()}"
                          for i, p in enumerate(reader.pages, 1)), encoding="utf-8")
        if path.exists() and path.suffix == ".docx":
            with zipfile.ZipFile(path) as archive:
                document = ET.fromstring(archive.read("word/document.xml"))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = ["".join(p.itertext()) for p in document.findall(".//w:p", ns)]
            (ROOT / (path.stem + ".txt")).write_text("\n".join(paragraphs), encoding="utf-8")
            supplement_tables = []
            for index, table in enumerate(document.findall(".//w:tbl", ns), 1):
                rows = [["".join(cell.itertext()) for cell in row.findall("w:tc", ns)]
                        for row in table.findall("w:tr", ns)]
                supplement_tables.append(dict(table=f"S{index}", rows=rows))
            (ROOT / "ma_supplement_tables.json").write_text(
                json.dumps(supplement_tables, ensure_ascii=False, indent=2), encoding="utf-8")
            s4 = supplement_tables[3]["rows"]
            treated = next(row for row in s4 if row[0] == "FCF of treated flue gas")
            untreated = next(row for row in s4 if row[0] == "FCF of untreated flue gas")
            plants = s4[0][2:]
            plant_rows = []
            for i, plant in enumerate(plants):
                plant_rows.append(dict(
                    plant=plant,
                    fossil_carbon_fraction_treated_pct=float(treated[3+i*3]),
                    fossil_carbon_fraction_untreated_pct=float(untreated[3+i*3]),
                    unit="percent_total_carbon_in_CO2_not_energy_fraction",
                    locator="Supplementary Table S4, Ave column",
                    sample_period="2022-11 to 2023-11",
                    scope="7 sampled plants, 8 operating conditions; not national annual estimates"))
            with (ROOT / "ma_measured_flue_gas_fractions.csv").open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=plant_rows[0])
                writer.writeheader()
                writer.writerows(plant_rows)
            assert min(p["fossil_carbon_fraction_treated_pct"] for p in plant_rows) == 44.54
            assert max(p["fossil_carbon_fraction_treated_pct"] for p in plant_rows) == 53.12
    cec = next(table for table in tables if table["id"] == "cec_2014_reuse")
    assert cec["rows"][25][3:6] == ["GWh", "10,680", "13,190"]
    assert cec["rows"][58][3:6] == ["MW", "21,533", "22,110"]
    assert "2183万千瓦" in (ROOT / "nea_electricity2014.txt").read_text("utf-8")
    assert "3639万千瓦" in (ROOT / "ndrc_pumped_2021.txt").read_text("utf-8")
    assert "390亿千瓦时" in (ROOT / "ndrc_pumped_2021.txt").read_text("utf-8")
    assert "5869万千瓦" in (ROOT / TEXT_REUSE["nea_2024_reuse"]).read_text("utf-8")
    anchors = [
        (2014, "generation", 13.19, "TWh", "cec_2014_reuse",
         "HTML tr26; current-year2014 column", "CEC national detailed unofficial reprint"),
        (2014, "capacity", 22110, "MW", "cec_2014_reuse",
         "HTML tr59; current-year2014 column", "CEC later detailed vintage"),
        (2014, "capacity", 21830, "MW", "nea_2014_reuse",
         "电源建设, 截至2014年底", "NEA preliminary national vintage; do not average"),
        (2021, "generation", 39, "TWh", "ndrc_2021",
         "2022-06-28 press conference, second answer on pumped storage", "National annual"),
        (2021, "capacity", 36390, "MW", "ndrc_2021",
         "same answer, 截至2021年底", "National year-end"),
        (2024, "generation", 65.7, "TWh", "hydrochina_2024",
         "PDF page26, section5.2, visually verified", "National annual; expressly part of full-scope hydro"),
        (2024, "capacity", 58690, "MW", "hydrochina_2024",
         "PDF page12, section3.1, visually verified", "National year-end"),
        (2024, "capacity", 58690, "MW", "nea_2024_reuse",
         "（一）水电建设和运行情况", "National year-end"),
    ]
    rows = [dict(year=y, metric=m, value=v, unit=u, source_id=s, locator=l, scope=c)
            for y, m, v, u, s, l, c in anchors]
    rows.extend(dict(year=y, metric="pumping_electricity_consumption", value="", unit="TWh",
                     source_id="", locator="No verified national annual observation obtained",
                     scope="missing; not zero; no inference from NBS-EI hydro difference or EIA net figure")
                for y in (2014, 2021, 2024))
    with (ROOT / "pumped_storage_anchors.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    visual = dict(
        source_file="hydrochina_renewables_2024.pdf",
        extraction_method="manual transcription from rendered original PDF; no searchable text layer",
        page12=dict(section="3.1常规水电与抽水蓄能",
                    capacity_10k_kw=5869, new_capacity_10k_kw=775,
                    limitation="NEA corresponding new capacity753 preserved as separate vintage, not averaged"),
        page26=dict(section="5.2常规水电与抽水蓄能",
                    generation_100m_kwh=657, annual_change_pct=14.5, utilisation_hours=1217,
                    included_in="全口径水电发电量",
                    pumping_electricity_consumption=None),
        verified_render_files=["tmp/pdfs/q2_scope_components/hydro_p12.png",
                               "tmp/pdfs/q2_scope_components/hydro_p26.png"])
    (ROOT / "visual_pdf_anchors.json").write_text(
        json.dumps(visual, ensure_ascii=False, indent=2), encoding="utf-8")
    for entry in manifest:
        entry["production_admitted"] = False
        entry["canonical_reuse"] = entry["file"].startswith("../")
        entry["bytes"] = (ROOT / entry["file"]).stat().st_size
    (ROOT / "source_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    (ROOT / "normalized_tables.json").write_text(
        json.dumps(tables, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved evidence files: {len(manifest)}", flush=True)


if __name__ == "__main__":
    main()
