"""Build traceable first-round research tables; never run an energy model."""

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
from lxml import html
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "processed"
CAT = DATA / "catalog"
OUT.mkdir(exist_ok=True)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
SOURCES = json.loads((CAT / "sources.json").read_text(encoding="utf-8"))
SOURCE = {s["id"]: s for s in SOURCES}
RETRIEVAL = {s["id"]: s for s in json.loads((CAT / "retrieval_manifest.json").read_text(encoding="utf-8"))}
DATASETS = []
CHECKS = []
FIELDS = ["year", "region", "variable", "value", "unit", "source_id",
          "source_locator", "status", "boundary"]


def check(name, passed, detail, severity="error"):
    CHECKS.append(dict(check=name, passed=bool(passed), severity=severity, detail=str(detail)))


def save_csv(name, rows, columns=None):
    frame = pd.DataFrame(rows, columns=columns)
    frame.to_csv(OUT / name, index=False, encoding="utf-8-sig", lineterminator="\n")
    return frame


def register(name, frame, sources, years, use, limitations, eligibility="usable_with_scope"):
    DATASETS.append(dict(
        dataset=name, path="processed/" + name, rows=len(frame), columns=len(frame.columns),
        source_ids=";".join(sources), observed_years=years, use=use,
        eligibility=eligibility, limitations=limitations,
    ))


def record(year, region, variable, value, unit, source_id, locator, boundary,
           status="observed_or_published_estimate"):
    return [year, region, variable, value, unit, source_id, locator, status, boundary]


def source_text(source_id):
    source = SOURCE[source_id]
    file = DATA / source["path"]
    if not file.exists():
        return ""
    target = DATA / "extracted" / (source_id.lower() + ".txt")
    if target.exists():
        return target.read_text(encoding="utf-8")
    if source["format"] == "html":
        encoding = "gb18030" if "yearbook" in file.name else "utf-8"
        tree = html.fromstring(file.read_bytes(), parser=html.HTMLParser(encoding=encoding))
        for node in tree.xpath("//script|//style"):
            node.drop_tree()
        text = "\n".join(x.strip() for x in tree.text_content().splitlines() if x.strip())
    elif source["format"] == "pdf":
        text = "\n\n".join(f"[PDF page {i}]\n{p.extract_text()}"
                           for i, p in enumerate(PdfReader(file).pages, 1))
    else:
        return ""
    target.write_text(text, encoding="utf-8")
    return text


def transcriptions():
    transcription = json.loads((DATA / "extracted/nbs_verified_transcription.json").read_text(encoding="utf-8"))
    groups = {
        "energy_annual": ("nbs_energy_annual.csv", "National annual primary production and consumption"),
        "capacity_annual": ("nbs_capacity_annual.csv", "National year-end installed power capacity"),
        "products_annual": ("nbs_products_annual.csv", "National product output"),
        "sector_use_2023": ("nbs_sector_use_2023.csv", "Published sector fuel-use snapshot"),
    }
    for key, (name, use) in groups.items():
        group = transcription[key]
        rows = []
        for values in group["rows"]:
            for i, column in enumerate(group["columns"][1:], 1):
                if values[i] is None:
                    continue
                if key == "sector_use_2023":
                    year, region = 2023, values[0]
                else:
                    year, region = values[0], "China_mainland"
                source = group["source_ids"][0]
                if key == "energy_annual" and column.startswith("consumption"):
                    source = group["source_ids"][1]
                suffix = column.split("_")[-1]
                unit = {"pct": "%", "10kW": "10^4 kW", "10ktce": "10^4 tce",
                        "10kt": "10^4 t", "100Mt": "10^8 t", "100Mm3": "10^8 m3",
                        "100GWh": "10^8 kWh"}[suffix]
                rows.append(record(year, region, column, values[i], unit, source,
                                   f"table image; row={values[0]}; column={column}",
                                   group.get("boundary_note", use)))
        frame = save_csv(name, rows, FIELDS)
        register(name, frame, group["source_ids"], ",".join(map(str, sorted(frame.year.unique()))),
                 use, group.get("boundary_note", "Raw source units retained"))
    rows = []
    balances = transcription["balance_checkpoints"]
    for source, table in balances["tables"].items():
        for variable, values in table["rows"].items():
            for year, value in zip(balances["years"], values):
                unit = {"10ktce": "10^4 tce", "10kt": "10^4 t",
                        "100GWh": "10^8 kWh"}[table["unit"]]
                rows.append(record(year, "China_mainland", variable, value, unit,
                                   source, f"table image; row={variable}; year={year}",
                                   balances["boundary_note"]))
    frame = save_csv("nbs_balance_checkpoints.csv", rows, FIELDS)
    register("nbs_balance_checkpoints.csv", frame, list(balances["tables"]), "2015,2020,2022,2023",
             "Balance checkpoints and trade quantities, not annual interpolation",
             balances["boundary_note"])
    rows = []
    group = transcription["province_demand"]
    for values in group["rows"]:
        for year, value in zip(group["years"], values[1:]):
            rows.append(record(year, values[0], "electricity_use", value, "10^8 kWh",
                               group["source_ids"][0], f"table 9-14; province={values[0]}; year={year}",
                               "Provincial annual consumption; selected years, rounded source values"))
    frame = save_csv("nbs_province_demand.csv", rows, FIELDS)
    register("nbs_province_demand.csv", frame, group["source_ids"], "2015,2020,2023,2024",
             "Regional demand scale; input to region grouping",
             "31 provinces; not a continuous annual provincial panel")
    group = transcription["electricity_2025"]
    rows = [record(2025, "China_mainland", "capacity_" + k, v, "10^4 kW",
                   "NEA_ELECTRICITY_2025_TABLE", f"table; {k}", "Year-end capacity, hydro includes pumped storage")
            for k, v in group["capacity_10kW"].items()]
    rows.append(record(2025, "China_mainland", "line_loss_rate", group["line_loss_pct"], "%",
                       "NEA_ELECTRICITY_2025_TABLE", "table; national line loss", "National annual average"))
    rows.append(record(2025, "China_mainland", "utilization_hours", group["average_utilization_hours_plants_6000kW_plus"],
                       "hour", "NEA_ELECTRICITY_2025_TABLE", "table; utilization",
                       "Only plants of 6000 kW and above; not total-system capacity factor"))
    frame = save_csv("nea_electricity_2025.csv", rows, FIELDS)
    register("nea_electricity_2025.csv", frame, ["NEA_ELECTRICITY_2025_TABLE"], "2025",
             "Latest capacity crosscheck", "Not a complete 2025 multi-energy baseline")
    energy = pd.DataFrame(transcription["energy_annual"]["rows"],
                          columns=transcription["energy_annual"]["columns"])
    for prefix in ["production", "consumption"]:
        columns = [c for c in energy if c.startswith(prefix + "_") and c.endswith("_pct")]
        errors = (energy[columns].sum(axis=1) - 100).abs()
        check("nbs_" + prefix + "_shares_rounding", errors.max() <= 0.2,
              f"max difference from 100%: {errors.max():.3f} percentage points")
    capacity = pd.DataFrame(transcription["capacity_annual"]["rows"],
                            columns=transcription["capacity_annual"]["columns"])
    c = capacity[capacity.year >= 2014]
    discrepancy = c.iloc[:, 2:].sum(axis=1) - c.total_10kW
    check("nbs_capacity_components_rounding", discrepancy.abs().max() <= 2,
          f"Maximum rounding residual: {discrepancy.abs().max()} x10^4 kW")
    check("province_demand_31_regions", len(transcription["province_demand"]["rows"]) == 31, "31 provinces")
    for source, table in balances["tables"].items():
        r = table["rows"]
        if "balance_difference" in r:
            residual = np.array(r["available_supply"]) - np.array(r["consumption"]) - np.array(r["balance_difference"])
            check(source + "_published_balance_difference", np.max(np.abs(residual)) <= 1,
                  f"max source-rounding discrepancy={np.max(np.abs(residual))}; statistical residual preserved")


