"""Offline Q2 runner. National admission failure is a nonzero result, never a forecast."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
CODE = ["run.py","scripts/run_q2.py","src/energy_model/q2_operations.py",
        "src/energy_model/q2_agents.py","src/energy_model/q2_experiments.py","requirements-q2.txt"]
OWNER = "p2/lb"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def csv_write(path,rows):
    fields = list(dict.fromkeys(k for row in rows for k in row)) or ["status"]
    with path.open("w",encoding="utf-8",newline="") as f:
        w = csv.DictWriter(f,fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict)) else v for k,v in row.items()})


def within(path):
    p = (ROOT/path).resolve()
    if not p.is_relative_to(ROOT) or p.is_relative_to((ROOT/"data/restricted").resolve()):
        raise ValueError("Input path outside allowed repository data")
    return p


def preflight(config):
    if config.get("schema_version") != 1 or config.get("owner") != OWNER:
        raise ValueError("Unknown Q2 contract schema/owner")
    if config.get("base_sha") != "804ec15ee43874303986a7ad91b2cde05c65b124":
        raise ValueError("Unexpected agreed base")
    admitted,roles = [],set()
    for item in config["inputs"]:
        if item["role"] in roles:
            raise ValueError("Duplicate input role")
        roles.add(item["role"])
        path = within(item["path"])
        if not path.is_file() or sha(path) != item["sha256"]:
            raise ValueError("Missing/changed input: "+item["path"])
        if not item["review"] or not item["allowed_use"]:
            raise ValueError("Unreviewed use: "+item["path"])
        admitted.append(dict(item))
    mode = config["mode"]
    if mode == "synthetic_engineering":
        if roles != {"history_model","forecast_model","design","observations"} or not config["warning"]:
            raise ValueError("Incomplete/unlabelled synthetic experiment")
        if config.get("scientific_acceptance") is not False or any(i["allowed_use"] != mode for i in admitted):
            raise ValueError("Synthetic data cannot be promoted to national scientific acceptance")
    elif mode == "national_pending_review":
        if any(i["allowed_use"] != "candidate_inventory_only" for i in admitted):
            raise ValueError("Pending national sources may only be inspected as candidates")
    else:
        raise ValueError("Unsupported/unreviewed experiment mode")
    return admitted


def verify_latest(folder):
    """Reviewer hook: old success is invalid after a failure, input/code change or artifact edit."""
    folder = Path(folder).resolve()
    latest = load(folder.parent/(folder.name+".latest-attempt.json"))
    m = load(folder/"run_manifest.json")
    if not latest.get("output_valid_for_this_attempt") or latest["run_id"] != m["run_id"] or latest["status"] != "success_engineering":
        raise ValueError("No matching latest successful attempt")
    if sha(folder/"run_manifest.json") != latest["manifest_sha256"]:
        raise ValueError("Changed manifest")
    if m["code_hashes"] != {p:sha(ROOT/p) for p in CODE}:
        raise ValueError("Stale code")
    config_path = within(m["config_path"])
    if sha(config_path) != m["config_sha256"]:
        raise ValueError("Stale configuration")
    if preflight(load(config_path)) != m["inputs"]:
        raise ValueError("Changed input records")
    for name,digest in m["outputs"].items():
        if sha(folder/name) != digest:
            raise ValueError("Changed output: "+name)
    return m


def plot_results(folder, paths, fit):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes = plt.subplots(1,2,figsize=(11,4),layout="constrained")
    axes[0].plot([p["year"] for p in paths],[p["combustion_co2_t"] for p in paths],label="Synthetic S0")
    axes[0].set(xlabel="Year",ylabel="Combustion CO2 (t)")
    for split,color in (("training","#2563eb"),("already_seen_evaluation","#e97722")):
        rows = [r for r in fit if r["metric"] == "primary_energy_mwh" and r["method"] == "coupled_agents" and r["split"] == split]
        axes[1].plot([r["year"] for r in rows],[r["simulated"] for r in rows],color=color,label=split)
        axes[1].scatter([r["year"] for r in rows],[r["observed"] for r in rows],color=color,marker="x")
    axes[1].set(xlabel="Year",ylabel="Synthetic primary energy (MWh)")
    for ax in axes:
        ax.legend(fontsize=7)
        ax.grid(alpha=.2)
    fig.suptitle("ENGINEERING FIXTURE ONLY — NOT A CHINA FORECAST")
    fig.savefig(folder/"engineering_paths.png",dpi=150)
    plt.close(fig)


def execute(config_path,output):
    # Validate output confinement before creating anything. Never overwrite unrelated directories.
    out = (ROOT/output).resolve()
    parent = (ROOT/"outputs/q2").resolve()
    if out.parent != parent or out.name.endswith((".attempts",".json")):
        raise ValueError("Output must be a direct child of outputs/q2")
    if out.exists() and (not (out/"run_manifest.json").is_file() or load(out/"run_manifest.json").get("owner") != OWNER):
        raise ValueError("Refusing to overwrite an unowned result directory")
    parent.mkdir(parents=True,exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")+"-"+uuid.uuid4().hex[:8]
    attempt = parent/(out.name+".attempts")/run_id
    attempt.mkdir(parents=True)
    latest_path = parent/(out.name+".latest-attempt.json")
    latest = dict(run_id=run_id,owner=OWNER,status="running",output_valid_for_this_attempt=False,
                  attempt_path=attempt.relative_to(ROOT).as_posix())
    dump(latest_path,latest)
    start = time.perf_counter()
    def git(*args):
        r = subprocess.run(["git",*args],cwd=ROOT,capture_output=True,text=True,encoding="utf-8")
        return r.stdout.strip() if r.returncode == 0 else "unavailable"
    manifest = dict(run_id=run_id,owner=OWNER,command=[sys.executable,*sys.argv],
        git_sha=git("rev-parse","HEAD"),dirty=bool(git("status","--porcelain","--untracked-files=normal")),
        utc_started=datetime.now(timezone.utc).isoformat(),python=sys.version,
        code_hashes={p:sha(ROOT/p) for p in CODE},status="running",q2_scientific_complete=False)
    exit_code = 2
    try:
        p = within(config_path)
        manifest.update(config_path=p.relative_to(ROOT).as_posix(),config_sha256=sha(p))
        config = load(p)
        manifest["inputs"] = preflight(config)
        manifest["base_sha"] = config["base_sha"]
        manifest["mode"] = config["mode"]
        if config["mode"] == "national_pending_review":
            csv_write(attempt/"gaps_and_conflicts.csv",config["gaps"])
            manifest["status"] = "blocked_national_inputs"
            manifest["error"] = "National historical/current initialization and common scientific design not admitted; see gaps_and_conflicts.csv"
            (attempt/"report.md").write_text("# 问题二全国入口：部分实现，正式预测未运行\n\n"
                "起点：`"+config["base_sha"]+"`。本次成功核验候选输入文件身份，但这些文件只有候选清点用途。\n\n"
                "| 缺口 | 现有材料 | 仍需解决 |\n|---|---|---|\n"+
                "\n".join(f"| {g['id']} | {g['available']} | {g['required']} |" for g in config["gaps"])+
                "\n\n正式退出码为 2。没有生成全国历史拟合、2030/2060预测或达标结论；工程夹具成果另存。\n",encoding="utf-8")
        else:
            from energy_model.q2_experiments import calibrate,forecast,target_rows
            packages = {n:importlib.metadata.version(n) for n in ("mesa","scipy","numpy","pandas","matplotlib")}
            expected = dict(mesa="3.3.1",scipy="1.16.3",numpy="2.3.5",pandas="3.0.1",matplotlib="3.10.7")
            if packages != expected:
                raise ValueError("Dependency versions differ from requirements-q2.txt: "+str(packages))
            manifest["dependencies"] = packages
            values = {i["role"]:load(within(i["path"])) for i in config["inputs"]}
            if values["history_model"]["scope"] != "synthetic_engineering_fixture" or values["forecast_model"]["scope"] != "synthetic_engineering_fixture":
                raise ValueError("Synthetic contract accepts synthetic models only")
            calibration,fit = calibrate(values["history_model"],values["observations"],values["design"])
            baseline,sensitivity = forecast(values["forecast_model"],calibration["best"]["parameters"],values["design"],calibration["equivalent_parameters"])
            targets,peak = target_rows(baseline.paths,values["design"])
            dump(attempt/"calibration.json",calibration)
            dump(attempt/"frozen_experiment.json",values["design"])
            dump(attempt/"project_queue.json",baseline.projects)
            dump(attempt/"peak.json",peak)
            for name,rows in (("history_fit",fit),("baseline_path",baseline.paths),("targets_2030_2060",targets),
                              ("sensitivity",sensitivity),("assets",baseline.asset_log),("behavior",baseline.behavior),
                              ("operations",baseline.operation_log),("accounts",baseline.accounts),
                              ("balances",baseline.balance_log),("solver_stages",baseline.stage_log)):
                csv_write(attempt/(name+".csv"),rows)
            csv_write(attempt/"gaps_and_conflicts.csv",[
                dict(id="engineering_only",required="Empirical national calibration and prediction remain incomplete"),
                dict(id="national_accounting",required="Chinese primary-energy/ETS/asset-age/CO2 bridge, not fixture defaults"),
                dict(id="2005_base",required="Same-scope 2005 emissions/constant-price GDP before intensity judgement"),
                dict(id="device_stock",required="Cohort retirement and age constraints beyond aggregate replacement proxy"),
                dict(id="chronology",required="Repeated known day is not annual weather/seasonal storage validation")])
            plot_results(attempt,baseline.paths,fit)
            failed = sum(r["status"] != "success" for r in sensitivity)
            (attempt/"report.md").write_text("# Q2 工程闭环验算（全部合成，非中国预测）\n\n"
                "本次执行了 Mesa 年度主体、SciPy 跨时段 LP、27 组多目标参数搜索、已接触留出、持平基线、关闭投资/替代的规则对照、独立2024初态至2060以及三因素灵敏度。\n\n"
                "校准观测由同一模型生成，只证明程序与约束可运行，不证明真实历史解释力；不能将拟合优度写入全国模型验证结论。\n\n"
                f"最佳训练损失：{calibration['best']['loss']:.6g}；等效参数组：{len(calibration['equivalent_parameters'])}；灵敏度失败记录：{failed}。\n\n"
                "正式全国入口保持非零阻断。研究假设、全国数据审查和团队验收尚未完成。\n\n"
                "![工程验算](engineering_paths.png)\n",encoding="utf-8")
            manifest.update(status="success_engineering",seed=values["design"]["seed"],solver="SciPy linprog / HiGHS",
                solver_tolerance=1e-8,max_residual=max(p["max_residual"] for p in baseline.paths),
                forecast_years=[2024,2060],training_years=[2015,2021],evaluation_years=[2022,2024],
                sensitivity_failed_records=failed)
            exit_code = 0
    except Exception as exc:
        manifest["status"] = getattr(exc,"status","invalid_input")
        manifest["error"] = f"{type(exc).__name__}: {exc}"
        (attempt/"report.md").write_text("# 本次运行失败\n\n"+manifest["error"]+"\n\n旧结果不代表本次成功。\n",encoding="utf-8")
    manifest["seconds"] = time.perf_counter()-start
    manifest["outputs"] = {p.name:sha(p) for p in sorted(attempt.iterdir()) if p.is_file()}
    dump(attempt/"run_manifest.json",manifest)
    if exit_code == 0:
        if out.exists():
            old_id = load(out/"run_manifest.json")["run_id"]
            out.rename(attempt.parent/("preserved-"+old_id))
        attempt.rename(out)
        latest.update(status=manifest["status"],output_valid_for_this_attempt=True,
                      manifest_sha256=sha(out/"run_manifest.json"),attempt_path=out.relative_to(ROOT).as_posix())
    else:
        latest.update(status=manifest["status"],error=manifest["error"],manifest_sha256=sha(attempt/"run_manifest.json"))
    dump(latest_path,latest)
    print(json.dumps(dict(status=manifest["status"],exit_code=exit_code,artifact_path=latest["attempt_path"],
                         q2_scientific_complete=False,error=manifest.get("error")),ensure_ascii=False))
    return exit_code


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",default="workflow/q2_inputs.json")
    p.add_argument("--output-dir",default="outputs/q2/p2_lb")
    args = p.parse_args()
    return execute(args.config,args.output_dir)


if __name__ == "__main__":
    raise SystemExit(main())
