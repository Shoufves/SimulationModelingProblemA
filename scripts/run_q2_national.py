"""Reproducible empirical Q2 candidate: real observations, conditional projections.

Scientific quality and execution success are separate fields. A completed run
does not confer team approval or turn boundary proxies into official metrics.
"""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
from itertools import product
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile
import os
from concurrent.futures import ProcessPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from energy_model.q2_national import NationalModel, observations, get
from energy_model.q2_operations import Q2Error
from energy_model.q2_experiments import peak_check

CODE = ["run.py","scripts/run_q2_national.py","scripts/build_q2_national_inputs.py","src/energy_model/q2_national.py",
        "src/energy_model/q2_finance.py",
        "src/energy_model/q2_operations.py","src/energy_model/q2_experiments.py","requirements-q2.txt"]
INPUTS = ["data/catalog/q2_national_input_review.json","data/processed/q2/national_observations.csv",
          "data/processed/q2/technical_references.json","workflow/q2_national_design.json"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def dump(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def csv_write(path, rows):
    fields = list(dict.fromkeys(k for r in rows for k in r)) or ["status"]
    with Path(path).open("w",encoding="utf-8",newline="") as f:
        w = csv.DictWriter(f,fieldnames=fields); w.writeheader()
        for r in rows:
            w.writerow({k:json.dumps(v,ensure_ascii=False,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in r.items()})


def preflight():
    review = load(ROOT/INPUTS[0])
    if review["status"] != "author_reviewed_conditional_research_inputs" or review["team_approved"]:
        raise ValueError("Author candidate cannot impersonate team approval")
    for p,digest in review["products"].items():
        if sha(ROOT/p) != digest:
            raise ValueError("Changed reviewed product "+p)
    for s in review["sources"]:
        p = (ROOT/s["path"]).resolve()
        if not p.is_relative_to(ROOT) or p.is_relative_to(ROOT/"data/restricted") or sha(p) != s["sha256"]:
            raise ValueError("Changed/forbidden source "+s["path"])
    with (ROOT/INPUTS[1]).open(encoding="utf-8",newline="") as f:
        rows = list(csv.DictReader(f))
    data = observations(rows)
    design = load(ROOT/INPUTS[3])
    with (ROOT/"data/processed/q1/reviewed_2024_additions.csv").open(encoding="utf-8-sig",newline="") as f:
        additions = {r["variable"]:float(r["value"]) for r in csv.DictReader(f) if r["year"] == "2024" and r["region"] == "China" and r["value"]}
    if design["assumptions"]["new_storage_2024_power_mw"] != additions["new_storage_power"]*1000 or design["assumptions"]["new_storage_2024_energy_mwh"] != additions["new_storage_energy"]*1000:
        raise ValueError("2024 storage state differs from reviewed same-year source")
    if design["base_sha"] != "804ec15ee43874303986a7ad91b2cde05c65b124" or design["evaluation_identity"] != "already_seen_not_blind":
        raise ValueError("Wrong base/validation identity")
    if design["training_years"] != list(range(2015,2022)) or design["evaluation_years"] != [2022,2023,2024]:
        raise ValueError("Window changed")
    if not design["frozen_before_this_run_evaluation"]:
        raise ValueError("Unfrozen design")
    import math
    if math.prod(len(v) for v in design["parameter_grid"].values()) != design["search_budget"]:
        raise ValueError("Grid differs from declared budget")
    # No holdout observation contributes to error scales.
    for t in design["targets"]:
        valid = [get(data,y,t["observation"])*t["multiplier"] for y in design["training_years"] if (y,t["observation"]) in data]
        if not valid:
            raise ValueError("Missing training family "+t["metric"])
        t["scale"] = t.get("absolute_scale") or sum(valid)/len(valid)*t["scale_from_training_mean_fraction"]
    return data,design,rows


def verify_latest(folder):
    folder=Path(folder).resolve()
    latest=load(folder.parent/(folder.name+".latest-attempt.json"))
    m=load(folder/"run_manifest.json")
    if not latest.get("output_valid_for_this_attempt") or latest["run_id"]!=m["run_id"] or m["status"]!="success_conditional_candidate":
        raise ValueError("Latest national attempt is not successful")
    if sha(folder/"run_manifest.json")!=latest["manifest_sha256"]:
        raise ValueError("Changed national manifest")
    if m["code_hashes"]!={p:sha(ROOT/p) for p in CODE} or m["input_hashes"]!={p:sha(ROOT/p) for p in INPUTS}:
        raise ValueError("Stale national code or inputs")
    preflight()
    for name,digest in m["outputs"].items():
        if sha(folder/name)!=digest:
            raise ValueError("Changed national output "+name)
    return m


def loss(paths,data,design,years,method):
    indexed = {r["year"]:r for r in paths}
    total,parts,residuals = 0,[],[]
    for target in design["targets"]:
        cells = []
        for year in years:
            key = (year,target["observation"])
            if key not in data:
                continue
            expected = data[key]*target["multiplier"]
            value = indexed[year][target["metric"]]
            r = dict(year=year,method=method,metric=target["metric"],observed=expected,simulated=value,
                residual=value-expected,scaled_residual=(value-expected)/target["scale"],
                relative_error=(value-expected)/expected if expected else None,source_metric=target["observation"])
            residuals.append(r); cells.append(r)
        part = sum(r["scaled_residual"]**2 for r in cells)/len(cells)*target["weight"] if cells else None
        if part is not None:
            total += part
        parts.append(dict(metric=target["metric"],n=len(cells),loss=part,
            mape=sum(abs(r["relative_error"]) for r in cells)/len(cells) if cells else None,
            mae=sum(abs(r["residual"]) for r in cells)/len(cells) if cells else None,
            missing_years=[y for y in years if (y,target["observation"]) not in data]))
    return total,parts,residuals


def calibration_trial(payload):
    i,theta,data,design=payload
    try:
        model=NationalModel(data,design,theta,2014,detail=False).run(2021)
        value,components,_=loss(model.paths,data,design,design["training_years"],"national_candidate")
        return dict(index=i,parameters=theta,status="success",loss=value,components=components)
    except (Q2Error,ValueError) as exc:
        return dict(index=i,parameters=theta,status=getattr(exc,"status","error"),loss=None,error=str(exc))


def calibrate(data,design,folder):
    keys = sorted(design["parameter_grid"])
    trials = []
    payloads=[(i,dict(zip(keys,v)),data,design) for i,v in enumerate(product(*(design["parameter_grid"][k] for k in keys)))]
    # Independent deterministic candidates; map preserves original index/ties.
    for name in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS"):
        os.environ[name]="1"
    workers=max(1,min(4,int(os.environ.get("Q2_WORKERS","4"))))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i,trial in enumerate(pool.map(calibration_trial,payloads,chunksize=5)):
            trials.append(trial)
            if (i+1)%50==0:
                print(f"Training {i+1}/{design['search_budget']}",flush=True)
    valid = sorted((r for r in trials if r["loss"] is not None),key=lambda r:r["loss"])
    dump(folder/"training_trials.json",trials)
    if not valid:
        raise Q2Error("calibration_failed","All national training candidates failed")
    best = valid[0]
    bound = best["loss"]*(1+design["equivalent_relative_tolerance"])+design["equivalent_absolute_tolerance"]
    equivalents = [r["parameters"] for r in valid if r["loss"] <= bound]
    calibration = dict(best=best,equivalent_parameters=equivalents,search_budget=len(trials),
        successful_trials=len(valid),selection="training loss only; no holdout retuning",evaluation_identity=design["evaluation_identity"])
    dump(folder/"training_selection.json",calibration)
    return calibration


def targets(paths,data,design):
    index = {p["year"]:p for p in paths}
    historical = [dict(year=y,positive_co2_t=get(data,y,"gcb_positive_co2_t")*
        get(data,2021,"btr_positive_co2_t")/get(data,2021,"gcb_positive_co2_t")) for y in range(2005,2025)]
    # BTR 2005 and 2020/21 are direct observations; other annual points are a labelled bridge.
    for p in historical:
        if (p["year"],"btr_positive_co2_t") in data:
            p["positive_co2_t"] = get(data,p["year"],"btr_positive_co2_t")
    peak = peak_check(historical+paths,design["peak_persistence_years"])
    peak["historical_bridge"] = "GCB annual relative movement scaled to BTR2021; official BTR 2005/2020/2021 retained; approximate scope bridge"
    result = []
    metrics = dict(primary_energy_tce="tce statistical bridge",nonfossil_share_proxy="fraction (conditional proxy)",
        positive_co2_t="t CO2",net_removals_t="t CO2",net_co2_t="t CO2",neutralisation_ratio="R/P",
        energy_intensity="tce/GDP2024index",carbon_intensity="tCO2/GDP2024index",
        unmet_service_mwh="MWh useful service",total_capacity_mw="MW",electricity_generation_mwh="MWh")
    for y in (2030,2060):
        row = index[y]
        for metric,unit in metrics.items():
            target = .25 if y == 2030 and metric == "nonfossil_share_proxy" else .8 if metric == "nonfossil_share_proxy" else 1 if y == 2060 and metric == "neutralisation_ratio" else None
            result.append(dict(year=y,metric=metric,value=row[metric],unit=unit,target=target,
                judgement="proxy_above_target" if target is not None and row[metric]>=target else "proxy_below_target" if target is not None else "conditional_output",
                boundary="Mainland CO2; not all-GHG neutrality; primary-energy conversion is a fixed-anchor research bridge"))
        result.append(dict(year=y,metric="peak_year",value=peak["year"],unit="year",target=2030,judgement=peak["status"],boundary=peak["historical_bridge"]))
        result.append(dict(year=y,metric="peak_value",value=peak["value"],unit="t CO2",target=None,judgement=peak["status"],boundary=peak["historical_bridge"]))
        for by in (2005,2025):
            for metric in ("energy_intensity","carbon_intensity"):
                if by == 2025:
                    base = index[2025][metric]
                else:
                    value = get(data,by,"consumption_10ktce")*1e4 if metric.startswith("energy") else get(data,by,"btr_positive_co2_t")
                    base = value/(get(data,by,"real_gdp")/get(data,2024,"real_gdp"))
                reduction = 1-row[metric]/base
                target = .65 if y == 2030 and by == 2005 and metric == "carbon_intensity" else .17 if y == 2030 and by == 2025 and metric == "carbon_intensity" else None
                result.append(dict(year=y,metric=metric+f"_reduction_vs_{by}",value=reduction,unit="fraction",target=target,
                    judgement="conditional_meets" if target is not None and reduction>=target else "conditional_misses" if target is not None else "conditional_output",
                    boundary="Gross total CO2/GDP; energy intensity is not policy assessment after exclusions"))
    return result,peak


def evaluate(data,design,calibration,folder):
    best = calibration["best"]["parameters"]
    history = NationalModel(data,design,best,2014).run(2024)
    fitting,quality = [],{}
    for name,years in (("training",design["training_years"]),("already_seen_evaluation",design["evaluation_years"])):
        value,parts,rows = loss(history.paths,data,design,years,"national_candidate")
        quality[name] = dict(loss=value,components=parts)
        fitting += [dict(split=name,**r) for r in rows]
    # Last TRAINING observation for every target, not year t-1 holdout observations.
    persistence = []
    for year in design["evaluation_years"]:
        row = dict(year=year)
        for t in design["targets"]:
            available = [y for y in design["training_years"] if (y,t["observation"]) in data]
            row[t["metric"]] = get(data,max(available),t["observation"])*t["multiplier"]
        persistence.append(row)
    value,parts,rows = loss(persistence,data,design,design["evaluation_years"],"training_last_value")
    quality["persistence"] = dict(loss=value,components=parts)
    fitting += [dict(split="already_seen_evaluation",**r) for r in rows]
    alternative = NationalModel(data,design,best,2014,investment=False,substitution=False,detail=False).run(2024)
    value,parts,rows = loss(alternative.paths,data,design,design["evaluation_years"],"no_new_investment_or_substitution")
    quality["alternative_rules"] = dict(loss=value,components=parts)
    fitting += [dict(split="already_seen_evaluation",**r) for r in rows]
    threshold = design["fit_acceptance"]
    h = {r["metric"]:r for r in quality["already_seen_evaluation"]["components"]}
    train = {r["metric"]:r for r in quality["training"]["components"]}
    checks = dict(energy=h["primary_energy_tce"]["mape"]<=threshold["energy_mape"],
        generation=h["electricity_generation_mwh"]["mape"]<=threshold["generation_mape"],
        capacity=h["total_capacity_mw"]["mape"]<=threshold["capacity_mape"],
        wind_capacity=h["wind_capacity_mw"]["mape"]<=threshold["technology_capacity_mape"],
        solar_capacity=h["solar_capacity_mw"]["mape"]<=threshold["technology_capacity_mape"],
        structure=h["peo_share"]["mae"]<=threshold["peo_share_mae"],
        sparse_training_combustion=train["combustion_co2_t"]["mape"]<=threshold["combustion_mape_training_only"])
    quality["acceptance"] = dict(checks=checks,all_thresholds_passed=all(checks.values()),
        emissions_holdout="No same-scope BTR 2022-2024 observation; not evaluated as zero error",team_approved=False)
    calibration["quality"] = quality
    dump(folder/"calibration.json",calibration)
    csv_write(folder/"history_fit.csv",fitting)
    csv_write(folder/"historical_path.csv",history.paths)
    csv_write(folder/"external_emissions_diagnostic.csv",[dict(year=r["year"],model_co2_t=r["positive_co2_t"],
        gcb_fossil_industry_t=get(data,r["year"],"gcb_positive_co2_t"),comparison="different boundary; no holdout calibration loss") for r in history.paths])
    return history


def experiments(data,design,calibration,folder):
    theta = calibration["best"]["parameters"]
    baseline = NationalModel(data,design,theta,2024).run(2060)
    rows,peak = targets(baseline.paths,data,design)
    csv_write(folder/"targets_2030_2060.csv",rows); dump(folder/"peak.json",peak)
    for name,records in (("baseline_path",baseline.paths),("assets",baseline.assets),("behavior",baseline.behavior),
                         ("accounts",baseline.finance),("operations",baseline.operations),("balances",baseline.balances),("solver_stages",baseline.stages)):
        csv_write(folder/(name+".csv"),records)
    dump(folder/"project_queue.json",baseline.projects)
    settings = [("one_factor",name+"="+str(value),{name:value},theta) for name,values in design["sensitivity"].items() for value in values]
    settings += [("equivalent_parameters",str(i),{},t) for i,t in enumerate(calibration["equivalent_parameters"]) if t!=theta]
    for name,values in {"primary_bridge_multiplier":[.9,1.1],"removals_multiplier":[.5,1.5],
        "process_multiplier":[.7,1.3],"nonenergy_multiplier":[.5,1.5],"capex_multiplier":[.7,1.3],
        "renewable_availability_multiplier":[.8,1.2],"fuel_price_multiplier":[.7,1.3],
        "initial_age_multiplier":[.75,1.25],"construction_elasticity":[.5,1.5],
        "electricity_terminal_elasticity":[.6,1.0],"project_equity_fraction":[.15,.4],
        "grid_initial_headroom":[1.05,1.3],"grid_build_fraction":[.05,.15]}.items():
        settings += [("assumption_bounds",name+"="+str(v),{name:v},theta) for v in values]
    import numpy as np
    rng = np.random.default_rng(design["seed"])
    factor_names = ["gdp_growth_delta","cost_decline_delta","carbon_price_multiplier"]
    morris_links = []
    for trajectory in range(design["morris_trajectories"]):
        point = rng.integers(0,2,3).astype(float)*.5
        permutation = rng.permutation(3)
        for step in range(4):
            variant = dict(zip(factor_names,[float(-.01+.02*point[0]),float(-.01+.02*point[1]),float(.5+point[2])]))
            settings.append(("morris",f"{trajectory}/{step}",variant,theta))
            if step < 3:
                j = int(permutation[step])
                morris_links.append(dict(before=f"{trajectory}/{step}",after=f"{trajectory}/{step+1}",factor=factor_names[j],normalised_step=.5))
                point[j] += .5
    from scipy.stats import qmc
    sample = qmc.LatinHypercube(d=3,seed=design["seed"]).random(design["joint_latin_hypercube_samples"])
    settings += [("joint_LHS",str(i),dict(gdp_growth_delta=-.01+.02*p[0],cost_decline_delta=-.01+.02*p[1],carbon_price_multiplier=.5+p[2]),theta) for i,p in enumerate(sample)]
    sensitivity,failures = [],[]
    for i,(kind,label,variant,t) in enumerate(settings):
        try:
            model = NationalModel(data,design,t,2024,variant=variant,detail=False).run(2060)
            target,p = targets(model.paths,data,design)
            for r in target:
                base = next(b["value"] for b in rows if b["year"] == r["year"] and b["metric"] == r["metric"])
                sensitivity.append(dict(kind=kind,label=label,variant=variant,parameters=t,status="success",**r,
                    delta_from_S0=r["value"]-base if r["value"] is not None and base is not None else None))
        except (Q2Error,ValueError) as exc:
            failures.append(dict(kind=kind,label=label,variant=variant,status=getattr(exc,"status","error"),error=str(exc)))
        if (i+1)%5 == 0:
            print(f"Sensitivity {i+1}/{len(settings)}",flush=True)
    csv_write(folder/"sensitivity.csv",sensitivity)
    elementary = []
    indexed = {(r["label"],r["year"],r["metric"]):r for r in sensitivity if r["kind"] == "morris"}
    for link in morris_links:
        for baseline_target in rows:
            year,metric = baseline_target["year"],baseline_target["metric"]
            before = indexed.get((link["before"],year,metric),{}).get("value")
            after = indexed.get((link["after"],year,metric),{}).get("value")
            elementary.append(dict(**link,year=year,metric=metric,elementary_effect=(after-before)/.5 if before is not None and after is not None else None,
                status="success" if before is not None and after is not None else "non_numeric_or_failed"))
    csv_write(folder/"morris_effects.csv",elementary)
    summary = []
    for metric in sorted({r["metric"] for r in rows}):
        for year in (2030,2060):
            for factor in factor_names:
                values = [r["elementary_effect"] for r in elementary if r["metric"]==metric and r["year"]==year and r["factor"]==factor and r["elementary_effect"] is not None]
                summary.append(dict(year=year,metric=metric,factor=factor,n=len(values),
                    mu_star=float(np.mean(np.abs(values))) if values else None,sigma=float(np.std(values)) if values else None,
                    interpretation="Small deterministic screening design; no convergence/precision guarantee"))
    csv_write(folder/"morris_summary.csv",summary)
    dump(folder/"sensitivity_failures.json",failures)
    dump(folder/"experiment_coverage.json",dict(executed=len(settings),successful=len(settings)-len(failures),failures=len(failures),
        joint_sample_size=len(sample),morris_trajectories=design["morris_trajectories"],probabilistic_claim=False,range_interpretation="Tested conditional domain, not confidence interval or real-world probability"))
    return baseline,rows,sensitivity,failures


def plot(folder,history,baseline,data):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes = plt.subplots(2,2,figsize=(12,8),layout="constrained")
    for ax,metric,label,scale in zip(axes.flat,["primary_energy_tce","peo_share","positive_co2_t","wind_solar_capacity_mw"],
        ["Primary energy (billion tce proxy)","PEO / nonfossil proxy (%)","Positive CO2 (Gt)","Wind + solar (GW)"],[1e9,.01,1e9,1e3]):
        ax.plot([r["year"] for r in history.paths],[r[metric]/scale for r in history.paths],label="Historical simulation")
        ax.plot([r["year"] for r in baseline.paths],[r[metric]/scale for r in baseline.paths],label="Conditional S0")
        observed_metric = dict(primary_energy_tce="consumption_10ktce",peo_share="consumption_primary_electricity_other_pct",
            positive_co2_t="btr_positive_co2_t",wind_solar_capacity_mw="wind_plus_solar_capacity_mw")[metric]
        multiplier = 10000 if metric == "primary_energy_tce" else .01 if metric == "peo_share" else 1
        years=[y for y in range(2015,2025) if (y,observed_metric) in data]
        ax.scatter(years,[data[y,observed_metric]*multiplier/scale for y in years],marker="x",s=20,color="black",label="Observations (scope-labelled)")
        ax.set(xlabel="Year",ylabel=label); ax.grid(alpha=.2); ax.legend(fontsize=8)
    fig.suptitle("Mainland aggregate candidate - conditional, not official forecast")
    fig.savefig(folder/"national_paths.png",dpi=160); plt.close(fig)


def report(folder,calibration,rows,failures):
    def val(year,metric):
        return next(r["value"] for r in rows if r["year"]==year and r["metric"]==metric)
    quality = calibration["quality"]
    text = "# 问题二：全国聚合条件模型候选结果\n\n"
    text += "本次使用真实历史观测进行有限多目标校准，并从独立2024年规模与重建资产初态推演至2060年。结果是附带明确假设的研究候选；未获团队批准，不是官方预测。\n\n"
    text += "## 任务一：主体、决策与交互\n\nMesa组织煤油气及生物质供给商、八类发电主体、工业热/交通/建筑热服务代理、存量电力服务、电网储能和政府。设备逐批到龄退出并更新；企业按滞后利润预期和NPV申请，政府按共同融资限额批准，项目分期支出并在建设期后投产。\n\n"
    text += "供给商报送有限国产/进口交付能力；运行层先满足服务，再按资源费用加已覆盖碳履约机会成本安排调度；政策转移从社会资源成本中扣除另行结算。企业承担出资、债务及偿付约束，外部股权与贷款进入共同投资额度。电网和储能各有预算、建设能力与投运队列，电源新增不扩大电网上限。储能读取实际弃电与缺供，新设备从空SOC开始，跨年继承库存并记录退役库存处置。\n\n"
    text += "## 任务二：真实历史校准及验证\n\n"
    text += f"训练2015—2021年；2022—2024年为已接触留出。{calibration['search_budget']}组候选中{calibration['successful_trials']}组运行成功，按训练损失选出的参数为 `{json.dumps(calibration['best']['parameters'],ensure_ascii=False)}`；保留{len(calibration['equivalent_parameters'])}组等效参数。\n\n"
    text += "| 指标 | 训练MAPE | 已接触留出MAPE | 留出可比年数 |\n|---|---:|---:|---:|\n"
    train = {p["metric"]:p for p in quality["training"]["components"]}
    for p in quality["already_seen_evaluation"]["components"]:
        fmt=lambda v: "无同口径观测" if v is None else f"{v:.2%}"
        text += f"| {p['metric']} | {fmt(train[p['metric']]['mape'])} | {fmt(p['mape'])} | {p['n']} |\n"
    text += f"\n留出综合损失：本模型{quality['already_seen_evaluation']['loss']:.4f}，训练末值持平{quality['persistence']['loss']:.4f}，关闭新增投资和替代{quality['alternative_rules']['loss']:.4f}。这些损失均只累计有同口径观测的指标。\n\n"
    text += f"预先指定误差门槛逐项结果：`{json.dumps(quality['acceptance']['checks'],ensure_ascii=False)}`。未通过项保留为失败，不借事后改阈值宣称验证成功。燃烧排放只有2020/2021两年同口径训练观测，2022—2024没有同口径清单；GCB仅作异口径外部诊断。\n\n"
    text += "## 任务三：S0条件结果\n\n| 指标 | 2030 | 2060 |\n|---|---:|---:|\n"
    for metric,label,scale in [("primary_energy_tce","能源消费（亿tce，桥接）",1e8),("nonfossil_share_proxy","非化石占比代理（%）",.01),
        ("positive_co2_t","正CO₂排放（亿t）",1e8),("net_removals_t","净移除（亿tCO₂）",1e8),
        ("net_co2_t","剩余净排放（亿tCO₂）",1e8),("neutralisation_ratio","中和率R/P（%）",.01),
        ("carbon_intensity_reduction_vs_2005","较2005碳强度降幅（%）",.01),("energy_intensity_reduction_vs_2005","较2005总能耗强度降幅（%）",.01),
        ("carbon_intensity_reduction_vs_2025","较2025碳强度降幅（%）",.01)]:
        text += f"| {label} | {val(2030,metric)/scale:.3f} | {val(2060,metric)/scale:.3f} |\n"
    text += f"\n持续达峰判据给出的峰年：{val(2030,'peak_year')}；全路径最大正排放{val(2030,'peak_value')/1e9:.3f} GtCO₂。`None`表示未确认达峰，并非零排放。需连续五年不反弹且余下路径低于峰值，历史年序列含明确的GCB→BTR桥接。\n\n"
    text += "目标对照逐项保存在 `targets_2030_2060.csv`：2030占比25%、相对2005碳强度65%、相对2025碳强度17%，2060占比80%及R/P≥1分开比较。一次能源折算仍是统计锚点桥接，不能据代理值宣布通过官方考核；CO₂不等于全部温室气体。\n\n"
    text += "## 任务四：灵敏度与稳健性\n\nGDP增长率±1个百分点、风光成本降幅±1个百分点、碳价0.5/1.5倍分别实际运行；同时运行等效参数、碳汇/工业过程/原料比例/成本/风光出力/统计桥接/初始年龄/建设能力边界、6条Morris轨迹以及12点三因素联合Latin Hypercube。全部条件及与S0的差值见 `sensitivity.csv`，Morris逐步效应及μ*/σ见同名表。样本仅用于首轮有界筛选，没有宣称数值精度已收敛。\n\n"
    text += f"试验求解失败{len(failures)}项，原样登记于 `sensitivity_failures.json`。样本代表所检验假设范围，不能解读为达标概率。\n\n"
    text += "## 必须随结果保留的限制\n\n"
    text += "- 历史资料版本、价格及技术参数是事后重建；未把2024物理规模回填2015。已接触评估不能变成盲测。\n- 设备年龄、初始建设队列、细分火电和部门服务是聚合重建；不声称逐厂/逐户普查。\n- 电网是独立投资的全国交付能力代理，不是跨省网络。24小时循环代表日不验证季节性、极端天气或全年可靠性；库存不乘年度权重。\n- 2026年发布的碳配额参考从2027年年度决策启用。终端燃料代理不足以识别工业ETS覆盖，S0不虚构覆盖比例；覆盖机制以单独反例验证。\n- 初态PEO统计桥代理与直接等价值口径分列；后者不作为官方非化石考核。水电统计含抽蓄，完整充放电拆分仍受原观测边界限制。氢在燃料余量/非能源用途内隐含，未另加能源；没有可准入的全国转换初态时不伪造独立氢链、CCUS减排或负排放。\n- 融资、施工及电网参数为明示结构假设，已作范围试验。用电弹性从历史拟合值渐变至条件终值，制造业建设能力增长独立于电站存量并逐渐收敛。\n- BTR工业过程及净碳汇以条件路径外推；中和率R/P不是全温室气体中和认证。社会分配、就业、AI专项及国际冲击属于后续问题三。\n\n"
    text += "复现：`python -B -X utf8 scripts/build_q2_national_inputs.py`，然后 `python -B -X utf8 scripts/run_q2_national.py`。假设全表见 `frozen_design.json`，原件、转换与排除项见问题二输入审查；Q1原契约不变。\n"
    (folder/"report.md").write_text(text,encoding="utf-8")


def main():
    p=argparse.ArgumentParser(); p.add_argument("--output-dir",default="outputs/q2/p2_lb_national"); p.add_argument("--train-only",action="store_true")
    args=p.parse_args()
    out=(ROOT/args.output_dir).resolve()
    if out.parent != ROOT/"outputs/q2":
        raise ValueError("National output must be under outputs/q2")
    if out.exists() and not (out/"run_manifest.json").exists():
        raise ValueError("Refusing to replace unowned output")
    # Archive completed/failed own attempts intact before a new run.
    if out.exists():
        old=load(out/"run_manifest.json")
        if old.get("owner") != "p2/lb":
            raise ValueError("Wrong output owner")
        archive=out.parent/(out.name+".attempts")/old["run_id"]
        archive.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(out),str(archive))
    out.mkdir(parents=True)
    start=time.perf_counter()
    run_id=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    manifest=dict(run_id=run_id,owner="p2/lb",status="running",q2_scientific_complete=False,
        code_hashes={x:sha(ROOT/x) for x in CODE},input_hashes={x:sha(ROOT/x) for x in INPUTS},
        git_sha=subprocess.run(["git","rev-parse","HEAD"],cwd=ROOT,capture_output=True,text=True).stdout.strip(),
        python=sys.version,command=sys.argv,team_approved=False)
    dump(out/"run_manifest.json",manifest)
    latest=out.parent/(out.name+".latest-attempt.json")
    dump(latest,dict(run_id=run_id,status="running",output_valid_for_this_attempt=False))
    try:
        data,design,_=preflight(); dump(out/"frozen_design.json",design)
        with zipfile.ZipFile(out/"model_snapshot.zip","w",zipfile.ZIP_DEFLATED) as snapshot:
            for name in CODE+INPUTS:
                info=zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                snapshot.writestr(info,(ROOT/name).read_bytes())
        calibration=calibrate(data,design,out)
        if args.train_only:
            manifest["status"]="training_only"
        else:
            history=evaluate(data,design,calibration,out)
            baseline,rows,sensitivity,failures=experiments(data,design,calibration,out)
            plot(out,history,baseline,data); report(out,calibration,rows,failures)
            manifest.update(status="success_conditional_candidate",fit_thresholds_passed=calibration["quality"]["acceptance"]["all_thresholds_passed"],
                q2_scientific_complete=False,max_residual=max(r["max_residual"] for r in history.paths+baseline.paths),
                sensitivity_failures=len(failures),completion_note="Four task outputs exist; independent self-check and scientific adequacy assessment still required")
    except Exception as exc:
        manifest.update(status="failed",error_type=type(exc).__name__,error=str(exc)); raise
    finally:
        manifest["elapsed_seconds"]=time.perf_counter()-start
        manifest["outputs"]={f.name:sha(f) for f in sorted(out.iterdir()) if f.is_file() and f.name!="run_manifest.json"}
        dump(out/"run_manifest.json",manifest)
        dump(latest,dict(run_id=run_id,status=manifest["status"],output_valid_for_this_attempt=manifest["status"]=="success_conditional_candidate",
            manifest_sha256=sha(out/"run_manifest.json")))
    print(json.dumps({k:manifest[k] for k in ("status","elapsed_seconds")}),flush=True)


if __name__=="__main__":
    main()