def national_research_series():
    codebook = pd.read_csv(DATA / "raw/batch1_national/owid_energy_codebook.csv").set_index("column")
    raw = pd.read_csv(DATA / "raw/batch1_national/owid_energy_data.csv")
    china = raw[raw.iso_code.eq("CHN") & raw.year.between(2005, 2025)].copy()
    variables = [
        "coal_production", "oil_production", "gas_production", "coal_consumption",
        "oil_consumption", "gas_consumption", "primary_energy_consumption",
        "electricity_demand", "electricity_generation", "coal_electricity", "gas_electricity",
        "oil_electricity", "hydro_electricity", "nuclear_electricity", "wind_electricity",
        "solar_electricity", "biofuel_electricity", "other_renewable_electricity",
        "net_elec_imports", "low_carbon_share_elec",
    ]
    rows = []
    for _, row in china.iterrows():
        for variable in variables:
            if pd.isna(row[variable]):
                continue
            rows.append(record(int(row.year), "China", variable, row[variable], codebook.loc[variable, "unit"],
                               "OWID_ENERGY_CHINA_ARCHIVE", f"iso_code=CHN; year={int(row.year)}; column={variable}",
                               "OWID upstream: " + str(codebook.loc[variable, "source"]) +
                               "; official primary-energy shares and hydro definitions may differ",
                               "research_compilation"))
    frame = save_csv("china_energy_research_annual.csv", rows, FIELDS)
    register("china_energy_research_annual.csv", frame,
             ["OWID_ENERGY_CHINA_ARCHIVE", "OWID_ENERGY_CODEBOOK"], "2005-2024; electricity also 2025",
             "Fuel series, electricity mix and source crosschecks",
             "Compilation; primary-energy substitution method is not NBS accounting; shared upstream sources limit independence")
    rows = []
    wdi = json.loads((DATA / "raw/batch1_national/wdi_china_macro_2005_2025.json").read_text(encoding="utf-8"))
    units = {"NY.GDP.MKTP.KN": "constant LCU (CNY; source series base)",
             "NY.GDP.MKTP.CN": "current CNY", "SP.POP.TOTL": "person",
             "NY.GDP.MKTP.KD.ZG": "%", "FP.CPI.TOTL": "index 2010=100",
             "PA.NUS.FCRF": "CNY/USD annual average"}
    for item in wdi[1]:
        if item["value"] is not None:
            identifier = item["indicator"]["id"]
            rows.append(record(int(item["date"]), "China", identifier, item["value"], units[identifier],
                               "WDI_CHINA_MACRO", f"indicator={identifier}; date={item['date']}",
                               item["indicator"]["value"] + "; WDI download version lastupdated=" + wdi[0]["lastupdated"]))
    frame = save_csv("china_macro_annual.csv", rows, FIELDS)
    register("china_macro_annual.csv", frame, ["WDI_CHINA_MACRO", "WDI_GDP_DEFINITION"], "2005-2025",
             "Demand drivers, real GDP, exchange rates, CPI",
             "WDI commonly incorporates national statistics, not an independent GDP observation; CPI is not technology capex deflator")
    gcb = pd.read_csv(DATA / "raw/batch1_national/GCB2025v15_MtCO2_flat.csv")
    china = gcb[gcb["ISO 3166-1 alpha-3"].eq("CHN") & gcb.Year.between(2005, 2024)]
    rows = []
    for _, row in china.iterrows():
        for variable in ["Total", "Coal", "Oil", "Gas", "Cement", "Flaring", "Other"]:
            rows.append(record(int(row.Year), "China", variable, row[variable], "Mt CO2",
                               "GCB_GCB2025v15_MtCO2_flat", f"ISO=CHN; Year={int(row.Year)}; {variable}",
                               "GCB2025v15 territorial fossil and industry emissions; excludes land-use net flux and removals",
                               "published_inventory_estimate"))
    frame = save_csv("china_co2_gcb_annual.csv", rows, FIELDS)
    register("china_co2_gcb_annual.csv", frame, ["GCB_GCB2025v15_MtCO2_flat",
             "GCB_GCB2025v15_MtCO2_flat_metadata", "GCB_GCB2025v15_sources_flat",
             "GCB_GCP_fossilCO2_2025v15"], "2005-2024",
             "Emissions crosscheck; fossil/industry component separation",
             "Not full-economy net GHG; GCB and OWID fuel series share Energy Institute sources, so not fully independent")
    discrepancy = china[["Coal", "Oil", "Gas", "Cement", "Flaring", "Other"]].sum(axis=1) - china.Total
    check("gcb_component_sum", discrepancy.abs().max() < 0.00002,
          f"Maximum component residual={discrepancy.abs().max():.8f} MtCO2")


