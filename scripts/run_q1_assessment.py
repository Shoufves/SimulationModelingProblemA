"""Reproduce mmj's Q1 candidate offline; no implicit download or model admission."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from energy_model.q1 import (Q1Error, balance_table, concentration, identity, inside,
    number, price_volatility, ratio_records, read_csv, read_json, screening_lcoe,
    sha, spatial_difference, write_csv, write_json)

HISTORY_FIELDS = ["record_id","year","region","energy","variable","value","unit",
    "source_key","source_locator","input_id","input_path","original_value","transformation",
    "status","boundary","missing_reason","independence","selected_provenance_path","selected_source_key"]
INDICATOR_FIELDS = ["indicator_id","dimension","year","region","energy","value","unit",
    "direction","formula","input_refs","valid_years","status","interpretation"]
GAP_FIELDS = ["gap_id","topic","years","status","evidence","reason","impact","next_action"]
ROLE_FIELDS = ["energy","role","advantage","shortcoming","synergy","evidence","q2_position","boundary"]
HANDOFF_FIELDS = ["handoff_id","kind","year","variable","value","unit","evidence",
    "status","condition","model_position","split"]


def git(*args):
    result = subprocess.run(["git","-C",str(ROOT),*args], capture_output=True,
                            encoding="utf-8", errors="replace")
    if result.returncode:
        raise Q1Error("Cannot record Git provenance")
    return result.stdout.strip()


def energy_name(var):
    for token, name in [("hydrogen","氢"),("coal","煤"),("oil","油"),("crude","油"),
                        ("gas","气"),("hydro","水电"),("nuclear","核电"),("wind","风电"),
                        ("solar","太阳能"),("pv","光伏"),("biomass","生物质"),("storage","储能")]:
        if token in var.lower():
            return name
    return "综合/电力"


def validate_inputs(root, manifest):
    if manifest.get("schema_version") != 1 or manifest.get("candidate") != "p1/mmj":
        raise Q1Error("Unknown Q1 input contract")
    ids = [r["id"] for r in manifest["inputs"]]
    expected = {"nbs","products","balance","demand","province","macro","co2","snapshot",
                "cost","cost_method","price","pipeline","lng","coal_trade","communique","renewables"}
    if set(ids) != expected or len(ids) != len(expected):
        raise Q1Error("Missing or duplicate Q1 input groups")
    entries = [*manifest["inputs"], *manifest["sources"].values(), manifest["evidence_review"]]
    for item in entries:
        path = inside(root, item["path"])
        if not path.is_file() or sha(path) != item["sha256"]:
            raise Q1Error("Input missing or fingerprint mismatch: " + item["path"])
    review = read_json(inside(root, manifest["evidence_review"]["path"]))
    if not review["checks"] or not all(r["passed"] for r in review["checks"]):
        raise Q1Error("Q1 evidence review has unresolved failures")
    return {r["id"]: r for r in manifest["inputs"]}


def normalize(root, inputs):
    all_rows, by_input = [], {}
    for key, item in inputs.items():
        path = inside(root, item["path"])
        obj = read_json(path) if path.suffix == ".json" else read_csv(path)
        raw_rows = obj["observations"] if isinstance(obj, dict) else obj
        records = []
        for i, r in enumerate(raw_rows, 2):
            year = int(obj["year"] if isinstance(obj, dict) else r["year"])
            var = r.get("variable", r.get("indicator_id", ""))
            if key == "nbs" and (r["family"] not in ("energy","capacity") or not 2015 <= year <= 2024):
                continue
            if key in ("products","macro","co2") and not 2015 <= year <= 2024:
                continue
            if key == "macro" and var != "NY.GDP.MKTP.KN":
                continue
            if key == "cost" and (year != 2024 or r["source_id"] != "IRENA_COST_2024_PDF"):
                continue
            if key == "price" and (r["status"] != "archived_reference" or
                                   r["source_id"] != "WB_PINK_SHEET_STABLE" or not 2015 <= year <= 2024):
                continue
            if key == "snapshot" and year != 2024 and var not in (
                    "new_storage_power","new_storage_energy","new_storage_average_duration"):
                continue
            # Avoid counting the identical NBS totals again as separate observations.
            if key == "communique" and var not in (
                "crude_oil_production","generation_thermal","generation_nuclear","generation_wind",
                "generation_solar","clean_energy_consumption_share_including_gas_pct",
                "coal_lignite_import_quantity","coal_lignite_import_value","crude_oil_import_quantity",
                "crude_oil_import_value","petroleum_products_import_quantity","petroleum_products_import_value",
                "natural_gas_import_quantity","natural_gas_import_value","adjusted_energy_intensity_growth_pct",
                "co2_intensity_growth_pct"):
                continue
            source_id = obj.get("source_id") if isinstance(obj, dict) else r.get("source_id")
            source_key = r.get("source_key") or next((s for s in item["source_keys"]
                         if s.endswith(":"+str(source_id))), "")
            selected_source_key = source_key
            if key == "nbs" and source_key == "mmj:S01":
                source_key = "yx:NBS_2025_C09-02"  # same table image, reviewed against transcription
            if not source_key or source_key not in item["source_keys"]:
                raise Q1Error("Missing source mapping: " + key + "/" + str(source_id))
            if key in ("pipeline","lng","coal_trade"):
                var = "imports_from_" + r["origin"]
                region = r["destination"]
                locator = r["sheet"] + "!" + r["cell"]
            else:
                region = r.get("region", obj.get("region", "") if isinstance(obj, dict) else "")
                locator = r.get("source_locator",r.get("locator",""))
            value = number(r["value"])
            if not locator or not region or not r["unit"]:
                raise Q1Error("Missing row provenance: " + key)
            record = dict(record_id=f"{key}:{i}",year=year,region=region,
                energy=energy_name(var), variable=var, value=value, unit=r["unit"],
                source_key=source_key, source_locator=locator, input_id=key,input_path=item["path"],
                original_value=r["value"],transformation="identity; source units retained",
                status=r.get("status",obj.get("status","published") if isinstance(obj,dict) else "published"),
                boundary=r.get("boundary",r.get("scope",item["boundary"])),
                missing_reason=r.get("missing_reason","") if value is None else "",
                independence="Same-source repetitions/version releases are not independent validation",
                selected_provenance_path=r.get("dataset_path",item["path"]),
                selected_source_key=selected_source_key)
            if key == "nbs":
                record["source_locator"] += f"; NBS table image; year={year}; column={var}"
                record["boundary"] = item["boundary"]
            # Keep H2 lower-bound qualifier machine-visible.
            if var == "hydrogen_output":
                record["status"] = "lower_bound_exceeds"
                record["boundary"] += "; original says >3650, not equality"
            if value is None and not record["missing_reason"]:
                raise Q1Error("Unexplained missing value: " + record["record_id"])
            records.append(record)
        by_input[key] = records
        all_rows.extend(records)
    keys = [(r["input_id"],r["year"],r["region"],r["variable"],r["unit"],r["source_key"]) for r in all_rows]
    if len(keys) != len(set(keys)):
        raise Q1Error("Duplicate Q1 observation keys")
    return all_rows, by_input


def calculate(root, manifest, inputs):
    history, rows = normalize(root, inputs)
    indicators, gaps, handoff = [], [], []
    def select(group, variable, year, region=None):
        found = [r for r in rows[group] if r["variable"]==variable and r["year"]==year
                 and (region is None or r["region"]==region)]
        if len(found) != 1:
            raise Q1Error(f"Expected one {group}/{variable}/{year}/{region}, got {len(found)}")
        return found[0]
    def val(group, variable, year, region=None):
        result = select(group,variable,year,region)["value"]
        if result is None:
            raise Q1Error(f"Required observation missing: {group}/{variable}/{year}")
        return result
    def refs(*records):
        return ";".join(r["record_id"] for r in records)
    def add(key, dim, year, energy, value, unit, direction, formula, records, status, note,
            region="中国大陆", valid=None):
        indicators.append(dict(indicator_id=key,dimension=dim,year=year,region=region,
            energy=energy,value=value,unit=unit,direction=direction,formula=formula,
            input_refs=refs(*records) if not isinstance(records,str) else records,
            valid_years=valid or str(year),status=status,interpretation=note))
    def gap(key,topic,years,status,evidence,reason,impact,action):
        gaps.append(dict(gap_id=key,topic=topic,years=years,status=status,evidence=evidence,
            reason=reason,impact=impact,next_action=action))
    # History levels/structure, and descriptive endpoint trends under one NBS edition.
    for var in ("production_10ktce","consumption_10ktce","total_10kW","thermal_10kW",
                "hydro_10kW","nuclear_10kW","wind_10kW","solar_10kW"):
        a,b = select("nbs",var,2015), select("nbs",var,2024)
        add("growth_"+var,"规模趋势",2024,energy_name(var),100*(b["value"]/a["value"]-1),
            "%","描述","100*(2024/2015-1)",[a,b],"descriptive_same_edition",
            "九个年间隔；公布口径序列，不代替可比口径官方增速",valid="2015;2024")
    for year in range(2015,2025):
        energy = select("nbs","consumption_10ktce",year)
        gdp = select("macro","NY.GDP.MKTP.KN",year)
        carbon = select("co2","Total",year)
        ei = energy["value"]*1e11/gdp["value"]  # 10^4 tce -> kgce; per 10^4 CNY
        ci = carbon["value"]*1e10/gdp["value"]  # Mt -> t, per 10^4 CNY
        add("energy_intensity","低碳",year,"综合",ei,"kgce/10^4 constant CNY","越低越好",
            "consumption(10^4tce)*1e11/GDP(constant CNY)",[energy,gdp],
            "conditional_cross_source_boundary","WDI CHN与大陆统计的研究对照；WDI基期未重标；非官方扣除指标")
        add("carbon_intensity","低碳",year,"综合",ci,"tCO2/10^4 constant CNY","越低越好",
            "GCB Total(Mt)*1e10/GDP(constant CNY)",[carbon,gdp],
            "conditional_cross_source_boundary","领土化石与工业；不含土地利用和移除；不是全经济净排放")
        for variable in ("consumption_coal_pct","consumption_oil_pct","consumption_gas_pct",
                         "consumption_primary_electricity_other_pct"):
            r=select("nbs",variable,year)
            add(variable,"低碳",year,energy_name(variable),r["value"],"%","描述",
                "source composition", [r],"published_category",
                "一次电力及其他保留原名，不改称非化石；气是化石")
    for kind in ("energy","carbon"):
        annual=[r for r in indicators if r["indicator_id"]==kind+"_intensity"]
        base=next(r for r in annual if r["year"]==2015)
        for r in annual:
            add(kind+"_intensity_index","低碳",r["year"],"综合",100*r["value"]/base["value"],
                "2015=100","越低越好",f"100*{kind}_intensity_t/{kind}_intensity_2015",
                r["input_refs"]+";"+base["input_refs"],"conditional_cross_source_boundary",
                "固定基期相对变化；保留跨源地域/GDP口径条件")
    # Net dependency is only computed from the same balance table.
    balance_rows = read_csv(inside(root,inputs["balance"]["path"]))
    ledgers = []
    for year in (2015,2020,2022,2023):
        for source, fuel in [("NBS_2025_C09-03","总能源"),("NBS_2025_C09-04","石油"),
                             ("NBS_2025_C09-05","煤"),("NBS_2025_C09-06","电力")]:
            ledgers.append(balance_table(balance_rows,source,year))
            if fuel not in ("石油","煤"):
                continue
            table = {r["variable"]:r for r in balance_rows if r["source_id"]==source and int(r["year"])==year}
            iv = "imports_oil_products_inclusive" if fuel=="石油" else "imports"
            ev = "exports_oil_products_inclusive" if fuel=="石油" else "exports"
            rrefs = [r for r in rows["balance"] if r["year"]==year
                     and r["source_key"].endswith(":"+source) and r["variable"] in (iv,ev,"consumption")]
            add("net_import_dependency_"+fuel,"保障",year,fuel,
                ratio_records(table[iv],table[ev],table["consumption"]),"%","越低暴露越小",
                "100*(imports-exports)/consumption; same ledger",rrefs,"scoped_published_ledger",
                "石油含制品及国际加油；煤平衡生产与产品表不同；不代替失供概率")
    concentration_results = {}
    for group in ("pipeline","lng","coal_trade"):
        trade = read_csv(inside(root,inputs[group]["path"]))
        result = concentration(trade)
        concentration_results[group] = result
        for variable,label in [("reported_bin_hhi","报告来源组集中度"),("country_hhi_lower_infimum","逐国HHI下确界"),
                               ("country_hhi_upper","逐国HHI上界")]:
            add(group+"_"+variable,"保障",2024,group,result[variable],"0-1","越低集中越小",
                "sum(source share^2); unresolved groups split only for bound",rows[group],
                "exact" if result["exact_country_hhi"] else "bounded_not_country_point",
                label+"；界为同一诊断，不作两个独立得分")
    # Same-report gas top five share; no incompatible domestic denominator is used.
    top, total = select("snapshot","gas_top5_import_volume",2024),select("snapshot","gas_imports_total",2024)
    add("gas_top5_share","保障",2024,"气",100*top["value"]/total["value"],"%","越低集中越小",
        "100*top5_import_volume/total_imports",[top,total],"same_report",
        "原报告约81%；没有构造五国份额，也不据此计算HHI")
    add("gas_net_import_dependency","保障",2024,"气",None,"%","越低暴露越小",
        "100*(imports-exports)/same_boundary_consumption",rows["snapshot"],"blocked",
        "缺同口径出口/库存与消费桥接，不把进口/表观消费冒充净进口依赖")
    # Non-fossil-like generation subset explicitly excludes biomass in thermal.
    generation_total = select("products","generation_100GWh",2024)
    components = [select("products","hydro_generation_100GWh",2024)] + [
        select("communique","generation_"+v,2024) for v in ("nuclear","wind","solar")]
    add("hydro_nuclear_wind_solar_generation_share","低碳",2024,"水核风太阳能",
        100*sum(r["value"] for r in components)/generation_total["value"],"%","描述",
        "100*(NBS hydro+nuclear+wind+solar)/NBS total",components+[generation_total],
        "cross_release_diagnostic","水电含抽蓄边界未分；不含火电内生物质；不是一次非化石消费占比")
    pv = select("renewables","pv_utilization_pct",2024)
    wind = select("renewables","wind_utilization_pct",2024)
    for r in (pv,wind):
        add(r["variable"],"协调",2024,energy_name(r["variable"]),r["value"],"%","越高越好",
            "published utilization, not capacity factor",[r],"published_scoped",
            "未有理论可发电量，不由利用率反推弃电量；年末容量不用于全国容量因子")

    # Common service, price year, life AND discount convention for wind comparison.
    cost_result = []
    for technology in ("onshore_wind","offshore_wind"):
        cap=select("cost",technology+"_installed_cost_weighted_average",2024)
        cf=select("cost_method",technology+"_new_project_capacity_factor",2024)
        om=select("cost_method",technology+"_fixed_om",2024)
        life=select("cost_method",technology+"_economic_life",2024)
        if life["value"] != manifest["assumptions"]["common_life_years"]:
            raise Q1Error("Cost lifetime disagrees with shared analysis convention")
        if cap["unit"] != "2024 USD/kW" or om["unit"] != "2024 USD/kW/year" or cf["unit"] != "fraction":
            raise Q1Error("Cost price-year/unit mismatch")
        for rate in manifest["assumptions"]["real_wacc"]:
            value=screening_lcoe(cap["value"],om["value"],cf["value"],life["value"],rate)
            cost_result.append(dict(technology=technology,real_wacc=rate,life=life["value"],
                                   capex=cap["value"],om=om["value"],cf=cf["value"],value=value))
            add(f"screening_{technology}_wacc_{rate:.2f}","经济",2024,technology,value,"2024 USD/kWh","越低越好",
                f"(CAPEX*CRF({rate},{life['value']})+OM)/(8760*CF)",[cap,cf,om,life],
                "conditional_common_financing_sensitivity",
                f"共同实际WACC={rate:.0%}为研究假设；25年、恒定年电量；未含储能/保供/系统接网外部成本；非全国校准成本")
    for technology in ("onshore_wind","offshore_wind","utility_solar_PV"):
        r=select("cost",technology+"_LCOE",2024)
        add("published_"+technology+"_lcoe","经济",2024,technology,r["value"],r["unit"],"越低越好",
            "IRENA published LCOE",[r],"published_technology_specific_financing",
            "共同报告方法/25年，但国家技术WACC不同；仅报告对照，不解释为固定融资技术净效应；不再叠加CAPEX")
    volatility = {}
    for variable in sorted({r["variable"] for r in rows["price"]}):
        raw = [r for r in read_csv(inside(root,inputs["price"]["path"])) if
               r["status"]=="archived_reference" and r["variable"]==variable]
        result=price_volatility(raw)
        volatility[variable]=result
        add("price_log_sd_"+variable,"经济","2015-2024",variable,result["value"],
            "sample SD(log annual change)","越低波动越小","stdev(log(P_t/P_t-1)); consecutive covered years only",
            [r for r in rows["price"] if r["variable"]==variable],"partial_window",
            json.dumps(result,ensure_ascii=False),region="国际基准",valid="2015-2020; 5 adjacent changes")
    # Mainland province sets are checked exactly; both annual shares use own sum.
    gen = {r["region"]:r for r in rows["province"] if r["variable"]=="generation_100GWh"}
    demand = {r["region"]:r for r in rows["demand"] if r["year"]==2024}
    expected = [r["region"] for r in rows["province"] if r["variable"]=="generation_100GWh"]
    if len(expected)!=31:
        raise Q1Error("Expected 31 mainland province generation records")
    spatial=spatial_difference(gen,demand,expected)
    spatial["generation_sum_minus_national"]=spatial["generation_sum"]-generation_total["value"]
    spatial["consumption_national_comparator"]=None
    spatial["consumption_national_comparator_reason"]="同版本2024全国用电未在本轮所选表内；不跨版本强校正"
    for key,variable,regions,denominator in [
        ("coal_shanxi_inner_mongolia_share","raw_coal_100Mt",("山西","内蒙古"),
         select("products","raw_coal_100Mt",2024)),
        ("gas_four_province_production_share","natural_gas_100Mm3",("四川","新疆","陕西","内蒙古"),
         select("products","natural_gas_100Mm3",2024)),
        ("hydro_sichuan_yunnan_generation_share","hydro_generation_100GWh",("四川","云南"),
         select("products","hydro_generation_100GWh",2024))]:
        terms=[select("province",variable,2024,region) for region in regions]
        if any(r["unit"]!=denominator["unit"] or r["value"] is None for r in terms):
            raise Q1Error("Regional production ratio boundary or missing value")
        add(key,"协调",2024,energy_name(variable),100*sum(r["value"] for r in terms)/denominator["value"],
            "%","描述","100*selected provincial amounts/national same-table product total",
            terms+[denominator],"same_table_regional_distribution",
            "已选明确地区："+"/".join(regions)+"；不把其他省空白填零，不代表资源储量或供应安全")
    add("provincial_generation_use_share_distance","协调",2024,"电力",spatial["value"],"0-1","描述",
        "0.5*sum_i(abs(G_i/sum(G)-D_i/sum(D)))",list(gen.values())+list(demand.values()),
        "same_year_31_province_diagnostic","两端分母各自31省合计；非输电量、非不安全概率")
    for r in spatial["regions"]:
        add("province_share_difference","协调",2024,"电力",100*r["share_difference"],"percentage point","描述",
            "100*(G_i/sum(G)-D_i/sum(D))",[gen[r["region"]],demand[r["region"]]],
            "same_year_31_province_diagnostic","正表示发电空间份额更大；实际潮流还需省际交易/损耗/边界",
            region=r["region"])
    for variable in ("new_storage_power","new_storage_energy","new_storage_average_duration"):
        r=select("snapshot",variable,2025)
        add(variable,"协调",2025,"新型储能",r["value"],r["unit"],"描述","source 2025 update only",
            [r],"separate_2025_update","不可回填2024；名牌功率/能量不能代替运行SOC与可用率")
    power,energy=select("snapshot","new_storage_power",2025),select("snapshot","new_storage_energy",2025)
    add("storage_nameplate_energy_power_ratio","协调",2025,"新型储能",energy["value"]/power["value"],"h","描述",
        "GWh/GW",[energy,power],"separate_2025_update","总名牌比；不是所有项目统一时长；不是连续放电保障承诺")
    # Carbon bookkeeping is a component identity plus an explicitly blocked physical crosscheck.
    carbon_ledgers=[]
    for year in range(2015,2025):
        carbon_values={r["variable"]:r["value"] for r in rows["co2"] if r["year"]==year}
        carbon_ledgers.append(dict(year=year,unit="Mt CO2",source="yx:GCB_GCB2025v15_MtCO2_flat",
            boundary="territorial fossil/industry; excludes land-use/removals; CHN code",
            observed=carbon_values,identity=identity(carbon_values,
                {k:1 for k in ("Coal","Oil","Gas","Cement","Flaring","Other")},"Total"),
            interpretation="同清单分项核对，不是用燃料投入独立重建排放"))
    # All missing research dimensions are itemized, without creating zero-valued observations.
    gap("price_2021_2024","价格","2021-2024","blocked_version","price",
        "可用旧版止于2020；新版及lb价格隔离未解除","不能称完整十年波动/国内到厂价",
        "共同审查清洁原始版本及价年，另行输入修订")
    gap("nonfossil_consumption","非化石一次消费","2015-2024","blocked_definition","nbs;communique",
        "一次电力及其他、含气清洁能源均不直接等于非化石","低碳分维保留煤份额/强度诊断，不给该点估计",
        "取得同口径非化石分类与折标系数")
    gap("gas_net_dependency","天然气净进口依赖","2024","blocked_boundary","snapshot",
        "缺同口径出口、消费、库存；EI标准热值与国内体积未桥接","只给同报告进口CR5与EI分通道集中度",
        "获取完整天然气平衡表和标准状态")
    gap("firm_cost","跨能源保供成本","2024","not_estimated","cost;cost_method",
        "统一风电厂门发电成本不含时序、可靠性、储能与输电外部成本","不作九能源成本排序；PV无共同融资重算",
        "补全热电燃料、运行与网络边界后比较同可靠性服务")
    gap("regional_grid","省际网络与弃电","2024","blocked_operational","province;demand;renewables",
        "空间份额不能还原潮流；利用率不能反推弃电；线路候选隔离","无法计算LOLP/弃电电量/小时调度约束",
        "核验省际交换、线路容量、小时供需及理论可发电量")
    gap("storage_2024","储能初态","2024","blocked_state","renewables;snapshot",
        "抽蓄只有功率；2025新型储能不可回填；SOC/效率/功率约束不足","不能初始化全国储能库存与保供时长",
        "取得2024分技术分区功率能量及初始SOC")
    gap("physical_carbon","物理燃烧/捕集碳账","2024","blocked_physical_crosscheck","balance;co2",
        "2024燃料投入、NCV、燃烧/原料分流、氧化率、过程排放和捕集/封存缺失",
        "GCB分项恒等式不构成能源-碳物理闭合；不输出净零",
        "以燃烧活动重建，捕集与封存分记，电力不重复记消费侧排放")
    gap("hydrogen_categories","氢统计","2024","approximate_and_lower_bound","snapshot",
        ">3650总量与约2070+760+770+32=3632；类别近似且总量是下界",
        "18只是相对公布门槛的差，不是精确统计残差；产能不当产量",
        "取得有上下界的分类与原料/燃料去向；不强配平")
    gap("cross_release","发电版本差异","2024","conflict_preserved","products;communique;renewables",
        "NBS水14256.82/风9970.4/太阳能8390.4 vs NEA水14239/风9916/PV8341(亿kWh)",
        "不平均；NBS规模与NEA技术参考分别输出；太阳能与PV不是同名技术",
        "由两人复核范围/修订版本；不得当独立校准目标")
    gap("ten_year_technology","技术完整历史/区域","2015-2024","partial_coverage","history.csv",
        "全国规模/结构/容量十年；细分发电、氢、生物质与分区技术历史仍缺",
        "缺年不插值；全国项目清单不由官方附件样本外推","补充同口径能源产品/技术年表")
    gap("mainland_bridge","跨源地域和GDP定义","2015-2024","candidate_cross_source","macro;co2;nbs",
        "WDI/GCB用CHN代码，NBS用大陆；GDP历史修订与基期未逐一桥接",
        "强度仅研究对照，不作为官方扣除指标或全国校准准入",
        "核对地域元数据及GDP修订/基价，提交Q2输入审查")
    gap("new_extractions","共同输入增量确认","2024","pending_peer_confirmation","province;cost_method",
        "源原件已在锁定base，两份细化表是本方案新提取","不悄悄替换三人共同输入",
        "PR/Issue公开增量；两名成员核对后主持人确认是否修订共同输入")
    for ledger in ledgers:
        if ledger["year"]==2023:
            gap("balance_"+ledger["source"],"静态账残差","2023","published_residual",
                ledger["source"],json.dumps({k:ledger[k] for k in
                    ("supply_minus_consumption","published_difference","difference_rounding_residual")},ensure_ascii=False),
                "保留实际差异；不强配平，不外推2024","按原表范围、库存与舍入逐项核对")
    # Q2 handoff contains values ONLY as candidates; accepted-source status is separate.
    for r in rows["nbs"]:
        if r["year"]!=2024:
            continue
        handoff.append(dict(handoff_id=r["record_id"],kind="初态候选",year=2024,
            variable=r["variable"],value=r["value"],unit=r["unit"],evidence=r["record_id"],
            status="candidate_not_admitted",condition="同口径源表审查；容量为年末且火电含非煤，水电含抽蓄",
            model_position="年度规模/结构与容量边界；非机组初态",split="2024已接触留出"))
    for r in rows["nbs"] + rows["products"] + rows["macro"] + rows["co2"]:
        if 2015 <= r["year"] <= 2024:
            handoff.append(dict(handoff_id="target_"+r["record_id"],kind="校准目标候选",year=r["year"],
                variable=r["variable"],value=r["value"],unit=r["unit"],evidence=r["record_id"],
                status="candidate_not_admitted",condition="去重、GDP/地域/排放口径桥接；不能当已校准",
                model_position="历史损失函数候选；不复制同源版本",
                split="训练2015-2021" if r["year"]<=2021 else "已接触留出2022-2024"))
    for key in ("regional_grid","storage_2024","physical_carbon","gas_net_dependency","firm_cost"):
        g=next(g for g in gaps if g["gap_id"]==key)
        handoff.append(dict(handoff_id="blocked_"+key,kind="约束/待补输入",year=2024,
            variable=g["topic"],value=None,unit="见缺口",evidence=g["evidence"],status="blocked",
            condition=g["reason"],model_position=g["impact"],split="不进入校准"))
    roles = make_roles()
    static=dict(schema_version=1,scope="2023 detailed checkpoints separated from 2024 snapshot and 2025 update",
        energy_ledgers=ledgers,carbon_components=carbon_ledgers,
        national_2024_physical_energy_carbon_closure=dict(status="blocked",value=None,
            reasons=["同年燃料能源平衡与NCV/氧化率不足","原料/燃烧与过程排放未分","捕集/封存与移除不足"],
            double_count_controls=["电力是转换载体，不加到一次能源消费","氢生产投入不再作为新一次能源",
                                   "过程碳与燃烧碳分开","捕集不等于永久封存"]),
        trade_concentration=concentration_results,spatial=spatial,prices=volatility,
        comparable_costs=cost_result,
        hydrogen=dict(published_total_lower_bound_exclusive=val("snapshot","hydrogen_output",2024),
            approximate_category_sum=sum(val("snapshot",v,2024) for v in
                ("coal_hydrogen_output","gas_hydrogen_output","byproduct_hydrogen_output","electrolysis_hydrogen_output")),
            unit="10^4 tonne",status="not_an_exact_balance"))
    return history,indicators,roles,handoff,gaps,static


def make_roles():
    # Research interpretation, explicitly separated from measured observations.
    data = [
        ("煤","大规模供能与电热调节","国内规模大、可库存","碳排放、洗选口径和灵活性成本",
         "与风光互补；热电耦合；CCUS需额外能耗","nbs/consumption_coal_pct; products/raw_coal_100Mt; balance/C09-05; co2/Coal",
         "煤矿/热电主体；燃料库存、排放与运行约束","火电不等煤电；平衡表与产品表产量不同"),
        ("油","交通燃料和石化原料","液体燃料储运方便","净进口暴露大；燃烧与原料不能混算",
         "终端电气化、替代燃料和炼化用氢","balance/C09-04; communique/crude_oil_import_quantity; co2/Oil",
         "进口、炼化、交通与原料流分记","原油生产/进口不等全部石油消费；不双计制品"),
        ("气","工业/城市燃料与调峰发电","调节和终端用途广","进口来源集中、季节库存/甲烷和燃料成本未知",
         "储气、管网、气电和需求响应","snapshot/gas_*; pipeline; lng; co2/Gas",
         "气源-储气-气电链，季节与通道约束","国内体积与EI标准热值气不直接相加；不是非化石"),
        ("水电","可再生发电与调节","库容水电可提供调节","来水季节性、生态约束和跨区依赖",
         "与风光储及跨区输送协同","nbs/hydro_10kW; province/hydro_generation_100GWh; renewables",
         "常规水电与抽蓄分开；水量和库容约束","总水电含抽蓄；抽蓄不是一次能源；未计算水文可靠性"),
        ("核电","稳定低直接排放电量","全年稳定供电潜力","工程周期、资本和安全/运行约束资料不足",
         "与可变电源协调检修和负荷调节","nbs/nuclear_10kW; communique/generation_nuclear",
         "机组投建/检修/出力边界候选","年末容量非全年平均；不把直接低碳当全生命周期零碳"),
        ("风电","可变可再生电源","规模增长；同价年陆风成本参考低","出力时序/网络和消纳约束",
         "跨区、储能、负荷响应与气煤调峰","nbs/wind_10kW; communique/generation_wind; renewables/wind_utilization_pct; cost",
         "分区资源出力、建退役及成本主体","利用率不当容量因子；新建项目CF不替代全国存量"),
        ("光伏","可变日间电源","快速扩张；模块化部署","昼夜错配、网络和储能需求",
         "储能、需求侧移峰、可再生电解制氢","nbs/solar_10kW; renewables/pv_generation; cost/utility_solar_PV_LCOE",
         "区分太阳能总项与PV；DC/AC边界明确","不强合太阳能/PV版本；未给同融资PV重算或保供成本"),
        ("生物质","燃料型发电/热与资源利用","可调燃料路径候选","可持续原料、运输、生命周期排放与规模约束",
         "热电联产；BECCS需可持续性及永久封存证明","renewables/biomass_capacity; renewables/biomass_generation; communique/thermal scope",
         "原料供给、转换与过程碳","在火电分类中可能交叉；不重复加总；不默认碳中性/负排放"),
        ("氢能","二次载体和化工原料","可衔接难电气化需求与可再生电力","当前化石制氢主导；效率/储运成本缺失",
         "电解-储氢-工业；化石制氢与CCUS分别计碳","snapshot/hydrogen_output; snapshot/*hydrogen*",
         "生产投入/产氢/库存/终端用途与损失","总量>3650万吨；12.5万吨/年是可再生产能；不当新一次能源"),
        ("储能","跨时段搬运电能/气氢库存","功率与能量分开可描述调节","初始SOC、效率、时长与可用率不足",
         "与风光、调峰、需求响应共同约束","renewables/pumped_storage_capacity; snapshot/new_storage_*",
         "P/E/SOC/充放电效率连续状态","2025新型储能136GW/351GWh不回填2024；抽蓄不另加总容量"),
        ("输送","跨区电/气资源配置","缓解资源与负荷空间分离","候选线路未核验；容量/潮流和损耗缺失",
         "风光水电外送、管道气与多区域平衡","province; demand; snapshot/gas_imports_pipeline",
         "分区有向网络、流量上限与损耗","空间份额距离不是实际净外送或安全评分；未准入候选线路"),
        ("CCUS","排放捕集、利用与封存链","难减排路径候选","捕集率、能耗、运输与永久封存数据不足",
         "工业、化石电厂及条件BECCS","static_balance.json/blocked physical carbon; co2 component boundary",
         "排放生成/捕集/利用/永久封存分别记账","没有实测全国规模；捕集不等移除，利用不等永久封存")]
    return [dict(zip(ROLE_FIELDS,r)) for r in data]


def report(indicators,roles,gaps,static,history):
    def v(key,year=2024):
        return next(r["value"] for r in indicators if r["indicator_id"]==key and r["year"]==year)
    lines = [
        "# Q1 当前多能源发展现状：mmj 候选研究交付",
        "",
        "四项研究均已实现为离线可复现候选；工程与方法自检不等于 A7 两人批准。",
        "实际观测、条件成本实验和阻断项分别标记。全国真实初态、历史校准、预测仍未完成。",
        "",
        "## 1. 历史规模、结构、区域与贸易/价格",
        "",
        "2015—2024 使用统计局2025版同表去重序列；2024是候选现状，2023细账与2025更新分开。"
        "history.csv 保留原值、原单位、源页表/单元格、版本与缺失原因；同源重复转录不增加独立观测。",
        "",
        "|指标|2015|2024|变化|",
        "|---|---:|---:|---:|"]
    for var,label,unit in [
        ("production_10ktce","一次能源生产","万吨标准煤"),
        ("consumption_10ktce","能源消费","万吨标准煤"),
        ("total_10kW","年末总装机","万千瓦"),
        ("wind_10kW","风电装机","万千瓦"),("solar_10kW","太阳能装机","万千瓦")]:
        a=next(r["value"] for r in history if r["input_id"]=="nbs" and r["variable"]==var and r["year"]==2015)
        b=next(r["value"] for r in history if r["input_id"]=="nbs" and r["variable"]==var and r["year"]==2024)
        lines.append(f"|{label}（{unit}）|{a:g}|{b:g}|{100*(b/a-1):.2f}%|")
    lines += [
        "",
        f"煤炭消费比重从63.8%降至{v('consumption_coal_pct'):.1f}%，但其绝对规模未据此判定下降。"
        "2024油18.2%、气8.8%、一次电力及其他19.8%保留原分类。含气清洁能源28.6%不是非化石。",
        "原煤47.81亿吨、气2464.51亿立方米、总发电100868.81亿千瓦时（10086.881 TWh）。"
        "九类能源细分十年发电与区域技术面板未齐全，缺口逐项列示，不填缺年。",
        "",
        "2024进口公报分别保留煤及褐煤54270万吨、原油55342万吨、成品油4823万吨、气13169万吨及金额。"
        "这些质量不能无依据转换为国内气体体积或加总为一次能量。2015/2020/2022/2023同表煤油进出口与消费另列。",
        "",
        "## 2. 四维评价",
        "",
        "|维度|定量结果|解释|",
        "|---|---|---|",
        f"|保障|2023煤净进口依赖{v('net_import_dependency_煤',2023):.2f}%；石油{v('net_import_dependency_石油',2023):.2f}%|同表同单位；不是2024或原油依赖|",
        f"|低碳|2024煤份额{v('consumption_coal_pct'):.1f}%；水核风太阳能发电占比{v('hydro_nuclear_wind_solar_generation_share'):.2f}%|后者含水电抽蓄未拆分，不代替一次非化石份额|",
        f"|经济|统一25年、5%实际WACC的陆风{v('screening_onshore_wind_wacc_0.05'):.5f}、海风{v('screening_offshore_wind_wacc_0.05'):.5f}（2024 USD/kWh）|共同融资条件实验，非官方LCOE重现、非到户或保供服务成本|",
        f"|协调|2024年31省发用电份额距离{v('provincial_generation_use_share_distance'):.5f}；风/PV利用率95.9%/96.8%|空间错配提示协调需求，不能直接断言不安全或推弃电量|",
        "",
        "保障方面，同EI标准的分通道管道气、LNG与EJ煤分别计算来源组HHI；未解析来源组给逐国HHI界，"
        f"国内报告气进口前五来源合计占{v('gas_top5_share'):.2f}%。不构造五国点份额，不把总进口/表观消费叫净依赖。",
        "",
        "|2024来源表|报告来源组HHI|逐国HHI下确界|逐国HHI上界|",
        "|---|---:|---:|---:|"]
    for group,r in static["trade_concentration"].items():
        lines.append(f"|{group}|{r['reported_bin_hhi']:.6f}|{r['country_hhi_lower_infimum']:.6f}|{r['country_hhi_upper']:.6f}|")
    lines += [
        "",
        "低碳方面，逐年列出不变价GDP下能耗和GCB碳强度。WDI采用源系列基期，不冒称2020基价。"
        "CHN代码与大陆口径桥接仍为条件；GCB仅领土化石与工业，排除土地利用和移除，"
        "与公报扣除原料及非化石的官方能耗强度不可直接对比。没有为缺维重新配权的总评分。",
        f"研究口径下2024能耗强度为{v('energy_intensity'):.2f} kgce/万元不变价CNY，"
        f"2015=100指数为{v('energy_intensity_index'):.2f}；碳强度为{v('carbon_intensity'):.4f} tCO2/万元，"
        f"2015=100指数为{v('carbon_intensity_index'):.2f}。这表示单位产出的变化，不等于总排放下降。",
        "",
        "经济性采用 IRENA 同一原件的2024中国新建风电样本CAPEX、O&M和CF，统一25年、年末折现与恒定年输出，"
        "L=(CAPEX×CRF+O&M)/(8760×CF)，按3%、5%、7%实际WACC做敏感性。3/5/7%是透明分析假设，"
        "不是中国实测融资率。报告公布陆风/光伏/海风LCOE=0.029/0.033/0.056另列，技术WACC不同，"
        "不解释为固定融资净效应，不再叠加CAPEX/O&M。成本仅未保供厂门kWh，不评价等可靠性全系统服务。",
        "",
        "|技术|3%|5%|7%|单位|",
        "|---|---:|---:|---:|---|"]
    for tech in ("onshore_wind","offshore_wind"):
        values=[r["value"] for r in static["comparable_costs"] if r["technology"]==tech]
        lines.append("|"+tech+"|"+"|".join(f"{x:.5f}" for x in values)+"|2024 USD/kWh|")
    lines += ["",
        "价格波动固定考察2015—2024，仅使用可核验旧版年度价格。六个国际基准各有2015—2020六水平、"
        "五个相邻对数变化；样本标准差如下。2021—2024隔离缺失，不跨缺年、不拼接新版、不当国内到厂价。",
        "",
        "|国际基准|对数变化样本标准差|有效相邻变化数|",
        "|---|---:|---:|"]
    for key,r in static["prices"].items():
        lines.append(f"|{key}|{r['value']:.5f}|{r['observations']}|")
    lines += ["",
        "协调性用两端各自31省合计作为份额分母，完整省集、同年和单位必须一致。",
        f"省级发电合计{static['spatial']['generation_sum']:.2f}亿千瓦时，与全国产品表差"
        f"{static['spatial']['generation_sum_minus_national']:.2f}；用电合计{static['spatial']['consumption_sum']:.0f}亿千瓦时。"
        "未选到同版全国用电比较值，明确保留缺失。正份额差表示发电空间份额较大，不代表实测外送量。",
        "2024抽蓄58.69GW仅功率；2025新型储能136GW/351GWh及约2.58h单独展示，不能回填2024或替代SOC。",
        f"同表地区分布：山西/内蒙古原煤产量合计占全国{v('coal_shanxi_inner_mongolia_share'):.2f}%；"
        f"四川/新疆/陕西/内蒙古天然气产量合计占{v('gas_four_province_production_share'):.2f}%；"
        f"四川/云南水电发电合计占{v('hydro_sichuan_yunnan_generation_share'):.2f}%。"
        "这些是生产/发电空间份额，不是地下资源储量份额；其余省份的源表空白仍缺失。",
        "",
        "|省份|发电份额−用电份额（百分点）|",
        "|---|---:|"]
    ordered=sorted(static["spatial"]["regions"],key=lambda r:r["share_difference"])
    for r in ordered[:5]+ordered[-5:][::-1]:
        lines.append(f"|{r['region']}|{100*r['share_difference']:.3f}|")
    lines += [
        "",
        "![全国规模与结构](overview.png)",
        "",
        "![省级空间份额差](regional.png)",
        "",
        "## 3. 能源角色、优势、短板与接口",
        "",
        "|能源/配套|角色与优势|短板|协同及Q2位置|",
        "|---|---|---|---|"]
    for r in roles:
        lines.append(f"|{r['energy']}|{r['role']}；{r['advantage']}|{r['shortcoming']}|{r['synergy']}；{r['q2_position']}|")
    lines += ["",
        "角色判断是研究解释，不当成新的统计观测。energy_roles.csv逐条列证据和边界；"
        "煤/气调峰、核电稳定性、水库调节是待模型约束验证的作用，不宣称已由年度统计证明可靠性。",
        "",
        "## 4. 静态核对、Q2交接与未闭合原因",
        "",
        "|2023账|单位|供给重建残差（公布供给−计算）|使用重建残差|供给−消费|公布平衡差额|",
        "|---|---|---:|---:|---:|---:|"]
    for r in static["energy_ledgers"]:
        if r["year"]==2023:
            lines.append(f"|{r['source']}|{r['unit']}|{r['supply']['residual']}|{r['use']['residual']}|"
                         f"{r['supply_minus_consumption']}|{r['published_difference']}|")
    lines += ["",
        "总能源消费=终端+加工转换损失−回收能+损失；石油=终端+转换投入+损失；煤=终端+转换投入；"
        "发电/供热属于转换投入的嵌套行，不再次相加。电力=终端+输配损失。"
        "2023总能源供给−消费15520与公布15519相差1，保留。石油、煤供给重建各有−1舍入残差。"
        "氢约分类合计3632万吨，总量原文为超3650万吨，18仅是相对门槛的差，不能当精确残差。",
        "",
        "GCB逐年分项和与Total的残差逐一保留。此恒等式只检验同清单算术，"
        "不是独立燃烧活动核算。2024物理能源—碳闭合明确阻断：燃烧/原料分流、热值、氧化率、"
        "过程排放、捕集、封存与移除不齐全。电力、氢不再作为一次能量重复加总，捕集不等永久封存。",
        "",
        "model_handoff.csv给出2024年末规模/容量初态候选、2015—2024校准目标候选与阻断约束。"
        "2015—2021用于训练；2022—2024是已接触留出，不重新包装为盲测。"
        "所有候选仍需Q2输入审查，未修改原九子集用途契约。",
        "",
        "## 缺口与验收",
        "",
        "完整列表见 gaps_and_conflicts.csv；重点为价格版本、一次非化石定义、气平衡、"
        "同可靠性跨能源成本、时序网络/弃电、2024储能状态、物理碳账、技术长面板和跨源地域/GDP桥接。"
        "这些限制不以零值填补，也不通过一致性检查自动准入。",
        "",
        "A1—A4：四项研究方法、适用范围定量结果与证据缺项已交付候选；不是全国所有输入已补齐。"
        "A5—A6：以本次run_manifest和validation证据中的实际执行为准。"
        "A7：待另外两人核对同一最终SHA并批准；当前没有正式验收通过或合并结论。",
        "",
        "复现：`python -B -X utf8 run.py q1 --output-dir outputs/q1/review_mmj`。"
        "入口仅使用已登记本地文件；缺失、指纹不符、单位/边界错误返回非零。"
        "输入与输出哈希、命令、依赖、Git提交和工作树状态见run_manifest.json。"
    ]
    return "\n".join(lines)+"\n"


def plots(out,history,static):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    # English plot labels avoid platform-specific CJK font dependence.
    years=list(range(2015,2025))
    def series(var):
        return [next(r["value"] for r in history if r["input_id"]=="nbs" and
                     r["variable"]==var and r["year"]==year) for year in years]
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":10})
    fig,axes=plt.subplots(1,2,figsize=(11,4.2))
    axes[0].plot(years,[v/10000 for v in series("production_10ktce")],marker="o",label="Production")
    axes[0].plot(years,[v/10000 for v in series("consumption_10ktce")],marker="s",label="Consumption")
    axes[0].set(ylabel="100 million tce",title="NBS 2025 edition: mainland China")
    axes[0].legend()
    axes[1].stackplot(years,*[series("consumption_"+v+"_pct") for v in
        ("coal","oil","gas","primary_electricity_other")],
        labels=["Coal","Oil","Gas","Primary electricity & other"])
    axes[1].set(ylim=(0,100),ylabel="Primary consumption (%)",title="Published categories (not non-fossil proxy)")
    axes[1].legend(loc="lower left")
    for ax in axes:
        ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(out/"overview.png",dpi=160,metadata={"Software":"Q1 mmj"});plt.close(fig)
    regions=static["spatial"]["regions"]
    ids=sorted(range(len(regions)),key=lambda i:regions[i]["share_difference"])
    fig,ax=plt.subplots(figsize=(10,4.5))
    ax.bar(range(31),[100*regions[i]["share_difference"] for i in ids])
    ax.set(xticks=range(31),xticklabels=[str(i+1) for i in ids],
           xlabel="Province index in regional.csv (NBS source row order)",
           ylabel="Generation share - consumption share (percentage points)",
           title="2024 same-year spatial diagnostic; not observed power transfers")
    ax.axhline(0,color="black",linewidth=.8);ax.grid(axis="y",alpha=.2)
    fig.tight_layout();fig.savefig(out/"regional.png",dpi=160,metadata={"Software":"Q1 mmj"});plt.close(fig)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",default="outputs/q1/p1_mmj")
    parser.add_argument("--inputs",default="workflow/q1_inputs.json")
    args=parser.parse_args()
    staging=None
    try:
        # Output must stay within dedicated Q1 research area, with ownership check.
        output=inside(ROOT,args.output_dir)
        q1root=(ROOT/"outputs/q1").resolve()
        if not output.is_relative_to(q1root) or output==q1root:
            raise Q1Error("Output must be a dedicated directory under outputs/q1/")
        if output.exists() and any(output.iterdir()):
            existing=output/"run_manifest.json"
            if not existing.is_file() or read_json(existing).get("candidate")!="p1/mmj":
                raise Q1Error("Refusing to overwrite a directory not owned by this Q1 candidate")
        input_path=inside(ROOT,args.inputs)
        manifest=read_json(input_path)
        inputs=validate_inputs(ROOT,manifest)
        # Check source contracts separately from candidate research admission.
        history,indicators,roles,handoff,gaps,static=calculate(ROOT,manifest,inputs)
        output.parent.mkdir(parents=True,exist_ok=True)
        # Inherit workspace ACLs. Windows tempfile's private mode can make moved
        # artifacts unreadable to the desktop sandbox even after publication.
        staging=output.parent/(".q1-mmj-"+uuid.uuid4().hex)
        staging.mkdir()
        for name,records,fields in [
            ("history.csv",history,HISTORY_FIELDS),("indicators.csv",indicators,INDICATOR_FIELDS),
            ("energy_roles.csv",roles,ROLE_FIELDS),("model_handoff.csv",handoff,HANDOFF_FIELDS),
            ("gaps_and_conflicts.csv",gaps,GAP_FIELDS)]:
            write_csv(staging/name,records,fields)
        regional=[dict(index=i+1,**r) for i,r in enumerate(static["spatial"]["regions"])]
        write_csv(staging/"regional.csv",regional,list(regional[0]))
        write_json(staging/"static_balance.json",static)
        (staging/"report.md").write_bytes(report(indicators,roles,gaps,static,history).encode("utf-8"))
        plots(staging,history,static)
        codes=["run.py","scripts/run_q1_assessment.py","scripts/prepare_q1_inputs.py",
               "src/energy_model/q1.py"]
        protected=read_json(ROOT/"archive/organization_20261017/file_disposition.json")
        preserved=[r for r in protected if r["action"]=="protect" or
                   ("/" not in r["path"] and not r["path"].startswith("~$"))]
        for r in preserved:
            if sha(ROOT/r["target"])!=r["sha256"]:
                raise Q1Error("Protected original changed: "+r["target"])
        result=dict(schema_version=1,candidate="p1/mmj",success=True,
            result_status="Q1_research_candidate_with_explicit_gaps_pending_A7",
            base_sha=manifest["base_sha"],code_commit_sha=git("rev-parse","HEAD"),
            dirty_worktree=bool(git("status","--porcelain")),worktree_status=git("status","--porcelain"),
            command=["python","-B","-X","utf8","run.py","q1","--inputs",args.inputs,"--output-dir",args.output_dir],
            python=sys.version,executable=sys.executable,
            dependencies={"matplotlib":importlib.metadata.version("matplotlib"),
                          "core":"Python standard library"},
            random_steps=False,network_access=False,
            input_manifest=dict(path=args.inputs,sha256=sha(input_path)),
            input_hashes={r["path"]:r["sha256"] for r in inputs.values()},
            source_hashes={k:r["sha256"] for k,r in manifest["sources"].items()},
            evidence_review=manifest["evidence_review"],
            code_hashes={p:sha(ROOT/p) for p in codes},
            configuration=manifest["assumptions"],
            protected_originals_verified={r["target"]:r["sha256"] for r in preserved},
            counts=dict(history=len(history),indicators=len(indicators),roles=len(roles),
                        handoff=len(handoff),gaps=len(gaps)),
            scientific_limits=[g["gap_id"] for g in gaps],
            acceptance=dict(A1="candidate_results_with_itemized_coverage",
                A2="four_dimensions_quantified_with_scope_limits",
                A3="source_cells_and_review_attached_pending_independent_confirmation",
                A4="candidate_handoff_and_unclosed_physical_balance_explicit",
                A5="requires_independent_reproduction",A6="see outputs/validation/q1_mmj_validation.json",
                A7="pending_two_peer_reviews_no_merge"),
            outputs={p.name:sha(p) for p in sorted(staging.iterdir())})
        write_json(staging/"run_manifest.json",result)
        output.mkdir(exist_ok=True)
        # Publish the success manifest last, only after every artifact was generated.
        old_manifest=output/"run_manifest.json"
        if old_manifest.exists():
            old_manifest.unlink()
        for p in sorted(staging.iterdir(),key=lambda p:p.name=="run_manifest.json"):
            os.replace(p,output/p.name)
        print(json.dumps(dict(success=True,output_dir=args.output_dir,counts=result["counts"],
                              acceptance="candidate pending two peer reviews; gaps explicit"),ensure_ascii=False))
        return 0
    except (Q1Error,OSError,KeyError,ValueError,ImportError) as exc:
        print("Q1 FAILED: "+str(exc),file=sys.stderr)
        return 1
    finally:
        if staging is not None:
            # Known staging path generated by this process, within the Q1 root.
            if staging.resolve().is_relative_to((ROOT/"outputs/q1").resolve()):
                for p in staging.iterdir():
                    if p.is_file():
                        p.unlink()
                staging.rmdir()


if __name__=="__main__":
    raise SystemExit(main())
