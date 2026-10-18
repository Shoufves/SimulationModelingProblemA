"""Local workflow reports and evidence admission checks; no network or model execution."""
import argparse
import hashlib
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_record_sha256(record):
    return hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def local_file(root, value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("缺少相对文件路径")
    relative = Path(value)
    resolved = (root / relative).resolve()
    if relative.is_absolute() or not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"路径必须位于工作区内: {value}")
    if not resolved.is_file():
        raise ValueError(f"文件不存在: {value}")
    return resolved


def check_hash(root, value, expected):
    path = local_file(root, value)
    if not isinstance(expected, str) or sha256(path) != expected.lower():
        raise ValueError(f"SHA256不一致: {value}")
    return path


def official_url_allowed(url, domains):
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        return (
            parts.scheme in {"https", "http"}
            and not parts.username and not parts.password
            and parts.port in {None, 80, 443}
            and any(host == d.lower() or host.endswith("." + d.lower()) for d in domains)
        )
    except (TypeError, ValueError, AttributeError):
        return False


def source_ids(value):
    """Support current dataset-level, row-level and observation-level provenance."""
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"source_id", "default_source_id"} and isinstance(child, str):
                found.add(child)
            elif key == "source_ids" and isinstance(child, list):
                found.update(x for x in child if isinstance(x, str))
            elif key == "row_sources" and isinstance(child, dict):
                found.update(x for x in child.values() if isinstance(x, str))
            else:
                found.update(source_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.update(source_ids(child))
    return found


def measurements(dataset):
    numeric = lambda x: type(x) in (int, float) and math.isfinite(x)
    if "rows" in dataset:
        columns = dataset["columns"]
        return sum(numeric(value) for row in dataset["rows"]
                   for column, value in zip(columns, row) if column != "year")
    return sum(numeric(row.get("value")) for row in dataset.get("observations", []))


def check_graph(stages):
    errors = []
    by_id = {s["id"]: s for s in stages}
    if len(by_id) != len(stages):
        errors.append("阶段ID重复")
    visiting, visited = set(), set()

    def visit(stage_id):
        if stage_id in visiting:
            errors.append(f"阶段依赖存在循环: {stage_id}")
            return
        if stage_id in visited:
            return
        if stage_id not in by_id:
            errors.append(f"未知依赖阶段: {stage_id}")
            return
        visiting.add(stage_id)
        for dependency in by_id[stage_id].get("depends_on", []):
            visit(dependency)
        visiting.remove(stage_id)
        visited.add(stage_id)

    for stage_id in by_id:
        visit(stage_id)
    return errors


def check_workflow(root, state, requirements):
    errors = check_graph(state["stages"])
    by_id = {s["id"]: s for s in state["stages"]}
    if set(by_id) != {f"W{i}" for i in range(10)}:
        errors.append("工作流须覆盖W0—W9")
    if state["current_stage"] not in by_id:
        errors.append("当前阶段不存在")
    requirement_ids = [r["id"] for r in requirements["requirements"]]
    if len(set(requirement_ids)) != len(requirement_ids):
        errors.append("需求ID重复")
    for stage in state["stages"]:
        try:
            local_file(root, stage["prompt"])
            if stage["status"] not in {"pending", "ready", "in_progress", "done"}:
                raise ValueError(f"非法阶段状态: {stage['id']}")
            if stage["status"] == "done":
                if not stage.get("evidence"):
                    raise ValueError(f"已完成阶段缺少证据: {stage['id']}")
                for value in stage["evidence"]:
                    local_file(root, value)
                if any(by_id.get(d, {}).get("status") != "done"
                       for d in stage.get("depends_on", [])):
                    raise ValueError(f"已完成阶段的依赖未完成: {stage['id']}")
        except ValueError as exc:
            errors.append(str(exc))
    for requirement in requirements["requirements"]:
        if not requirement.get("stages") or any(s not in by_id for s in requirement["stages"]):
            errors.append(f"需求阶段映射无效: {requirement['id']}")
        if requirement["status"] not in {"not_started", "partial", "done"}:
            errors.append(f"需求状态无效: {requirement['id']}")
        if not requirement.get("acceptance"):
            errors.append(f"缺少验收条件: {requirement['id']}")
        for evidence in requirement.get("progress_evidence", []):
            try:
                local_file(root, evidence)
            except ValueError as exc:
                errors.append(str(exc))
        if requirement["status"] == "done":
            if not requirement.get("progress_evidence") or any(
                    by_id.get(s, {}).get("status") != "done" for s in requirement["stages"]):
                errors.append(f"需求完成声明缺少成果或阶段验收: {requirement['id']}")
    originals = []
    for item in read_json(root / "workflow/provided_inputs.json")["inputs"]:
        try:
            check_hash(root, item["path"], item["sha256"])
            originals.append({"path": item["path"], "unchanged": True})
        except ValueError as exc:
            errors.append(str(exc))
            originals.append({"path": item["path"], "unchanged": False})
    return {"passed": not errors, "errors": errors, "original_inputs": originals}


def nonempty(record, keys):
    for key in keys:
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise ValueError(f"缺少文字字段: {key}")


def check_formal_inputs(root, dataset_paths=None):
    manifest = read_json(root / "workflow/model_inputs.json")
    reviews = read_json(root / "data/evidence_reviews.json")["reviews"]
    registry = read_json(root / "data/sources.json")
    domains = [r["domain"] for r in read_json(root / "workflow/source_domains.json")["domains"]]
    by_source = {r["source_id"]: r for r in registry["sources"]}
    by_review = {r["review_id"]: r for r in reviews}
    errors, accepted = [], []
    selected = None if dataset_paths is None else set(dataset_paths)
    if len(by_source) != len(registry["sources"]):
        errors.append("来源ID重复")
    if len(by_review) != len(reviews):
        errors.append("核验记录ID重复")
    if not manifest["inputs"]:
        errors.append("正式输入清单为空；尚无完成准入的数据子集。")
    seen_datasets = set()
    for item in manifest["inputs"]:
        label = item.get("dataset_path", "<missing>")
        if selected is not None and label not in selected:
            continue
        try:
            nonempty(item, ["dataset_path", "review_id", "purpose"])
            if label in seen_datasets:
                raise ValueError("正式输入数据集重复")
            seen_datasets.add(label)
            review = by_review.get(item["review_id"])
            if not review:
                raise ValueError("找不到对应核验记录")
            if review.get("status") != "reviewed" or review.get("dataset_path") != label:
                raise ValueError("核验状态或对应路径不符")
            nonempty(review, ["reviewer", "checked_on"])
            checked_on = date.fromisoformat(review["checked_on"])
            if checked_on > date.today():
                raise ValueError("核验日期不能在未来")
            for flag in ("original_values_checked", "units_period_scope_checked",
                         "revision_compatibility_checked"):
                if review.get(flag) is not True:
                    raise ValueError(f"未完成实质检查: {flag}")
            dataset_path = check_hash(root, label, review.get("dataset_sha256"))
            record_hashes = review.get("source_records_sha256")
            if record_hashes is None:
                check_hash(root, "data/sources.json", review.get("source_registry_sha256"))
            dataset = read_json(dataset_path)
            used = source_ids(dataset)
            if not used or not used.issubset(by_source):
                raise ValueError("数据集缺少来源ID或引用未知来源")
            if record_hashes is not None:
                if not isinstance(record_hashes, dict) or set(record_hashes) != used:
                    raise ValueError("来源记录哈希必须恰好覆盖数据集所用来源")
                global_hash = review.get("source_registry_sha256")
                if (not isinstance(global_hash, str) or len(global_hash) != 64
                        or any(c not in "0123456789abcdef" for c in global_hash)):
                    raise ValueError("缺少有效的审查时来源目录版本")
                if any(record_hashes[sid] != source_record_sha256(by_source[sid]) for sid in used):
                    raise ValueError("SHA256不一致: 数据集引用的来源记录")
            if measurements(dataset) == 0:
                raise ValueError("数据集无可用数值观测")
            covered = set()
            for evidence in review.get("evidence_files", []):
                sid = evidence.get("source_id")
                if sid not in by_source:
                    raise ValueError("证据引用未知来源")
                if evidence.get("capture_kind") not in {"official_original", "official_page_capture"}:
                    raise ValueError("不接受搜索摘要或未识别的证据类型")
                nonempty(evidence, ["official_url", "locator", "captured_on",
                                    "scope_and_units", "revision_note", "extraction_method"])
                if not official_url_allowed(evidence["official_url"], domains):
                    raise ValueError("证据网址不属于登记的官方域名")
                if evidence["official_url"] != by_source[sid]["url"]:
                    raise ValueError("证据网址与来源登记不一致，需核对并更新登记")
                if not by_source[sid].get("publisher") or not by_source[sid].get("title"):
                    raise ValueError("来源登记缺少发布机构或文件名称")
                captured_on = date.fromisoformat(evidence["captured_on"])
                if captured_on > checked_on:
                    raise ValueError("证据留存日期晚于核验日期")
                path = check_hash(root, evidence.get("path"), evidence.get("sha256"))
                if path.stat().st_size == 0:
                    raise ValueError("证据文件为空")
                covered.add(sid)
            if not used.issubset(covered):
                raise ValueError("缺少来源证据: " + ", ".join(sorted(used - covered)))
            accepted.append({"dataset_path": label, "review_id": review["review_id"],
                             "source_ids": sorted(used)})
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(f"{label}: {exc}")
    if selected is not None:
        errors += [f"{path}: 正式清单未登记所需数据集"
                   for path in sorted(selected - seen_datasets)]
    return {
        "passed": not errors, "errors": errors, "accepted_inputs": accepted,
        "declared_inputs": len(manifest["inputs"]),
        "limitation": "仅检查已登记子集的证据结构和文件一致性；不自动验证原文真伪、转录正确性、数据覆盖完整性、情景参数或模型有效性。未准入不等于原数值错误。"
    }


def make_report(root, stage_id=None):
    state = read_json(root / "workflow/state.json")
    requirements = read_json(root / "workflow/requirements.json")
    workflow = check_workflow(root, state, requirements)
    formal = check_formal_inputs(root)
    stage_id = stage_id or state["current_stage"]
    stages = {s["id"]: s for s in state["stages"]}
    if stage_id not in stages:
        raise ValueError(f"未知阶段: {stage_id}")
    inventory = []
    for path in sorted((root / "data/observations").glob("*.json")):
        data = read_json(path)
        inventory.append({"path": path.relative_to(root).as_posix(),
                          "measurements": measurements(data),
                          "source_ids": sorted(source_ids(data)), "sha256": sha256(path)})
    summary = {status: sum(r["status"] == status for r in requirements["requirements"])
               for status in ("not_started", "partial", "done")}
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "selected_stage": stage_id, "current_stage": state["current_stage"],
        "workflow_check": workflow, "formal_input_check": formal,
        "requirement_status_counts": summary,
        "source_registry_count": len(read_json(root / "data/sources.json")["sources"]),
        "observation_inventory": inventory,
        "measurement_count": sum(r["measurements"] for r in inventory),
        "stages": state["stages"],
        "pending_dependencies": [d for d in stages[stage_id]["depends_on"]
                                 if stages[d]["status"] != "done"],
    }
    return report