def latest_and_conversion_tables():
    rows = []
    text = source_text("NBS_COMMUNIQUE_2025")
    for variable, value, unit, token, locator in [
        ("GDP_current", 1401879, "10^8 CNY", "1401879", "section I, GDP"),
        ("GDP_real_growth", 5.0, "%", "增长5.0%", "section I, real GDP growth"),
        ("year_end_population", 140489, "10^4 person", "140489", "section I, population"),
        ("exchange_rate", 7.1429, "CNY/USD annual average", "7.1429", "section I, exchange rate"),
        ("primary_energy_production", 51.3, "10^8 tce", "51.3亿吨标准煤", "section III"),
        ("primary_energy_consumption", 61.7, "10^8 tce", "61.7亿吨标准煤", "section XII"),
        ("coal_consumption_share", 51.4, "%", "51.4%", "section XII"),
        ("clean_energy_consumption_share_including_gas", 30.4, "%", "30.4%", "section XII"),
        ("NEV_production", 1652.4, "10^4 vehicle", "1652.4", "section I/III"),
        ("NEV_stock", 4397, "10^4 vehicle", "4397", "section I"),
    ]:
        check("nbs_2025_token_" + variable, token in text, locator)
        rows.append(record(2025, "China_mainland", variable, value, unit,
                           "NBS_COMMUNIQUE_2025", locator,
                           "Preliminary official bulletin; excludes Hong Kong, Macao and Taiwan; clean energy includes natural gas",
                           "preliminary_published"))
    frame = save_csv("nbs_latest_2025.csv", rows, FIELDS)
    register("nbs_latest_2025.csv", frame, ["NBS_COMMUNIQUE_2025"], "2025",
             "Partial latest-year macro/energy/vehicle crosscheck",
             "Not a full energy balance or transport activity panel; WDI exchange-rate discrepancy unresolved")
    macro = pd.read_csv(OUT / "china_macro_annual.csv")
    wdi_fx = float(macro.loc[macro.year.eq(2025) & macro.variable.eq("PA.NUS.FCRF"), "value"].iloc[0])
    check("fx_2025_cross_source_agreement", abs(wdi_fx - 7.1429) < 0.001,
          f"WDI={wdi_fx}; NBS=7.1429 CNY/USD. Keep versions separate; no price conversion pending definition/version check.",
          severity="warning")
    rows = []
    # Transcribed from archived table 9-10 after visually checking all selected rows.
    efficiency = [
        (2005, 71.1, 39.0, 97.1, 96.9), (2014, 73.1, 43.5, 93.7, 97.5),
        (2015, 73.4, 44.2, 92.1, 96.9), (2016, 73.5, 44.6, 92.8, 96.4),
        (2017, 73.0, 45.0, 92.8, 96.0), (2018, 72.8, 45.5, 92.4, 95.6),
        (2019, 69.7, 45.8, 92.6, 95.3), (2020, 70.1, 46.2, 93.1, 95.3),
        (2021, 69.9, 47.1, 93.2, 95.4), (2022, 69.9, 47.9, 93.3, 95.5),
        (2023, 70.4, 47.9, 93.4, 96.3),
    ]
    for year, *values in efficiency:
        for variable, value in zip(["conversion_total", "generation_and_heat",
                                    "coking", "refining_and_oil_products"], values):
            rows.append(record(year, "China_mainland", variable, value, "%",
                               "NBS_2025_C09-10", f"table 9-10 image; year={year}; column={variable}",
                               "Aggregate statistical conversion efficiency, not individual generating-unit electric efficiency. Total excludes coal washing from 2019 (GB/T 28398-2023).",
                               "visually_verified_transcription"))
    frame = save_csv("nbs_conversion_efficiency.csv", rows, FIELDS)
    register("nbs_conversion_efficiency.csv", frame, ["NBS_2025_C09-10"], "2005,2014-2023",
             "Aggregate conversion-efficiency checkpoints",
             "Combined generation/heat statistic cannot become a coal/gas plant efficiency; total has a 2019 coverage break")
    rows = []
    values = {
        2024: [
            ("conventional_hydro_capacity", 377, "GW", "3.77亿千瓦"),
            ("pumped_hydro_capacity", 58.69, "GW", "5869万千瓦"),
            ("wind_capacity", 521, "GW", "5.21亿千瓦"),
            ("offshore_wind_capacity", 41.27, "GW", "4127万千瓦"),
            ("solar_PV_capacity", 886, "GW", "8.86亿千瓦"),
            ("biomass_capacity", 45.99, "GW", "4599万千瓦"),
            ("hydro_generation", 1423.9, "TWh", "14239亿千瓦时"),
            ("wind_generation", 991.6, "TWh", "9916亿千瓦时"),
            ("solar_PV_generation", 834.1, "TWh", "8341亿千瓦时"),
            ("biomass_generation", 208.3, "TWh", "2083亿千瓦时"),
            ("wind_energy_utilization_rate", 95.9, "%", "95.9%"),
            ("solar_PV_energy_utilization_rate", 96.8, "%", "96.8%"),
        ],
        2025: [
            ("conventional_hydro_capacity", 380, "GW", "3.8亿千瓦"),
            ("pumped_hydro_capacity", 65.94, "GW", "6594万千瓦"),
            ("wind_capacity", 640, "GW", "6.4亿千瓦"),
            ("offshore_wind_capacity", 47, "GW", "0.47亿千瓦"),
            ("solar_PV_capacity", 1200, "GW", "12亿千瓦"),
            ("biomass_capacity", 47.43, "GW", "4743万千瓦"),
            ("CSP_capacity", 1.82, "GW", "182万千瓦"),
            ("hydro_generation", 1460, "TWh", "1.46万亿千瓦时"),
            ("wind_generation", 1130, "TWh", "1.13万亿千瓦时"),
            ("solar_PV_generation", 1170, "TWh", "1.17万亿千瓦时"),
            ("biomass_generation", 224.7, "TWh", "2247亿千瓦时"),
            ("CSP_generation", 1.6, "TWh", "16亿千瓦时"),
            ("wind_energy_utilization_rate", 94, "%", "94%"),
            ("solar_PV_energy_utilization_rate", 95, "%", "95%"),
        ],
    }
    for year, entries in values.items():
        source = "NEA_RENEWABLE_" + str(year)
        text = source_text(source)
        for variable, value, unit, token in entries:
            check(f"renewables_{year}_{variable}", token in text, token)
            rows.append(record(year, "China_mainland", variable, value, unit, source,
                               "technology subsection; token=" + token,
                               "Source rounded national values; PV is not all solar; hydro generation scope may differ by publication; utilization rate is not capacity factor",
                               "published_rounded_converted_units"))
    frame = save_csv("nea_renewables_2024_2025.csv", rows, FIELDS)
    register("nea_renewables_2024_2025.csv", frame,
             ["NEA_RENEWABLE_2024", "NEA_RENEWABLE_2025"], "2024,2025",
             "Conventional/pumped hydro split, biomass, PV/CSP and utilization references",
             "Two-year snapshots; no inferred hourly capacity factors, biomass feedstock supply or 2024 new-storage state")


