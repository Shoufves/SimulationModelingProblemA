"""Independently audit joint-search coverage, training losses and selection."""
from copy import deepcopy
from datetime import datetime, timezone
from itertools import product
from math import isclose, isfinite
from pathlib import Path
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "src")]
from review_q2_revenue_candidate import review
from run_q2_empirical_support import preflight, scope_inputs, sha
from run_q2_national import loss


def audit_sequence(config, warm, trials, stages):
    """Reconstruct expected candidates and strict training-only winners."""
    position, seen, bests = 0, set(), {}
    if len(stages) != len(config["blocks"]) + 1:
        raise ValueError("Missing search stage")
    for stage, block in enumerate([None, *config["blocks"]]):
        expected = []
        for authority in config["authority_scenarios"]:
            parent = deepcopy(bests[authority]["parameters"] if authority in bests
                              else warm[str(authority)]["parameters"])
            candidates = [parent] if block is None else [
                {**parent, **dict(zip(sorted(block), values))}
                for values in product(*(block[k] for k in sorted(block)))
            ]
            for p in candidates:
                key = authority, tuple(sorted(p.items()))
                if key not in seen:
                    seen.add(key)
                    expected.append((authority, p))
        for authority, parameters in expected:
            if position >= len(trials):
                raise ValueError("Missing declared candidate")
            trial = trials[position]
            if trial["index"] != position or trial["authority"] != authority or trial["parameters"] != parameters:
                raise ValueError("Candidate order or parameters differ from declared search")
            position += 1
            if trial["status"] == "failed":
                if trial["loss"] is not None or not trial.get("error"):
                    raise ValueError("Malformed failed trial")
                continue
            if trial["status"] != "success" or not isfinite(trial["loss"]) or trial["loss"] < 0:
                raise ValueError("Invalid training score")
            if [p["year"] for p in trial["paths"]] != config["training_years"]:
                raise ValueError("Candidate contains non-training years")
            if authority not in bests or trial["loss"] < bests[authority]["loss"]:
                bests[authority] = trial
        expected_best = {str(a): dict(index=b["index"], loss=b["loss"]) for a, b in bests.items()}
        actual = stages[stage]
        if actual != dict(stage=stage, block=block, count=position, best=expected_best):
            raise ValueError("Stage winner is not the deterministic training-only winner")
    if position != len(trials):
        raise ValueError("Undeclared extra trials")
    return bests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder")
    args = parser.parse_args()
    folder = (ROOT / args.folder).resolve()
    if not folder.is_relative_to(ROOT / "outputs/q2_revenue_recalibration"):
        raise ValueError("Expected historical research folder")
    # Existing reviewer checks the complete status and all frozen source hashes.
    fit = review(folder)
    read = lambda name: json.loads((folder / name).read_text("utf-8"))
    config, trials, stages = read("design.json"), read("trials.json"), read("training_stages.json")
    results = read("results.json")
    expected_cases = {f"authority_{a}_{mode}" for a in config["authority_scenarios"]
                      for mode in ("full", "without_municipal_composition")}
    if set(results["results"]) != expected_cases or set(fit["cases"]) != expected_cases:
        raise ValueError("Missing or undeclared evaluation case")
    if read("source_snapshot.json") != results["source_sha256"]:
        raise ValueError("Final sources differ from pre-training snapshot")
    warm_path = ROOT / config["warm_start_run"] / "training_selection.json"
    warm = json.loads(warm_path.read_text("utf-8"))["scenarios"]
    winners = audit_sequence(config, warm, trials, stages)
    selected = read("training_selection.json")
    expected = {str(a): {k: b[k] for k in ("index", "parameters", "loss", "components")} for a, b in winners.items()}
    if selected != dict(selection_uses="2015_2021_only", scenarios=expected):
        raise ValueError("Persisted selection differs from training winners")
    d, s, _ = preflight()
    data, design, *_ = scope_inputs(d, s, warm["25"]["parameters"], recovery_share=.5)
    for target in design["targets"]:
        values = [data[y, target["observation"]] * target["multiplier"]
                  for y in config["training_years"] if (y, target["observation"]) in data]
        target["scale"] = target.get("absolute_scale") or sum(values) / len(values) * target["scale_from_training_mean_fraction"]
    errors = []
    for trial in trials:
        if trial["status"] != "success":
            continue
        actual, components, _ = loss(trial["paths"], data, design, config["training_years"], "independent_joint_audit")
        error = abs(actual - trial["loss"])
        errors.append(error)
        if not isclose(actual, trial["loss"], rel_tol=1e-12, abs_tol=1e-12) or components != trial["components"]:
            raise ValueError("Recomputed training score/components differ")
    for authority, winner in winners.items():
        full = read(f"authority_{authority}_full.json")
        if full["parameters"] != winner["parameters"] or full["paths"][:len(config["training_years"])] != winner["paths"]:
            raise ValueError("Evaluation did not preserve selected training trajectory")
    checks = dict(declared_candidate_coverage=True, deterministic_training_only_selection=True,
                  every_successful_training_loss_recomputed=True, training_trajectories_preserved_in_evaluation=True,
                  all_frozen_source_hashes_match=True, six_evaluation_cases_preserved=True,
                  before_and_after_source_snapshots_match=True)
    result = dict(created_at=datetime.now(timezone.utc).isoformat(), checks=checks, passed=all(checks.values()),
                  trial_count=len(trials), failed_count=sum(t["status"] == "failed" for t in trials),
                  maximum_training_loss_difference=max(errors, default=0),
                  selected_training_loss={a: b["loss"] for a, b in winners.items()},
                  unchanged_fit_failures={n: c["failed_checks"] for n, c in fit["cases"].items()},
                  source_sha256={p.relative_to(ROOT).as_posix(): sha(p.relative_to(ROOT)) for p in
                                 (Path(__file__), folder / "trials.json", folder / "training_stages.json",
                                  folder / "training_selection.json", folder / "results.json")},
                  scientific_acceptance=False, team_approved=False)
    (folder / "search_review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "source_sha256"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