def write_reports(root, report):
    out = root / "outputs/workflow"
    out.mkdir(parents=True, exist_ok=True)
    (out / "status.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                   encoding="utf-8")
    formal = report["formal_input_check"]
    lines = ["# 工作流状态", "", f"生成时间：{report['generated_at']}", "",
             f"当前优先阶段：{report['current_stage']}；本次提示词阶段：{report['selected_stage']}。",
             "工作流结构检查：" + ("通过" if report["workflow_check"]["passed"] else "未通过") + "。",
             "正式输入证据检查：" + ("通过（仅限已登记子集，不代表全国模型数据齐备）" if formal["passed"] else "未通过") + "。",
             f"原始题给文件：{sum(x['unchanged'] for x in report['workflow_check']['original_inputs'])}"
             f"/{len(report['workflow_check']['original_inputs'])} 份哈希一致。",
             f"来源登记：{report['source_registry_count']} 项；"
             f"观测文件：{len(report['observation_inventory'])} 份；"
             f"数值观测：{report['measurement_count']} 项；"
             f"本次通过结构准入的正式子集：{len(formal['accepted_inputs'])} 份。",
             "题目需求状态：" + json.dumps(report["requirement_status_counts"], ensure_ascii=False),
             "", "## 阶段", "", "|阶段|任务|记录状态|", "|---|---|---|"]
    lines.extend(f"|{s['id']}|{s['title']}|{s['status']}|" for s in report["stages"])
    lines += ["", "## 尚待解决", ""]
    lines += ["- " + e for e in report["workflow_check"]["errors"] + formal["errors"]]
    incomplete = [s for s in report["stages"] if s["status"] != "done"]
    lines += [f"- {s['id']} {s['title']}：{s['acceptance']}" for s in incomplete]
    lines += [
        "- 先完成全国年度主体决策闭环，再考虑区域或小时级增强。",
        "- 原始数据文件和来源登记中的旧状态说明不等于本工作流正式准入。",
        "", formal["limitation"],
        "阶段及需求状态为人工验收记录；本工具仅核查结构、依赖和文件，未自动判定科研任务完成。",
        "scenario_assumptions中的假设仍须按W4—W6人工检查依据、范围和敏感性。",
    ]
    markdown = "\n".join(lines) + "\n"
    (out / "status.md").write_text(markdown, encoding="utf-8")
    stage = next(s for s in report["stages"] if s["id"] == report["selected_stage"])
    prompt = (local_file(root, "prompts/00_master.md").read_text(encoding="utf-8")
              + "\n\n---\n\n"
              + local_file(root, stage["prompt"]).read_text(encoding="utf-8")
              + "\n\n---\n\n" + markdown)
    if report["pending_dependencies"]:
        prompt += ("\n本阶段尚有正式验收依赖：" + "、".join(report["pending_dependencies"])
                   + "。可以进行独立设计和开发；不得跳过依赖并宣称正式验收完成。\n")
    (out / "next_prompt.md").write_text(prompt, encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--stage", choices=[f"W{i}" for i in range(10)])
    parser.add_argument("--check-formal-inputs", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = make_report(args.root.resolve(), args.stage)
        write_reports(args.root.resolve(), report)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"工作流读取失败: {exc}", file=sys.stderr)
        return 1
    print(f"已生成 outputs/workflow/；提示词阶段 {report['selected_stage']}。")
    if not report["workflow_check"]["passed"]:
        print("\n".join(report["workflow_check"]["errors"]))
        return 1
    if args.check_formal_inputs and not report["formal_input_check"]["passed"]:
        print("\n".join(report["formal_input_check"]["errors"]))
        return 2
    print("结构检查通过。正式输入检查：" +
          ("通过。" if report["formal_input_check"]["passed"] else "尚未通过；详见状态报告。"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
