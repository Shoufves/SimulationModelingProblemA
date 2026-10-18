"""Validate source data, derive indices, and evaluate historical baselines."""

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from energy_model.baselines import evaluate_baselines, fit_baselines


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def table_records(table: dict, known_sources: set[str]) -> list[dict]:
    columns = table["columns"]
    if columns[0] != "year" or len(set(columns)) != len(columns):
        raise ValueError("Table needs a unique year-first column schema")
    records, years = [], set()
    for row in table["rows"]:
        if len(row) != len(columns):
            raise ValueError("Row width differs from schema")
        year = row[0]
        if type(year) is not int or year in years:
            raise ValueError("Years must be unique integers")
        years.add(year)
        source_id = table.get("row_sources", {}).get(str(year), table.get("source_id"))
        locator = table.get("row_locators", {}).get(str(year), table.get("locator"))
        if source_id not in known_sources or not locator:
            raise ValueError(f"Missing source or locator for {year}")
        for value in row[1:]:
            if value is not None and (
                type(value) not in (int, float) or not math.isfinite(value)
            ):
                raise ValueError(f"Invalid numeric observation in {year}")
        records.append(dict(zip(columns, row), source_id=source_id, locator=locator))
    return sorted(records, key=lambda record: record["year"])


def audit_tables(tables: dict, records: dict) -> dict:
    checks, warnings = [], []

    def check(name: str, actual: float, expected: float, tolerance: float) -> None:
        checks.append({
            "name": name, "actual": actual, "expected": expected,
            "tolerance": tolerance, "passed": abs(actual - expected) <= tolerance,
        })

    for row in records["energy_consumption_2015_2024"]:
        check(
            f"energy_share_sum_{row['year']}",
            sum(row[key] for key in tables["energy_consumption_2015_2024"]["columns"][2:]),
            100, 0.21,
        )
    for row in records["power_capacity_2015_2024"]:
        components = ["thermal", "hydro", "nuclear", "wind", "solar", "other"]
        check(
            f"capacity_components_{row['year']}",
            sum(row[key] for key in components), row["total"], 4.0,
        )
    for row in records["power_generation_2015_2024"]:
        known = [row[key] for key in ("thermal", "hydro", "nuclear", "wind", "solar")]
        residual = row["total"] - sum(value for value in known if value is not None)
        check(f"generation_not_overallocated_{row['year']}", max(0, -residual), 0, 0.6)
        if any(value is None for value in known):
            warnings.append({
                "code": "UNALLOCATED_GENERATION", "year": row["year"],
                "residual_100m_kwh": residual,
                "message": "Missing solar remains null; residual is not assigned to solar",
            })
    for name in ("coal_balance_2015_2023", "petroleum_balance_selected_years"):
        for row in records[name]:
            expected = (
                row["production"] + row["imports"] - row["exports"]
                + row["inventory_change_opening_minus_closing"]
            )
            check(f"{name}_supply_{row['year']}", row["available_supply"], expected, 2.1)
            check(
                f"{name}_difference_{row['year']}",
                row["available_supply"] - row["consumption"],
                row["statistical_difference"], 2.1,
            )
            if name.startswith("coal") and row["washing_loss"] is not None:
                check(
                    f"coal_consumption_components_{row['year']}",
                    row["final_consumption"] + row["conversion_input"] + row["washing_loss"],
                    row["consumption"], 2.1,
                )
    summaries = {}
    for name, table in tables.items():
        table_rows = records[name]
        years = [row["year"] for row in table_rows]
        missing = [
            {"year": row["year"], "column": key}
            for row in table_rows for key in table["columns"][1:] if row[key] is None
        ]
        summaries[name] = {
            "years": years,
            "missing_years_2015_2024": sorted(set(range(2015, 2025)) - set(years)),
            "measurements": sum(
                row[key] is not None for row in table_rows for key in table["columns"][1:]
            ),
            "missing_cells": missing,
            "status": table["status"],
        }
        if "mixed" in table["status"] or "partial" in table["status"]:
            warnings.append({
                "code": "INCOMPLETE_OR_MIXED_VINTAGE", "table": name,
                "message": table["status"],
            })
    warnings.extend([
        {"code": "YEARBOOK_SNAPSHOTS_MISSING", "message": "Yearbook images are not archived; scoped official-page captures are reviewed separately in evidence_reviews.json"},
        {"code": "GDP_CHAIN_APPROXIMATION", "message": "Real GDP index chains growth rates rounded to 0.1 percentage point"},
        {"code": "NO_NATIONAL_CO2_FORECAST", "message": "Fuel combustion, process emissions and removals remain incomplete"},
    ])
    return {
        "passed": all(item["passed"] for item in checks),
        "checks": checks, "warnings": warnings, "tables": summaries,
    }


