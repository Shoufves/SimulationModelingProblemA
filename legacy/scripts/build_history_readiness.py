"""Separate pending evidence, mixed vintages and genuinely missing observations."""
import json
from collections import Counter
from pathlib import Path

from workflow_status import check_formal_inputs, read_json, sha256, source_ids

ROOT = Path(__file__).resolve().parents[1]
YEARS = set(range(2015, 2025))
TABLES = [
    ("energy_consumption_2015_2024", "能源消费总量与结构"),
    ("macro_growth_2015_2024", "实际GDP/能源/电力增速"),
    ("power_capacity_2015_2024", "分电源年末装机"),
    ("power_generation_2015_2024", "分电源发电量"),
    ("coal_balance_2015_2023", "煤炭平衡"),
    ("petroleum_balance_selected_years", "石油平衡"),
    ("fuel_production_2023_2024", "煤油气实物产量"),
]


def classify(data, admitted=False, historical_scope_reviewed=False):
    columns = data["columns"]
    if not columns or columns[0] != "year" or len(set(columns)) != len(columns):
        raise ValueError("Expected unique year-first columns")
    rows = data["rows"]
    if any(len(row) != len(columns) or type(row[0]) is not int for row in rows):
        raise ValueError("Invalid table row")
    years = [row[0] for row in rows]
    if len(set(years)) != len(years):
        raise ValueError("Duplicate year")
    missing_years = sorted(YEARS - set(years))
    missing_cells = [{"year": row[0], "column": columns[i]}
                     for row in rows for i in range(1, len(columns)) if row[i] is None]
    sources = sorted(source_ids(data))
    issues = []
    if not admitted:
        issues.append("evidence_review_pending")
    if len(sources) > 1:
        issues.append("mixed_sources_need_scope_revision_bridge")
    if missing_years or missing_cells:
        issues.append("observations_missing")
    return {"recorded_years": sorted(years), "missing_years": missing_years,
            "missing_cells": missing_cells, "source_ids": sources, "issues": issues,
            "all_ten_year_rows_present": not missing_years,
            "all_recorded_cells_present": not missing_cells,
            "whole_dataset_admitted": admitted,
            "historical_scope_reviewed": historical_scope_reviewed,
            "continuous_calibration_ready": admitted and historical_scope_reviewed and
                not missing_years and not missing_cells}


