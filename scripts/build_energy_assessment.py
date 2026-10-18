"""Scoped multi-energy Q1 profile. Requires admitted S13 observations."""
import json
import math
from pathlib import Path

from workflow_status import check_formal_inputs, read_json, sha256

ROOT = Path(__file__).resolve().parents[1]
INPUT = "data/observations/energy_official_communique_2024.json"


def calculate(data):
    if data.get("year") != 2024 or data.get("source_id") != "S13":
        raise ValueError("Expected the S13 2024 single-release dataset")
    records = data["observations"]
    by_id = {r["indicator_id"]: r for r in records}
    if len(by_id) != len(records):
        raise ValueError("Duplicate indicator IDs")

    def value(key, unit):
        record = by_id[key]
        number = record["value"]
        if record["unit"] != unit or type(number) not in (int, float) or not math.isfinite(number):
            raise ValueError(f"Wrong unit or nonfinite number: {key}")
        return number

    total = value("generation_total", "亿千瓦时")
    energy = value("total_energy_consumption", "亿吨标准煤")
    production = value("primary_energy_production", "亿吨标准煤")
    volume = value("carbon_allowance_turnover_volume", "亿吨")
    if min(total, energy, production, volume) <= 0:
        raise ValueError("Nonpositive generation, energy or market volume")
    generation = {k: value("generation_" + k, "亿千瓦时")
                  for k in ("thermal", "hydro", "nuclear", "wind", "solar")}
    if any(n < 0 for n in generation.values()):
        raise ValueError("Negative generation")
    coal_share = value("coal_consumption_share_pct", "%")
    clean_share = value("clean_energy_consumption_share_including_gas_pct", "%")
    if not 0 <= coal_share <= 100 or not 0 <= clean_share <= 100:
        raise ValueError("Share outside [0,100]")

    imports = []
    for key, label in (("coal_lignite", "煤及褐煤"), ("crude_oil", "原油"),
                       ("petroleum_products", "成品油"), ("natural_gas", "天然气")):
        quantity = value(key + "_import_quantity", "万吨")
        amount = value(key + "_import_value", "亿元")
        if quantity <= 0 or amount < 0:
            raise ValueError("Invalid import quantity/value")
        imports.append({"commodity": key, "label": label, "quantity_10k_t": quantity,
                        "value_100m_yuan": amount,
                        "import_unit_value_yuan_per_t": amount / quantity * 10000})
    energy_growth = value("total_energy_consumption_growth_pct", "%")
    gdp_growth = value("real_gdp_growth_pct", "%")
    if energy_growth <= -100 or gdp_growth <= -100:
        raise ValueError("Invalid annual growth")
    return {
        "year": 2024, "status": "partial_q1_single_release_not_calibrated_forecast",
        "source_ids": ["S13"], "total_energy_consumption_100m_tce": energy,
        "primary_energy_production_100m_tce": production,
        "coal_consumption_share_pct": coal_share,
        "clean_energy_consumption_share_including_gas_pct": clean_share,
        "generation_100m_kwh": {"total": total, **generation},
        "generation_share_pct": {k: v / total * 100 for k, v in generation.items()},
        "wind_solar_generation_share_pct": (generation["wind"] + generation["solar"]) / total * 100,
        "hydro_nuclear_wind_solar_generation_share_pct":
            sum(generation[k] for k in ("hydro", "nuclear", "wind", "solar")) / total * 100,
        "generation_rounding_residual_100m_kwh": total - sum(generation.values()),
        "imports": imports,
        "reported_adjusted_energy_intensity_growth_pct":
            value("adjusted_energy_intensity_growth_pct", "%"),
        "illustrative_total_energy_per_real_gdp_growth_pct":
            ((1 + energy_growth / 100) / (1 + gdp_growth / 100) - 1) * 100,
        "reported_co2_intensity_growth_pct": value("co2_intensity_growth_pct", "%"),
        "carbon_allowance_turnover_ratio_yuan_per_tco2e":
            value("carbon_allowance_turnover_value", "亿元") / volume,
        "nonfossil_primary_energy_share_pct": None,
        "net_import_dependency_pct": None,
        "national_co2_total": None,
        "formulas": {
            "generation_share": "分项年度发电量/同表发电总量*100",
            "import_unit_value": "进口金额(亿元)/进口质量(万吨)*10000",
            "carbon_turnover_ratio": "成交额(亿元)/成交量(亿吨)",
            "illustrative_total_intensity_change": "(1+总能耗同比)/(1+实际GDP同比)-1；只用已舍入公布增速",
        },
        "boundaries": [
            "清洁能源消费28.6%含天然气，不是非化石能源消费占比。",
            "火电含生物质等，不能把火电全部计为煤电或化石发电。",
            "国内气产量是亿立方米，进口是万吨；无官方换算参数时不计算天然气进口依赖。",
            "进口单位价值由年度商品组合计算，不能替代现货价格或生产成本。",
            "成交额/成交量是派生年度交易比值，不是期末碳价，也不是未来碳价政策。",
            "总能耗/实际GDP示例与扣除原料和非化石用能的官方强度指标边界不同。",
            "碳强度降幅不是排放总量降幅；缺绝对基准，不能据此给出全国CO2吨数。",
            "所有公报值为初步数；与年鉴的历史修订桥接仍待完成。",
        ],
    }