def derive_history(records: dict, anchors: dict) -> dict:
    energy = {row["year"]: row for row in records["energy_consumption_2015_2024"]}
    macro = {row["year"]: row for row in records["macro_growth_2015_2024"]}
    expected_years = set(range(2015, 2025))
    if set(energy) != expected_years or set(macro) != expected_years:
        raise ValueError("Energy and GDP must both cover every year from 2015 to 2024")
    rows, gdp = [], 100.0
    energy_base = energy[2015]["total_energy_consumption"]
    for year in range(2015, 2025):
        if year > 2015:
            gdp *= 1 + macro[year]["real_gdp_growth_pct"] / 100
        total = energy[year]["total_energy_consumption"]
        rows.append({
            "year": year, "energy_mtce": total * 0.01,
            "energy_index_2015": total / energy_base * 100,
            "real_gdp_index_2015": gdp,
            "energy_intensity_index_2015": total / energy_base / (gdp / 100) * 100,
            "source_ids": [energy[year]["source_id"], macro[year]["source_id"]],
            "derivation": "energy: 10000 tce * 0.01; GDP: chained real growth; intensity: E_index/GDP_index*100",
        })
    observations = {row["indicator_id"]: row for row in anchors["observations"]}
    total_2025 = observations["total_energy_consumption"]
    growth_2025 = observations.get("real_gdp_growth_pct")
    if total_2025["value"] is not None and growth_2025 and growth_2025["value"] is not None:
        gdp *= 1 + growth_2025["value"] / 100
        total_mtce = total_2025["value"] * 100
        rows.append({
            "year": 2025, "energy_mtce": total_mtce,
            "energy_index_2015": total_mtce / rows[0]["energy_mtce"] * 100,
            "real_gdp_index_2015": gdp,
            "energy_intensity_index_2015": total_mtce / rows[0]["energy_mtce"] / (gdp / 100) * 100,
            "source_ids": [total_2025["source_id"], growth_2025["source_id"]],
            "derivation": "Separate 2025 communique check; 100 million tce * 100; no refitting",
        })
    return {
        "status": "derived_indices_not_official_constant_price_GDP",
        "rows": rows,
        "notes": [
            "Intensity covers total energy/GDP, not the official adjusted energy-intensity target.",
            "2025 preliminary observations are a separately labeled check, not a revised historical yearbook row.",
        ],
    }


def derive_power_history(records: dict) -> dict:
    capacity = {row["year"]: row for row in records["power_capacity_2015_2024"]}
    generation = {row["year"]: row for row in records["power_generation_2015_2024"]}
    rows = []
    for year in sorted(capacity.keys() & generation.keys()):
        cap, gen = capacity[year], generation[year]
        known_generation = sum(
            gen[key] for key in ("thermal", "hydro", "nuclear", "wind", "solar")
            if gen[key] is not None
        )
        rows.append({
            "year": year,
            "year_end_capacity_gw": {
                key: cap[key] * 0.01
                for key in ("total", "thermal", "hydro", "nuclear", "wind", "solar", "other")
            },
            "generation_twh": {
                key: gen[key] * 0.1 if gen[key] is not None else None
                for key in ("total", "thermal", "hydro", "nuclear", "wind", "solar")
            },
            "unallocated_generation_or_rounding_twh": (gen["total"] - known_generation) * 0.1,
            "source_ids": {"capacity": cap["source_id"], "generation": gen["source_id"]},
            "derivation": "10000 kW * 0.01 = GW; 100 million kWh * 0.1 = TWh",
        })
    return {
        "status": "unit_normalized_mixed_generation_vintages_pending_alignment",
        "rows": rows,
        "notes": [
            "No capacity factors are calculated from year-end capacity.",
            "Missing solar remains null; unallocated generation is not a solar estimate.",
        ],
    }


