"""Read-only source extraction and research index; never modifies model inputs."""
from pathlib import Path
import csv
import hashlib
import json
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CANONICAL = {
    "nea_renewable_2024.html": ROOT/"data/raw/batch1_national/nea_renewable_2024.html",
    "biomass_2024_people.html": ROOT/"data/raw/q1/bio_industry_interview.html",
}
RELATIVE_CANONICAL = {
    "nea_renewable_2024.html": "../batch1_national/nea_renewable_2024.html",
    "biomass_2024_people.html": "../q1/bio_industry_interview.html",
}

sources = [
    ("ei_2025_original.xlsx", "https://snapshots.owid.io/99/805119256ece8c0b5b24181295b66d", "Energy Institute, original bytes archived by OWID", "China rows in 10 generation sheets; Definitions A50; Other inputs A61", "Original workbook MD5 matches OWID DVC99805119256ece8c0b5b24181295b66d. 2005-2024 all generation components close. Other is not all oil or all pumped; inputs-named sheets report electrical output."),
    ("owid_snapshot_download.py", "https://raw.githubusercontent.com/owid/etl/master/etl/snapshot.py", "OWID", "_download_dvc_file; public MD5-addressed download", "Public snapshot retrieval method; master downloaded 2026-10-20"),
    ("owid_snapshot_config.py", "https://raw.githubusercontent.com/owid/etl/master/etl/config.py", "OWID", "R2_SNAPSHOTS_PUBLIC_READ", "Public snapshot base URL, not private bucket or credentials"),
    ("owid_electricity_mix_20260424.py", "https://raw.githubusercontent.com/owid/etl/master/etl/steps/data/garden/energy/2026-04-24/electricity_mix.py", "OWID", "process_ember_data line 117; combine_ei_and_ember_data lines 202–225", "Confirms Other fossil renamed oil; master download, not a historical Git commit"),
    ("ember_yearly_page.html", "https://ember-energy.org/data/yearly-electricity-data/", "Ember", "Data download format update July 2026; monthly revisions; CSV/methodology links", "Version and provenance only"),
    ("ember_yearly_global.csv", "https://files.ember-energy.org/public-downloads/generation/outputs/release_generation_yearly_global.csv", "Ember", "ISO 3 code=CHN; Year=2014–2024; Generation (TWh), Capacity (GW)", "Current same-download full mix; not identical to frozen OWID vintage"),
    ("ember_methodology.pdf", "https://files.ember-energy.org/public-downloads/ember_electricity_data_methodology.pdf", "Ember", "PDF p9 fuel definitions; p10 gross generation; p31 China; p32 capacity", "Other fossil includes oil/petroleum products, manufactured gases and waste; aggregate does not identify composition"),
    ("ember_china_generation_methodology.pdf", "https://storage.googleapis.com/emb-prod-bkt-publicdata/public-downloads/ember_china_generation_methodology.pdf", "Ember", "August 2026 version, PDF p3 bioenergy, p4 thermal disaggregation/annual pumped correction, p6 caveats", "Current methodology; not proof of all revisions between historical downloads"),
    ("ember_api_openapi.json", "https://api.ember-energy.org/v1/openapi.json", "Ember", "API definitions and fuel labels", "Corroborating primary metadata"),
    ("eia_china_generation_api.json", "https://api.eia.gov/v2/international/data/?api_key=DEMO_KEY&frequency=annual&data[0]=value&facets[countryRegionId][]=CHN&facets[activityId][]=12&start=2014&end=2024&length=5000", "EIA", "Annual CHN Generation, BKWH, products 2,27–38,82,116,117,2890", "Separate oil/other gases; same-query full mix, all available years"),
    ("eia_international_metadata.json", "https://api.eia.gov/v2/international/?api_key=DEMO_KEY", "EIA", "International route metadata", "Route identity; does not document all Chinese source revisions"),
    ("eia_oil_series_metadata.json", "https://api.eia.gov/v2/seriesid/INTL.32-12-CHN-BKWH.A?api_key=DEMO_KEY", "EIA", "China Oil Generation annual series", "Separate pure oil series, not OWID Other fossil"),
    ("eia_product_metadata.json", "https://api.eia.gov/v2/international/facet/productId/?api_key=DEMO_KEY&facets[productId][]=32&length=5000", "EIA", "Oil facet", "Product identification"),
    ("eia_net_generation_glossary.html", "https://www.eia.gov/tools/glossary/index.php?id=Net+generation", "EIA", "Net generation definition and pumped-storage note", "Gross minus station auxiliaries; pumping deducted"),
    ("owid_eia_international_20260505.py", "https://raw.githubusercontent.com/owid/etl/master/etl/steps/data/garden/eia/2026-05-05/international_energy.py", "OWID", "Electricity flows tuples including Electricity net generation and Biomass and waste electricity net generation", "Corroborates net labels; does not establish China waste biogenic fraction"),
    ("owid_ei_2025.py", "https://raw.githubusercontent.com/owid/etl/master/etl/steps/data/garden/energy_institute/2025-06-27/statistical_review_of_world_energy.py", "OWID", "electbyfuel_oil mapped to oil_electricity_generation_twh; other field commented out", "Feather omits Other; original XLSX now read, do not drop it to manufacture closure"),
    ("owid_ei_snapshot.dvc", "https://raw.githubusercontent.com/owid/etl/master/snapshots/energy_institute/2025-06-27/statistical_review_of_world_energy.xlsx.dvc", "OWID", "Original EI xlsx URL and original MD5", "Original EI URL blocked by Cloudflare during this session"),
    ("owid_ei_2025.meta.json", "https://catalog.ourworldindata.org/garden/energy_institute/2025-06-27/statistical_review_of_world_energy/statistical_review_of_world_energy.meta.json", "OWID", "fields.oil_electricity_generation_twh; gross output metadata", "Public mirror metadata, compared to original workbook footnotes"),
    ("owid_ei_2025.feather", "https://catalog.ourworldindata.org/garden/energy_institute/2025-06-27/statistical_review_of_world_energy/statistical_review_of_world_energy.feather", "OWID", "2025-06-27 EI garden table", "Read after installing pyarrow19.0.1; Float32 cross-check only. Canonical extraction now uses original XLSX full precision and includes Other."),
    ("cec2014_portal.html", "https://chinaenergyportal.org/2014-detailed-electricity-statistics/", "China Energy Portal, reproducing CEC", "电力统计基本数据一览表: full generation/capacity; 6000kW+ subrows; note4", "Unofficial mirror. Original CEC 2015-11-30/146012.html returns404; distinguish preliminary NEA statistics"),
    ("nea_biomass_2014_reply.html", "https://zfxxgk.nea.gov.cn/auto81/201512/t20151211_1994.htm", "NEA", "2014-end renewable electricity capacity paragraph", "2014 biomass capacity948万kW, official"),
    ("nea_electricity2014.html", "https://gzb.nea.gov.cn/dtyw/hyxx/202310/t20231023_192081.html", "NEA regional office", "2014年电力工业运行简况, 电源建设", "Preliminary2014 gas capacity5567万kW; differs from later CEC detailed5697"),
    ("nea_biomass2018.html", "https://www.nea.gov.cn/2019-01/28/c_137780519.htm", "NEA", "五、生物质发电建设和运行情况", "2018 capacity1781万kW; generation906亿kWh"),
    ("nea_biomass2020.html", "https://hzj.nea.gov.cn/dtyw/gjnyjdt/202309/t20230913_74826.html", "NEA regional office", "2021Q1 press conference, 4.生物质发电建设和运行情况", "2020 capacity2952万kW; generation1326亿kWh"),
    ("nea_biomass2021.html", "https://www.nea.gov.cn/2022-01/28/c_1310445390.htm", "NEA", "2022Q1 press conference, 五、生物质发电建设和运行情况", "2021 capacity3798万kW; generation1637亿kWh"),
    ("nea_renewable_2024.html", "https://www.nea.gov.cn/20250221/e10f363cabe3458aaf78ba4558970054/c.html", "NEA", "（四）生物质发电建设和运行情况", "2024 capacity4599万kW; generation2083亿kWh. Existing catalog already held selected capture"),
    ("biomass_2024_people.html", "https://paper.people.com.cn/zgnyb/pc/content/202504/14/content_30068709.html", "中国能源报/人民日报; industry report interview", "《2025中国生物质能产业年度报告》discussion", "2024 agriculture/forestry1709万kW; waste2738万kW. Not the full underlying industry report"),
    ("cec_annual2025_release.html", "https://chinapower.org.cn/detail/447983.html", "中国电力发展促进会; CEC report release", "三、电力总装机保持快速增长", "2024 gas approximately1.4亿kW; biomass4597万kW differs from NEA4599, preserve revision"),
    ("gas2024_cq_exchange.html", "https://www.chinacqpgx.com/hy/shownews?id=13164", "重庆石油天然气交易中心, industry analysis", "燃气发电产业 paragraph", "2024 gas approximately1.4亿kW/0.32万亿kWh, rounded secondary cross-check"),
]

