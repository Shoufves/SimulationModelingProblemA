"""Build a scoped Q1 electricity profile from an admitted official release."""
import json
from pathlib import Path
from workflow_status import check_formal_inputs, read_json, sha256

ROOT = Path(__file__).resolve().parents[1]
INPUT = "data/observations/power_official_release_2024.json"
YEARBOOK_CANDIDATE = "data/observations/power_capacity_2015_2024.json"


def calculate(data):
    row = dict(zip(data["columns"], data["rows"][0]))
    if row["year"] != 2024 or row["total"] <= 0:
        raise ValueError("Expected the positive-total 2024 cross-section")
    technologies = ("hydro", "thermal", "nuclear", "wind", "solar")
    capacity = {key: row[key] / 100 for key in ("total",) + technologies}
    shares = {key: row[key] / row["total"] * 100 for key in technologies}
    residual = row["total"] - sum(row[key] for key in technologies)
    investment = row["power_project_investment_100m_yuan"] + row["grid_investment_100m_yuan"]
    return {
        "year": 2024, "capacity_gw": capacity, "capacity_share_pct": shares,
        "wind_solar_capacity_share_pct": (row["wind"] + row["solar"]) / row["total"] * 100,
        "hydro_nuclear_wind_solar_capacity_share_pct":
            sum(row[key] for key in ("hydro", "nuclear", "wind", "solar")) / row["total"] * 100,
        "unallocated_capacity_10k_kw": residual,
        "line_loss_pct": row["line_loss_pct"],
        "utilization_hours_plants_ge_6000kw": row["utilization_hours_plants_ge_6000kw"],
        "power_project_investment_100m_yuan": row["power_project_investment_100m_yuan"],
        "grid_investment_100m_yuan": row["grid_investment_100m_yuan"],
        "combined_reported_investment_100m_yuan": investment,
        "scope": "单一2024官方发布版本，仅电力横截面，不代表完整能源系统评价",
        "formulas": {"capacity_gw": "容量(万千瓦)/100", "share_pct": "分项容量/全国容量*100",
                     "residual": "总容量-原表所列五类容量之和"},
    }


