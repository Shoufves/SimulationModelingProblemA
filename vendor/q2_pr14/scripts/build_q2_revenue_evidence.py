"""Rebuild reviewed tariff observations and policy facts, without forecasting gaps.

Literal national figures below were read in the NEA originals. Exact-section
matching protects transcriptions; it does not establish a homogeneous panel.
These tables are NOT automatically admitted as a fleet's future cash receipts.
"""
import csv
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re

import pdfplumber

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data/processed/q2/revenue"
TECHS = ("coal", "hydro", "wind", "gas", "nuclear", "solar", "biomass")
PRICES = {
    2013: [427.01,283.19,562.31,682.60,436.15,1064.37,720.23],
    2014: [418.77,291.61,572.06,758.36,455.70,1075.82,846.14],
    2015: [384.20,286.93,594.01,789.82,434.03,1056.89,732.83],
    2016: [362.08,265.81,566.98,695.17,420.89,918.12,736.82],
    2017: [371.65,258.93,562.30,664.94,402.95,939.90,765.36],
    2018: [370.52,267.19,529.01,584.10,395.02,859.79,677.99],
}
AUX_USE = {
    2013: [7.01,1.54,2.50,2.66,6.27,10.20,9.64],
    2014: [6.99,1.38,2.51,2.59,6.24,8.59,9.46],
    2015: [6.94,1.71,3.08,3.06,6.38,2.43,13.37],
    2016: [6.74,.97,2.90,2.20,6.97,1.62,11.88],
    2017: [6.88,1.00,2.95,2.23,6.58,1.90,11.73],
    2018: [6.70,.95,2.52,2.87,6.19,1.81,11.40],
}
PRICE_PAGES = {2016:[4,5,6,6,6,6,6],2017:[4,5,6,6,6,6,6],2018:[5,6,6,8,8,7,8]}
AUX_PAGES = {2016:[1,2,3,3,3,3,3],2017:[1,2,3,3,3,3,3],2018:[1,2,3,4,4,3,4]}


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def html_text(path):
    parser = Text()
    raw = path.read_bytes()
    declaration = re.search(br"charset\s*=\s*[\"']?([\w-]+)", raw[:10000], re.I)
    encoding = declaration[1].decode("ascii") if declaration else "utf-8-sig"
    parser.feed(raw.decode(encoding))
    return re.sub(r"\s+", "", " ".join(parser.parts))


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def build():
    inventory = json.loads((ROOT/"data/raw/q2_revenue/source_inventory.json").read_text(encoding="utf-8"))
    sources = {r["path"]: r for r in inventory}
    for path, record in sources.items():
        if hashlib.sha256((ROOT/path).read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("Original changed: " + path)
    cache, records = {}, []
    for year in PRICES:
        name = "nea_prices_2013_2014.html" if year <= 2014 else f"nea_prices_{year}."+("html" if year == 2015 else "pdf")
        path = "data/raw/q2_revenue/"+name
        if path not in cache:
            if name.endswith("html"):
                cache[path] = {0: html_text(ROOT/path)}
            else:
                with pdfplumber.open(ROOT/path) as pdf:
                    cache[path] = {i+1: re.sub(r"\s+", "", p.extract_text() or "") for i,p in enumerate(pdf.pages)}
        for metric, values, page_map, marker in (
            ("feed_in_tariff",PRICES,PRICE_PAGES,"平均上网电价"),
            ("auxiliary_own_use",AUX_USE,AUX_PAGES,"综合厂用电率"),
        ):
            for index, tech in enumerate(TECHS):
                page = page_map[year][index] if year > 2015 else 0
                text = cache[path][page]
                # Only the national narrative; never match a provincial number
                # or the report's revised prior-year annex by accident.
                chunks = re.findall(r"从全国.{0,600}?(?:详见|见图)", text)
                value = values[year][index]
                number = f"{value:.2f}".rstrip("0").rstrip(".")
                suffix = r"0*" if "." in number else r"(?:\.0+)?"
                pattern = r"(?<![\d.])"+re.escape(number)+suffix+r"(?![\d.])"
                evidence = next((c for c in chunks if marker in c and re.search(pattern,c)),None)
                if evidence is None:
                    raise ValueError(f"National section mismatch: {year} {metric} {tech} {value}")
                records.append(dict(year=year,technology=tech,metric=metric,value=value,
                    unit="nominal_CNY_per_MWh_VAT_inclusive" if metric=="feed_in_tariff" else "percent_of_gross_generation",
                    source_path=path,source_sha256=sources[path]["sha256"],source_url=sources[path]["url"],
                    locator=f"physical page {page}; national narrative" if page else "national narrative; sections I/II",
                    evidence=evidence,report_vintage="2013_2014" if year<=2014 else str(year),
                    scope="reporting major power enterprises; mainland excluding Tibet; coverage/revisions vary",
                    allowed_use="historical_revenue_or_own_use_diagnostic_only",
                    blocked_use="automatic_cash_payment; homogeneous_panel; unreviewed_future_tariff; pure_oil_tariff"))
    DEST.mkdir(parents=True,exist_ok=True)
    with (DEST/"nea_tariff_and_auxiliary_use.csv").open("w",newline="",encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream,fieldnames=list(records[0]))
        writer.writeheader();writer.writerows(records)
    # Original 426 notice is explicit about VAT and accumulated eligibility.
    facts = []
    def fact(file, key, value, unit, anchors, limitation):
        path = "data/raw/q2_revenue/"+file
        text = html_text(ROOT/path)
        if not all(re.sub(r"\s+", "", phrase) in text for phrase in anchors):
            raise ValueError("Policy text mismatch: "+key)
        facts.append(dict(key=key,value=value,unit=unit,source_path=path,source_sha256=sources[path]["sha256"],
            source_url=sources[path]["url"],verified_text_anchors=anchors,limitation=limitation,
            allowed_use="policy_rule_only_not_national_cash_observation"))
    life="mof_subsidy_lifetime_2020_426.html"
    fact("nea_full_purchase_2007_25.html","renewable_full_purchase_2007",2007,"start_year",
        ["2007年9月1日","生物质发电","优先调度"],
        "Safety/connection conditions still apply; does not include nuclear as renewable or prove nationwide perfect enforcement")
    fact("nea_clean_dispatch_2015_518.html","clean_dispatch_annual_plan_2015",2015,"start_year",
        ["发改运行[2015]518号","风电、光伏发电、生物质发电按照本地区资源条件全额安排发电","气电根据供热、调峰及平衡需要"],
        "Annual aggregate approximation; nuclear has safety/peaking conditions; gas not assigned baseload or guaranteed universal utilisation")
    fact(life,"biomass_lifetime_hours",82500,"hours",["82500","沼气"],"Eligible approved/listed projects only; commissioned capacity and prior generation required")
    fact(life,"biomass_years",15,"years_since_grid_connection",["满15年"],"Full anniversary boundary; do not reset clock at simulation initial year")
    fact(life,"wind_solar_years",20,"years_since_grid_connection",["满20年"],"Existing listed projects; new project eligibility determined separately")
    fact(life,"wind_resource_zone_hours",[48000,44000,40000,36000],"hours",["48000","44000","40000","36000"],"No unobserved nationwide average; offshore 52000 separate")
    fact(life,"solar_resource_zone_hours",[32000,26000,22000],"hours",["32000","26000","22000"],"Qualifying leader/2019-2020 bidding projects have 10% increase; zones required")
    fact(life,"subsidy_formula","(eligible_supported_tariff-local_coal_reference)/(1+applicable_VAT_rate)","CNY_per_kWh",["当地燃煤发电上网基准价","适用增值税率"],"NEA total tariff already contains support: never add full support twice; CPI applies after nominal settlement")
    fact("mof_levy_2013.html","levy_2013_09_25",15,"CNY_per_MWh",["2013年9月25日","1.5","居民生活和农业生产以外"],"Tax base is eligible consumption, not nationwide gross generation")
    # The original page uses a private-use punctuation glyph between 1 and 9.
    fact("mof_levy_2016.html","levy_2016_01_01",19,"CNY_per_MWh",["2016年1月1日","不含新疆维吾尔自治区、西藏自治区","居民生活和农业生产以外"],"Regional exemptions; eligible self-supply/direct transactions; collection rate and actual appropriations are not observed here")
    fact("mof_subsidy_budget_rules_2020.html","finite_budget",True,"rule",["以收定支","年度补贴总额","优先顺序"],"An equal-priority allocation algorithm is a research rule; actual recipient priority/annual cash remain separate inputs")
    fact("mof_vat_2018.html","general_goods_vat_2018_05_01",.16,"fraction",["17%","16%","2018年5月1日"],"General-regime goods rate; not an observed effective rate for the whole power fleet or tax refunds")
    fact("mof_vat_2019.html","general_goods_vat_2019_04_01",.13,"fraction",["16%","13%","2019年4月1日"],"General-regime rate; exemptions, refunds and input credits require separate treatment")
    fact("ndrc_biomass_tariff_2010.html","agroforestry_supported_tariff_2010",750,"nominal_VAT_inclusive_CNY_per_MWh",["0.75","2010年7月1日","高出部分"],"Agroforestry, not municipal waste or the whole aggregated bioenergy category; tender and pre-existing approved prices differ; only premium above local coal benchmark uses levy fund")
    fact("ndrc_waste_tariff_2012_801.html","municipal_waste_tariff_2012",650,"nominal_VAT_inclusive_CNY_per_MWh",["0.65","280","50%","0.1"],"Eligible waste electricity capped by verified waste tonnes times 280kWh/t and actual exports; low waste-equivalent fraction loses eligibility; provincial grid bears 0.1CNY/kWh premium before central allocation; exact 50% boundary requires separate clarification")
    fact("ndrc_gas_tariff_2014_3009.html","gas_provincial_differentiated_revenue_2015",True,"rule",["2015年1月1日","省级负责制","财政补贴","气价优惠"],"CHP, peaking and distributed gas have distinct provincial mechanisms; no nationwide uniform gas subsidy amount; heat revenues require heat load and physical output")
    fact("ndrc_renewable_parity_2021.html","new_onshore_wind_and_nonhousehold_pv_no_central_subsidy_2021",True,"rule",["2021年起","中央财政不再补贴","陆上风电"],"Scope is new approvals/filings specified by policy, not cancellation of existing qualified claims or all solar/wind categories")
    fact("ndrc_renewable_market_2025.html","renewable_market_difference_settlement_2025",True,"rule",["2025年6月1日","差价结算","系统运行费用"],"Provincial eligible energy, mechanism price, term and project vintage required; two-sided price settlement is not renewable-levy fiscal subsidy; not yet connected to default model")
    dump(DEST/"subsidy_policy_facts.json",facts)
    dump(ROOT/"data/catalog/q2_revenue_review.json",dict(status="author_scoped_source_review_not_model_activation_or_team_approval",
        reviewed_on="2026-10-20",source_sha256={p:r["sha256"] for p,r in sources.items()},
        observation_count=len(records),policy_fact_count=len(facts),
        scope_notes=["Historical report vintages not spliced into a homogeneous census", "Prices include VAT and support; no cash collection observation",
        "Local subsidy allocation cannot stand for national budget", "No post-2018 tariff or national levy base imputed",
        "CPI and applicable tax treatment must be explicit before operational revenue admission",
        "Own-use is distinct from grid loss; shared optional physical/revenue boundary implemented, national inputs not activated",
        "Gas differentiated provincial revenues, agroforestry support, waste two-level allocation and 2025 market difference settlement must remain separate"],
        production_model_activated=False,team_approved=False))
    print(f"Built {len(records)} tariff/own-use observations and {len(facts)} policy facts")


if __name__ == "__main__":
    build()