def build(root=ROOT):
    formal = check_formal_inputs(root)
    if not formal["passed"] or INPUT not in {i["dataset_path"] for i in formal["accepted_inputs"]}:
        raise ValueError("S13 dataset has not passed evidence admission")
    result = calculate(read_json(root / INPUT))
    result["input_sha256"] = sha256(root / INPUT)
    result["source_registry_sha256"] = sha256(root / "data/sources.json")
    out = root / "outputs/current_assessment"
    out.mkdir(parents=True, exist_ok=True)
    (out / "energy_2024.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 问题一：2024多能源现状初评", "",
        "来源：国家统计局2025-02-28发布的2024年统计公报（S13）。"
        "33项观测及所用脚注已逐值核对，限定独立公报版本。"
        "本报告补充电力初评，尚未完成十年四维综合评价或模型校准。",
        "", "## 供给与需求", "",
        f"一次能源生产{result['primary_energy_production_100m_tce']}亿吨标准煤，"
        f"能源消费{result['total_energy_consumption_100m_tce']}亿吨标准煤。"
        "两者相减不能直接解释为净进口或失供量；还缺完整贸易、库存及能源平衡。",
        f"煤炭消费占比{result['coal_consumption_share_pct']}%，"
        f"含天然气的清洁能源消费占比{result['clean_energy_consumption_share_including_gas_pct']}%。"
        "两类不构成完整互补分类，不能据此反算油气分项或非化石份额。",
        "", "## 发电结构", "",
        "|电源|发电量（亿千瓦时）|同表发电量占比（%）|", "|---|---:|---:|",
    ]
    labels = {"thermal": "火电", "hydro": "水电", "nuclear": "核电", "wind": "风电", "solar": "太阳能"}
    lines += [f"|{label}|{result['generation_100m_kwh'][k]:.1f}|"
              f"{result['generation_share_pct'][k]:.2f}|" for k, label in labels.items()]
    lines += [
        f"|合计|{result['generation_100m_kwh']['total']:.1f}|100.00|", "",
        f"风光发电占比{result['wind_solar_generation_share_pct']:.2f}%；"
        f"水核风光合计{result['hydro_nuclear_wind_solar_generation_share_pct']:.2f}%。"
        "这组发电占比与S17装机占比分列，不能替代非化石一次能源消费占比。",
        f"总量减分项和的舍入残差为{result['generation_rounding_residual_100m_kwh']:.1f}亿千瓦时，保留原数。",
        "火电内含煤油气、生物质和余热等。水电中抽蓄边界仍需分项衔接，不能直接把该组合折为一次能源量。",
        "", "## 进口与经济性", "",
        "|商品|进口（万吨）|金额（亿元）|派生单位价值（元/吨）|", "|---|---:|---:|---:|",
    ]
    lines += [f"|{r['label']}|{r['quantity_10k_t']}|{r['value_100m_yuan']}|"
              f"{r['import_unit_value_yuan_per_t']:.2f}|" for r in result["imports"]]
    lines += [
        "", "单位价值反映全年商品组合，未分煤种、油品、合同和运输，不作为技术成本或现货价格。"
        "天然气进口质量与国内产量体积不能直接相除；煤及褐煤进口与原煤产量也缺热值桥接。"
        "原油净进口、库存和成品油转换尚缺，因此本报告不发布进口依赖率。",
        f"碳配额成交额/成交量派生比值为"
        f"{result['carbon_allowance_turnover_ratio_yuan_per_tco2e']:.2f}元/吨CO2当量，"
        "只描述年度成交，不用作期末价格或外生未来政策路径。",
        "", "## 必须分开的强度口径", "",
        f"公报公布的扣除原料用能及非化石能源后的单位GDP能耗同比为"
        f"{result['reported_adjusted_energy_intensity_growth_pct']:.1f}%。"
        "若仅把能源消费增速4.3%与实际GDP增速5.0%代入总能耗/实际GDP公式，"
        f"得到约{result['illustrative_total_energy_per_real_gdp_growth_pct']:.2f}%。"
        "这是用舍入增速计算的口径示例，不是对官方降幅的更正；两个指标的分子不同，不能互作校准目标。",
        f"单位GDP二氧化碳排放同比{result['reported_co2_intensity_growth_pct']:.1f}%，"
        "不等于全国排放总量下降同样幅度；本子集没有CO2绝对量和全口径核算所需活动量。",
        "", "## 对模型的直接约束", "",
        "政府主体分别读取总能源强度、考核强度、CO2强度；需求主体区分燃烧与原料用能；"
        "供给主体区分国产气体积与进口质量；转换模块避免发电及成品油重复计入一次能源。"
        "碳市场成交额、成交量只作历史市场观测，不能当作免费设定未来碳价的依据。",
        "", "## 还缺什么", "",
        "消费、宏观增速、装机三张十年表已录齐，仍待原表证据、脚注及范围复核；"
        "发电分项和煤油气历史另有缺年、缺字段及版本衔接任务，详见outputs/data_review/history_readiness.md。"
        "仍需GDP修订桥接、煤油气完整平衡、部门终端和非燃烧用途、"
        "热值/排放因子、工业过程排放与移除、峰荷与有效供给、技术成本和地区数据。"
        "四维评价和2030/2060预测均保持未完成。",
        "", "复现：run_verified.ps1。证据定位见data/evidence_reviews.json与"
        "data/raw/official/S13_selected_capture.txt；数据目录见outputs/data_review/catalog.md。",
    ]
    (out / "energy_2024_partial.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    profile = build()
    print(json.dumps({"year": profile["year"], "status": profile["status"],
                      "wind_solar_generation_share_pct": profile["wind_solar_generation_share_pct"]},
                     ensure_ascii=False))
