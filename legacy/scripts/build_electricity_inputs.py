"""Annual electricity anchors from admitted releases; no hourly or national initialization."""
import json
from pathlib import Path

from build_gas_assessment import lookup
from workflow_status import check_formal_inputs, read_json, sha256

ROOT = Path(__file__).resolve().parents[1]
DEMAND = "data/observations/electricity_demand_official_2024.json"
RENEWABLE = "data/observations/renewable_operation_official_2024.json"
ENERGY = "data/observations/energy_official_communique_2024.json"
POWER = "data/observations/power_official_release_2024.json"
INPUTS = (DEMAND, RENEWABLE, ENERGY, POWER)
CONVERSIONS = {
    "亿千瓦时": (0.1, "TWh"), "万亿千瓦时": (1000, "TWh"),
    "万千瓦": (0.01, "GW"), "亿千瓦": (100, "GW"), "%": (1, "%"),
}
RENEWABLE_UNITS = {
    "renewable_capacity_total": "亿千瓦", "renewable_generation_total": "万亿千瓦时",
    "hydro_capacity_total": "亿千瓦", "conventional_hydro_capacity": "亿千瓦",
    "pumped_storage_capacity": "万千瓦", "hydro_generation": "亿千瓦时",
    "wind_capacity": "亿千瓦", "wind_generation": "亿千瓦时",
    "wind_utilization_pct": "%", "solar_capacity_summary": "亿千瓦",
    "pv_capacity_detailed": "亿千瓦", "pv_generation": "亿千瓦时",
    "pv_utilization_pct": "%", "biomass_capacity": "万千瓦",
    "biomass_generation": "亿千瓦时",
}
RENEWABLE_LABELS = {
    "renewable_capacity_total": "可再生能源装机合计", "renewable_generation_total": "可再生能源发电合计",
    "hydro_capacity_total": "水电装机（含抽蓄）", "conventional_hydro_capacity": "常规水电装机",
    "pumped_storage_capacity": "抽蓄功率", "hydro_generation": "水电发电量",
    "wind_capacity": "风电装机", "wind_generation": "风电发电量",
    "wind_utilization_pct": "风电平均利用率", "solar_capacity_summary": "太阳能装机（总述）",
    "pv_capacity_detailed": "光伏装机（专段）", "pv_generation": "光伏发电量",
    "pv_utilization_pct": "光伏发电利用率", "biomass_capacity": "生物质装机",
    "biomass_generation": "生物质发电量",
}


def normalize(data, path, source, expected):
    value = lookup(data, source)
    index = {r["indicator_id"]: r for r in data["observations"]}
    if set(index) != set(expected):
        raise ValueError("Unexpected indicator set")
    normalized = {}
    for key, unit in expected.items():
        number = value(key, unit)
        if unit == "%" and key.endswith("growth_pct"):
            if number < -100:
                raise ValueError("Invalid growth rate")
        elif number < 0 or (unit == "%" and number > 100):
            raise ValueError("Invalid physical quantity or rate")
        factor, target = CONVERSIONS[unit]
        normalized[key] = {
            "value": number * factor, "unit": target,
            "raw_value": number, "raw_unit": unit,
            "formula": f"原值 × {factor:g}",
            "input_ref": {"dataset_path": path, "source_id": source,
                          "field": key, "locator": index[key]["locator"]},
            "scope": index[key]["scope"],
        }
    return normalized