index = []
for name, url, publisher, locator, use in sources:
    path = CANONICAL.get(name,HERE/name)
    if not path.is_file():
        continue
    index.append(dict(
        path=path.relative_to(ROOT).as_posix(), url=url, publisher=publisher,
        retrieved_at_utc=datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        bytes=path.stat().st_size, locator=locator, allowed_research_use=use,
        production_admitted=False,canonical_reuse=name in CANONICAL,
    ))

existing = [
    ("data/raw/batch1_national/owid_energy_data.csv", "https://github.com/owid/energy-data", "Frozen legacy OWID actual model source"),
    ("data/raw/batch1_national/owid_energy_codebook.csv", "https://github.com/owid/energy-data", "oil_electricity names oil but cites mixed upstream"),
    ("data/raw/lb/base/owid/energy_README.md", "https://github.com/owid/energy-data", "Links to exact ETL2026-04-24 step"),
    ("data/raw/official/S25_selected_capture.txt", "https://www.nea.gov.cn/20250221/e10f363cabe3458aaf78ba4558970054/c.html", "Already catalogued NEA2024 selected capture"),
]
for rel, url, note in existing:
    path=ROOT/rel
    index.append(dict(path=rel,url=url,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),existing_read_only_source=True,note=note,production_admitted="existing contract only"))

