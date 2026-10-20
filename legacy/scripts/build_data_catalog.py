"""Generate a data index without relocating evidence or approving observations."""
import json
from datetime import datetime
from pathlib import Path

from workflow_status import check_formal_inputs, measurements, read_json, sha256, source_ids

ROOT = Path(__file__).resolve().parents[1]


def build(root=ROOT):
    admission = check_formal_inputs(root)
    accepted = {item["dataset_path"]: item for item in admission["accepted_inputs"]}
    reviews = {item["review_id"]: item for item in read_json(root / "data/evidence_reviews.json")["reviews"]}
    entries = []
    for path in sorted((root / "data/observations").glob("*.json")):
        relative = path.relative_to(root).as_posix()
        data = read_json(path)
        registration = accepted.get(relative)
        review = reviews[registration["review_id"]] if registration else None
        years = ([row[data["columns"].index("year")] for row in data["rows"]]
                 if "rows" in data and "year" in data["columns"]
                 else [data.get("year")])
        years = sorted({year for year in years if year is not None})
        entries.append({
            "path": relative, "sha256": sha256(path), "measurements": measurements(data),
            "years": years, "source_ids": sorted(source_ids(data)),
            "admission": "reviewed_scoped_subset" if review else "candidate_not_admitted",
            "review_id": review["review_id"] if review else None,
            "restriction": review.get("usage_restriction") if review else "仅探索；未获正式证据准入",
            "evidence_paths": [e["path"] for e in review["evidence_files"]] if review else [],
        })
    result = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "formal_input_check_passed": admission["passed"], "errors": admission["errors"],
        "datasets": entries,
        "total_measurements": sum(r["measurements"] for r in entries),
        "scoped_reviewed_measurements": sum(r["measurements"] for r in entries
                                            if r["admission"] == "reviewed_scoped_subset"),
        "note": "数值单元计数，跨文件可能重复，不是独立样本数。准入限登记用途，不代表全国模型数据齐备。",
    }
    out = root / "outputs/data_review"
    out.mkdir(parents=True, exist_ok=True)
    (out / "catalog.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# 观测数据目录", "", f"生成时间：{result['generated_at']}", "",
             f"共{len(entries)}个文件、{result['total_measurements']}个数值单元；"
             f"其中{result['scoped_reviewed_measurements']}个在注明范围内通过证据检查。", "",
             result["note"], "",
             "候选和已核验文件保留在同一观测目录，通过正式清单与本表识别，避免移动文件破坏路径及哈希。"
             "正式清单为workflow/model_inputs.json，核验依据为data/evidence_reviews.json。", "",
             "|文件|年份|数值单元|来源|准入状态|", "|---|---|---:|---|---|"]
    for row in entries:
        years = row["years"]
        span = str(years[0]) if len(years) == 1 else ", ".join(str(y) for y in years)
        status = "限定用途已核验" if row["review_id"] else "候选，未准入"
        lines.append(f"|[{Path(row['path']).name}](../../{row['path']})|{span}|"
                     f"{row['measurements']}|{', '.join(row['source_ids'])}|{status}|")
    lines += ["", "## 已核验子集的使用限制", ""]
    for row in entries:
        if row["review_id"]:
            lines += [f"- {Path(row['path']).name}：{row['restriction']}；"
                      f"审查{row['review_id']}，证据{'、'.join(row['evidence_paths'])}。"]
    if not admission["passed"]:
        lines += ["", "## 当前证据检查错误", ""]
        lines += ["- " + error for error in admission["errors"]]
    lines += ["", "题给附件标准表另见data/processed/attachment_assets.json及outputs/attachments/report.md；"
              "不计入上述官方观测单元，不能当全国总体。", "",
              "更新目录：运行scripts/build_data_catalog.py或run_verified.ps1。"]
    (out / "catalog.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    catalog = build()
    print(json.dumps({key: catalog[key] for key in
                      ("total_measurements", "scoped_reviewed_measurements", "formal_input_check_passed")},
                     ensure_ascii=False))