def calculate(demand, renewable, energy, power):
    sectors = ("primary_industry", "secondary_industry", "tertiary_industry", "household")
    expected_demand = {
        "electricity_consumption_total": "亿千瓦时", "electricity_consumption_growth_pct": "%",
        "generation_industrial_above_designated_size": "亿千瓦时",
        **{s + "_consumption": "亿千瓦时" for s in sectors},
        **{s + "_growth_pct": "%" for s in sectors},
    }
    d = normalize(demand, DEMAND, "S24", expected_demand)
    r = normalize(renewable, RENEWABLE, "S25", RENEWABLE_UNITS)
    e = lookup(energy, "S13")
    total = d["electricity_consumption_total"]["value"]
    if total <= 0:
        raise ValueError("Nonpositive annual demand")
    raw_residual = d["electricity_consumption_total"]["raw_value"] - sum(
        d[s + "_consumption"]["raw_value"] for s in sectors)
    if raw_residual != 0:
        raise ValueError("Demand categories do not close to this release total")
    sector_rows = [{
        "sector": s, "consumption": d[s + "_consumption"],
        "share_pct": d[s + "_consumption"]["value"] / total * 100,
        "share_formula": "该类同版年度用电量 / 同版全社会年度用电量 × 100",
        "growth": d[s + "_growth_pct"],
    } for s in sectors]

    if power.get("source_id") != "S17" or len(power["rows"]) != 1:
        raise ValueError("Expected S17 single-year capacity release")
    p = dict(zip(power["columns"], power["rows"][0]))
    if p["year"] != 2024:
        raise ValueError("Wrong power period")
    comparisons = []
    for field, alternative, label in (
        ("hydro", "hydro_capacity_total", "水电"),
        ("wind", "wind_capacity", "风电"),
        ("solar", "solar_capacity_summary", "太阳能总述"),
        ("solar", "pv_capacity_detailed", "太阳能/光伏专段"),
    ):
        if power["units"][field] != "万千瓦":
            raise ValueError("Wrong S17 capacity unit")
        left = p[field] / 100
        right = r[alternative]["value"]
        comparisons.append({
            "label": label, "unit": "GW",
            "left": {"source_id": "S17", "dataset_path": POWER, "field": field, "value": left},
            "right": r[alternative],
            "right_minus_left": right - left,
            "compatibility": "category_bridge_pending" if alternative == "pv_capacity_detailed"
                             else "release_bridge_pending",
        })
    for field, alternative, label in (
        ("generation_hydro", "hydro_generation", "水电发电"),
        ("generation_wind", "wind_generation", "风电发电"),
        ("generation_solar", "pv_generation", "太阳能/光伏发电"),
    ):
        left = e(field, "亿千瓦时") * 0.1
        right = r[alternative]["value"]
        comparisons.append({
            "label": label, "unit": "TWh",
            "left": {"source_id": "S13", "dataset_path": ENERGY, "field": field, "value": left},
            "right": r[alternative],
            "right_minus_left": right - left,
            "compatibility": "category_bridge_pending" if alternative == "pv_generation"
                             else "release_bridge_pending",
        })
    return {
        "year": 2024, "status": "scoped_annual_reference_inputs",
        "demand": {"total": d["electricity_consumption_total"], "sectors": sector_rows,
                   "growth": d["electricity_consumption_growth_pct"],
                   "closure_residual_twh": raw_residual * 0.1},
        "separate_industrial_generation_reference":
            d["generation_industrial_above_designated_size"],
        "renewable_reference": r, "version_comparisons": comparisons,
        "demand_growth_comparison": {
            "s24_pct": d["electricity_consumption_growth_pct"]["value"],
            "s13_pct": e("electricity_consumption_growth_pct", "%"),
            "interpretation": "相同字段一致不证明其他统计范围和历史序列一致"},
        "unknowns": {
            "hourly_load_mw": None, "pumped_storage_energy_gwh": None,
            "pumped_storage_duration_h": None, "biomass_co2_factor": None,
            "biomass_emissions": None, "capacity_factors": None,
            "curtailed_energy_twh": None, "national_supply_demand_gap_twh": None,
        },
        "ready_for": ["2024四类年度用电规模与份额参考", "独立版本技术容量和发电描述",
                      "抽蓄功率、生物质技术规模参考", "风光利用率观测及版本诊断"],
        "blocked_for": ["逐时负荷及缺供评价", "全国资产与部门设备完整初始化",
                        "抽蓄能量与连续运行参数", "生物质排放核算",
                        "2015—2024历史拟合及行为识别", "2030/2060预测"],
        "rules": [
            "规模以上工业发电量不与全社会用电量相减求缺供。",
            "利用率不是容量因子；年末装机不充当全年平均装机。",
            "水电含抽蓄，不再重复加抽蓄；不跨精度强配平。",
            "生物质不默认零排放，不加回S17全国总量或从S13火电擅自拆出。",
            "太阳能总述和光伏专段分列；版本差额不归为光热或统计修订。",
            "第二产业不等于制造业，居民生活不等于全部建筑；年度份额不冒充小时曲线。",
        ],
    }