def prices_and_market():
    rows = []
    definitions = {
        "Crude oil, average": "USD/bbl", "Crude oil, Brent": "USD/bbl",
        "Coal, Australian": "USD/metric tonne", "Natural gas, US": "USD/MMBtu",
        "Natural gas, Europe": "USD/MMBtu", "Liquefied natural gas, Japan": "USD/MMBtu",
    }
    for source_id, filename, status in [
        ("WB_PINK_SHEET_STABLE", "wb_commodity_prices_stable.xlsx", "archived_reference"),
        ("WB_PINK_SHEET_ANNUAL", "wb_commodity_prices_annual.xlsx", "quarantined_version_check"),
    ]:
        frame = pd.read_excel(DATA / "raw/batch1_national" / filename,
                              sheet_name="Annual Prices (Nominal)", header=6)
        for _, row in frame.iterrows():
            year = pd.to_numeric(row.iloc[0], errors="coerce")
            if pd.isna(year) or not 2005 <= year <= 2025:
                continue
            for variable, unit in definitions.items():
                value = pd.to_numeric(row[variable], errors="coerce")
                if not pd.isna(value):
                    rows.append(record(int(year), "International_benchmark", variable, value, unit, source_id,
                                       f"'Annual Prices (Nominal)'!year={int(year)}; column={variable}",
                                       "Annual nominal benchmark; not Chinese delivered or contract price", status))
    frame = save_csv("commodity_price_references.csv", rows, FIELDS)
    register("commodity_price_references.csv", frame, ["WB_PINK_SHEET_STABLE", "WB_PINK_SHEET_ANNUAL"],
             "2005-2020 archived; 2005-2025 candidate",
             "Price reference and version comparison",
             "2026 endpoint workbook includes a comparison/editing Cover; candidate quarantined pending clean-original crosscheck",
             "mixed_eligibility_see_status")
    a = frame[frame.source_id.eq("WB_PINK_SHEET_STABLE")]
    b = frame[frame.source_id.eq("WB_PINK_SHEET_ANNUAL")]
    comparison = a.merge(b, on=["year", "variable"], suffixes=("_archive", "_candidate"))
    comparison["difference"] = comparison.value_candidate - comparison.value_archive
    comparison = save_csv("commodity_price_version_comparison.csv",
                         comparison[["year", "variable", "value_archive", "value_candidate", "difference"]])
    register("commodity_price_version_comparison.csv", comparison,
             ["WB_PINK_SHEET_STABLE", "WB_PINK_SHEET_ANNUAL"], "2005-2020 overlap",
             "Version diagnostic only; units inherit commodity_price_references.csv variable definitions",
             "No reconciliation or authority decision inferred from agreement/disagreement",
             "supporting_quality_diagnostic")
    rows = []
    for source_id, year, volume, amount, locator in [
        ("CEA_ANNUAL_2024", 2024, 188646053, 18113576584.23, "annual total"),
        ("CEA_ANNUAL_2025", 2025, 234597856, 14629891128.06, "Dec monthly bulletin; Jan-Dec annual cumulative"),
    ]:
        text = source_text(source_id)
        check(source_id + "_volume_in_source", f"{volume:,}" in text, locator)
        check(source_id + "_amount_in_source", f"{amount:,.2f}" in text, locator)
        for variable, value, unit in [
            ("annual_CEA_volume", volume, "t CO2 allowance"),
            ("annual_CEA_turnover", amount, "CNY nominal"),
            ("annual_transaction_weighted_unit_value", amount / volume, "CNY/t CO2 allowance"),
        ]:
            rows.append(record(year, "National_ETS", variable, value, unit, source_id, locator,
                               "All reported trade modes; turnover/volume is not daily close-price mean",
                               "derived_ratio" if "weighted" in variable else "published_market_total"))
    frame = save_csv("cea_market_annual.csv", rows, FIELDS)
    register("cea_market_annual.csv", frame, ["CEA_ANNUAL_2024", "CEA_ANNUAL_2025"], "2024,2025",
             "Carbon-market aggregate unit value", "2025 source is monthly, annual cumulative explicitly extracted; 2021-2023 remain a gap")


PROVINCES = [
    ("BJ", "北京"), ("TJ", "天津"), ("HE", "河北"), ("SX", "山西"), ("NM", "内蒙古"),
    ("LN", "辽宁"), ("JL", "吉林"), ("HL", "黑龙江"), ("SH", "上海"), ("JS", "江苏"),
    ("ZJ", "浙江"), ("AH", "安徽"), ("FJ", "福建"), ("JX", "江西"), ("SD", "山东"),
    ("HA", "河南"), ("HB", "湖北"), ("HN", "湖南"), ("GD", "广东"), ("GX", "广西"),
    ("HI", "海南"), ("CQ", "重庆"), ("SC", "四川"), ("GZ", "贵州"), ("YN", "云南"),
    ("XZ", "西藏"), ("SN", "陕西"), ("GS", "甘肃"), ("QH", "青海"), ("NX", "宁夏"), ("XJ", "新疆"),
]


