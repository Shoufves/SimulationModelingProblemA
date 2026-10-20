"""Joint training search across renewable yield, construction and investment.

Keep the historical mechanism, target weights and acceptance thresholds fixed.
The earlier coarse search is a warm start, not proof of a global optimum.
All three unknown commitment authorities remain separate reported scenarios.
"""
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from itertools import product
from pathlib import Path
import argparse
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from run_q2_revenue_recalibration import build, preflight, training_loss, metrics, extract, save, sha
from review_q2_revenue_candidate import review

WORKER_INPUTS = None


def worker_init():
    global WORKER_INPUTS
    data, design, _ = preflight()
    WORKER_INPUTS = data, design


def trial(payload):
    index, authority, parameters, config = payload
    data, design = WORKER_INPUTS
    record = dict(index=index, authority=authority, parameters=parameters)
    try:
        model, *_, extra = build(data, design, config, parameters, authority, end_year=2021)
        score, components, _ = training_loss(model)
        record.update(status="success", loss=score, components=components,
                      paths=model.paths, source_paths=extra)
    except (ValueError, RuntimeError) as exc:
        record.update(status="failed", loss=None, error=str(exc))
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", default="workflow/q2_joint_recalibration.json")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    design_path = (ROOT / args.design).resolve()
    if not design_path.is_relative_to(ROOT / "workflow"):
        raise ValueError("Joint search design must be in workflow")
    config = json.loads(design_path.read_text("utf-8"))
    source = (ROOT / config["warm_start_run"]).resolve()
    if not source.is_relative_to(ROOT / "outputs/q2_revenue_recalibration"):
        raise ValueError("Expected a prior historical research run")
    review(source)
    old = json.loads((source / "results.json").read_text("utf-8"))
    selection = json.loads((source / "training_selection.json").read_text("utf-8"))
    if selection["selection_uses"] != "2015_2021_only":
        raise ValueError("Warm start was not selected on training only")
    if config["training_years"] != list(range(2015, 2022)) or config["evaluation_years"] != [2022, 2023, 2024]:
        raise ValueError("Unreviewed split")
    if config["authority_scenarios"] != [5, 25, 100]:
        raise ValueError("Do not select an unknown authority from evaluation")
    sources = set(old["source_sha256"]) | {
        design_path.relative_to(ROOT).as_posix(), Path(__file__).relative_to(ROOT).as_posix(),
        (source / "results.json").relative_to(ROOT).as_posix(),
        (source / "training_selection.json").relative_to(ROOT).as_posix(),
        "docs/sources/q2_joint_search.md",
    }
    hashes = {p: sha(p) for p in sorted(sources)}
    folder = ROOT / "outputs/q2_revenue_recalibration" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    save(folder / "design.json", config)
    save(folder / "source_snapshot.json", hashes)
    save(folder / "status.json", dict(status="running", scientific_acceptance=False))
    trials, bests, seen, stages = [], {}, {}, []
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = "1"
    try:
        with ProcessPoolExecutor(max_workers=max(1, min(4, args.workers)), initializer=worker_init) as pool:
            # Stages are sequential; independent candidates are evaluated in
            # parallel and consumed in deterministic input order (including ties).
            for stage, block in enumerate([None, *config["blocks"]]):
                payloads = []
                for authority in config["authority_scenarios"]:
                    parent = deepcopy(bests[authority]["parameters"] if authority in bests
                                      else selection["scenarios"][str(authority)]["parameters"])
                    candidates = [parent] if block is None else [
                        {**parent, **dict(zip(sorted(block), values))}
                        for values in product(*(block[k] for k in sorted(block)))
                    ]
                    for parameters in candidates:
                        key = authority, tuple(sorted(parameters.items()))
                        if key in seen:
                            continue
                        index = len(trials) + len(payloads)
                        seen[key] = index
                        payloads.append((index, authority, parameters, config))
                for item in pool.map(trial, payloads):
                    if item.get("source_paths") and not set(item["source_paths"]).issubset(sources):
                        raise ValueError("Unfrozen worker input source")
                    trials.append(item)
                    authority = item["authority"]
                    if item["loss"] is not None and (authority not in bests or item["loss"] < bests[authority]["loss"]):
                        bests[authority] = item
                    if len(trials) % 24 == 0:
                        save(folder / "trials.json", trials)
                        print("completed", len(trials), "training candidates", flush=True)
                if set(bests) != set(config["authority_scenarios"]):
                    raise ValueError("At least one authority has no successful training candidate")
                stages.append(dict(stage=stage, block=block, count=len(trials),
                                   best={a: dict(index=b["index"], loss=b["loss"]) for a, b in bests.items()}))
                save(folder / "trials.json", trials)
                save(folder / "training_stages.json", stages)
                print("stage", stage, {a: round(b["loss"], 6) for a, b in bests.items()}, flush=True)
        if any(sha(p) != v for p, v in hashes.items()):
            raise ValueError("Sources changed during training")
        chosen = {str(a): {k: b[k] for k in ("index", "parameters", "loss", "components")} for a, b in bests.items()}
        # Durable selection receipt precedes any evaluation execution.
        save(folder / "training_selection.json", dict(selection_uses="2015_2021_only", scenarios=chosen))
        data, design, _ = preflight()
        refs = {(r["year"], r["category"]): r["value_twh"] * 1e6 for r in extract()[0]}
        results = {}
        for authority, best in chosen.items():
            for mode, options in (("full", {}), ("without_municipal_composition", dict(include_bio=False))):
                name = f"authority_{authority}_{mode}"
                m, assumptions, prices, changes, extra = build(data, design, config, best["parameters"],
                                                               int(authority), end_year=2024, **options)
                if not set(extra).issubset(sources):
                    raise ValueError("Unfrozen evaluation input source")
                output = dict(parameters=best["parameters"], assumptions=assumptions, metrics=metrics(m, refs),
                    paths=m.paths, finance=m.finance, operations=m.operations, projects=m.projects,
                    assets=m.assets, balances=m.balances, behavior=m.behavior, price_inputs=prices,
                    lifetime_rule_changes=changes, fund_history=m.revenue_policy.history,
                    municipal_service_history=m.bioenergy.history if m.bioenergy else [],
                    training_components=training_loss(m)[1])
                save(folder / (name + ".json"), output)
                results[name] = dict(metrics=output["metrics"], end=m.paths[-1],
                    max_cash_residual_cny=max(abs(r["cash_balance_residual_cny"]) for r in m.paths),
                    max_physical_residual=max(r["max_residual"] for r in m.paths))
                print(name, {t: round(output["metrics"][t]["already_seen_evaluation"]["mape"] * 100, 2)
                             for t in ("gas", "oil", "biomass", "wind", "solar")}, flush=True)
        if any(sha(p) != v for p, v in hashes.items()):
            raise ValueError("Sources changed during evaluation")
        save(folder / "results.json", dict(status="conditional_retrained_candidate_not_final_acceptance",
            training_only_selection=True, evaluation_identity="already_seen_not_blind",
            production_default_changed=False, source_sha256=hashes, results=results))
        lines = ["# 风光收益与建设的联合训练", "", "模型机制、目标权重和误差门槛保持不变；2015—2021选参，2022—2024已接触评估。",
                 "三种未知承诺额度分别训练并全部报告；不按评估选择财政制度。有限搜索不证明全局最优。", "",
                 "|条件|气电MAPE|纯油MAPE|生物能源MAPE|风电MAPE|光伏MAPE|", "|---|---:|---:|---:|---:|---:|"]
        for name, item in results.items():
            lines.append("|" + name + "|" + "|".join(
                f"{item['metrics'][t]['already_seen_evaluation']['mape']*100:.2f}%"
                for t in ("gas", "oil", "biomass", "wind", "solar")) + "|")
        lines += ["", "训练设计、所有成功和失败尝试、先于评估保存的选参记录、逐项误差与物理/现金账均保留。此结果不能替代正式预测和整题验收。", ""]
        (folder / "report.md").write_text("\n".join(lines), "utf-8")
        save(folder / "status.json", dict(status="complete_conditional_experiment", scientific_acceptance=False,
                                         trial_count=len(trials)))
    except Exception as exc:
        save(folder / "status.json", dict(status="failed", scientific_acceptance=False, error=str(exc)))
        raise
    print(folder.relative_to(ROOT).as_posix(), flush=True)


if __name__ == "__main__":
    main()
