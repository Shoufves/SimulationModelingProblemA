"""Training-only model comparison for the conditional nonpower fuel residual.

This is a driver diagnosis, not an integrated energy-system simulation. A
residual includes transformation/statistical differences and is not observed
sectoral final use. No evaluation residual is injected into the annual model.
"""
from datetime import datetime, timezone
from itertools import product
from math import exp, expm1, log
from pathlib import Path
import argparse
import json
import sys

import numpy as np
from scipy.optimize import lsq_linear

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from energy_model.q2_identification import nonpower_residual
from run_q2_empirical_support import preflight, scope_inputs, sha
from review_q2_revenue_candidate import review


def fit(data, years, fuel, intensity, tau=None, penalty=0):
    anchor = nonpower_residual(data, 2014, fuel)
    x = np.array([log(data[y, "real_gdp"] / data[2014, "real_gdp"]) for y in years])
    z = np.array([log(nonpower_residual(data, y, fuel) / anchor) - (y - 2014) * log(1 - intensity) for y in years])
    alpha0 = float(x @ z / (x @ x))
    if tau is None:
        return dict(alpha=alpha0, beta=0., tau=None, anchor_mwh=anchor)
    # The extra adjustment saturates; it cannot become an unbounded quadratic
    # trend. Fixed, symmetric bounds apply to all fuels before evaluation.
    matrix = np.column_stack((x, [-expm1(-(y - 2014) / tau) for y in years]))
    matrix = np.vstack((matrix, np.eye(2) * penalty**.5))
    rhs = np.concatenate((z, np.array([min(2., max(-1., alpha0)), 0.]) * penalty**.5))
    solution = lsq_linear(matrix, rhs, bounds=([-1., -1.], [2., 1.]), tol=1e-12)
    if not solution.success:
        raise ValueError("Training driver solve failed")
    return dict(alpha=float(solution.x[0]), beta=float(solution.x[1]), tau=tau, anchor_mwh=anchor)


def predict(parameters, data, year, intensity):
    elapsed = year - 2014
    adjustment = (parameters["beta"] * -expm1(-elapsed / parameters["tau"])) if parameters["tau"] else 0.
    return parameters["anchor_mwh"] * exp(parameters["alpha"] * log(data[year, "real_gdp"] / data[2014, "real_gdp"])
                                        + adjustment) * (1 - intensity)**elapsed


def choose(data, fuel, intensity, config):
    candidates = [dict(tau=None, penalty=0)] + [dict(tau=t, penalty=p) for t, p in product(config["taus"], config["penalties"])]
    records = []
    for candidate in candidates:
        folds = []
        for target in config["rolling_targets"]:
            trained = fit(data, list(range(2015, target)), fuel, intensity, **candidate)
            value = predict(trained, data, target, intensity)
            observed = nonpower_residual(data, target, fuel)
            folds.append(dict(target_year=target, training_years=list(range(2015, target)),
                              prediction_mwh=value, conditional_residual_mwh=observed,
                              squared_log_error=log(value / observed)**2))
        records.append(dict(**candidate, folds=folds,
                            rolling_score=sum(r["squared_log_error"] for r in folds)/len(folds),
                            parameters=fit(data, config["training_years"], fuel, intensity, **candidate)))
    selected = min(range(len(records)), key=lambda i: records[i]["rolling_score"])
    return dict(selected_index=selected, candidates=records)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--historical-run", default="outputs/q2_revenue_recalibration/20261019T221146446406Z")
    args = parser.parse_args()
    prior = (ROOT / args.historical_run).resolve()
    if not prior.is_relative_to(ROOT / "outputs/q2_revenue_recalibration"):
        raise ValueError("Expected a historical model run")
    review(prior)
    config = dict(training_years=list(range(2015, 2022)), evaluation_years=[2022, 2023, 2024],
                  rolling_targets=[2018, 2019, 2020, 2021], taus=[1., 2., 4., 8.], penalties=[0., .01, .1, 1.],
                  transient_form="alpha*log(GDP/GDP2014)+beta*(1-exp(-elapsed/tau))",
                  bounds=dict(alpha=[-1, 2], beta=[-1, 1]), selection="minimum rolling squared log error, baseline first on ties",
                  scope="conditional nonpower residual diagnosis only; no annual model parameters replaced")
    folder = ROOT / "outputs/q2_nonpower_diagnostic" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    save = lambda n, obj: (folder / n).write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+"\n", "utf-8")
    save("design.json", config)
    d, s, _ = preflight()
    warm = json.loads((prior / "training_selection.json").read_text("utf-8"))["scenarios"]["25"]["parameters"]
    data, design, *_ = scope_inputs(d, s, warm, recovery_share=.5)
    intensity = design["assumptions"]["service_intensity_decline"]
    chosen = {fuel: choose(data, fuel, intensity, config) for fuel in ("coal", "oil", "gas")}
    save("training_selection.json", chosen)  # precedes evaluation
    rows = []
    for fuel, record in chosen.items():
        for method, index in (("anchored_gdp", 0), ("training_selected", record["selected_index"])):
            parameters = record["candidates"][index]["parameters"]
            for year in config["training_years"] + config["evaluation_years"]:
                value = predict(parameters, data, year, intensity)
                actual = nonpower_residual(data, year, fuel)
                rows.append(dict(fuel=fuel, method=method, year=year,
                                 split="training" if year <= 2021 else "already_seen_evaluation",
                                 conditional_residual_mwh=actual, model_residual_mwh=value, relative_error=value/actual-1))
    sources = set(json.loads((prior / "results.json").read_text("utf-8"))["source_sha256"])
    sources.add(Path(__file__).relative_to(ROOT).as_posix())
    save("results.json", dict(rows=rows, source_sha256={p: sha(p) for p in sorted(sources)},
         selected_before_evaluation=True, integrated_model_changed=False, scientific_acceptance=False,
         limits=["Residuals are not observed final/industrial consumption", "No industrial activity evidence or causal policy interpretation",
                 "A driver-only error is not the national simulation error", "Already-seen evaluation remains already seen"]))
    lines = ["# 非电燃料趋势诊断", "", "仅用2015—2021内部滚动预测选择GDP趋势或有界渐近调整项，之后报告已接触评估。未把评估残差注入年度模型。",
             "输入是一次燃料减固定效率发电用料的条件残差，含非能源和其他转换/统计差异，不能当作工业终端实测。", "",
             "|燃料|方法|训练期MAPE|已接触评估MAPE|2024偏差|", "|---|---|---:|---:|---:|"]
    for fuel in chosen:
        for method in ("anchored_gdp", "training_selected"):
            subset = [r for r in rows if r["fuel"] == fuel and r["method"] == method]
            scores = [sum(abs(r["relative_error"]) for r in subset if r["split"] == split)/sum(r["split"] == split for r in subset)
                      for split in ("training", "already_seen_evaluation")]
            lines.append(f"|{fuel}|{method}|{scores[0]*100:.2f}%|{scores[1]*100:.2f}%|{subset[-1]['relative_error']*100:+.2f}%|")
    lines += ["", "此独立诊断尚未改变系统调度、投资、现金和前瞻，不能用表中误差宣告全模型修复。", ""]
    (folder / "report.md").write_text("\n".join(lines), "utf-8")
    print(folder.relative_to(ROOT).as_posix())
    print("\n".join(lines))


if __name__ == "__main__":
    main()