def mechanisms():
    file = DATA / "raw/batch2_mechanisms/zenodo_Appendix_1_Hourly_electric_power_load_final.csv"
    with file.open(encoding="utf-8-sig") as stream:
        raw_headers = next(csv.reader(stream, delimiter=";"))
    load = pd.read_csv(file, sep=";")
    check("load_8760_by_31", load.shape == (8760, 32), load.shape)
    check("load_hours_contiguous", load.iloc[:, 0].tolist() == list(range(1, 8761)), "Hourly index 1..8760")
    check("load_nonnegative_complete", load.iloc[:, 1:].notna().all().all() and load.iloc[:, 1:].min().min() >= 0,
          f"Minimum hourly energy={load.iloc[:, 1:].min().min()}")
    rows = []
    for index, (code, province) in enumerate(PROVINCES, 1):
        rows.append(dict(position=index, raw_header=raw_headers[index], province=province,
                         canonical_code=code,
                         mapping_basis="Positional province sequence crosschecked with abbreviations sheet; raw first HB=Hebei, second HB=Hubei",
                         status="positional_mapping_requires_regional_spotcheck"))
    mapping = save_csv("province_column_mapping.csv", rows)
    register("province_column_mapping.csv", mapping,
             ["ZENODO_LOAD_FILE_1", "ZENODO_LOAD_FILE_4"], "2018 load",
             "Explicit source-column to province mapping",
             "First HB is assigned to Hebei by source province order; spatial validation remains necessary",
             "supporting_mapping")
    check("raw_load_duplicate_header_detected", raw_headers.count("HB") == 2,
          "Duplicate HB retained in raw; canonical output first HE, second HB")
    prepared = load.copy()
    prepared.columns = ["hour_index"] + [code for code, _ in PROVINCES]
    prepared.insert(0, "timestamp_UTC_plus_08", [
        (datetime(2018, 1, 1) + timedelta(hours=i)).isoformat() + "+08:00" for i in range(8760)
    ])
    prepared.to_csv(OUT / "province_load_2018_MWh.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    register("province_load_2018_MWh.csv", prepared, ["ZENODO_LOAD_FILE_1", "ZENODO_LOAD_FILE_2", "ZENODO_LOAD_FILE_4"],
             "2018 hourly", "Illustrative province load chronology",
             "Reconstructed from daily extremes and typical-day profiles; units hourly MWh, not independent hourly meter observations")
    totals = []
    for code, province in PROVINCES:
        totals.append(dict(year=2018, province=province, code=code,
                           annual_TWh=float(prepared[code].sum() / 1e6),
                           peak_hour_MWh=float(prepared[code].max()),
                           source_id="ZENODO_LOAD_FILE_1", status="reconstructed_not_observed"))
    summary = save_csv("province_load_2018_summary.csv", totals)
    register("province_load_2018_summary.csv", summary, ["ZENODO_LOAD_FILE_1"], "2018",
             "Reconstructed hourly series annual/peak aggregation",
             "Derived from same load data, not independent validation; peak is one-hour energy in MWh",
             "supporting_aggregation")
    check("load_total_source_rounding", abs(summary.annual_TWh.sum() - 6900.1) < 0.01,
          f"Load sum={summary.annual_TWh.sum():.4f} TWh; not forced to match separate annual statistics")
    book = pd.ExcelFile(DATA / "raw/batch2_mechanisms/zenodo_Appendix_3_Transmission_lines_between_provinces.xlsx")
    edges = []
    for sheet in ["HVAC", "HVDC"]:
        data = pd.read_excel(book, sheet_name=sheet)
        for _, row in data.iterrows():
            edges.append(dict(source_sheet_label=sheet, line_no=row.iloc[0], capacity_GW=row.iloc[1],
                              from_province_code=row.iloc[2], to_province_code=row.iloc[3], reference_year=2022,
                              source_id="ZENODO_LOAD_FILE_4",
                              status="quarantined_type_and_year_crosscheck",
                              note="Workbook AC/DC labels appear reversed for recognizable corridors; preserve labels, do not auto-correct or treat as net transfer capability"))
    frame = save_csv("transmission_lines_candidate.csv", edges)
    register("transmission_lines_candidate.csv", frame, ["ZENODO_LOAD_FILE_4", "ZENODO_LOAD_FILE_2", "ZENODO_LOAD_FILE_5"],
             "Updated to 2022 per methods", "Candidate province links and nominal capacities",
             "AC/DC type mismatch suspected; nameplate is not secure simultaneous transfer capability; cannot initialize 2024 unchanged",
             "quarantined_type_and_year_crosscheck")
    plants = pd.read_csv(DATA / "raw/batch2_mechanisms/wri_global_power_plant_database.csv", low_memory=False)
    china = plants[plants.country.eq("CHN")].copy()
    china.insert(0, "source_id", "WRI_POWER_PLANTS")
    china.to_csv(OUT / "china_power_plants_wri_snapshot.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    register("china_power_plants_wri_snapshot.csv", china, ["WRI_POWER_PLANTS", "WRI_POWER_PLANTS_DEFINITIONS"],
             "v1.3 historical snapshot; variable field years", "Candidate names, fuel, coordinates and commissioning years",
             f"{len(china)} records, commissioning years present in {china.commissioning_year.notna().sum()}; not complete current fleet or retirement panel")
    check("plant_commissioning_missing_preserved", china.commissioning_year.isna().sum() > 0,
          f"{china.commissioning_year.isna().sum()} missing dates, not filled with zero")
    hydro = pd.read_csv(DATA / "raw/batch2_mechanisms/hydro_reservoir_attributes.csv")
    hydro.to_csv(OUT / "reservoir_attributes_candidate.csv", index=False, encoding="utf-8-sig", lineterminator="\n")
    register("reservoir_attributes_candidate.csv", hydro, ["HYDRO_RESERVOIR_ATTRIBUTES", "HYDRO_DAILY_METADATA"],
             "Historical year groups unlabeled in CSV", "43 reservoir identifiers, capacity and water-consumption attributes",
             "Repeated annual columns have no year row in CSV; do not assign dates; daily inflow payload not retrieved",
             "identifiers_usable_annual_groups_pending")
    rows = []
    dates = [
        (1, "2008-11-21", "2014-11-22", 1089, 40),
        (2, "2009-06-17", "2015-10-16", 1089, 40),
        (3, "2010-12-31", "2016-10-24", 1089, 40),
        (4, "2012-11-17", "2017-09-17", 1089, 40),
        (5, "2015-05-07", "2021-01-30", 1161, 60),
        (6, "2015-12-22", "2022-03-25", 1161, 60),
    ]
    for unit, start, operation, capacity, life in dates:
        rows.append(dict(project=f"Fuqing_{unit}", technology="nuclear", capacity_MW=capacity,
                         construction_start=start, first_operation="", commercial_operation=operation,
                         completion_date_precision="day", design_life_year=life,
                         source_id="MEE_FUQING_ASSETS",
                         note="Page shows 2015 publication label but contains 2022 status: living page, not 2015 information set; design life is not approved retirement date"))
    rows.append(dict(project="Baihetan", technology="hydro", capacity_MW=16000,
                     construction_start="2017-07", first_operation="2021-06-28",
                     commercial_operation="2022-12-20", completion_date_precision="day; construction month only",
                     design_life_year=None, source_id="PROJECT_BAIHETAN",
                     note="Full-capacity completion; do not interpret first operation as full commissioning"))
    frame = save_csv("project_timing_examples.csv", rows)
    register("project_timing_examples.csv", frame, ["MEE_FUQING_ASSETS", "NEA_FUQING_PROJECT", "PROJECT_BAIHETAN"],
             "2008-2022 dates; page retrieved 2026", "Observed construction/commissioning examples and nuclear design life",
             "7 examples from 2 sites, not representative delay distribution; approval/financing queue not observed")


