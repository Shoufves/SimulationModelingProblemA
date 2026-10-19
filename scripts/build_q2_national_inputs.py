"""Reproduce scoped Q2 observations from reviewed originals, without changing Q1 contracts.

The literal NBS cells and BTR/IEA cells below were read from the original page
images. Machine comparisons check transcription, not independent verification.
National simulations must separately disclose reconstruction assumptions.
"""
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data/processed/q2"
sys.path.insert(0,str(ROOT/"src"))
from energy_model.q2_admission import SOURCE_REQUIREMENTS


def sha(path):
    return hashlib.sha256((ROOT/path).read_bytes()).hexdigest()


def read(path):
    with (ROOT/path).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", encoding="utf-8")


# Image C09-02, columns total, coal, oil, gas, primary electricity and other.
ENERGY = {
    2005:[261369,72.4,17.8,2.4,7.4], 2006:[286467,72.4,17.5,2.7,7.4],
    2007:[311442,72.5,17.0,3.0,7.5], 2008:[320611,71.5,16.7,3.4,8.4],
    2009:[336126,71.6,16.4,3.5,8.5], 2010:[360648,69.2,17.4,4.0,9.4],
    2011:[387043,70.2,16.8,4.6,8.4], 2012:[402138,68.5,17.0,4.8,9.7],
    2013:[416913,67.4,17.1,5.3,10.2], 2014:[428334,65.8,17.3,5.6,11.3],
    2015:[434113,63.8,18.4,5.8,12.0], 2016:[441492,62.2,18.7,6.1,13.0],
    2017:[455827,60.6,18.9,6.9,13.6], 2018:[471925,59.0,18.9,7.6,14.5],
    2019:[485584,57.5,19.0,8.0,15.4], 2020:[496514,56.7,18.9,8.4,16.0],
    2021:[525027,55.7,18.8,8.8,16.7], 2022:[541274,55.6,18.4,8.4,17.6],
    2023:[571327,54.8,18.8,8.5,17.9], 2024:[596000,53.2,18.2,8.8,19.8]}
# Image C09-15: total, thermal, hydro, nuclear, wind, solar, other; 10^4 kW.
# 2011 reported total != sum: preserve the discrepancy; never rescale components.
CAPACITY = {
    2009:[87410,65108,19629,908,1760,3,3],
    2010:[96641,70967,21606,1082,2958,26,3],
    2011:[106253,76834,23298,1257,4623,212,19],
    2012:[114676,81968,24947,1257,6142,341,20],
    2013:[125768,87009,28044,1466,7652,1589,8],
    2014:[137887,93232,30486,2008,9657,2486,19],
    2015:[152527,100554,31954,2717,13075,4218,9],
    2016:[165051,106094,33207,3364,14747,7631,7],
    2017:[177708,110495,34359,3582,16325,12942,7],
    2018:[189997,114408,35259,4466,18427,17433,5],
    2019:[200985,118957,35804,4874,20915,20429,5],
    2020:[220504,124960,37028,4989,28165,25356,5],
    2021:[237689,129739,39094,5326,32871,30654,5],
    2022:[256317,133527,41396,5557,36564,39268,5],
    2023:[292224,139099,42237,5691,44144,61048,5],
    2024:[334922,144462,43552,6083,52078,88742,5]}
BTR = {
    2005:dict(positive=653345.2, net=580478.5, combustion=578429.9,
              process=74864.7, waste=50.7, removals=72866.7),
    2020:dict(positive=1120166.8, net=985904.0, combustion=966087.9,
              process=153211.8, waste=867.1, removals=134262.9),
    2021:dict(positive=1162800.9, net=1028151.0, combustion=1009504.3,
              process=152398.3, waste=898.3, removals=134649.9)}


