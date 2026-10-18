"""Q1 synthesis from admitted 2024 subsets; no composite score or forecast."""
import json
import math
from pathlib import Path

from build_energy_assessment import INPUT as ENERGY, calculate as energy_profile
from build_verified_assessment import INPUT as POWER, calculate as power_profile
from build_gas_assessment import REPORT as GAS, lookup
from workflow_status import check_formal_inputs, read_json, sha256

ROOT = Path(__file__).resolve().parents[1]
INPUTS = (ENERGY, POWER, GAS)


def concentration_bounds(group_volume, total_volume, group_count):
    """Conservative country bounds with unobserved shares and unknown remainder count."""
    if (type(group_count) is not int or group_count < 1
            or any(type(x) not in (int, float) or not math.isfinite(x)
                   for x in (group_volume, total_volume))
            or not 0 <= group_volume <= total_volume or total_volume <= 0):
        raise ValueError("Invalid named-origin group")
    share = group_volume / total_volume
    return {
        "hhi_lower_bound_10000": share ** 2 / group_count * 10000,
        "hhi_upper_bound_10000": (share ** 2 + (1 - share) ** 2) * 10000,
        "largest_origin_share_lower_pct": share / group_count * 100,
        "largest_origin_share_upper_pct": max(share, 1 - share) * 100,
        "country_hhi_point": None,
        "interpretation": "公布舍入值下的保守算术界；不是点估计、置信区间或安全分级",
    }