def build(root=ROOT):
    admission = check_formal_inputs(root)
    accepted = {item["dataset_path"] for item in admission["accepted_inputs"]}
    demand_subsets = {
        "data/observations/demand_energy_total_2015_2024.json",
        "data/observations/demand_real_gdp_growth_2015_2024.json",
    }
    comparison_inputs = {
        "data/observations/energy_official_communique_2024.json",
        "data/observations/gas_official_report_2024.json",
    }
    if not admission["passed"] or not comparison_inputs.issubset(accepted):
        raise ValueError("Reviewed single-year comparison inputs failed evidence admission")
    inventory = []
    datasets = {}
    for name, label in TABLES:
        relative = f"data/observations/{name}.json"
        data = read_json(root / relative)
        datasets[name] = data
        inventory.append({"path": relative, "label": label, "sha256": sha256(root / relative),
                          **classify(data, relative in accepted)})

    verified_path = "data/observations/energy_official_communique_2024.json"
    official = {r["indicator_id"]: r["value"] for r in read_json(root / verified_path)["observations"]}
    bridge = []
    for name, field, official_field, factor in (
        ("energy_consumption_2015_2024", "total_energy_consumption", "total_energy_consumption", 1 / 10000),
        ("energy_consumption_2015_2024", "coal_share", "coal_consumption_share_pct", 1),
        ("macro_growth_2015_2024", "real_gdp_growth_pct", "real_gdp_growth_pct", 1),
        ("macro_growth_2015_2024", "energy_consumption_growth_pct", "total_energy_consumption_growth_pct", 1),
        ("macro_growth_2015_2024", "electricity_consumption_growth_pct", "electricity_consumption_growth_pct", 1),
    ):
        data = datasets[name]
        row = dict(zip(data["columns"], next(r for r in data["rows"] if r[0] == 2024)))
        normalized = row[field] * factor
        bridge.append({"candidate_path": f"data/observations/{name}.json", "year": 2024,
                       "candidate_field": field, "conversion_factor": factor,
                       "candidate_normalized": normalized, "reviewed_dataset": verified_path,
                       "reviewed_field": official_field, "reviewed_value": official[official_field],
                       "difference": normalized - official[official_field],
                       "status": "single_value_match_only_not_historical_admission"})
    for field in ("total", "thermal", "hydro", "nuclear", "wind", "solar"):
        data = datasets["power_generation_2015_2024"]
        row = dict(zip(data["columns"], next(r for r in data["rows"] if r[0] == 2024)))
        bridge.append({"candidate_path": "data/observations/power_generation_2015_2024.json",
                       "year": 2024, "candidate_field": field, "candidate_normalized": row[field],
                       "conversion_factor": 1, "reviewed_dataset": verified_path,
                       "reviewed_field": "generation_" + field,
                       "reviewed_value": official["generation_" + field],
                       "difference": row[field] - official["generation_" + field],
                       "status": "single_row_match_only_not_historical_admission"})
    gas_path = "data/observations/gas_official_report_2024.json"
    gas_year = read_json(root / gas_path)["year"]
    absent = [
        {"family": "天然气供需/部门完整历史", "recorded_years_in_current_report": [gas_year],
         "missing_years_2015_2024": sorted(YEARS - {gas_year}),
         "note": "2024仅报告/快报横截面，出口、库存和部门绝对量仍缺；并非完整平衡表"},
        {"family": "部门终端燃烧/原料用能、热值/排放因子、成本设备寿命",
         "recorded_years_in_current_model_input": [],
         "note": "现有资料不能构成所需输入；逐字段补齐，不能借总消费十年覆盖替代"},
    ]
    result = {
        "window": "2015-2024", "formal_input_check_passed": admission["passed"],
        "tables": inventory, "single_year_matches": bridge, "genuinely_incomplete_families": absent,
        "input_sha256": {verified_path: sha256(root / verified_path), gas_path: sha256(root / gas_path)},
        "note": "转录来自同版不等于已核验；单年数值相同不等于历史范围/修订桥接完成。此检查不批准数据。",
        "counts": {"complete_rows_and_cells_single_source_tables": sum(
            row["all_ten_year_rows_present"] and row["all_recorded_cells_present"] and len(row["source_ids"]) == 1
            for row in inventory),
            "tables_missing_years": sum(bool(row["missing_years"]) for row in inventory),
            "tables_with_mixed_sources": sum(len(row["source_ids"]) > 1 for row in inventory)},
        "minimal_demand_subsets_admitted": demand_subsets.issubset(accepted),
        "minimal_demand_scope": "仅总能源10值和GDP增速10值；不批准原完整结构/宏观表",
    }
    out = root / "outputs/data_review"
    out.mkdir(parents=True, exist_ok=True)
    (out / "history_readiness.json").write_text(json.dumps(
        result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 十年历史：已转录、待核验与实际缺项", "",
        "窗口：2015—2024。此前笼统称“缺同口径十年历史”不准确。"
        "三张同版年鉴表的十年行及数值已录齐；其主要任务是补证据和复核，不能重复采集十年数字。"
        "跨版平衡表和部门数据另有真实缺口。以下依据本地表逐行统计，不作新官方事实认定。",
        "", "最小需求子集：" + (
            "总能源10值和实际GDP增速10值已分别准入，可运行条件回算；原图在线核读、"
            "人工文字摘录留存，原图/截图未本地归档。原80值整表仍为候选。"
            if result["minimal_demand_subsets_admitted"] else "尚未全部准入。"),
        "", "|资料|已录年份|真正缺年|空值字段|来源|当前工作|", "|---|---|---|---|---|---|",
    ]
    for row in inventory:
        years = row["recorded_years"]
        missing = "、".join(map(str, row["missing_years"])) or "无"
        fields = Counter(cell["column"] for cell in row["missing_cells"])
        blank = "、".join(f"{key}×{n}" for key, n in fields.items()) or "无"
        tasks = ["证据复核"] if not row["whole_dataset_admitted"] else []
        if len(row["source_ids"]) > 1:
            tasks.append("跨版/范围桥接")
        if row["missing_years"] or row["missing_cells"]:
            tasks.append("补实际缺项")
        lines.append(f"|{row['label']}|{','.join(map(str, years))}|{missing}|{blank}|"
                     f"{','.join(row['source_ids'])}|{'；'.join(tasks)}|")
    lines += [
        "", "煤炭washing_loss空白不能填0；旧年太阳能不能用总量残差冒充。"
        "“同版”只是现有转录的来源登记，尚未得到完整原表复核，不能直接宣布校准可用。",
        "", "## 可先确认的2024文件一致性", "",
        "下列候选字段与已核验S13子集逐值比较；能源总量从万吨标准煤除以10000转成亿吨标准煤。"
        "这能缩小需要检查的范围，但不批准整张历史表；发电旧年仍有不同来源和太阳能缺失。",
        "", "|候选文件/字段|换单位后候选值|已核验2024值|差值|", "|---|---:|---:|---:|",
    ]
    for row in bridge:
        lines.append(f"|{Path(row['candidate_path']).stem}/{row['candidate_field']}|"
                     f"{row['candidate_normalized']:.12g}|{row['reviewed_value']:.12g}|{row['difference']:.8g}|")
    lines += [
        "", "装机S05年鉴转录与S17发布版本不同，见electricity_2024_partial.md的版本比较；"
        "不得按其中一个版本覆盖另一个。上述相同值也可能来自相同底层发布，不称为独立双来源。",
        "", "## 确实尚缺的历史", "",
        "天然气当前报告只覆盖2024横截面，2015—2023未形成完整历史，2024本身也缺出口/库存等。"
        "部门终端燃烧/原料、热值/因子和技术成本设备输入另立缺口，不能借总量十年覆盖掩盖。",
        "", "## 执行顺序与并行边界", "",
        "1. 两个最小需求子集的准入另见正式清单；继续核验整表其余字段与装机，不重复采集已录数字。",
        "2. 仅对确缺年份/分项补数，跨版数据建立桥接表，不拼成伪同口径序列。",
        "3. 主体代码与合成机制验证可同步进行，不等待全部数据；正式校准只使用相应用途已准入数据。",
        "4. 原表图片网络受阻时寻找可访问的同版官方正文/数据发布，失败保留状态，不重复无效下载。",
        "", "更新：运行scripts/build_history_readiness.py或run_verified.ps1。"
        "不修改任何观测值或证据准入状态。",
    ]
    (out / "history_readiness.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = build()
    print(json.dumps(result["counts"], ensure_ascii=False))