def build():
    DEST.mkdir(parents=True, exist_ok=True)
    sources = {}
    catalog = json.loads((ROOT/"data/catalog/sources_unified.json").read_text(encoding="utf-8"))
    def source(path, use, review, locator):
        entries = [r for r in catalog if r.get("canonical_path") == path]
        sources[path] = dict(path=path, sha256=sha(path), source_keys=[r["source_key"] for r in entries],
            url=entries[0].get("url") if entries else None, allowed_use=use, review=review, locator=locator,
            status="author_scoped_review_not_team_approval",
            allowed_operations=SOURCE_REQUIREMENTS[path]["operations"])
        if use != SOURCE_REQUIREMENTS[path]["allowed_use"]:
            raise ValueError("Source-use contract differs from reviewed builder: "+path)
        return path
    nbs_e = source("data/raw/batch1_national/nbs_2025_C09-02.jpg", "energy_observations_and_initial_scale",
        "Full image visually read; 100 literal cells checked against unified CSV; PEO is not automatically nonfossil", "Table 9-2; 2005-2024")
    nbs_k = source("data/raw/batch1_national/nbs_2025_C09-15.jpg", "capacity_observations_and_initial_scale",
        "Full image visually read; 112 literal cells checked against unified CSV; thermal includes biomass; hydro includes pumped", "Table 9-15; 2009-2024")
    records = []
    def add(year, metric, value, unit, path, locator, boundary, use="observation"):
        if value is None:
            raise ValueError("Missing observations must be excluded, not imputed")
        records.append(dict(year=year, metric=metric, value=float(value), unit=unit,
            source_path=path, source_sha256=sha(path), locator=locator, boundary=boundary, use=use))
    unified = {(int(r["year"]),r["variable"]):float(r["value"]) for r in read("data/processed/unified/nbs_history.csv")}
    for year, values in ENERGY.items():
        fields = ["consumption_10ktce","consumption_coal_pct","consumption_oil_pct","consumption_gas_pct","consumption_primary_electricity_other_pct"]
        for field, value in zip(fields, values):
            if unified[year,field] != value and (year,field,unified[year,field],value) != (2006,"consumption_10ktce",284647,286467):
                raise ValueError(f"NBS energy original/CSV conflict {year} {field}")
            add(year,field,value,"10^4 tce" if field.endswith("10ktce") else "%",nbs_e,
                f"year={year}; column={field}","Mainland NBS statistical equivalent; PEO != proven nonfossil")
    for year, values in CAPACITY.items():
        for field,value in zip(["total","thermal","hydro","nuclear","wind","solar","other"],values):
            if unified[year,field+"_10kW"] != value:
                raise ValueError(f"NBS capacity original/CSV conflict {year} {field}")
            add(year,field+"_capacity_mw",value*10,"MW",nbs_k,f"year={year}; column={field}; x10 MW",
                "Mainland year-end stock; hydro includes pumped; thermal includes bioenergy")
    owid = source("data/raw/batch1_national/owid_energy_data.csv", "generation_observations_initial_decomposition_crosscheck",
        "CHN rows machine-matched to processed transcription; secondary compilation (EI/Ember); not independent of their upstream", "iso_code=CHN; years 2005-2024")
    raw = {int(r["year"]):r for r in read(owid) if r["iso_code"] == "CHN" and 2005 <= int(r["year"]) <= 2024}
    cols = ["electricity_generation","electricity_demand","coal_electricity","gas_electricity","oil_electricity",
            "hydro_electricity","nuclear_electricity","wind_electricity","solar_electricity","biofuel_electricity","net_elec_imports"]
    for r in read("data/processed/china_energy_research_annual.csv"):
        year,col = int(r["year"]),r["variable"]
        if year not in raw or col not in cols:
            continue
        if not raw[year].get(col) or float(raw[year][col]) != float(r["value"]):
            raise ValueError(f"OWID raw/processed mismatch {year} {col}")
        add(year,col+"_mwh",float(r["value"])*1e6,"MWh",owid,f"CHN,{year},{col}; TWh x1e6",
            "EI/Ember compilation; hydro includes pumped generation; biofuel overlaps other_renewable (not added)")
    macro = source("data/raw/batch1_national/wdi_china_macro_2005_2025.json", "constant_GDP_ratios_and_CPI_deflation",
        "All selected GDP/CPI values matched original API JSON; FX explicitly excluded after official NBS conflict", "CHN; GDP constant LCU, CPI; 2005-2024")
    raw_macro = json.loads((ROOT/macro).read_text(encoding="utf-8"))[1]
    original = {(int(r["date"]),r["indicator"]["id"]):r["value"] for r in raw_macro}
    for r in read("data/processed/china_macro_annual.csv"):
        year,col = int(r["year"]),r["variable"]
        if year > 2024 or col not in {"NY.GDP.MKTP.KN","FP.CPI.TOTL"}:
            continue
        if float(original[year,col]) != float(r["value"]):
            raise ValueError("WDI transcription changed")
        add(year,"real_gdp" if col.startswith("NY.") else "cpi",float(r["value"]),r["unit"],macro,
            f"indicator={col}; year={year}","GDP used only as constant-price ratios; CPI conversion is an explicit broad deflator proxy")
    btr = source("data/raw/lb/base/reports/china_btr1_2024.pdf", "CO2_calibration_sparse_years_and_conditional_bridge",
        "Table 1-4a physical pp30-31 visually checked; CO2 column only, 10^4 tonnes; HK/Macao chapters separate; no all-GHG neutrality claim",
        "Table 1-4a; physical pp30-31; printed pp20-21; 2005/2020/2021")
    for year, row in BTR.items():
        for key,value in row.items():
            add(year,"btr_"+key+"_co2_t",value*1e4,"t CO2",btr,f"Table 1-4a; {year}; {key}; x1e4",
                "National inventory Part I; CO2 only; international bunkers/biomass combustion memo items excluded")
    gcb = source("data/raw/batch1_national/GCB2025v15_MtCO2_flat.csv", "external_diagnostic_and_conditional_peak_bridge",
        "CHN raw annual Total rechecked for all 20 years, Mt to t; compared against BTR at all three common years. Separate author-scoped admission of annual relative-movement bridge, not empirical scope equivalence. See gcb_peak_bridge_review.json and docs/solutions/p2-lb-review7-response.md; never training or official peak certification", "Country China, ISO CHN, 2005-2024; Total; BTR table 1-4a 2005/2020/2021")
    for r in read(gcb):
        if r.get("ISO 3166-1 alpha-3") == "CHN" and 2005 <= int(r["Year"]) <= 2024:
            add(int(r["Year"]),"gcb_positive_co2_t",float(r["Total"])*1e6,"t CO2",gcb,
                f"CHN,{r['Year']},Total; Mt x1e6","GCB fossil and industry boundary, differs from BTR", "external_diagnostic_and_conditional_peak_bridge")
    gcb_values = {r["year"]:r["value"] for r in records if r["source_path"]==gcb}
    if set(gcb_values) != set(range(2005,2025)) or any(v<=0 for v in gcb_values.values()):
        raise ValueError("Incomplete/nonpositive GCB annual bridge")
    scale = BTR[2021]["positive"]*1e4/gcb_values[2021]
    bridge_review = dict(status="author_reviewed_conditional_bridge_not_empirical_equivalence",team_approved=False,
        reviewer="lb author; independent team review still required",source_hashes={p:sha(p) for p in (gcb,btr)},
        checked_years=list(range(2005,2025)),scale_btr2021_over_gcb2021=scale,
        formula="GCB_t[y] * BTR_positive_CO2_t[2021] / GCB_t[2021]; retain direct BTR observations in 2005/2020/2021",
        allowed_operations=["external_diagnostic","conditional_peak_bridge"],
        excluded_operations=["initialization","calibration","same_scope_evaluation","official_peak_certification"],
        limitations="Single-anchor proportional movement is a research assumption; residual differences at 2005/2020 remain. No process CO2 added to GCB, no LULUCF/net/all-GHG equivalence, no additional observations imputed for training.",
        common_year_checks=[dict(year=y,gcb_t=gcb_values[y],btr_positive_t=BTR[y]["positive"]*1e4,
            scaled_gcb_t=gcb_values[y]*scale,relative_gap_to_btr=gcb_values[y]*scale/(BTR[y]["positive"]*1e4)-1) for y in sorted(BTR)])
    dump(DEST/"gcb_peak_bridge_review.json",bridge_review)
    fx = source("data/raw/lb/ai_social/nbs_bulletin_2024.txt", "2024_currency_conversion",
        "Text explicitly reports annual mean 1 USD = 7.1217 CNY; WDI 7.197491 excluded, no averaging", "National 2024 bulletin; exchange-rate paragraph")
    if "7.1217" not in (ROOT/fx).read_text(encoding="utf-8-sig"):
        raise ValueError("Official FX evidence missing")
    add(2024,"cny_per_usd",7.1217,"CNY/USD",fx,"全年人民币平均汇率 paragraph","Annual average, not year-end")
    iea = source("data/raw/lb/base/reports/iea_oecd_generation_cost_2020.pdf", "technical_reference_not_observed_2024_fleet",
        "China rows physically checked pp50-51,58-61; direct overnight/O&M components, never residual LCOE; 2018 USD projected 2025 new plants",
        "Tables 3.2a,3.3,3.4a,3.11a,3.12,3.13a; methodology chapter2")
    tech = dict(
        coal=dict(overnight_usd2018_kw=800,efficiency=.45,om_usd2018_mwh=14.97,life=40,lead=4),
        gas=dict(overnight_usd2018_kw=560,efficiency=.58,om_usd2018_mwh=13.49,life=30,lead=3),
        nuclear=dict(overnight_usd2018_kw=2500,efficiency=.33,om_usd2018_mwh=26.42,fuel_usd2018_mwh=10,life=60,lead=7),
        source=iea, price_conversion="2018USD x6.62 CNY/USD (report Table2.2) x WDI CPI2024/CPI2018; broad deflator proxy")
    irena = source("data/raw/batch3_scenarios/irena_power_costs_2024.pdf", "wind_solar_capex_new_project_reference",
        "Reuse existing reviewed China new-project cells and source-locator chain; not national fleet CF; offshore/onshore distinct",
        "physical pp71,95,119; O&M p209 TableA3")
    for path, use in [("data/processed/technology_accounting_parameters.csv","IPCC and IRENA source-located reference cells"),
                      ("data/processed/q1/cost_method_parameters.csv","Q1 reviewed O&M cells; new Q2 conditional use"),
                      ("data/processed/q1/reviewed_2024_additions.csv","Q1 reviewed 2024 storage power/energy and nonfossil anchor, new scoped Q2 use"),
                      ("data/raw/official/S28_qinshan_design_life_capture.txt","First Chinese nuclear unit grid date 1991-12-15; restrict reconstructed nuclear age; not a national licence database"),
                      ("data/raw/batch3_scenarios/ipcc_2006_stationary_combustion.pdf","IPCC default NCV emission-factor reference"),
                      ("data/processed/fuel_storage_hydrogen_snapshots.csv","reported snapshots, not inferred inventory"),
                      ("data/processed/cea_market_annual.csv","2024 annual turnover/volume, not universal compliance price"),
                      ("data/raw/lb/international/cn_ets_allocation_2026.pdf","output-based allocation design, effective information after publication only"),
                      ("data/raw/lb/international/cn_ets_notice.txt","publication date 2026-09-02; no retrospective information"),
                      ("data/processed/policy_target_reference.csv","source-specific target comparison only, no forced attainment")]:
        source(path,use,"Scoped reference; exact implemented assumptions are separately declared",use)
    with (DEST/"national_observations.csv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(records[0])); w.writeheader(); w.writerows(records)
    dump(DEST/"technical_references.json",tech)
    review=dict(schema_version=1,owner="p2/lb",base_sha="804ec15ee43874303986a7ad91b2cde05c65b124",
        status="author_reviewed_conditional_research_inputs",team_approved=False,
        observations=len(records),sources=list(sources.values()),
        transcription_conflicts=[dict(year=2006,metric="consumption_10ktce",unified_csv=284647,
            original_image=286467,decision="Q2 uses visually verified original; Q1 files unchanged; outside training window")],
        exclusions=["data/restricted", "WDI exchange rate", "OWID other_renewable duplicated with biofuel",
            "NBS PEO as automatic official nonfossil", "GCB+BTR process double addition", "2026 policies before publication"],
        products={p.relative_to(ROOT).as_posix():sha(p.relative_to(ROOT)) for p in (DEST/"national_observations.csv",DEST/"technical_references.json",DEST/"gcb_peak_bridge_review.json")})
    dump(ROOT/"data/catalog/q2_national_input_review.json",review)
    print(json.dumps(dict(observations=len(records),source_files=len(sources),status=review["status"])))


if __name__ == "__main__":
    build()
