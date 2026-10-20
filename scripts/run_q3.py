"""Offline Q3 experiments with explicit stage completion and current receipts."""
import argparse
from copy import deepcopy
import csv
from datetime import datetime, timezone
import json
from math import isclose, fsum
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(ROOT/"scripts"))
from run_q2_national import preflight as q2_preflight, sha, load, dump, csv_write, CODE as Q2_CODE
from energy_model.q2_national import NationalModel
from energy_model.q2_operations import Q2Error, number
from energy_model.q3_events import EVENT_SCENARIOS, run_event, safety_metrics, interaction
from energy_model.q3_transition import service_totals
from q3_campaign import validate_protocol, run_campaign
from q3_reporting import generate_report

BASE = "500436ffe8a9ecdf0ebcad3cdae87ef9deddbf93"
CODE = list(dict.fromkeys([*Q2_CODE, "scripts/run_q3.py", "src/energy_model/q3_events.py",
                          "scripts/prepare_q3_inputs.py", "scripts/check_q3_environment.py",
                          "src/energy_model/q3_transition.py", "scripts/q3_campaign.py",
                          "scripts/freeze_q3_transition.py", "scripts/q3_reporting.py"]))


def safe_path(relative):
    p = (ROOT/relative).resolve()
    if not p.is_relative_to(ROOT) or p.is_relative_to(ROOT/"data/restricted"):
        raise Q2Error("invalid_input", "Forbidden Q3 input path")
    return p


def preflight(config_path):
    config = load(config_path)
    if "previous_protocol" in config and sha(safe_path(config["previous_protocol"]))!=config["previous_protocol_sha256"]:
        raise Q2Error("changed_input","Previous frozen protocol changed")
    if config["base_sha"] != BASE or config["owner"] != "p3/mmj":
        raise Q2Error("invalid_input", "Wrong Q3 common base/owner")
    if config["status"] != "author_frozen_conditional_proposal" or config["team_approved"]:
        raise Q2Error("invalid_input", "Proposal must not impersonate team approval")
    if set(config["scenarios"]) != {"S0", "SP", "SG", "ST", "SW", "SGW"}:
        raise Q2Error("missing_input", "All six scenario specifications are required")
    for scenario, parameter in (("SP", "carbon_price_multiplier"), ("ST", "storage_new_project_cost_multiplier")):
        values = config["scenarios"][scenario]
        if set(values) != {parameter, "public_year", "effective_year"} or values["public_year"] != 2024 or values["effective_year"] != 2025:
            raise Q2Error("invalid_input", "Unsupported scenario timing or extra intervention: " + scenario)
        number(values[parameter], scenario + "." + parameter, 1e-9)
    if config["scenarios"]["S0"] != {}:
        raise Q2Error("invalid_input", "S0 cannot contain an undeclared intervention")
    safety = config["safety"]
    if type(safety["recovery_periods"]) is not int or safety["recovery_periods"] < 1:
        raise Q2Error("invalid_input", "Recovery requires a positive number of periods")
    number(safety["relative_shortage_tolerance"], "relative shortage tolerance", 0, 1)
    number(safety["absolute_shortage_tolerance_mwh"], "absolute shortage tolerance")
    if not config.get("frozen_at_utc") or not config.get("events"):
        raise Q2Error("missing_input", "Missing frozen configuration/event grid")
    ids = [e["id"] for e in config["events"]]
    if len(ids) != len(set(ids)) or {e["split"] for e in config["events"]} != {"selection", "test"}:
        raise Q2Error("invalid_input", "Unique events and distinct selection/test conditions required")
    if config["initial_year"] != 2024 or config["end_year"] != 2060 or config["snapshot_year"] != 2030:
        raise Q2Error("invalid_input", "Unsupported initial state or experiment time grid")
    review_path = safe_path(config["source_review"])
    if sha(review_path) != config["source_review_sha256"]:
        raise Q2Error("changed_input", "Q3 use review changed; do not refresh its hash automatically")
    review = load(review_path)
    required = {"conditional_annual_scenarios", "conditional_event_composition", "conditional_event_shape", "h02_battery_response_freeze"}
    if review["status"] != "author_reviewed_conditional_proposal" or review["base_sha"] != BASE or review["team_approved"] or not required <= set(review["permissions"]):
        raise Q2Error("withdrawn_use", "Q3 purpose is not admitted")
    for rel, digest in {**config["input_hashes"], **review["source_hashes"]}.items():
        if sha(safe_path(rel)) != digest:
            raise Q2Error("changed_input", "Changed Q3 input " + rel)
    if "transition" in config:
        validate_protocol(config)
        transition_path=safe_path(config["transition_review"])
        if sha(transition_path)!=config["transition_review_sha256"]:
            raise Q2Error("changed_input","Transition-use review changed")
        admission=load(transition_path)
        purposes={"conditional_retirement_timing","fixed_application_replay","public_infrastructure_programmes","finite_policy_screening"}
        if admission["status"]!="author_reviewed_conditional_protocol" or admission["team_approved"] or not purposes<=set(admission["permissions"]):
            raise Q2Error("withdrawn_use","Transition purpose withdrawn")
        if admission["base_sha"]!=BASE or admission["inherited_review_sha256"]!=config["source_review_sha256"]:
            raise Q2Error("changed_input","Transition review is not tied to inherited evidence")
        if config["transition"]["channel_fraction"]!=review["trade"]["fraction"]:
            raise Q2Error("changed_input","Planning and events use different source composition")
    # Parameters/results belong to the LOCKED Q2 handoff, not a later branch.
    for rel in ("outputs/q2/p2_lb_national/calibration.json", "outputs/q2/p2_lb_national/baseline_path.csv"):
        original = subprocess.run(["git", "show", BASE+":"+rel], cwd=ROOT, capture_output=True, check=True).stdout
        import hashlib
        if hashlib.sha256(original).hexdigest() != config["input_hashes"][rel]:
            raise Q2Error("changed_input", "Q2 inherited result differs from locked base")
    data, design, _ = q2_preflight()
    theta = load(ROOT/"outputs/q2/p2_lb_national/calibration.json")["best"]["parameters"]
    return config, review, data, design, theta


