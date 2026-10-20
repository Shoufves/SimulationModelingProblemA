"""Observed-2024 opening, 2025--2060 paired scenarios and bounded policies.

Historical parameters are selected on 2015--2021 only. Observed opening stocks
are initial conditions, never evidence of historical predictive accuracy.
"""
from concurrent.futures import ProcessPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/"scripts"), str(ROOT/"src")]
from run_q2_national import preflight, targets, csv_write
from q2_current_factory import build
from review_q2_revenue_candidate import review
from energy_model.q2_forward_current import activate_forward, forward_summary


def load(path):
    return json.loads(Path(path).read_text("utf-8"))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n", "utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


WORKER = None


def worker_init(hashes):
    global WORKER
    from q2_verified_input_cache import install
    install(hashes)
    WORKER = preflight()[:2]


def trial(payload):
    source, authority, spec, folder, endpoint = payload
    name = spec["name"]
    try:
        data, design = WORKER
        source = ROOT/source
        config = load(source/"design.json")
        selection = load(source/"training_selection.json")
        if selection["selection_uses"] != "2015_2021_only":
            raise ValueError("Training selection is not admissible")
        theta = selection["scenarios"][str(authority)]["parameters"]
        opening_variant = spec.pop("opening_variant", {})
        model, assumptions, sources = build(data, design, config, theta, authority,
                                           opening_variant=opening_variant)
        initial = dict(year=2024, total_capacity_mw=data[2024,"total_capacity_mw"],
            primary_energy_tce=data[2024,"consumption_10ktce"]*1e4,
            generator_capacity_mw=dict(model.initial_capacities),
            opening_balance_sheet=deepcopy(model.opening_balance_sheet),
            opening_subsidy_replay=deepcopy(model.opening_subsidy_replay),
            condition="observed aggregate physical scale; age/queue/accounts reconstructed")
        model = activate_forward(model, config, spec, end_year=endpoint)
        model.run(endpoint)
        paths = [r for r in model.paths if r["year"]>=2025]
        target, peak = targets(paths, model.data, model.design) if endpoint==2060 else ([], {})
        summary = forward_summary(model)
        result = dict(name=name, spec=spec, authority=authority, thermal_mode=config["thermal_mode"],
            status="complete_conditional_projection_not_scientific_acceptance",
            historical_parameter_run=source.relative_to(ROOT).as_posix(), independent_observed_initial_state=True,
            opening_variant=opening_variant, initial_path=initial, paths=paths, targets=target, peak=peak, summary=summary,
            assumptions={**assumptions, **model.forward_assumptions},
            projects=model.projects, infrastructure_projects=model.grid.queue,
            finance=[r for r in model.finance if r["year"]>=2025],
            behavior=[r for r in model.behavior if r["year"]>=2025],
            operations=[r for r in model.operations if r["year"]>=2025],
            balances=[r for r in model.balances if r["year"]>=2025],
            subsidy_fund_history=[r for r in model.revenue_policy.history if r["year"]>=2025])
        path = folder/(name+".json")
        save(path, result)
        csv_write(folder/(name+"_path.csv"), paths)
        return dict(name=name, status="success", authority=authority, spec=spec,
                    result_file=path.name, result_sha256=sha(path), summary=summary,
                    targets=target, peak=peak, thermal_mode=config["thermal_mode"])
    except Exception as exc:
        result = dict(name=name, status="failed", spec=spec, error=str(exc), traceback=traceback.format_exc())
        save(folder/(name+"_failed.json"), result)
        return result


def paired_effects(results):
    lookup = {r["name"]:r for r in results if r["status"]=="success"}
    metrics = ("cumulative_unmet_service_mwh", "cumulative_positive_co2_t", "discounted_resource_cost_cny")
    rows = []
    for suffix in ("", "_freeze_gas"):
        keys = [n+suffix for n in ("S0", "SG", "SW", "SGW")]
        if not all(k in lookup for k in keys):
            continue
        for metric in metrics:
            a,g,w,gw = [lookup[k]["summary"][metric] for k in keys]
            rows.append(dict(channel="normal" if not suffix else "new_gas_investment_frozen",
                metric=metric, S0=a, SG=g, SW=w, SGW=gw,
                gas_effect=g-a, weather_effect=w-a, joint_effect=gw-a, interaction=gw-g-w+a,
                interpretation="signed algebraic interaction; smaller interaction is not lower absolute shortage"))
    return rows


