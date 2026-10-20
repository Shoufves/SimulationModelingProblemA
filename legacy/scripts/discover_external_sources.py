"""Register selected public file links exposed by already archived sources."""

import json
import sys
from pathlib import Path
from urllib.parse import urlencode, urljoin

from lxml import html


ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
DATA = ROOT / "data"
path = DATA / "catalog/sources.json"
sources = json.loads(path.read_text(encoding="utf-8"))
known = {s["id"] for s in sources}


def add(identifier, batch, title, publisher, url, target, fmt, role):
    if identifier not in known:
        sources.append(dict(id=identifier, batch=batch, title=title, publisher=publisher,
                            url=url, path=target, format=fmt, role=role))
        known.add(identifier)
        print(identifier, url)


contents = html.fromstring(
    (DATA / "raw/batch1_national/nbs_yearbook_2025_contents.html").read_bytes(),
    parser=html.HTMLParser(encoding="gb18030"),
)
selected = {f"C09-{n:02d}.jpg" for n in [1, 2, 3, 4, 5, 6, 9, 10, 14, 15, 17, 19]}
selected.add("zb09.pdf")
for link in contents.xpath("//a[@href]"):
    href = link.get("href")
    name = href.split("/")[-1]
    if name in selected:
        table_id = name.split(".")[0]
        add("NBS_2025_" + table_id, 1 if name not in {"C09-14.jpg", "C09-19.jpg"} else 2,
            link.text_content().strip(), "国家统计局",
            urljoin("https://www.stats.gov.cn/sj/ndsj/2025/", href),
            "raw/" + ("batch2_mechanisms/" if name in {"C09-14.jpg", "C09-19.jpg"} else "batch1_national/") + "nbs_2025_" + name,
            name.split(".")[-1], "official_yearbook_table")

metadata = json.loads((DATA / "raw/batch2_mechanisms/zenodo_province_load_metadata.json").read_text())
for index, item in enumerate(metadata["files"], 1):
    name = item["key"]
    if name.startswith("Appendix 2"):
        continue
    add("ZENODO_LOAD_FILE_" + str(index), 2, name, "Haochi Wu & Xiaoming Kan",
        item["links"]["self"], "raw/batch2_mechanisms/zenodo_" + name.replace(" ", "_"),
        name.split(".")[-1], "research_reconstructed_load_or_network")

gcb_metadata = DATA / "raw/batch1_national/gcb_national_metadata.json"
if gcb_metadata.exists():
    doc = json.loads(gcb_metadata.read_text(encoding="utf-8"))
    selected_gcb = {"GCB2025v15_MtCO2_flat.csv", "GCB2025v15_MtCO2_flat_metadata.json",
                    "GCB2025v15_sources_flat.csv", "GCP fossilCO2 2025v15.pdf"}
    for item in doc["files"]:
        name = item["key"]
        if name in selected_gcb:
            add("GCB_" + name.split(".")[0].replace(" ", "_"), 1, name, "Global Carbon Project",
                item["links"]["self"], "raw/batch1_national/" + name.replace(" ", "_"),
                name.split(".")[-1], "fossil_industry_co2_inventory")

hydro_metadata = DATA / "raw/batch2_mechanisms/hydro_daily_metadata.json"
if hydro_metadata.exists():
    doc = json.loads(hydro_metadata.read_text(encoding="utf-8"))
    for item in doc["files"]:
        if item["key"] == "dams_large.csv":
            add("HYDRO_RESERVOIR_ATTRIBUTES", 2, item["key"], "Liu et al., Zenodo 1471322",
                item["links"]["self"], "raw/batch2_mechanisms/hydro_reservoir_attributes.csv",
                "csv", "reservoir_attributes_and_historical_average")

query = urlencode({"m": "getTree", "dbcode": "hgnd", "wdcode": "zb", "id": "A07"})
add("NBS_ENERGY_API_TREE", 1, "国家数据能源年度指标目录（公开接口可得性检查）", "国家统计局",
    "https://data.stats.gov.cn/easyquery.htm?" + query,
    "raw/batch1_national/nbs_energy_api_tree.json", "json", "access_check")

for filename in ["raw/batch1_national/gcb_2025_index.html",
                 "raw/batch2_mechanisms/nea_province_renewable_2024_index.html"]:
    file = DATA / filename
    if file.exists():
        page = html.fromstring(file.read_bytes())
        print("\nLINKS", filename)
        for link in page.xpath("//a[@href]"):
            href = link.get("href", "")
            if any(term in href.lower() for term in ["zenodo", ".xlsx", ".csv", ".pdf", ".doc"]):
                print(link.text_content().strip()[:100], href)
                if filename.endswith("nea_province_renewable_2024_index.html") and href.endswith(".doc"):
                    add("NEA_PROVINCE_RENEWABLE_2024_DOC", 2, link.text_content().strip(), "国家能源局",
                        urljoin("https://www.nea.gov.cn/20251113/cc1fb0298a2944f8bd5441f67c9be9b3/c.html", href),
                        "raw/batch2_mechanisms/nea_province_renewable_2024.doc", "doc", "regional_official_tables")

path.write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding="utf-8")