oldrows=list(csv.DictReader((ROOT/"data/raw/batch1_national/owid_energy_data.csv").open(encoding="utf8")))
oldrows=[r for r in oldrows if r["iso_code"]=="CHN" and r["year"] in {"2014","2021","2024"}]
with (HERE/"frozen_owid_complete_anchors.csv").open("w",encoding="utf8",newline="") as f:
    writer=csv.DictWriter(f,fieldnames=oldrows[0].keys());writer.writeheader();writer.writerows(oldrows)

eia=list(csv.DictReader((HERE/"eia_china_generation_2014_2024.csv").open(encoding="utf8")))
ei={}
for row in eia:
    ei[int(row["period"]),row["productId"]]=float(row["value"])
checks=[]
for year in range(2014,2025):
    fossil=sum(ei[year,k] for k in ["30","31","32","2890"])
    total=ei[year,"28"]+ei[year,"29"]+ei[year,"27"]+ei[year,"82"]
    checks.append(dict(year=year,fossil_sum_residual_twh=fossil-ei[year,"28"],total_sum_residual_twh=total-ei[year,"2"]))
(HERE/"eia_same_download_closure.json").write_text(json.dumps(dict(
    source="eia_china_generation_api.json",checks=checks,
    passed=all(abs(r["fossil_sum_residual_twh"])<1e-4 and abs(r["total_sum_residual_twh"])<1e-4 for r in checks),
    limitation="Arithmetic closure does not validate gross/net coverage, waste biogenic fraction or national fuel/emissions allocation."
),indent=2),encoding="utf8")

