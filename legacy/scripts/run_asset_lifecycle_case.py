"""Run the reviewed Qinshan attachment/permit case; no dispatch or national expansion."""
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from energy_model.asset_lifecycle import bind_attachments, iso, snapshot
from workflow_status import check_formal_inputs, check_hash, local_file, read_json, sha256

CONFIG = "workflow/asset_case.json"
EXPECTED_DATASET = "data/observations/qinshan_asset_permit_case.json"


def execute(root=ROOT):
    config = read_json(root / CONFIG)
    if config["dataset_path"] != EXPECTED_DATASET:
        raise ValueError("Asset-case dataset change requires an explicit interface review")
    admission = check_formal_inputs(root, [config["dataset_path"]])
    if not admission["passed"]:
        raise ValueError("Asset evidence admission failed: " + "; ".join(admission["errors"]))
    data = read_json(local_file(root, config["dataset_path"]))
    cutoff = iso(config["evidence_cutoff"])
    if cutoff > date.today():
        raise ValueError("Evidence cutoff cannot be in the future")
    attachments = read_json(check_hash(root, config["attachment_path"], config["attachment_sha256"]))
    originals = read_json(root / "workflow/provided_inputs.json")
    original = next(item for item in originals["inputs"] if item["path"] == "附件4.xlsx")
    check_hash(root, original["path"], original["sha256"])
    mapped = bind_attachments(data, attachments)
    # Bind derived rows back to the original hash, not just a matching plant name.
    sheets = {(s["source_file"], s["sheet"]): s for s in attachments["source_sheets"]}
    for row in mapped:
        if sheets[(row["source_file"], row["sheet"])]["source_sha256"].lower() != original["sha256"].lower():
            raise ValueError("Processed row and attachment original hash differ")
    dates = [f"{year}-12-31" for year in config["annual_years"]] + config["boundary_dates"]
    if len(dates) != len(set(dates)):
        raise ValueError("Duplicate report dates")
    snapshots, comparisons = [], []
    for as_of in sorted(dates):
        state = snapshot(data, as_of, evidence_cutoff=config["evidence_cutoff"])
        omitted = snapshot(data, as_of, evidence_cutoff=config["evidence_cutoff"],
                           disabled_event_ids=config["disabled_event_ids"])
        snapshots.append(state)
        comparisons.append({
            "as_of": as_of, "all_selected_events_counts": state["permit_counts"],
            "omitting_selected_extension_counts": omitted["permit_counts"],
            "changed_unit_ids": [a["unit_id"] for a, b in zip(state["units"], omitted["units"])
                                 if a["permit_status"] != b["permit_status"]],
            "interpretation": "event_omission_diagnostic_not_energy_or_policy_effect",
        })
    reviews = read_json(root / "data/evidence_reviews.json")["reviews"]
    review_ids = {r["review_id"] for r in admission["accepted_inputs"]}
    tracked = [CONFIG, config["dataset_path"], config["attachment_path"], original["path"],
               "workflow/provided_inputs.json", "workflow/model_inputs.json",
               "workflow/official_data_policy.md", "workflow/source_domains.json",
               "data/sources.json", "data/evidence_reviews.json",
               "scripts/run_asset_lifecycle_case.py", "scripts/workflow_status.py",
               "src/energy_model/asset_lifecycle.py"]
    tracked += [e["path"] for r in reviews if r["review_id"] in review_ids for e in r["evidence_files"]]
    provenance = {"bindings": admission["accepted_inputs"],
                  "sha256": {path: sha256(root / path) for path in sorted(set(tracked))}}
    run_id = hashlib.sha256(json.dumps(provenance, ensure_ascii=False,
                                      sort_keys=True).encode("utf-8")).hexdigest()[:16]
    result = {
        "run_id": run_id, "scope": config["scope"], "configuration": config,
        "attachment_bindings": mapped, "unit_count": len(data["units"]),
        "permit_event_count": len(data["permit_events"]),
        "snapshots": snapshots, "event_omission_comparisons": comparisons,
        "ready_for": ["selected_attachment_unit_identity", "documented_permit_event_replay"],
        "blocked_for": [
            "precise_operating_capacity_initialization", "commercial_commissioning_and_retirement",
            "dispatch", "economic_life_extension_decision", "national_abm_calibration"],
        "limitations": data["limitations"], "provenance": provenance,
    }
    destination = root / "outputs/asset_cases" / ("qinshan_" + run_id)
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if destination.exists():
        if (destination / "result.json").read_text(encoding="utf-8") != payload:
            raise ValueError("Same asset version already has a different result")
    else:
        destination.mkdir(parents=True)
        (destination / "result.json").write_text(payload, encoding="utf-8")
        lines = ["# 题给核电附件：真实许可事件回放", "", config["scope"], "",
                 "7台机组映射附件4的3条厂级记录；精确机组MW、商业投运及实际退役仍未知。",
                 "文件生成日作为信息可见起点是回放约定，未核实公众最早获知日。", "",
                 "|日期|所选文件期限内台数|已登记期限已过待核查|遗漏2021延续事件后的期限内台数|",
                 "|---|---:|---:|---:|"]
        for state, comparison in zip(snapshots, comparisons):
            counts = state["permit_counts"]
            lines.append(f"|{state['as_of']}|{counts.get('covered_by_recorded_end_date', 0)}|"
                         f"{counts.get('recorded_end_passed_needs_review', 0)}|"
                         f"{comparison['omitting_selected_extension_counts'].get('covered_by_recorded_end_date', 0)}|")
        lines += ["", "## 对题目模型的实际作用", "",
                  "许可延续事件能改变资产期限状态。设计寿命届满或已登记许可截止，均不自动产生实际退役。"
                  "2021年原许可截止至延续事件可见前保持待核查，不能据此推断停机或行政法律状态。",
                  "未来行只显示所收集文件的截止期限，不能当作退役、发电或政策效果预测。",
                  "未取得其他续证不等于不存在其他续证，本次不声称完成当前许可清单普查。", "",
                  "## 附件使用", "",
                  "|原记录|原名称|原容量数值|原单位|对应机组台数|",
                  "|---|---|---:|---|---:|"]
        for binding in mapped:
            lines.append(f"|{binding['record_id']}|{binding['original_name']}|"
                         f"{binding['original_capacity']}|未声明|{len(binding['unit_ids'])}|")
        lines += ["", "原容量不换算、不平均分摊、不设全国扩展权重。", "", "## 限制", ""]
        lines += ["- " + text for text in data["limitations"]]
        (destination / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    index = ["# 真实资产案例入口", "", "当前仅秦山基地7台机组许可记录，范围不扩大到全国。", "",
             f"版本：qinshan_{run_id}。",
             f"- [结果报告](qinshan_{run_id}/report.md)",
             f"- [逐机组、逐时点状态与追溯](qinshan_{run_id}/result.json)",
             "- [实现与数据边界](../../docs/16_asset_lifecycle_case.md)",
             "- [本轮审查](../data_review/review_assets_20261017.md)", "",
             "运行run_verified.ps1或scripts/run_asset_lifecycle_case.py可复现。"]
    (destination.parent / "index.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    try:
        result = execute()
        print(json.dumps({key: result[key] for key in
                          ("run_id", "unit_count", "permit_event_count", "blocked_for")}, ensure_ascii=False))
    except (OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        print("资产案例拒绝执行：" + str(exc), file=sys.stderr)
        sys.exit(1)