def compare_baseline(paths, config):
    reference = list(csv.DictReader((ROOT/"outputs/q2/p2_lb_national/baseline_path.csv").open(encoding="utf-8")))
    if len(paths) != len(reference):
        raise Q2Error("regression", "Q2 baseline row count changed")
    differences, roundoff = [], []
    n = config["numerical"]
    for old, new in zip(reference, paths):
        for key, value in old.items():
            if str(new[key]) == value:
                continue
            try:
                v, w = float(value), float(new[key])
            except (ValueError, TypeError):
                differences.append(dict(year=old["year"], field=key, reference=value, actual=new[key]))
                continue
            if key == "cash_balance_residual_cny":
                # Existing q2_national.settle currency conservation limit.
                bound = max(n["cash_balance_absolute_cny"],
                            float(old["operating_resource_cost_cny"])*n["cash_balance_relative"])
                passed = abs(v) <= bound and abs(w) <= bound
            else:
                passed = isclose(v, w, rel_tol=n["relative_comparison_tolerance"],
                                 abs_tol=n["absolute_comparison_tolerance"])
            record = dict(year=old["year"], field=key, reference=value, actual=new[key], difference=w-v)
            (roundoff if passed else differences).append(record)
    return dict(passed=not differences, differences=differences, within_existing_tolerance=roundoff,
                bitwise_identical=not differences and not roundoff,
                scope="S0 replay with inherited calibration; original 1012-trial search not rerun")