def parameters_and_snapshots():
    rows = []
    def add(year, region, variable, value, unit, source, locator, boundary, status="published_parameter"):
        rows.append(record(year, region, variable, value, unit, source, locator, boundary, status))

    for fuel, default, lower, upper in [
        ("other_bituminous_coal", 94600, 89500, 99700),
        ("natural_gas", 56100, 54300, 58300),
        ("crude_oil", 73300, 71100, 75500),
        ("gas_diesel_oil", 74100, 72600, 74800),
    ]:
        for kind, value in [("default", default), ("lower", lower), ("upper", upper)]:
            add(2006, "IPCC_default", fuel + "_CO2_" + kind, value, "kg CO2/TJ NCV",
                "IPCC_ENERGY_STATIONARY", "PDF p16; Table 2.2",
                "Stationary energy-industry combustion defaults; source bounds not automatically Chinese parameter probabilities")
    for technology, capex, lower, upper, page in [
        ("onshore_wind", 856, 626, 1315, 71),
        ("utility_solar_PV", 591, 438, 867, 95),
        ("offshore_wind", 1520, 1434, 1869, 119),
    ]:
        for stat, value in [("weighted_average", capex), ("p05", lower), ("p95", upper)]:
            add(2024, "China", technology + "_installed_cost_" + stat, value, "2024 USD/kW",
                "IRENA_COST_2024_PDF", f"PDF p{page}; China row",
                "Newly commissioned project total installed cost; project dispersion is not a future learning-rate interval")
    for tech, value, page in [("onshore_wind", 0.029, 84), ("utility_solar_PV", 0.033, 106), ("offshore_wind", 0.056, 126)]:
        add(2024, "China", tech + "_LCOE", value, "2024 USD/kWh",
            "IRENA_COST_2024_PDF", f"PDF p{page}; China row, 2024",
            "LCOE benchmark, not enterprise revenue or an additional operating cost on top of capex/fuel")
    add(2022, "China", "coal_market_average_settlement_price", 0.449, "nominal CNY/kWh",
        "NEA_MARKET_ELECTRICITY_2022", "market regulator statement",
        "Coal generating unit market transaction mean; not uniform all-technology retail tariff")
    frame = save_csv("technology_accounting_parameters.csv", rows, FIELDS)
    register("technology_accounting_parameters.csv", frame,
             ["IPCC_ENERGY_STATIONARY", "IRENA_COST_2024_PDF", "NEA_MARKET_ELECTRICITY_2022"],
             "2006 defaults; 2022 settlement; 2024 capex/LCOE", "Starting parameter evidence",
             "Thermal investment/O&M, efficiencies, storage round-trip losses and capital structure still incomplete")
    rows.clear()
    for variable, value, unit, locator in [
        ("gas_production", 2465, "10^8 m3", "PDF p11"),
        ("gas_imports_total", 1817, "10^8 m3", "PDF p12"),
        ("gas_imports_pipeline", 760, "10^8 m3", "PDF p12"),
        ("gas_imports_LNG", 1057, "10^8 m3", "PDF p12"),
        ("gas_top5_import_volume", 1477, "10^8 m3", "PDF p12"),
        ("gas_city_distribution_share", 34, "%", "PDF p10"),
        ("gas_industrial_fuel_share", 41, "%", "PDF p10"),
        ("gas_power_share", 18, "%", "PDF p11"),
        ("gas_chemical_fertilizer_share", 7, "%", "PDF p11"),
        ("gas_new_storage_capacity", 80, "10^8 m3", "PDF p13"),
    ]:
        add(2024, "China", variable, value, unit, "NEA_NATURAL_GAS_2025", locator,
            "Report 2025 describes 2024; volume standard conditions and report categories retained; added storage is not actual inventory or daily withdrawal capability")
    add(2024, "China", "gas_apparent_consumption_flash", 4260.5, "10^8 m3",
        "NDRC_GAS_APPARENT_2024", "annual flash total",
        "Apparent consumption; do not equate to report end-use consumption without inventory/export/standard-condition check")
    for variable, value, unit, status in [
        ("hydrogen_output", 3650, "10^4 tonne", "lower_bound_exceeds"),
        ("coal_hydrogen_output", 2070, "10^4 tonne", "approximate"),
        ("gas_hydrogen_output", 760, "10^4 tonne", "approximate"),
        ("byproduct_hydrogen_output", 770, "10^4 tonne", "approximate"),
        ("electrolysis_hydrogen_output", 32, "10^4 tonne", "approximate"),
        ("renewable_hydrogen_capacity", 12.5, "10^4 tonne/year", "approximate"),
    ]:
        add(2024, "China", variable, value, unit, "NEA_HYDROGEN_2025", "PDF pp16-17",
            "Hydrogen includes feedstock and fuel; approximate categories need not sum; renewable capacity is not output", status)
    add(2025, "China", "new_storage_power", 136, "GW", "NEA_STORAGE_2025", "installed storage statement",
        "New-type storage, excludes pumped hydro", "rounded_published")
    add(2025, "China", "new_storage_energy", 351, "GWh", "NEA_STORAGE_2025", "installed storage statement",
        "New-type storage, excludes pumped hydro; nameplate, not event initial energy", "rounded_published")
    add(2025, "China", "new_storage_average_duration", 2.58, "hour", "NEA_STORAGE_2025", "duration statement",
        "Published fleet average, not uniform duration of all projects")
    for region, value in [("North", 32.5), ("Northwest", 28.2), ("East", 14.4), ("South", 13.1), ("Central", 11.1), ("Northeast", 0.7)]:
        add(2025, region, "new_storage_power_share", value, "%", "NEA_STORAGE_2025", "regional share statement",
            "Report grid-region definition; do not assume same as final model region grouping")
    frame = save_csv("fuel_storage_hydrogen_snapshots.csv", rows, FIELDS)
    register("fuel_storage_hydrogen_snapshots.csv", frame,
             ["NEA_NATURAL_GAS_2025", "NDRC_GAS_APPARENT_2024", "NEA_HYDROGEN_2025", "NEA_STORAGE_2025"],
             "2024,2025", "Shared-fuel allocation, import exposure and storage/hydrogen size",
             "Annual/snapshot constraints; no hourly fuel allocation, usable inventory, withdrawal curve, or full ten-year hydrogen panel")
    rows.clear()
    for region, value in [
        ("China", .5306), ("华北", .6361), ("东北", .5122), ("华东", .5500),
        ("华中", .5271), ("西北", .5543), ("南方", .4042), ("西南", .2472),
        ("北京", .5554), ("天津", .6796), ("河北", .6516), ("山西", .6634), ("内蒙古", .6479),
        ("辽宁", .4878), ("吉林", .4671), ("黑龙江", .5229), ("上海", .5737), ("江苏", .5827),
        ("浙江", .4974), ("安徽", .6553), ("福建", .4211), ("江西", .5836), ("山东", .6191),
        ("河南", .5897), ("湖北", .4044), ("湖南", .4976), ("广东", .4419), ("广西", .4476),
        ("海南", .3648), ("重庆", .5581), ("四川", .1564), ("贵州", .5683), ("云南", .1333),
        ("陕西", .6335), ("甘肃", .4471), ("青海", .1796), ("宁夏", .6187), ("新疆", .6021),
    ]:
        add(2023, region, "average_electricity_CO2_factor", value, "kg CO2/kWh",
            "MEE_ELECTRICITY_CO2_2023", "PDF pp1-2, tables 1-3",
            "Published electricity accounting factor; not generator marginal emissions; Tibet not present in source provincial table")
    frame = save_csv("electricity_co2_factors_2023.csv", rows, FIELDS)
    register("electricity_co2_factors_2023.csv", frame, ["MEE_ELECTRICITY_CO2_2023"], "2023",
             "National/regional/provincial electricity-accounting crosscheck",
             "30 provincial factors only; electricity use emission allocation must not double-count generation emissions")