def render_plots(history: dict, baselines: dict, output: Path) -> list[str]:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return []
    rows = history["rows"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.6), layout="constrained")
    for key, label, color in [
        ("real_gdp_index_2015", "Real GDP (chained)", "#176B87"),
        ("energy_index_2015", "Energy consumption", "#D46B35"),
        ("energy_intensity_index_2015", "Energy / real GDP", "#387A43"),
    ]:
        axes[0].plot([row["year"] for row in rows], [row[key] for row in rows],
                     label=label, color=color, linewidth=2)
    axes[0].set(title="Historical indices", ylabel="2015 = 100", xlabel="Year")
    axes[0].legend(fontsize=8)
    axes[1].plot([row["year"] for row in rows], [row["energy_mtce"] for row in rows],
                 color="#222222", linewidth=2.5, marker="o", label="Observed")
    labels = {
        "constant_intensity": "Constant intensity", "energy_time_trend": "Energy trend",
        "gdp_elasticity": "GDP elasticity", "intensity_time_trend": "Intensity trend",
    }
    test = baselines["rows"] + baselines.get("independent_check", {}).get("rows", [])
    for name, label in labels.items():
        axes[1].plot([2021] + [row["year"] for row in test],
                     [baselines["fitted"]["anchor_energy_mtce"]]
                     + [row["predictions_mtce"][name] for row in test],
                     label=label, linewidth=1.5)
    axes[1].axvline(2021.5, color="#666666", linestyle=":", linewidth=1)
    axes[1].set(title="Conditional hindcast (observed GDP)",
                ylabel="Energy consumption (Mtce)", xlabel="Year")
    axes[1].legend(fontsize=8)
    for ax in axes:
        ax.grid(axis="y", alpha=0.2)
        ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(output / "history_and_baselines.png", dpi=180)
    plt.close(fig)
    return ["history_and_baselines.png"]