def annual_scenarios(config, data, design, theta, out):
    paths, ledgers, finance, queues, comparisons, services = [], [], [], [], [], []
    snapshot = None
    models = {}
    for scenario in ("S0", "SP", "ST"):
        print("Q3 annual " + scenario, flush=True)
        d, variant = deepcopy(design), {}
        if scenario == "SP":
            variant["carbon_price_multiplier"] = config["scenarios"][scenario]["carbon_price_multiplier"]
        if scenario == "ST":
            d["assumptions"]["storage_capex_cny_per_mwh"] *= config["scenarios"][scenario]["storage_new_project_cost_multiplier"]
        model = NationalModel(data, d, theta, config["initial_year"], variant=variant)
        while model.year <= config["end_year"]:
            year = model.year
            model.step()
            if scenario == "S0" and year == config["snapshot_year"]:
                snapshot = deepcopy(model.last_operation)
        models[scenario] = model
        # Q2's legacy cross-service sum is not a Q3 safety indicator.
        paths.extend(dict(scenario=scenario, experiment_scope="annual_no_disaster_calendar",
                          **{k:v for k,v in r.items() if k not in {"unmet_service_mwh","requested_service_mwh"}}) for r in model.paths)
        ledgers.extend(dict(scenario=scenario, **r) for r in model.operations)
        for year in range(2025, 2061):
            demand = [r for r in model.operations if r["year"] == year and r["kind"] == "demand"]
            services.extend(dict(scenario=scenario,year=year,unit="MWh_service_proxy",**r,
                scope="annual_weighted_quantity_only; no_annual_duration_or_probability") for r in service_totals(demand,365))
        finance.extend(dict(scenario=scenario, **r) for r in model.finance)
        queues.extend(dict(scenario=scenario, kind="generation", **r) for r in model.projects)
        queues.extend(dict(scenario=scenario, queue_type="infrastructure", **r) for r in model.grid.queue)
        for consumer in model.consumers.values():
            queues.extend(dict(scenario=scenario, kind="device", actor=consumer.name, **r) for r in consumer.queue)
        for row in model.paths:
            if row["year"] in (2030, 2060):
                comparisons.append(dict(scenario=scenario, scope="annual_no_disaster_calendar", year=row["year"],
                    resource_cost_cny=row["resource_cost_cny"], combustion_co2_t=row["combustion_co2_t"],
                    primary_energy_tce=row["primary_energy_tce"], nonfossil_share_proxy=row["nonfossil_share_proxy"],
                    storage_power_mw=row["storage_power_mw"], storage_energy_mwh=row["storage_energy_mwh"]))
    baseline = compare_baseline(models["S0"].paths, config)
    dump(out/"q2_baseline_replay.json", baseline)
    if not baseline["passed"]:
        raise Q2Error("regression", "Inherited Q2 S0 no longer reproduces")
    csv_write(out/"scenario_paths.csv", paths)
    csv_write(out/"annual_operations.csv", ledgers)
    csv_write(out/"annual_accounts.csv", finance)
    csv_write(out/"annual_queues.csv", queues)
    csv_write(out/"annual_service_metrics.csv", services)
    dump(out/"event_initial_state.json", snapshot)
    return snapshot, comparisons


def event_experiments(config, review, snapshot, out):
    metrics, operations, balances, sources, interactions, summaries, stages = [], [], [], [], [], [], []
    safety = config["safety"]
    fraction = review["trade"]["fraction"]
    for event in config["events"]:
        response_rows = {}
        reference = None
        for response in ("normal", "frozen_battery_discharge"):
            batch = []
            for scenario in EVENT_SCENARIOS:
                print(f"Q3 event {event['id']} {response} {scenario}", flush=True)
                run = run_event(snapshot, event, scenario, fraction,
                                discharge_reference=reference if response != "normal" else None)
                if scenario == "S0" and response == "normal":
                    reference = [r["discharge_mwh"] for r in run["result"]["storage"]]
                label = dict(event=event["id"], split=event["split"], response=response, scenario=scenario,
                             scope="independent_finite_event_not_annual_path")
                result = run["result"]
                rows = [dict(**label, **r) for r in safety_metrics(run,
                    relative_tolerance=safety["relative_shortage_tolerance"],
                    absolute_tolerance=safety["absolute_shortage_tolerance_mwh"],
                    recovery_periods=safety["recovery_periods"])]
                metrics.extend(rows); batch.extend(rows)
                for kind in ("fuel", "generation", "storage", "demand"):
                    operations.extend(dict(**label, kind=kind, **r,
                        start_hour=run["calendar"][r["period"]]["start_hour"],
                        end_hour=run["calendar"][r["period"]]["end_hour"]) for r in result[kind])
                balances.extend(dict(**label, **r) for r in result["balances"])
                sources.extend(dict(**label, **r) for r in run["sources"])
                stages.extend(dict(**label, **r) for r in result["stages"])
                summaries.append(dict(**label, solve_status=result["status"], resource_cost_cny=result["resource_cost"],
                    combustion_co2_t=fsum(r["combustion_co2_t"] for r in result["fuel"]),
                    storage_minimum_mwh=min([run["operation"]["storage"]["initial_mwh"]]+[r["closing_mwh"] for r in result["storage"]]),
                    gas_minimum_mwh=min([run["operation"]["fuels"]["gas"]["initial_mwh"]]+[r["closing_mwh"] for r in result["fuel"] if r["fuel"]=="gas"]),
                    import_gas_mwh=fsum(r["import_mwh"] for r in result["fuel"] if r["fuel"]=="gas"),
                    max_residual_mwh=result["max_residual"],
                    duration_hours=sum(p["hours"] for p in run["operation"]["periods"])))
            response_rows[response] = {r["sector"]:r for r in interaction(batch)}
        for sector, row in response_rows["normal"].items():
            frozen = response_rows["frozen_battery_discharge"][sector]
            interactions.append(dict(event=event["id"], split=event["split"], **row,
                J_frozen=frozen["J"], J_normal_minus_frozen=row["J"]-frozen["J"],
                attribution="specified_battery_discharge_response_only; no_all_mechanism_claim"))
    for name, records in (("safety_metrics", metrics), ("event_operations", operations),
                          ("event_balances", balances), ("source_supply", sources),
                          ("h02_results", interactions), ("solver_stages", stages), ("event_summary", summaries)):
        csv_write(out/(name+".csv"), records)
    return summaries, interactions