def build(root=ROOT):
    formal = check_formal_inputs(root)
    accepted = {r["dataset_path"]: r for r in formal["accepted_inputs"]}
    if not formal["passed"] or not set(INPUTS).issubset(accepted):
        raise ValueError("Electricity reference inputs have not passed evidence admission")
    result = calculate(*(read_json(root / path) for path in INPUTS))
    reviews = read_json(root / "data/evidence_reviews.json")["reviews"]
    ids = {accepted[p]["review_id"] for p in INPUTS}
    tracked = list(INPUTS) + [
        "data/sources.json", "data/evidence_reviews.json", "workflow/model_inputs.json",
        "scripts/build_electricity_inputs.py", "scripts/build_gas_assessment.py",
        "scripts/workflow_status.py",
    ]
    evidence = [e for review in reviews if review["review_id"] in ids
                for e in review["evidence_files"]]
    result["provenance"] = {
        "accepted_bindings": [accepted[p] for p in INPUTS],
        "evidence_files": evidence,
        "sha256": {p: sha256(root / p) for p in sorted(set(tracked))},
    }
    out = root / "outputs/current_assessment"
    out.mkdir(parents=True, exist_ok=True)
    (out / "electricity_inputs_2024.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    labels = {"primary_industry": "第一产业", "secondary_industry": "第二产业",
              "tertiary_industry": "第三产业", "household": "城乡居民生活"}
    lines = [
        "# 2024年度用电与可再生能源输入参考", "",
        "新增S24用电发布和S25可再生能源运行发布已逐值核对并限定准入。"
        "本报告实际生成年度量和份额，供后续模型接入审查；尚未接入全国主体或真实逐时运行。",
        "", "## 年度需求锚点", "",
        f"全社会用电量{result['demand']['total']['value']:.1f} TWh，"
        f"同比{result['demand']['growth']['value']:.1f}%。原单位亿千瓦时乘0.1转换为TWh。",
        "", "|分类|年度用电（TWh）|占总用电（%）|同比（%）|",
        "|---|---:|---:|---:|",
    ]
    for row in result["demand"]["sectors"]:
        lines.append(f"|{labels[row['sector']]}|{row['consumption']['value']:.1f}|"
                     f"{row['share_pct']:.4f}|{row['growth']['value']:.1f}|")
    lines += [
        "", "四类合计与公布总量残差为0 TWh。结构占比不能识别小时负荷或需求弹性；"
        "第二产业与居民分类不能分别改称纯制造业与全部建筑。",
        "另存规模以上工业发电量9418.1 TWh，仅保留原范围；"
        "不能与全社会用电量求差并解释为缺供。",
        "", "## 技术参考", "", "|原指标|规范量|原值与单位|",
        "|---|---:|---|",
    ]
    for key, row in result["renewable_reference"].items():
        lines.append(f"|{RENEWABLE_LABELS[key]}|{row['value']:.2f} {row['unit']}|"
                     f"{row['raw_value']} {row['raw_unit']}|")
    lines += [
        "", "抽蓄58.69 GW只确定功率；能量GWh与时长均未知。"
        "生物质45.99 GW、208.3 TWh不自动赋予零排放。"
        "风电95.9%、光伏96.8%保留为原文利用率，不用于年发电量计算或弃电反推。",
        "", "## 版本与分类并列检查", "",
        "|指标|S13或S17原版本规范量|S25规范量|S25减前者|桥接状态|",
        "|---|---:|---:|---:|---|",
    ]
    for row in result["version_comparisons"]:
        status = ("分类范围待桥接" if row["compatibility"] == "category_bridge_pending"
                  else "发布版本待桥接")
        lines.append(f"|{row['label']}|{row['left']['source_id']}："
                     f"{row['left']['value']:.2f} {row['unit']}|"
                     f"{row['right']['value']:.2f} {row['unit']}|"
                     f"{row['right_minus_left']:+.2f} {row['unit']}|{status}|")
    lines += [
        "", "差额只作版本/分类诊断，不能解释为修订影响的估计。"
        "太阳能总述887 GW和光伏专段886 GW分别保留，不用1 GW差额补光热。"
        "常规水电与抽蓄不再加到已含抽蓄的水电总量；生物质与其他表火电分类待桥接。",
        "", "## 接入边界", "",
        "已可用：" + "；".join(result["ready_for"]) + "。",
        "", "仍受限：" + "；".join(result["blocked_for"]) + "。",
        "消费/GDP/装机十年候选转录已存在，历史工作主要待原表证据、逐值复核和范围桥接。"
        "本轮没有真实历史误差，也不改变W5 pending。",
        "", "## 复现与文件", "",
        "运行run_verified.ps1或scripts/build_electricity_inputs.py。"
        "electricity_inputs_2024.json保存原值、单位转换、原字段定位、来源、审查绑定、"
        "证据与代码哈希；没有填补未知储能、排放或小时数据。"
        "审查记录：outputs/data_review/review_electricity_inputs_20261017.md。",
    ]
    (out / "electricity_inputs_2024_partial.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = build()
    print(json.dumps({"status": result["status"], "demand_twh": result["demand"]["total"]["value"],
                      "closure_residual_twh": result["demand"]["closure_residual_twh"],
                      "technology_fields": len(result["renewable_reference"])}, ensure_ascii=False))