def calculate(energy, power, gas):
    e, p, g = energy_profile(energy), power_profile(power), lookup(gas, "S22")
    if power.get("source_id") != "S17" or len(power["rows"]) != 1:
        raise ValueError("Expected single-year S17 release")
    for field in ("total", "hydro", "thermal", "nuclear", "wind", "solar"):
        if power["units"].get(field) != "万千瓦":
            raise ValueError("Power capacity unit mismatch")
    for field in ("power_project_investment_100m_yuan", "grid_investment_100m_yuan"):
        if power["units"].get(field) != "亿元" or p[field] < 0:
            raise ValueError("Power investment unit/value mismatch")
    if power["units"].get("line_loss_pct") != "%" or not 0 <= p["line_loss_pct"] <= 100:
        raise ValueError("Line loss unit/value mismatch")
    if p["combined_reported_investment_100m_yuan"] <= 0:
        raise ValueError("Nonpositive combined investment")
    raw_energy = lookup(energy, "S13")
    group = g("five_main_origins_imports", "亿立方米")
    imports = g("gas_imports", "亿立方米")
    lng = g("lng_imports", "亿立方米")
    pipeline = g("pipeline_imports", "亿立方米")
    if min(lng, pipeline) < 0 or abs(lng + pipeline - imports) > 1.5:
        raise ValueError("Inconsistent gas import routes")
    bounds = concentration_bounds(group, imports, 5)
    gas_power = g("power_consumption_share_pct", "%")
    if not 0 <= gas_power <= 100:
        raise ValueError("Invalid gas power-use share")
    subtotal = sum(item["value_100m_yuan"] for item in e["imports"])
    if subtotal <= 0:
        raise ValueError("Nonpositive selected import value")
    rows = []

    def add(key, dimension, label, value, unit, formula, refs, meaning):
        rows.append({"indicator_id": key, "dimension": dimension, "label": label,
                     "value": value, "unit": unit, "formula": formula,
                     "input_refs": refs, "interpretation": meaning})

    def ref(dataset, sid, fields):
        return {"dataset_path": dataset, "source_id": sid, "fields": fields}

    gas_refs = [ref(GAS, "S22", ["five_main_origins_imports", "gas_imports"])]
    add("gas_named_origins_share", "供给保障", "天然气五主要来源合计占进口",
        group / imports * 100, "%", "1477/1817×100", gas_refs,
        "仅描述已列五来源合计；不把五来源假设为均分。")
    add("gas_hhi_lower", "供给保障", "天然气来源HHI保守下界",
        bounds["hhi_lower_bound_10000"], "0—10000尺度",
        "10000×(五来源合计/总进口)^2/5", gas_refs,
        "由柯西不等式得到；余下来源贡献非负。不是精确HHI。")
    add("gas_hhi_upper", "供给保障", "天然气来源HHI保守上界",
        bounds["hhi_upper_bound_10000"], "0—10000尺度",
        "10000×[s^2+(1-s)^2]，s=五来源合计/总进口", gas_refs,
        "允许两组内部任意集中，且不假设五来源为完整排名；可能不可取到。")
    add("gas_lng_import_share", "供给保障", "LNG占天然气进口",
        lng / imports * 100, "%", "1057/1817×100",
        [ref(GAS, "S22", ["lng_imports", "gas_imports"])],
        "运输路径结构；不是价格风险、进口依赖率或失供率。")
    add("coal_energy_share", "清洁低碳", "煤炭能源消费占比",
        e["coal_consumption_share_pct"], "%", "官方直接观测",
        [ref(ENERGY, "S13", ["coal_consumption_share_pct"])],
        "能源消费结构；不能由此直接计算全国CO2。")
    add("wind_solar_generation_share", "清洁低碳", "风光发电占比",
        e["wind_solar_generation_share_pct"], "%",
        "(风电发电量+太阳能发电量)/同表总发电量×100",
        [ref(ENERGY, "S13", ["generation_wind", "generation_solar", "generation_total"])],
        "发电结构；不能替代非化石一次能源消费占比。")
    add("thermal_generation_share", "清洁低碳", "火电发电占比",
        e["generation_share_pct"]["thermal"], "%", "火电发电量/同表总发电量×100",
        [ref(ENERGY, "S13", ["generation_thermal", "generation_total"])],
        "火电包含生物质及余热等，不能全部解释为煤电或化石发电。")
    add("co2_intensity_change", "清洁低碳", "官方CO2强度同比",
        e["reported_co2_intensity_growth_pct"], "%", "官方直接观测",
        [ref(ENERGY, "S13", ["co2_intensity_growth_pct"])],
        "单位GDP口径；不是全国排放总量同比。")
    add("selected_import_value", "经济性", "四类商品进口金额小计",
        subtotal, "亿元", "煤及褐煤、原油、成品油、天然气进口金额相加",
        [ref(ENERGY, "S13", [r["commodity"] + "_import_value" for r in e["imports"]])],
        "同表所选四类商品的毛进口金额；不是全部能源进口额或全系统成本。")
    for item in e["imports"]:
        add(item["commodity"] + "_import_bill_share", "经济性",
            item["label"] + "占四类进口金额小计",
            item["value_100m_yuan"] / subtotal * 100, "%",
            "该商品进口金额/四类商品进口金额小计×100",
            [ref(ENERGY, "S13", [r["commodity"] + "_import_value" for r in e["imports"]])],
            "金额结构；不代表实物能源占比或边际成本。")
    add("grid_investment_share", "经济性", "电网占电源加电网报告投资",
        p["grid_investment_100m_yuan"] / p["combined_reported_investment_100m_yuan"] * 100,
        "%", "电网投资/(电源工程投资+电网投资)×100",
        [ref(POWER, "S17", ["grid_investment_100m_yuan", "power_project_investment_100m_yuan"])],
        "两项报告口径建设投入结构；不是最优投资比例或全行业成本。")
    energy_growth = raw_energy("total_energy_consumption_growth_pct", "%")
    elec_growth = raw_energy("electricity_consumption_growth_pct", "%")
    add("electricity_energy_growth_gap", "协调性", "电力与总能源消费增速差",
        elec_growth - energy_growth, "个百分点", "电力消费同比-总能源消费同比",
        [ref(ENERGY, "S13", ["electricity_consumption_growth_pct",
                             "total_energy_consumption_growth_pct"])],
        "同公报需求增长差，仅提示电力需求约束需单列；不是电气化率变化或协同效率。")
    add("gas_power_use_share", "协调性", "天然气报告中发电用气占比",
        gas_power, "%", "官方直接观测",
        [ref(GAS, "S22", ["power_consumption_share_pct"])],
        "识别气—电转换接口；缺同边界绝对用气和效率，不能算气电转换效率。")
    add("line_loss", "协调性", "全国线路损失率",
        p["line_loss_pct"], "%", "官方直接观测",
        [ref(POWER, "S17", ["line_loss_pct"])],
        "输配环节观测；缺范围匹配的送入电量，不换算损失电量。")
    missing = {
        "供给保障": ["峰值负荷和有效供给", "各来源进口分项", "工作气与可交付库存",
                     "完整净进口和燃料平衡", "实际失供量"],
        "清洁低碳": ["统一口径非化石一次能源消费", "燃烧/过程活动量及因子", "全国CO2绝对量"],
        "经济性": ["技术全寿命成本", "统一价格基年", "终端价格与部门负担", "收益和边际成本"],
        "协调性": ["气电投入产出及转换效率", "储能功率/能量及运行", "弃能、响应和跨区互济"],
    }
    findings = [
        {"claim": "风光在发电结构中已有可观测贡献；煤炭消费和火电仍须分别建模。",
         "metric_ids": ["wind_solar_generation_share", "coal_energy_share", "thermal_generation_share"],
         "model_action": "分别校准一次能源与发电结构，禁止以风光年末容量推算减排。",
         "limit": "不能由结构描述量化全国减排潜力。"},
        {"claim": "已知五来源合计不足以识别精确进口集中度；合计占比较高不等于国家份额已知。",
         "metric_ids": ["gas_named_origins_share", "gas_hhi_lower", "gas_hhi_upper", "gas_lng_import_share"],
         "model_action": "优先补各来源与路径交叉分项；供应中断机制须报告结构不确定性。",
         "limit": "不能把五国均分或把年度进口量当作中断期可交付量。"},
        {"claim": "四类商品进口金额的主要构成可量化，建设投资结构也有独立观测。",
         "metric_ids": ["selected_import_value", "crude_oil_import_bill_share", "grid_investment_share"],
         "model_action": "分别建立燃料采购和资本投资账本，补价格、寿命与效率后再比较政策成本。",
         "limit": "不能据金额结构认定某技术更经济或认定投资失衡。"},
        {"claim": "电力需求增长与一次能源需求增长需分别描述，天然气发电用途提供转换接口。",
         "metric_ids": ["electricity_energy_growth_gap", "gas_power_use_share", "line_loss"],
         "model_action": "年度需求与运行层保留气电转换、输配损耗和电力负荷约束。",
         "limit": "协同潜力是待检验机制；本轮未证明协调改善或安全收益。"},
    ]
    return {"year": 2024, "status": "partial_four_dimension_synthesis",
            "metrics": rows, "gas_concentration_bounds": bounds, "findings": findings,
            "missing_by_dimension": missing, "composite_score": None,
            "national_co2_total": None, "net_import_dependency_pct": None,
            "gas_to_power_efficiency": None, "adequacy_margin": None,
            "scope_note": "三个限定用途发布版本并列分析；跨版本不构造容量因子、能量平衡或全国得分。"}