def policies():
    rows = []
    for year, variable, value, unit, source, locator, qualifier in [
        (2030, "nonfossil_primary_share", 25, "%", "POLICY_CARBON_2026", "overall goals", "target"),
        (2030, "CO2_GDP_reduction_vs_2025", 17, "%", "POLICY_CARBON_2026", "overall goals", "target"),
        (2030, "wind_solar_capacity", 2800, "GW", "POLICY_CARBON_2026", "section II(1)", "at_least"),
        (2030, "conventional_hydro_capacity", 410, "GW", "POLICY_CARBON_2026", "section II(1)", "approximately"),
        (2030, "nuclear_operating_capacity", 110, "GW", "POLICY_CARBON_2026", "section II(1)", "approximately"),
        (2030, "pumped_hydro_capacity", 160, "GW", "POLICY_CARBON_2026", "section II(2)", "approximately"),
        (2030, "new_storage_power", 300, "GW", "POLICY_CARBON_2026", "section II(2)", "aspirational"),
        (2030, "demand_response_peak_share", 5, "%", "POLICY_CARBON_2026", "section II(2)", "at_least"),
        (2030, "CO2_GDP_reduction_vs_2005", 65, "%", "POLICY_CARBON_2021", "goals", "more_than"),
        (2060, "nonfossil_primary_share", 80, "%", "POLICY_CARBON_2021", "goals", "at_least"),
    ]:
        rows.append(record(year, "China", variable, value, unit, source, locator,
                           "Policy goal, not observed future data or guaranteed model outcome; " + qualifier, "policy_target"))
    frame = save_csv("policy_target_reference.csv", rows, FIELDS)
    register("policy_target_reference.csv", frame, ["POLICY_CARBON_2026", "POLICY_CARBON_2021", "POLICY_NDC_2035"],
             "2030,2060 targets; 2021/2026 documents", "Scenario comparison targets",
             "Does not specify full implemented incentives, future GDP, prices, removals or feasible technical pathways")


