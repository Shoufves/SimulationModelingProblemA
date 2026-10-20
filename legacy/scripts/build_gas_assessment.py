"""Scoped gas observations, boundary comparison and an incomplete fuel ledger."""
import json
import math
import sys
from pathlib import Path

from workflow_status import check_formal_inputs, read_json, sha256

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from energy_model.fuel_ledger import FuelLedger

REPORT = "data/observations/gas_official_report_2024.json"
QUICK = "data/observations/gas_apparent_consumption_2024.json"


def lookup(data, source):
    if data.get("year") != 2024 or data.get("source_id") != source:
        raise ValueError("Wrong period or source")
    rows = data["observations"]
    index = {r["indicator_id"]: r for r in rows}
    if len(index) != len(rows):
        raise ValueError("Duplicate indicator")

    def number(key, unit):
        row = index[key]
        result = row["value"]
        if row["unit"] != unit or type(result) not in (int, float) or not math.isfinite(result):
            raise ValueError(f"Wrong unit or number: {key}")
        return result
    return number


def calculate(report, quick):
    value, q = lookup(report, "S22"), lookup(quick, "S23")
    production = value("gas_production", "亿立方米")
    total = value("gas_imports", "亿立方米")
    pipeline = value("pipeline_imports", "亿立方米")
    lng = value("lng_imports", "亿立方米")
    concentration = value("five_main_origins_imports", "亿立方米")
    spot = value("lng_spot_imports", "亿立方米")
    apparent = q("gas_apparent_consumption", "亿立方米")
    storage_added = value("added_storage_capacity", "亿立方米")
    if min(production, total, lng, apparent) <= 0 or min(pipeline, concentration, spot, storage_added) < 0:
        raise ValueError("Invalid gas quantity")
    if concentration > total or spot > lng or abs(total - pipeline - lng) > 1.5:
        raise ValueError("Gas import subsets inconsistent")
    sectors = {key: value(key + "_consumption_share_pct", "%")
               for key in ("city_gas", "industrial_fuel", "power", "chemical_fertilizer")}
    if any(not 0 <= n <= 100 for n in sectors.values()) or abs(sum(sectors.values()) - 100) > 2:
        raise ValueError("Invalid rounded sector shares")
    growth = value("gas_consumption_growth_pct", "%")
    apparent_growth = q("gas_apparent_consumption_growth_pct", "%")
    # Apparent consumption is deliberately not treated as this ledger's domestic use.
    ledger = FuelLedger(
        year=2024, carrier="natural_gas", unit="亿立方米",
        reference_state=None, common_boundary_verified=False,
        production=production, imports=total)
    return {
        "year": 2024, "status": "partial_gas_profile_and_boundary_diagnostics",
        "source_ids": ["S22", "S23"], "gas_production_100m_m3": production,
        "gas_imports_100m_m3": total, "pipeline_imports_100m_m3": pipeline,
        "lng_imports_100m_m3": lng,
        "pipeline_import_share_pct": pipeline / total * 100,
        "lng_import_share_pct": lng / total * 100,
        "import_split_residual_100m_m3": total - pipeline - lng,
        "five_main_origins_share_derived_pct": concentration / total * 100,
        "five_main_origins_share_reported_pct": value("five_main_origins_reported_share_pct", "%"),
        "lng_spot_share_derived_pct": spot / lng * 100,
        "lng_spot_share_reported_pct": value("lng_spot_reported_share_pct", "%"),
        "sector_share_pct": sectors, "sector_share_sum_pct": sum(sectors.values()),
        "sector_absolute_volume_100m_m3": None,
        "gas_apparent_consumption_100m_m3": apparent,
        "gas_consumption_growth_report_pct": growth,
        "gas_apparent_consumption_growth_quick_pct": apparent_growth,
        "growth_scope_gap_percentage_points": apparent_growth - growth,
        "cross_release_arithmetic_gap": {
            "value_100m_m3": production + total - apparent,
            "formula": "S22产量 + S22进口 - S23表观消费",
            "status": "arithmetic_diagnostic_only_not_a_closed_balance",
            "meaning": "跨发布算术差；不能归为出口、库存、损耗或统计差，也不能作为调参目标",
        },
        "added_storage_capacity_100m_m3": storage_added,
        "total_storage_capacity_100m_m3": None, "storage_cover_days": None,
        "country_hhi": None, "net_import_dependency_pct": None,
        "fuel_ledger": ledger.evaluate(),
        "formulas": {
            "route_share_pct": "同报告进口分项/同报告进口总量*100",
            "five_named_origins_share_pct": "报告列示五主要来源合计/总进口*100；未证明完整国家排名",
            "lng_spot_share_pct": "LNG现货进口/LNG进口*100",
        },
        "limitations": [
            "报告消费和快报表观消费口径未桥接；部门份额不乘快报总量。",
            "城市燃气不是纯居民用气，化工化肥不是纯原料用气。",
            "发电用气属于转换投入，不与终端电力消费重复相加。",
            "进口体积采用官方报告已公布体积，不自行由质量换算；标准温压仍未明确。",
            "只给五来源合计，不计算缺各国份额的HHI。",
            "新增储气能力不是总能力或库存，不计算覆盖天数。",
            "缺出口、库存、损耗、统计差和同边界国内用量，不给正式燃料平衡或依赖率。",
            "官方发布编委会报告采用部分行业统计，来源身份及用途限制单独登记。",
        ],
    }


