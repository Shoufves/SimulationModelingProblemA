"""Evidence-gated execution of existing demand baselines; never admits data."""
import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from build_foundation import derive_history, table_records
from energy_model.baselines import evaluate_baselines, fit_baselines, predict_baselines
from workflow_status import check_formal_inputs, local_file, read_json, sha256

CONFIG = "workflow/demand_hindcast.json"
METHODS = ["constant_intensity", "energy_time_trend", "gdp_elasticity", "intensity_time_trend"]
DATASETS = {
    "energy_dataset": ("data/observations/demand_energy_total_2015_2024.json", "S01"),
    "macro_dataset": ("data/observations/demand_real_gdp_growth_2015_2024.json", "S06"),
}


def dataset_bindings(root, config):
    """Explicit configured paths and sources, still subject to independent admission."""
    bindings = {}
    for key, (_, default_source) in DATASETS.items():
        path = config[key]
        if not isinstance(path, str) or not path.startswith("data/observations/"):
            raise ValueError("输入须明确声明在观测目录中的数据集")
        local_file(root, path)
        sid = config.get("required_source_ids", {}).get(key, default_source)
        if not isinstance(sid, str) or not sid:
            raise ValueError("配置须声明来源ID")
        bindings[key] = (path, sid)
    return bindings


def inspect_inputs(root):
    config = read_json(root / CONFIG)
    # This entry point has a fixed research scope. A changed design needs review.
    if (config["train_years"] != list(range(2015, 2022))
            or config["evaluation_years"] != [2022, 2023, 2024]
            or config["methods"] != METHODS):
        raise ValueError("训练/评估年份或方法变动：须先审查研究方案及本入口")
    datasets = dataset_bindings(root, config)
    formal = check_formal_inputs(root, {path for path, _ in datasets.values()})
    errors = list(formal["errors"])
    accepted = {item["dataset_path"]: item for item in formal["accepted_inputs"]}
    bindings = []
    for key, (expected_path, sid) in datasets.items():
        if expected_path not in accepted:
            errors.append(f"{expected_path}：尚无匹配的正式输入及有效证据审查")
            continue
        binding = accepted[expected_path]
        if binding["source_ids"] != [sid]:
            errors.append(f"{expected_path}：来源版本不符合方案")
        bindings.append(binding)
    return config, {
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "ready_for": ["四种总量需求基线的条件回算"] if not errors else [],
        "blocked_for": errors,
        "accepted_bindings": bindings,
        "not_covered": ["全国ABM校准", "部门需求替代", "CO2与中和率", "正式情景"],
        "formal_check_limitation": formal["limitation"],
    }


def load_history(root, config):
    records = {}
    for key, (expected_path, sid) in dataset_bindings(root, config).items():
        table = read_json(root / expected_path)
        if table.get("source_id") != sid:
            raise ValueError("历史表来源版本发生变化")
        if key == "energy_dataset":
            if table.get("total_unit") != "万吨标准煤":
                raise ValueError("消费总量原单位必须是万吨标准煤")
            required = "total_energy_consumption"
            name = "energy_consumption_2015_2024"
        else:
            if table.get("unit") != "%":
                raise ValueError("宏观增速原单位必须是%")
            required = "real_gdp_growth_pct"
            name = "macro_growth_2015_2024"
        rows = table_records(table, {sid})
        if set(row["year"] for row in rows) != set(range(2015, 2025)):
            raise ValueError("历史表须完整覆盖2015—2024且不含额外年份")
        for row in rows:
            value = row.get(required)
            if type(value) not in (int, float):
                raise ValueError(f"{required}存在缺失")
            if key == "energy_dataset" and value <= 0:
                raise ValueError("能源总量必须为正")
            if key == "macro_dataset" and value <= -100:
                raise ValueError("GDP增长率必须大于-100%")
        records[name] = rows
    # Deliberately excludes unapproved 2025 anchors.
    return derive_history(records, {"observations": [
        {"indicator_id": "total_energy_consumption", "value": None}
    ]})["rows"]


def calculate(history, config):
    if [row["year"] for row in history] != list(range(2015, 2025)):
        raise ValueError("派生历史年份不符")
    fitted = fit_baselines(history, train_end=config["train_years"][-1])
    evaluation = evaluate_baselines(history, fitted)
    training = []
    for row in history:
        if row["year"] > fitted["anchor_year"]:
            continue
        predictions = predict_baselines(
            fitted, row["year"], row["real_gdp_index_2015"], allow_in_sample=True)
        training.append({
            "year": row["year"], "actual_energy_mtce": row["energy_mtce"],
            "predictions_mtce": predictions,
        })
    for row in training + evaluation["rows"]:
        actual = row["actual_energy_mtce"]
        row["errors"] = {
            method: {
                "signed_mtce": predicted - actual,
                "absolute_mtce": abs(predicted - actual),
                "absolute_pct": abs(predicted - actual) / actual * 100,
            } for method, predicted in row["predictions_mtce"].items()
        }
    return {
        "scope": config["scope"], "evaluation_status": config["evaluation_status"],
        "configuration": config, "historical_indices": history,
        "fitted": fitted, "training_rows": training, "evaluation": evaluation,
        "limitations": [
            config["limitation"], config["exogenous"],
            "增长率仅一位小数，GDP为近似链接指数；不同口径能耗增长率不强制配平。",
            "仅统计总量映射，无新增主体机制；不支持政策因果、全国排放或远期预测。",
        ],
    }