def inventory_and_coverage():
    check("source_ids_unique", len(SOURCE) == len(SOURCES), "Source identifiers must be unique")
    check("processed_all_registered",
          {p.name for p in OUT.glob("*.csv")} == {d["dataset"] for d in DATASETS},
          "Every processed CSV is covered by dataset_inventory.csv")
    variable_rows = []
    for dataset in DATASETS:
        frame = pd.read_csv(DATA / dataset["path"])
        check("shape_" + dataset["dataset"],
              frame.shape == (dataset["rows"], dataset["columns"]), frame.shape)
        ids = set(dataset["source_ids"].split(";"))
        check("lineage_" + dataset["dataset"],
              ids <= set(SOURCE) and all((DATA / SOURCE[s]["path"]).exists() for s in ids),
              sorted(ids))
        if set(FIELDS) <= set(frame.columns):
            check("long_table_fields_" + dataset["dataset"],
                  frame[FIELDS].notna().all().all(), "Long rows must have numeric value, unit, source and boundary")
            check("numeric_finite_" + dataset["dataset"], np.isfinite(frame.value).all(),
                  "No fabricated NaN/Inf numeric observations")
            check("unique_key_" + dataset["dataset"],
                  not frame.duplicated(["year", "region", "variable", "source_id"]).any(),
                  "Same year/region/variable/source cannot be counted twice")
            check("row_sources_" + dataset["dataset"], set(frame.source_id) <= ids,
                  sorted(set(frame.source_id) - ids))
            for (variable, unit), group in frame.groupby(["variable", "unit"]):
                variable_rows.append(dict(dataset=dataset["dataset"], variable=variable, unit=unit,
                                          source_ids=";".join(sorted(group.source_id.unique())),
                                          observed_year_min=group.year.min(),
                                          observed_year_max=group.year.max(),
                                          distinct_observed_years=group.year.nunique(),
                                          boundary=" | ".join(group.boundary.unique()),
                                          status=";".join(sorted(group.status.unique()))))
    pd.DataFrame(variable_rows).to_csv(CAT / "variable_dictionary.csv", index=False, encoding="utf-8-sig")
    support = json.loads((CAT / "support_and_gap_matrix.json").read_text(encoding="utf-8"))
    check("assumptions_support_complete",
          {x["id"] for x in support["assumptions"]} ==
          {f"A{i:02d}" for i in range(1, 11)} | {"H01", "H02"}, "A01-A10 and H01/H02")
    for entry in support["assumptions"] + support["gaps"]:
        check("support_evidence_" + entry["id"],
              all((OUT / name).exists() for name in entry["datasets"]),
              entry["datasets"])
    check("all_gaps_have_disposition",
          all(x["decision"] and x["next_evidence"] and x["claim_limit"] for x in support["gaps"]),
          f'{len(support["gaps"])} gap decisions')
    inventory = []
    for source in SOURCES:
        file = DATA / source["path"]
        retrieval = RETRIEVAL.get(source["id"], {})
        present = file.exists()
        checksum = hashlib.sha256(file.read_bytes()).hexdigest() if present else ""
        check("raw_hash_" + source["id"], not present or checksum == retrieval.get("sha256"),
              source["path"])
        status = "download_failed" if not present else "archived_not_all_fields_extracted"
        if source["role"] in {"discovery", "access_check", "dataset_metadata", "definitions"}:
            status = "metadata_only_not_numeric_dataset" if present else "download_failed"
        derived = [d["dataset"] for d in DATASETS if source["id"] in d["source_ids"].split(";")]
        if derived:
            status = "used_in_processed_tables_scope_limits_apply"
        inventory.append(dict(**source, file_exists=present, bytes=file.stat().st_size if present else 0,
                              sha256=checksum, retrieved_at=retrieval.get("retrieved_at", ""),
                              acquisition_status=status, processed_tables=";".join(derived),
                              download_error=retrieval.get("error", "")))
    pd.DataFrame(inventory).to_csv(CAT / "source_inventory.csv", index=False, encoding="utf-8-sig")
    pd.DataFrame(DATASETS).to_csv(CAT / "dataset_inventory.csv", index=False, encoding="utf-8-sig")
    annual_sets = {
        "official_energy_total_and_structure": ("nbs_energy_annual.csv", "production_10ktce"),
        "official_energy_consumption": ("nbs_energy_annual.csv", "consumption_10ktce"),
        "official_energy_consumption_coal_share": ("nbs_energy_annual.csv", "consumption_coal_pct"),
        "official_installed_capacity": ("nbs_capacity_annual.csv", "total_10kW"),
        "official_thermal_capacity": ("nbs_capacity_annual.csv", "thermal_10kW"),
        "official_hydro_capacity": ("nbs_capacity_annual.csv", "hydro_10kW"),
        "official_nuclear_capacity": ("nbs_capacity_annual.csv", "nuclear_10kW"),
        "official_wind_capacity": ("nbs_capacity_annual.csv", "wind_10kW"),
        "official_solar_capacity": ("nbs_capacity_annual.csv", "solar_10kW"),
        "official_product_generation": ("nbs_products_annual.csv", "generation_100GWh"),
        "coal_primary_production_research": ("china_energy_research_annual.csv", "coal_production"),
        "oil_primary_production_research": ("china_energy_research_annual.csv", "oil_production"),
        "gas_primary_production_research": ("china_energy_research_annual.csv", "gas_production"),
        "coal_primary_consumption_research": ("china_energy_research_annual.csv", "coal_consumption"),
        "oil_primary_consumption_research": ("china_energy_research_annual.csv", "oil_consumption"),
        "fuel_primary_consumption_research": ("china_energy_research_annual.csv", "gas_consumption"),
        "electricity_demand_research": ("china_energy_research_annual.csv", "electricity_demand"),
        "GDP_constant_LCU": ("china_macro_annual.csv", "NY.GDP.MKTP.KN"),
        "population": ("china_macro_annual.csv", "SP.POP.TOTL"),
        "territorial_fossil_industry_CO2": ("china_co2_gcb_annual.csv", "Total"),
    }
    sets = []
    for _, (filename, variable) in annual_sets.items():
        frame = pd.read_csv(OUT / filename)
        sets.append(set(frame.loc[frame.variable.eq(variable), "year"].astype(int)))
    common = sorted(set.intersection(*sets))
    continuous = [year for year in common if 2014 <= year <= 2024]
    check("core_annual_common_window", continuous == list(range(2014, 2025)), continuous)
    coverage = []
    for label, (filename, variable) in annual_sets.items():
        frame = pd.read_csv(OUT / filename)
        present = set(frame.loc[frame.variable.eq(variable), "year"].astype(int))
        for year in range(2005, 2026):
            coverage.append(dict(group=label, year=year, available=year in present, path="processed/" + filename,
                                 variable=variable, scope="national aggregate, not all mechanisms or independent validation"))
    pd.DataFrame(coverage).to_csv(CAT / "annual_coverage.csv", index=False, encoding="utf-8-sig")
    result = {
        "core_national_common_window": [2014, 2024],
        "core_window_year_count": 11,
        "candidate_national_baseline": 2024,
        "detailed_energy_balance_checkpoint": 2023,
        "latest_partial_crosscheck": 2025,
        "candidate_calibration_years": [2014, 2020],
        "candidate_holdout_years": [2021, 2024],
        "split_is_design_not_validation_result": True,
        "not_in_common_window_claim": [
            "continuous sector/provincial fuel balances",
            "clean-version delivered fuel price and enterprise tariffs",
            "same-year measured wind/solar/hydro/load event series",
            "complete project financial/approval/construction queues",
            "independent net-carbon-sink/removal pathway",
        ],
        "source_file_count": sum(x["file_exists"] for x in inventory),
        "failed_download_count": sum(not x["file_exists"] for x in inventory),
        "processed_dataset_count": len(DATASETS),
        "registered_source_count": len(SOURCES),
        "acquired_sources_by_batch": dict(Counter(str(x["batch"]) for x in inventory if x["file_exists"])),
        "assumption_support_count": len(support["assumptions"]),
        "gap_decision_count": len(support["gaps"]),
        "warning_count": sum(not c["passed"] and c["severity"] == "warning" for c in CHECKS),
        "checks": CHECKS,
        "error_count": sum(not c["passed"] and c["severity"] == "error" for c in CHECKS),
        "no_model_calibration_simulation_or_optimization_performed": True,
    }
    (CAT / "data_quality_checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "checks"}, ensure_ascii=False, indent=2))
    for item in CHECKS:
        if not item["passed"]:
            print("CHECK FAILED", item)
    if result["error_count"]:
        raise SystemExit("Data preparation checks failed; inspect before accepting the package.")


def main():
    transcriptions()
    national_research_series()
    latest_and_conversion_tables()
    prices_and_market()
    mechanisms()
    parameters_and_snapshots()
    policies()
    inventory_and_coverage()


if __name__ == "__main__":
    main()