anchors = [
    (2014,"gas_capacity_mw",55670,"NEA preliminary","nea_electricity2014.html","Full national year-end; later CEC detailed mirror differs"),
    (2014,"gas_capacity_mw",56970,"CEC detailed unofficial mirror","cec2014_portal.html","Full national year-end, not same vintage as NEA preliminary"),
    (2014,"gas_generation_twh",133.283,"CEC detailed unofficial mirror","cec2014_portal.html","Full national annual generation"),
    (2014,"oil_capacity_mw",5116,"CEC detailed unofficial mirror","cec2014_portal.html","Full national oil, excludes other thermal categories"),
    (2014,"oil_generation_twh",4.424,"CEC detailed unofficial mirror","cec2014_portal.html","Full national oil, not OWID Other fossil"),
    (2014,"biomass_capacity_mw",9480,"NEA official reply","nea_biomass_2014_reply.html","Policy biomass category"),
    (2014,"biomass_capacity_mw",10300,"CEC detailed unofficial mirror","cec2014_portal.html","Note4; preserve discrepancy from NEA9480"),
    (2014,"biomass_generation_twh",47.4,"CEC detailed unofficial mirror","cec2014_portal.html","Note4, includes waste; differs from OWID46.27"),
    (2014,"waste_capacity_mw",4685,"CEC detailed unofficial mirror","cec2014_portal.html","6000kW-and-above subset"),
    (2014,"agroforestry_capacity_mw",5117,"CEC detailed unofficial mirror","cec2014_portal.html","6000kW-and-above straw/bagasse/wood subset"),
    (2014,"waste_generation_twh",24.510,"CEC detailed unofficial mirror","cec2014_portal.html","6000kW-and-above subset"),
    (2014,"agroforestry_generation_twh",21.633,"CEC detailed unofficial mirror","cec2014_portal.html","6000kW-and-above subset"),
    (2018,"biomass_capacity_mw",17810,"NEA official","nea_biomass2018.html","National policy biomass category"),
    (2018,"biomass_generation_twh",90.6,"NEA official","nea_biomass2018.html","National policy biomass category"),
    (2020,"biomass_capacity_mw",29520,"NEA official","nea_biomass2020.html","Preserve published vintage"),
    (2020,"biomass_generation_twh",132.6,"NEA official","nea_biomass2020.html","National policy biomass category"),
    (2021,"biomass_capacity_mw",37980,"NEA official","nea_biomass2021.html","National policy biomass category"),
    (2021,"biomass_generation_twh",163.7,"NEA official","nea_biomass2021.html","National policy biomass category"),
    (2024,"gas_capacity_mw",140000,"CEC release rounded","cec_annual2025_release.html","Approximate1.4e8kW, not exact capacity"),
    (2024,"gas_generation_twh",320,"Industry rounded secondary","gas2024_cq_exchange.html","Approximate0.32e12kWh"),
    (2024,"biomass_capacity_mw",45990,"NEA official","nea_renewable_2024.html","National policy biomass category includes waste"),
    (2024,"biomass_generation_twh",208.3,"NEA official","nea_renewable_2024.html","National policy biomass category includes waste"),
    (2024,"biomass_capacity_mw",45970,"CEC release","cec_annual2025_release.html","Preserve difference from NEA45990"),
    (2024,"agroforestry_capacity_mw",17090,"Industry report interview secondary","biomass_2024_people.html","Approximate; does not provide fossil fraction"),
    (2024,"waste_capacity_mw",27380,"Industry report interview secondary","biomass_2024_people.html","Approximate; does not provide biogenic share"),
]
with (HERE/"technology_capacity_generation_anchors.csv").open("w",encoding="utf8",newline="") as f:
    writer=csv.writer(f)
    writer.writerow(["year","metric","value","evidence_level","source_file","scope_and_limitation"])
    writer.writerows((*r[:4],RELATIVE_CANONICAL.get(r[4],r[4]),r[5]) for r in anchors)

derived={}
for path in HERE.iterdir():
    if path.is_file() and path.name not in {"source_manifest.json","build_research_index.py"}:
        derived[path.name]=dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size)
(HERE/"source_manifest.json").write_text(json.dumps(dict(
    research_date="2026-10-20",scope="technology classification and initial-state evidence; no production changes",
    sources=index,files=derived,
    retrieval_failures=[
        "Official EI2025 XLSX and current download page returned Cloudflare challenge. Subsequently recovered exact original XLSX through official OWID public snapshot; MD5 matches DVC, not a challenge-page body.",
        "Original CEC2014 URL returns404; China Energy Portal mirror explicitly labelled.",
        "Initially pyarrow absent so feather unread. Resolved on2026-10-20 with pyarrow19.0.1; canonical extraction now standard-library original XLSX, no pyarrow production dependency.",
        "EIA guessed sources-and-definitions path returned404; use official glossary plus OWID net-series naming, not this failed path.",
        "Search result pages are discovery-only, not data evidence."
    ]
),ensure_ascii=False,indent=2)+"\n",encoding="utf8")
print(json.dumps(dict(sources=len(index),eia_closure_checks=len(checks),production_modified=False)))