def execute(root, check_only=False):
    config, readiness = inspect_inputs(root)
    history = None
    if not readiness["blocked_for"]:
        try:
            history = load_history(root, config)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            readiness["ready_for"] = []
            readiness["blocked_for"].append(f"字段/单位/年份检查未通过：{exc}")
    # Readiness is an audit artifact, never a calibration result.
    review_dir = root / "outputs/data_review"
    review_dir.mkdir(parents=True, exist_ok=True)
    (review_dir / "demand_readiness.json").write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if readiness["blocked_for"]:
        return 2, readiness
    if check_only:
        return 0, readiness
    result = calculate(history, config)
    tracked = [CONFIG, "data/sources.json", "data/evidence_reviews.json",
               "workflow/model_inputs.json", "scripts/run_demand_hindcast.py",
               "scripts/build_foundation.py", "scripts/workflow_status.py",
               "src/energy_model/baselines.py", "workflow/official_data_policy.md"]
    tracked += [value[0] for value in dataset_bindings(root, config).values()]
    reviews = read_json(root / "data/evidence_reviews.json")["reviews"]
    used_ids = {item["review_id"] for item in readiness["accepted_bindings"]}
    tracked += [e["path"] for r in reviews if r["review_id"] in used_ids
                for e in r["evidence_files"]]
    provenance = {
        "bindings": readiness["accepted_bindings"],
        "sha256": {path: sha256(root / path) for path in sorted(set(tracked))},
    }
    run_id = hashlib.sha256(json.dumps(
        provenance, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    result["provenance"] = provenance
    result["run_id"] = run_id
    # Created only after evidence checks, schema validation and actual calculation.
    destination = root / "outputs/calibration" / ("demand_" + run_id)
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if destination.exists():
        if (destination / "result.json").read_text(encoding="utf-8") != payload:
            raise ValueError("同一输入版本已有不同结果，禁止覆盖")
        return 0, {"run_id": run_id, "result": str(destination / "result.json")}
    destination.mkdir(parents=True)
    (destination / "result.json").write_text(payload, encoding="utf-8")
    lines = ["# 总能源需求条件回算", "", config["scope"], "",
             config["evaluation_status"] + "。评估期使用已实现GDP。", "",
             "|方法|评估MAPE %|RMSE Mtce|平均有符号误差 Mtce|",
             "|---|---:|---:|---:|"]
    for method, metric in result["evaluation"]["metrics"].items():
        lines.append(f"|{method}|{metric['mape_pct']:.4f}|{metric['rmse_mtce']:.4f}|"
                     f"{metric['mean_signed_error_mtce']:.4f}|")
    lines += ["", "逐年观测、模拟、误差、训练参数和证据哈希见result.json。",
              "四种方法全部报告，不根据留出结果选取最优方法。", ""]
    labels = {"constant_intensity": "强度冻结", "energy_time_trend": "能源时间趋势",
              "gdp_elasticity": "GDP弹性", "intensity_time_trend": "强度时间趋势"}
    lines += ["## 留出期逐年结果", "", "单位Mtce（百万吨标准煤）；误差为模拟减观测。",
              "", "|年份|方法|实际|模拟|有符号误差|绝对百分比误差（%）|",
              "|---|---|---:|---:|---:|---:|"]
    for row in result["evaluation"]["rows"]:
        for method in METHODS:
            error = row["errors"][method]
            lines.append(f"|{row['year']}|{labels[method]}|{row['actual_energy_mtce']:.2f}|"
                         f"{row['predictions_mtce'][method]:.2f}|{error['signed_mtce']:+.2f}|"
                         f"{error['absolute_pct']:.4f}|")
    lines += ["", "## 可以判断与仍不能判断", "",
              "本次实际检验的是给定已实现GDP的全国总能源统计映射，"
              "可作为后续主体机制的同窗口比较基线。十年样本、七年训练和三年评估"
              "不足以识别复杂主体行为；2022—2024已经接触，不是盲测。",
              "能源与GDP采用2025年鉴发布序列，原图在线核读、文字摘录本地留存；"
              "原图二进制和截图未归档，离线视觉复核能力受限。"
              "原候选整表、部门设备、燃料与CO2没有因此获得准入。",
              "", "## 限制", ""]
    lines += ["- " + value for value in result["limitations"]]
    (destination / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0, {"run_id": run_id, "result": str(destination / "result.json")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        status, report = execute(ROOT, args.check_only)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return status
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"需求回算停止：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