def verify_latest(folder):
    folder = Path(folder).resolve()
    latest = load(folder.parent/(folder.name+".latest-attempt.json"))
    manifest = load(folder/"run_manifest.json")
    if not latest.get("output_valid_for_this_attempt") or latest["run_id"] != manifest["run_id"]:
        raise Q2Error("stale_result", "Latest Q3 attempt is not valid")
    if sha(folder/"run_manifest.json") != latest["manifest_sha256"]:
        raise Q2Error("stale_result", "Q3 manifest changed")
    for group in ("code_hashes", "input_hashes"):
        for rel, expected in manifest[group].items():
            if sha(safe_path(rel)) != expected:
                raise Q2Error("stale_result", "Q3 code/input changed: " + rel)
    preflight(safe_path(manifest["config_path"]))
    for rel, digest in manifest["outputs"].items():
        p = (folder/rel).resolve()
        if not p.is_relative_to(folder) or sha(p) != digest:
            raise Q2Error("stale_result", "Q3 output changed: " + rel)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="workflow/q3_inputs_v5.json")
    parser.add_argument("--output-dir", default="outputs/q3/p3_mmj")
    parser.add_argument("--stage", choices=("full", "scenarios-h02"), default="full")
    args = parser.parse_args(argv)
    out = (ROOT/args.output_dir).resolve()
    if out.parent != ROOT/"outputs/q3":
        parser.error("Q3 output must be a direct child of outputs/q3")
    if out.exists():
        old = load(out/"run_manifest.json")
        if old.get("owner") != "p3/mmj":
            raise ValueError("Refusing to overwrite unowned output")
        archive = out.parent/(out.name+".attempts")/old["run_id"]
        archive.parent.mkdir(parents=True, exist_ok=True)
        if archive.exists():
            raise ValueError("Attempt archive already exists")
        shutil.move(str(out), str(archive))
    out.mkdir(parents=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    start = time.perf_counter()
    latest = out.parent/(out.name+".latest-attempt.json")
    manifest = dict(run_id=run_id, owner="p3/mmj", base_sha=BASE, status="running", stage=args.stage,
                    q3_scientific_complete=False, team_approved=False, code_hashes={}, input_hashes={},
                    python=sys.version, executable=sys.executable, command=sys.argv)
    dump(out/"run_manifest.json", manifest)
    dump(latest, dict(run_id=run_id, status="running", output_valid_for_this_attempt=False))
    code = 1
    try:
        config_path = safe_path(args.config)
        manifest["config_path"] = config_path.relative_to(ROOT).as_posix()
        config, review, data, design, theta = preflight(config_path)
        manifest["code_hashes"] = {p:sha(ROOT/p) for p in CODE}
        manifest["input_hashes"] = {**config["input_hashes"], manifest["config_path"]:sha(config_path),
                                    config["source_review"]:sha(safe_path(config["source_review"]))}
        if "transition_review" in config:
            manifest["input_hashes"][config["transition_review"]]=sha(safe_path(config["transition_review"]))
        if "previous_protocol" in config:
            manifest["input_hashes"][config["previous_protocol"]]=sha(safe_path(config["previous_protocol"]))
        manifest["git_sha"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        manifest["git_dirty"] = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT))
        import importlib.metadata
        manifest["dependencies"] = {p:importlib.metadata.version(p) for p in ("numpy","scipy","mesa","pandas","matplotlib")}
        dump(out/"frozen_config.json", config)
        dump(out/"inherited_q2_design.json", design)
        dump(out/"inherited_parameters.json", theta)
        with zipfile.ZipFile(out/"model_snapshot.zip","w",zipfile.ZIP_DEFLATED) as snapshot_archive:
            for relative in sorted(set(CODE)|set(manifest["input_hashes"])):
                info=zipfile.ZipInfo(relative,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                snapshot_archive.writestr(info,(ROOT/relative).read_bytes())
        snapshot, comparison = annual_scenarios(config, data, design, theta, out)
        summaries, h02 = event_experiments(config, review, snapshot, out)
        csv_write(out/"scenario_comparison.csv", comparison+summaries)
        missing = ["H01 two grids and three controls", "implementable policy selection", "one-factor sensitivity", "independent complete Q3 reproduction", "two team approvals"]
        campaign=None
        if args.stage=="full" and "transition" in config:
            campaign=run_campaign(config,data,design,theta,out)
            if not campaign["experiments_completed"]:
                raise Q2Error("campaign_failed","Unexpected experiment failures; inspect transition_failures.json")
            generate_report(out,config,campaign)
            missing=["independent complete Q3 reproduction", "two team approvals"]
        csv_write(out/"gaps_and_conflicts.csv", [dict(item=s, status="pending", blocks_full_q3=True) for s in missing]+[
            dict(item="inherited Q2 gas/oil/biomass generation residuals; single-node; already-seen evaluation; no CO2 holdout", status="retained_scope_limitation", blocks_full_q3=False)])
        for rel, digest in {**manifest["code_hashes"], **manifest["input_hashes"]}.items():
            if sha(ROOT/rel) != digest:
                raise Q2Error("changed_during_run", "Code or input changed during Q3 run")
        manifest.update(status="partial_stage_completed", completed=["S0_SP_ST_annual", "four_matched_finite_events", "H02_battery_response_freeze"],
                        pending=missing, event_cases=len(summaries), annual_scenarios=3)
        if campaign is not None:
            manifest.update(status="conditional_experiments_completed",experiments_complete=True,transition=campaign)
            manifest["completed"] += ["H01_two_grids_two_modes_four_rules","finite_constrained_policy_screen","six_single_factor_policy_grids"]
        report = "# P3/mmj 阶段结果\n\n当前仅完成六情景的年度/独立事件分层运行及 H02 指定电池响应冻结。Q3 尚未完成。\n\n"
        report += "年度 S0/SP/ST：2025—2060；S0/SG/SW/SGW：同一2030事前状态的连续条件窗口。短期结果不外推全年概率、不反馈为每年固定灾害。\n\n"
        report += "H02 的归因仅涉及电池放电上限响应；不代表全部耦合机制。源份额只用于条件进口包络拆分，未把年度体积当作小时交付能力。\n\n"
        maximum_j = max(abs(r["J"]) for r in h02)
        maximum_effect = max(abs(r["J_normal_minus_frozen"]) for r in h02)
        report += f"本次 {len(h02)} 个事件×服务记录中，最大绝对 J 为 {maximum_j:.12g} MWh服务代理量，最大绝对冻结差分为 {maximum_effect:.12g}。这组条件没有提供正向机制创新的证明；不得修改已看过的检验条件以追求非零结果。\n\n"
        report += "服务分别计量，年度服务见 annual_service_metrics.csv。连续事件按6小时时段计算；恢复时间是该分辨率下的服务恢复，期末库存另受相同约束，不是真实逐小时灾害观测。\n\n"
        if campaign is not None:
            report = report.replace("当前仅完成六情景的年度/独立事件分层运行及 H02 指定电池响应冻结。Q3 尚未完成。",
                "六情景、H01 两组网格与四类规则、固定项目/完整响应、H02、有限政策筛选及单因素敏感性已执行。完整自查和团队验收仍单独判断。")
            report += f"本次完成 {campaign['annual_runs']} 个年度转型实验；政策筛选结果为 {campaign['designated_policy_status']}，选定方案为 {campaign['selected_policy']}。固定项目融资失败 {campaign['fixed_project_failures']} 例，证据保存在 transition_failures.json。\n\n"
            report += "完整转型/政策报告、五方面建议和图表见 [transition_report.md](transition_report.md)；H01可行性与检验集分报。\n\n"
        report += "尚缺："+"；".join(missing)+"。退出码0只表示请求的计算流程完成，不代表团队批准或全国预测有效。\n"
        (out/"report.md").write_text(report, encoding="utf-8")
        code = 0 if args.stage == "scenarios-h02" or campaign is not None else 2
    except Exception as exc:
        manifest.update(status="failed", error_type=type(exc).__name__, error_status=getattr(exc,"status","error"), error=str(exc))
        print(f"Q3 FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
    finally:
        manifest["elapsed_seconds"] = time.perf_counter()-start
        manifest["exit_code"] = code
        manifest["outputs"] = {f.relative_to(out).as_posix():sha(f) for f in sorted(out.rglob("*")) if f.is_file() and f.name != "run_manifest.json"}
        dump(out/"run_manifest.json", manifest)
        dump(latest, dict(run_id=run_id, status=manifest["status"], output_valid_for_this_attempt=manifest["status"] in {"partial_stage_completed","conditional_experiments_completed"},
                         full_q3_complete=False, manifest_sha256=sha(out/"run_manifest.json")))
    print(json.dumps({k:manifest[k] for k in ("status","stage","elapsed_seconds","exit_code")}), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