def build(root=ROOT):
    formal = check_formal_inputs(root)
    if not formal["passed"] or INPUT not in {i["dataset_path"] for i in formal["accepted_inputs"]}:
        raise ValueError("The selected official release has not passed evidence admission")
    data = read_json(root / INPUT)
    result = calculate(data)
    candidate = read_json(root / YEARBOOK_CANDIDATE)
    yearbook = dict(zip(candidate["columns"], next(r for r in candidate["rows"] if r[0] == 2024)))
    release = dict(zip(data["columns"], data["rows"][0]))
    comparison = [{
        "indicator": key, "official_release_10k_kw": release[key],
        "yearbook_candidate_10k_kw": yearbook[key],
        "candidate_minus_release_10k_kw": yearbook[key] - release[key],
    } for key in ("total", "hydro", "thermal", "nuclear", "wind", "solar")]
    result["input_sha256"] = sha256(root / INPUT)
    result["version_comparison"] = {
        "status": "candidate_file_comparison_only",
        "note": "S05年鉴转录尚未通过证据准入；差异可能涉及修订、口径或转录，不能自动判为统计修订。",
        "candidate_sha256": sha256(root / YEARBOOK_CANDIDATE), "rows": comparison}
    out = root / "outputs/current_assessment"
    out.mkdir(parents=True, exist_ok=True)
    (out / "electricity_2024.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    labels = {"hydro": "水电", "thermal": "火电", "nuclear": "核电", "wind": "风电", "solar": "太阳能"}
    lines = ["# 问题一：2024年电力现状初评", "",
             "数据版本：国家能源局2025-01-21发布的2024年全国电力工业统计数据（S17）。"
             "原页面可见正文、表格与脚注已留存，10项转录值已复核。本报告是问题一的电力子模块，"
             "四维全国能源综合评价仍未完成。",
             "", "|电源|2024年末装机（GW）|占全国装机（%）|", "|---|---:|---:|"]
    lines += [f"|{labels[k]}|{result['capacity_gw'][k]:.2f}|{result['capacity_share_pct'][k]:.2f}|"
              for k in labels]
    lines += [
        f"|全国合计|{result['capacity_gw']['total']:.2f}|100.00|", "",
        f"原表所列五类分项与总量差{result['unallocated_capacity_10k_kw']}万千瓦，保留未分配差额，不强行配平。",
        f"风光装机占比为{result['wind_solar_capacity_share_pct']:.2f}%；水核风光四类装机合计占比为"
        f"{result['hydro_nuclear_wind_solar_capacity_share_pct']:.2f}%。"
        "这些是装机结构，不能替代发电量结构或非化石一次能源消费占比；火电包含的具体燃料类型仍需拆分。",
        "", "## 四维评价能支持到哪里", "",
        "|维度|本子集提供的量|现在可作的判断|仍缺什么|", "|---|---|---|---|",
        "|供给保障|总装机及技术结构|描述供给资产构成|峰值负荷、可用容量、燃料库存、进口依赖和失供数据，暂不评判充足性|",
        "|清洁低碳|风光、水核风光装机占比|描述设备结构|燃烧与工业过程排放、非化石消费；不能由容量直接推出减排量|",
        f"|经济性|电源工程投资{result['power_project_investment_100m_yuan']}亿元；"
        f"电网投资{result['grid_investment_100m_yuan']}亿元|描述官方报告的建设投入|"
        "价格、成本分项、资本寿命与产出；不能以投资额替代度电成本或收益|",
        f"|协调性|全国线路损失率{result['line_loss_pct']}%；6000千瓦及以上电厂利用小时"
        f"{result['utilization_hours_plants_ge_6000kw']}小时|提供网损及设备利用的部分观测|"
        "弃风弃光、储能能量、需求响应、跨区互济等，不给任意综合评分|",
        "", "## 与题给附件的联系", "",
        "四附件已形成890条逐行资产记录，详见outputs/attachments/report.md。用附件识别技术类型、"
        "项目差异和数据问题；全国容量采用官方全国表，绝不把附件容量加总外推。",
        "三峡项目容量及荒沟核准容量只作有日期的代表项目参照；核准容量不等于当年在运容量。",
        "", "## 版本冲突，单独保存", "",
        "下表比较已核验发布表与现有S05年鉴候选转录。年鉴原图尚未留存复核，"
        "表中差异尚不能全部归因于官方修订。此处只展示文件差异，不拼接历史校准。",
        "", "|指标|已核验发布表（万千瓦）|年鉴候选转录（万千瓦）|候选减发布表|", "|---|---:|---:|---:|"]
    lines += [f"|{labels.get(r['indicator'], '合计')}|{r['official_release_10k_kw']}|"
              f"{r['yearbook_candidate_10k_kw']}|{r['candidate_minus_release_10k_kw']:+}|" for r in comparison]
    lines += ["", "## 下一步", "",
              "优先取得2015—2024同口径能源消费与实际GDP原表、煤油气平衡及部门燃烧/非能源用途、"
              "热值与排放因子。电力各技术利用小时与容量需要相同统计范围和时点，"
              "不能用本表的全体利用小时直接给每类机组设容量因子。",
              "", "复现：运行scripts/build_verified_assessment.py。"
              "数据来源定位、留存文件和核验记录见data/sources.json、data/evidence_reviews.json。"]
    (out / "electricity_2024_partial.md").write_text("\n".join(lines)+"\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = build()
    print(json.dumps({key: result[key] for key in (
        "year", "wind_solar_capacity_share_pct", "hydro_nuclear_wind_solar_capacity_share_pct",
        "unallocated_capacity_10k_kw")}, ensure_ascii=False))