def make_report(audit: dict, history: dict, baselines: dict, figures: list[str]) -> str:
    rows = history["rows"]
    latest_yearbook = next(row for row in rows if row["year"] == 2024)
    n_checks = len(audit["checks"])
    lines = [
        "# 数据底座与历史基线检验", "",
        "生成依据：候选历史表、2025锚点及来源登记。结果可由`run_analysis.ps1`重新生成。"
        "本工具不作正式证据准入；最新完整目录见outputs/data_review/catalog.md，"
        "已核验单年初评见outputs/current_assessment/。", "",
        "## 本轮状态", "",
        f"- 已执行{n_checks}项内部一致性检查，通过{sum(c['passed'] for c in audit['checks'])}项。",
        "- 通过内部检查不等于已通过独立来源复核。",
        "- 已实现数据整理、需求统计基线和物理核算函数，尚未实现校准后的多智能体系统。",
        "- 当前不发布2030/2060预测或全国碳中和结论。", "",
        "## 数据覆盖", "",
        "| 数据表 | 已录年份 | 数值观测数（不含年份） | 2015—2024缺年 |",
        "| --- | --- | ---: | --- |",
    ]
    for name, table in audit["tables"].items():
        years = ",".join(str(year) for year in table["years"])
        missing = ",".join(str(year) for year in table["missing_years_2015_2024"]) or "无"
        lines.append(f"| {name} | {years} | {table['measurements']} | {missing} |")
    lines.extend([
        "", "## 可确认的派生描述", "",
        f"以2015年为100，2024年实际GDP链接指数为{latest_yearbook['real_gdp_index_2015']:.2f}，"
        f"能源消费指数为{latest_yearbook['energy_index_2015']:.2f}，"
        f"总能源强度指数为{latest_yearbook['energy_intensity_index_2015']:.2f}。",
        "GDP由一位小数的实际增长率链接，存在舍入误差；总能源强度与扣除原料用能、非化石消费后的官方指标不同。",
        "", "## 历史基线检验", "",
        "所有拟合只使用2015—2021年。2022—2024是历史留出检验；2025如有数据则独立列出。"
        "GDP相关方法使用留出年份实际GDP，属于条件回算，并非完整的事前预测。",
        "", "| 方法 | 2022—2024 MAPE | 2025绝对百分比误差 |",
        "| --- | ---: | ---: |",
    ])
    holdout_rows = [row for row in baselines["rows"] if row["year"] <= 2024]
    for name in baselines["metrics"]:
        mape = sum(
            abs(row["predictions_mtce"][name] / row["actual_energy_mtce"] - 1) * 100
            for row in holdout_rows
        ) / len(holdout_rows)
        row_2025 = next((
            row for row in baselines.get("independent_check", {}).get("rows", [])
            if row["year"] == 2025
        ), None)
        error = (
            f"{abs(row_2025['predictions_mtce'][name] / row_2025['actual_energy_mtce'] - 1) * 100:.2f}%"
            if row_2025 else "未提供"
        )
        lines.append(f"| {name} | {mape:.2f}% | {error} |")
    lines.extend([
        "", "这些方法用于给后续模型设定对照基线，不能解释政策作用，不能据此直接外推2060。"
        "本次未按留出结果选取或重新调整参数；模型开发后应另设最终检验。",
        "", "## 仍待解决", "",
        "- 发电量存在跨年鉴版本；2015—2023太阳能未单列，剩余量保留未分配。",
        "- 煤炭历史统计存在口径调整；石油与煤炭平衡表目前只能做分年核查，禁止直接作为连续校准序列。",
        "- 天然气平衡、终端部门需求、非能源原料、成本、排放因子、资产年龄及工期未补齐。",
        "- 年鉴原图尚无本地快照；S13、S17等已留存的官方网页子集按独立审查使用，不据此批准历史序列。",
        "", "## 下一阶段", "",
        "先锁定燃料统计桥接，补齐终端需求与排放因子，建立分载体能量账本；"
        "随后实现需求主体与投资主体，再开展多指标历史验证。",
    ])
    if figures:
        lines.extend(["", "## 图表", "", f"![历史指数和基线检验]({figures[0]})"])
    else:
        lines.extend(["", "本次未生成图表：运行环境未启用matplotlib，或指定了--no-plots。数值计算使用标准库。"])
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-plots", action="store_true")
    args = parser.parse_args()
    output = ROOT / "outputs" / "foundation"
    output.mkdir(parents=True, exist_ok=True)
    sources = read_json(ROOT / "data" / "sources.json")
    source_ids = [source["source_id"] for source in sources["sources"]]
    if len(set(source_ids)) != len(source_ids):
        raise ValueError("Source IDs must be unique")
    tables, records, hashes = {}, {}, {}
    for path in sorted((ROOT / "data" / "observations").glob("*.json")):
        data = read_json(path)
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        if "columns" in data:
            tables[path.stem] = data
            records[path.stem] = table_records(data, set(source_ids))
    anchors = read_json(ROOT / "data" / "observations" / "anchors_2025.json")
    anchor_ids = set()
    for row in anchors["observations"]:
        if row["indicator_id"] in anchor_ids:
            raise ValueError("Duplicate anchor indicator")
        anchor_ids.add(row["indicator_id"])
        if row["value"] is not None:
            source_id = row.get("source_id", anchors["default_source_id"])
            if source_id not in source_ids or not row.get("locator"):
                raise ValueError("Anchor source or locator is missing")
            if not math.isfinite(row["value"]):
                raise ValueError("Nonfinite anchor value")
    audit = audit_tables(tables, records)
    audit["observation_file_sha256"] = hashes
    audit["sources_sha256"] = hashlib.sha256(
        (ROOT / "data" / "sources.json").read_bytes()
    ).hexdigest()
    write_json(output / "data_audit.json", audit)
    if not audit["passed"]:
        failures = [row["name"] for row in audit["checks"] if not row["passed"]]
        raise ValueError(f"Data checks failed; inspect audit: {failures}")
    history = derive_history(records, anchors)
    fitted = fit_baselines(history["rows"])
    baselines = evaluate_baselines(
        [row for row in history["rows"] if row["year"] <= 2024], fitted
    )
    baselines["fitted"] = fitted
    baselines["holdout_years"] = [2022, 2023, 2024]
    independent_rows = [row for row in history["rows"] if row["year"] == 2025]
    baselines["independent_check_years"] = [row["year"] for row in independent_rows]
    if independent_rows:
        baselines["independent_check"] = evaluate_baselines(independent_rows, fitted)
    write_json(output / "historical_indices.json", history)
    write_json(output / "power_history.json", derive_power_history(records))
    write_json(output / "demand_baselines.json", baselines)
    figures = [] if args.no_plots else render_plots(history, baselines, output)
    (output / "report.md").write_text(
        make_report(audit, history, baselines, figures), encoding="utf-8"
    )
    print(json.dumps({
        "internal_checks": len(audit["checks"]),
        "all_checks_passed": audit["passed"],
        "table_measurements": sum(item["measurements"] for item in audit["tables"].values()),
        "anchor_measurements": sum(row["value"] is not None for row in anchors["observations"]),
        "figures": figures,
        "report": str(output / "report.md"),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