def policy_frontier(results):
    rows = [r for r in results if r["status"]=="success" and r["spec"].get("kind")=="policy_candidate"]
    # Minimise all three; report the finite tested set, not a global optimum.
    metrics = ("cumulative_unmet_service_mwh", "cumulative_positive_co2_t", "discounted_resource_cost_cny")
    answer = []
    for row in rows:
        dominated = []
        for other in rows:
            if other is row:
                continue
            a,b = row["summary"],other["summary"]
            if all(b[k]<=a[k]+max(1,abs(a[k]))*1e-9 for k in metrics) and any(b[k]<a[k]-max(1,abs(a[k]))*1e-9 for k in metrics):
                dominated.append(other["name"])
        answer.append(dict(name=row["name"],pareto_in_tested_set=not dominated,dominated_by=dominated,
                           **{k:row["summary"][k] for k in metrics},
                           infrastructure_approved_cny=row["summary"]["infrastructure_approved_cny"],
                           not_global_optimum=True))
    return answer


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--design", default="workflow/q2_current_delivery.json")
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--end-year", type=int, default=2060)
    args = parser.parse_args()
    path = ROOT/args.design
    config = load(path)
    specs = [s for s in config["scenarios"] if args.only is None or s["name"] in args.only]
    if not specs or len({s["name"] for s in specs})!=len(specs):
        raise ValueError("Nonempty distinct scenario names required")
    sources = {args.design, "scripts/run_q2_current_delivery.py", "scripts/run_q2_forward_delivery.py",
               "src/energy_model/q2_forward_current.py", "scripts/q2_current_factory.py",
               "docs/sources/q2_current_initial_state.md", "docs/sources/q2_current_delivery.md"}
    for source in set(config["historical_runs"].values()):
        review(ROOT/source)
        result = load(ROOT/source/"results.json")
        sources.update(result["source_sha256"])
        sources.update(source+"/"+p for p in ("design.json", "training_selection.json", "results.json",
            "authority_5_full.json", "authority_25_full.json", "authority_100_full.json"))
    # Obtain every physical-opening source before freezing the experiment.
    data, design = preflight()[:2]
    for source in set(config["historical_runs"].values()):
        historical_config = load(ROOT/source/"design.json")
        theta = load(ROOT/source/"training_selection.json")["scenarios"]["25"]["parameters"]
        _, _, opening_sources = build(data, design, historical_config, theta, 25)
        sources.update(opening_sources)
    hashes = {p:sha(ROOT/p) for p in sorted(sources)}
    folder = ROOT/"outputs/q2_current_delivery"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    save(folder/"design.json",config)
    save(folder/"source_snapshot.json",hashes)
    save(folder/"status.json",dict(status="running",scientific_acceptance=False))
    print(folder.relative_to(ROOT).as_posix(),flush=True)
    payloads=[]
    for raw in specs:
        spec=deepcopy(raw)
        mode=spec.pop("thermal_mode", "net58")
        authority=spec.pop("authority",25)
        payloads.append((config["historical_runs"][mode],authority,spec,folder,args.end_year))
    for name in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS"):
        os.environ[name]="1"
    results=[]
    with ProcessPoolExecutor(max_workers=args.workers,initializer=worker_init,initargs=(hashes,)) as pool:
        for result in pool.map(trial,payloads,chunksize=1):
            results.append(result)
            print(result["name"],result["status"],result.get("error",result.get("summary")),flush=True)
    if any(sha(ROOT/p)!=h for p,h in hashes.items()):
        save(folder/"status.json",dict(status="failed_source_changed",scientific_acceptance=False))
        raise ValueError("A source changed during forward experiments")
    pairs=paired_effects(results)
    frontier=policy_frontier(results)
    save(folder/"results.json",dict(status="conditional_scenario_set",scientific_acceptance=False,
        source_sha256=hashes,results=results,paired_effects=pairs,policy_frontier=frontier))
    csv_write(folder/"paired_effects.csv",pairs)
    csv_write(folder/"policy_frontier.csv",frontier)
    csv_write(folder/"targets.csv",[dict(scenario=r["name"],**t) for r in results if r["status"]=="success" for t in r["targets"]])
    failed=sum(r["status"]!="success" for r in results)
    save(folder/"status.json",dict(status="complete_conditional_scenarios" if not failed else "completed_with_failures",
        cases=len(results),failures=failed,scientific_acceptance=False))
    print("COMPLETE",len(results),"cases",failed,"failures",flush=True)


if __name__=="__main__":
    main()