def build(root=ROOT):
    admission = check_formal_inputs(root)
    accepted = {item["dataset_path"]: item for item in admission["accepted_inputs"]}
    if not admission["passed"] or not set(INPUTS).issubset(accepted):
        raise ValueError("Selected official subsets have not passed evidence admission")
    result = calculate(*(read_json(root / path) for path in INPUTS))
    reviews = read_json(root / "data/evidence_reviews.json")["reviews"]
    review_ids = {accepted[path]["review_id"] for path in INPUTS}
    evidence = [e for review in reviews if review["review_id"] in review_ids
                for e in review["evidence_files"]]
    tracked = list(INPUTS) + ["data/sources.json", "data/evidence_reviews.json",
                             "workflow/model_inputs.json",
                             "scripts/build_four_dimension_assessment.py",
                             "scripts/build_energy_assessment.py",
                             "scripts/build_verified_assessment.py",
                             "scripts/build_gas_assessment.py", "scripts/workflow_status.py"]
    result["provenance"] = {
        "accepted_bindings": [accepted[path] for path in INPUTS],
        "evidence_files": evidence,
        "sha256": {path: sha256(root / path) for path in sorted(set(tracked))},
    }
    out = root / "outputs/current_assessment"
    out.mkdir(parents=True, exist_ok=True)
    (out / "four_dimensions_2024.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    lines = ["# 问题一：2024四维阶段评价", "",
             "依据已准入的S13统计公报、S17电力发布表和S22天然气报告国内子集，"
             "将独立初评收束为四维指标与模型约束。未引入候选历史表，不给综合分数或全国安全等级。",
             "", "## 指标及结果", "",
             "|维度|指标|结果|公式|解释边界|", "|---|---|---:|---|---|"]
    lines += [f"|{r['dimension']}|{r['label']}|{r['value']:.2f} {r['unit']}|"
              f"{r['formula']}|{r['interpretation']}|" for r in result["metrics"]]
    bounds = result["gas_concentration_bounds"]
    lines += ["", "## 来源集中度究竟能判断到哪里", "",
              "设各国进口份额为p，HHI=10000×Σp²。已知五来源合计份额s，"
              "由Σp²≥s²/5得到保守下界；把五来源组和其余组分别任意集中，"
              "得到上界10000×[s²+(1−s)²]。不需要知道其余国家数，也不假设五来源内部均分或为完整排名。",
              f"按公布舍入值计算，HHI只被约束在{bounds['hhi_lower_bound_10000']:.2f}至"
              f"{bounds['hhi_upper_bound_10000']:.2f}的宽范围内。端点不一定能够取到，"
              "这不是统计置信区间，不套用没有论证的安全阈值。",
              f"最大单一来源占全部进口的份额至少为{bounds['largest_origin_share_lower_pct']:.2f}%，"
              f"至多为{bounds['largest_origin_share_upper_pct']:.2f}%；这同样是保守结构界，"
              "不能据此设定某国份额或实际失供量。整数公布值自身的舍入误差未额外建模。",
              "", "## 阶段判断与后续机制", ""]
    for item in result["findings"]:
        lines += [item["claim"], "", "模型接入：" + item["model_action"],
                  "结论限制：" + item["limit"], ""]
    lines += ["## 尚不能完成的评价", ""]
    lines += [f"- {dimension}：{'、'.join(values)}。" for dimension, values in result["missing_by_dimension"].items()]
    lines += ["", "协调性目前只有需求增速差、气电转换用途和输配观测，"
              "尚未得到跨能源互补效率、年度与运行反馈收益。问题一仍为部分完成。",
              "", "## 可追溯性与复现", "",
              "每项指标的dataset_path、source_id、原字段及公式保存在four_dimensions_2024.json；"
              "原字段定位和脚注见对应观测文件与证据审查。已用证据文件信息及代码/输入哈希随结果保存。",
              "运行run_verified.ps1，或直接运行scripts/build_four_dimension_assessment.py。",
              "同报告单位内求比；不把进口质量与国产气体积混算，不把装机与跨版本发电量相除。",
              "附件继续作为项目样本，不能给本报告的全国指标设置未经核实的扩样权重。"]
    (out / "four_dimensions_2024_partial.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = build()
    print(json.dumps({"status": result["status"], "metrics": len(result["metrics"]),
                      "gas_concentration_bounds": result["gas_concentration_bounds"]},
                     ensure_ascii=False, indent=2))