def build(root=ROOT):
    admitted = check_formal_inputs(root)
    paths = {item["dataset_path"] for item in admitted["accepted_inputs"]}
    if not admitted["passed"] or not {REPORT, QUICK}.issubset(paths):
        raise ValueError("Gas subsets have not passed evidence admission")
    result = calculate(read_json(root / REPORT), read_json(root / QUICK))
    result["input_sha256"] = {path: sha256(root / path) for path in (REPORT, QUICK)}
    result["source_registry_sha256"] = sha256(root / "data/sources.json")
    out = root / "outputs/current_assessment"
    out.mkdir(parents=True, exist_ok=True)
    (out / "gas_2024.json").write_text(json.dumps(
        result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    labels = {"city_gas": "城市燃气", "industrial_fuel": "工业燃料",
              "power": "发电", "chemical_fertilizer": "化工化肥"}
    lines = [
        "# 问题一：2024天然气现状与口径诊断", "",
        "依据S22能源局公开发布的2025版天然气报告（2024国内字段20项）及"
        "S23发改委2025-01-23运行快报（2024全年2项）。"
        "官方报告页面和相关脚注已读，PDF所用页已截图复核；本地留存是文本摘录，原件下载TLS失败。",
        "", "## 消费结构与模型主体", "",
        "|报告用气类别|占比（%）|模型接入边界|", "|---|---:|---|",
    ]
    boundaries = {"city_gas": "居民、采暖、公福商业、交通等混合类，不能直接视为居民主体",
                  "industrial_fuel": "工业燃料主体候选，仍需行业细分和设备/服务量",
                  "power": "气电转换投入；与电力调度相连，不能再次当终端电力计一次能源",
                  "chemical_fertilizer": "需要燃烧/原料拆分，不能全数视为非燃烧用途"}
    lines += [f"|{labels[key]}|{share:g}|{boundaries[key]}|"
              for key, share in result["sector_share_pct"].items()]
    lines += [
        "", "四类公布份额合计100%，报告本段未给与这些份额同边界的绝对消费量，"
        "部门绝对量保持null。不能乘另一份快报表观消费量，制造看似精确的部门数据。",
        "", "## 进口结构与安全指标", "",
        f"报告总进口{result['gas_imports_100m_m3']:g}亿立方米；"
        f"管道气{result['pipeline_imports_100m_m3']:g}、"
        f"LNG {result['lng_imports_100m_m3']:g}亿立方米，"
        f"派生占比{result['pipeline_import_share_pct']:.2f}%和{result['lng_import_share_pct']:.2f}%，"
        f"分项残差{result['import_split_residual_100m_m3']:g}。",
        f"五主要来源合计派生占比{result['five_main_origins_share_derived_pct']:.2f}%，"
        f"原文整数占比{result['five_main_origins_share_reported_pct']:g}%；两种精度分别保留。"
        "这支持描述来源集中性；缺各国分项，不计算HHI，不评定安全阈值。",
        f"LNG现货占LNG进口的派生比例{result['lng_spot_share_derived_pct']:.2f}%，"
        f"原文{result['lng_spot_share_reported_pct']:g}%。"
        "不能错用全部天然气进口作分母，也不据此直接等同价格风险或长协占比。",
        f"新增储气能力{result['added_storage_capacity_100m_m3']:g}亿立方米，只是年度增量；"
        "年末总能力、可提取工作气和库存未知，不算供气保障天数。",
        "", "## 两个消费口径分别保存", "",
        f"S23快报表观消费{result['gas_apparent_consumption_100m_m3']:g}亿立方米，同比"
        f"{result['gas_apparent_consumption_growth_quick_pct']:g}%；"
        f"S22报告消费同比{result['gas_consumption_growth_report_pct']:g}%。"
        f"增速差{result['growth_scope_gap_percentage_points']:.1f}个百分点；"
        "该差异尚未被分解为定义、版本或修订效应，不能择一覆盖另一个。",
        f"若仅作跨发布算术，报告产量+进口-快报表观消费差"
        f"{result['cross_release_arithmetic_gap']['value_100m_m3']:g}亿立方米。"
        "这是诊断数，不是已核验出口、库存、损耗或统计差，不用于调参配平。",
        "", "## 可执行燃料账本检查", "",
        "src/energy_model/fuel_ledger.py实行P+M-X-国内使用-库存增加-损耗-统计差=0。"
        "未知项保持None；库存增加和统计差允许负号；其他物理量非负。"
        "还必须确认相同体积状态、年份和统计边界才能验收闭合。",
        f"当前状态：{result['fuel_ledger']['status']}；"
        f"缺项：{', '.join(result['fuel_ledger']['missing_terms'])}。"
        "程序拒绝宣称平衡成立，不自动用差额补缺项。",
        "", "## 对三问的推进与剩余任务", "",
        "问题一补充天然气部门结构、进口路径与来源集中性；"
        "问题二得到气电/工业/城市燃气/化工主体的边界约束及缺失感知账本；"
        "问题三可据此设计管道/LNG供应中断与储气对冲实验，但尚未运行相关情景。",
        "天然气2015—2023完整历史尚未形成，2024仍缺出口、库存等平衡字段；"
        "另需终端燃烧/原料拆分、热值与排放因子、"
        "价格成本与调峰可用量。未给2030/2060预测，未建成校准多智能体系统。",
        "", "复现：run_verified.ps1。原值、证据、审查分别见data/observations/、"
        "data/raw/official/及data/evidence_reviews.json；目录见outputs/data_review/catalog.md。",
    ]
    (out / "gas_2024_partial.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = build()
    print(json.dumps({"year": result["year"], "ledger_status": result["fuel_ledger"]["status"],
                      "pipeline_import_share_pct": result["pipeline_import_share_pct"]}, ensure_ascii=False))
