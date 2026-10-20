"""Cross-run equivalence; never a replacement for a run's own SHA checks.

Numbers use the already frozen Q3 comparison tolerances. JSON integer types,
booleans, strings (including embedded hashes), structure and discrete choices
are exact. CSV has no type metadata, so identifiers and discrete columns are
explicitly exact; only finite numeric cells in other columns use tolerances.
"""
import csv
import gzip
import hashlib
import json
from math import isclose, isfinite
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISCRETE = frozenset("""id project policy_id selected selected_policy selected_epsilon
h01_epsilon epsilon vR vE multiplier delay priority period year decision_year
online_year exit_year decision online exit first_online_year first_commissioning_year
start_hour end_hour event_start_hour event_end_hour hours duration_hours
time_resolution_hours status solve_status recovery_status scenario sector carrier
tech actor kind mode rule family event split response stage label target probe
actions feasible pareto admissible valid violations grids capital_projects""".split())
Q3_JSON = frozenset(("event_initial_state.json", "frozen_config.json",
    "inherited_q2_design.json", "inherited_parameters.json", "selection_lock.json",
    "policy_tradeoffs.json", "transition_completion.json", "transition_failures.json"))
DIAGNOSTIC_METADATA = frozenset(("diagnostic_source.py", "frozen_protocol.json",
    "source_equivalence.json", "scientific_equivalence_source.py", "frozen_reproduction_protocol.json"))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def tolerances(config):
    n = config["numerical"]
    values = dict(relative=n["relative_comparison_tolerance"],
                  absolute=n["absolute_comparison_tolerance"],
                  currency_absolute=n["cash_balance_absolute_cny"])
    # These are the existing comparison bounds, not configurable relaxations.
    require(values == dict(relative=1e-10, absolute=1e-6, currency_absolute=.01),
            "Frozen Q3 comparison tolerances changed")
    return values


def stats():
    return dict(numeric_leaves=0, numeric_differences=0, exact_leaves=0,
                project_records=0, max_absolute_difference=0., max_relative_difference=0., examples=[])


def discrete(key):
    return key in DISCRETE or "sha256" in key or "hash" in key or key.endswith(("_year", "_records", "_count"))


def compare_value(a, b, bounds, result, path=(), exact=False):
    label = "/".join(map(str, path)) or "<root>"
    require(type(a) is type(b), "Scientific type differs: " + label)
    if isinstance(a, dict):
        require(a.keys() == b.keys(), "Scientific keys differ: " + label)
        if "id" in a and ("decision_year" in a or "online_year" in a):
            result["project_records"] += 1
        elif "actor" in a and "online" in a:
            result["project_records"] += 1
        for key in a:
            compare_value(a[key], b[key], bounds, result, path + (key,), exact or discrete(key))
    elif isinstance(a, list):
        require(len(a) == len(b), "Scientific list length differs: " + label)
        for i, (x, y) in enumerate(zip(a, b)):
            compare_value(x, y, bounds, result, path + (i,), exact)
    elif type(a) is float:
        result["numeric_leaves"] += 1
        require(isfinite(a) and isfinite(b), "Nonfinite scientific value: " + label)
        key = next((p for p in reversed(path) if isinstance(p, str)), "")
        absolute = bounds["currency_absolute"] if "cny" in key.lower() else bounds["absolute"]
        require(a == b if exact else isclose(a, b, rel_tol=bounds["relative"], abs_tol=absolute),
                f"Scientific value differs: {label}: {a!r} != {b!r}")
        if a != b:
            difference = abs(a - b)
            relative = difference / max(abs(a), abs(b))
            result["numeric_differences"] += 1
            result["max_absolute_difference"] = max(result["max_absolute_difference"], difference)
            result["max_relative_difference"] = max(result["max_relative_difference"], relative)
            if len(result["examples"]) < 3:
                result["examples"].append(dict(path=label, reference=a, candidate=b, absolute_difference=difference))
    else:
        result["numeric_leaves" if type(a) is int else "exact_leaves"] += 1
        require(a == b, f"Scientific discrete value differs: {label}: {a!r} != {b!r}")


def csv_content(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    require(bool(rows), "Empty scientific CSV: " + str(path))
    header = rows[0]
    # Existing exports can repeat a header (e.g. storage capacity). Compare
    # every column by position, never silently drop one with DictReader.
    require(all(len(row) == len(header) for row in rows[1:]), "Ragged scientific CSV: " + str(path))
    return header, rows[1:]


def compare_file(left, right, bounds, name):
    left, right = Path(left), Path(right)
    result = stats()
    if name.endswith(".csv"):
        ah, a = csv_content(left)
        bh, b = csv_content(right)
        require(ah == bh and len(a) == len(b), "Scientific CSV shape differs: " + name)
        for i, (x, y) in enumerate(zip(a, b)):
            for j, (key, u, v) in enumerate(zip(ah, x, y)):
                if not discrete(key):
                    try:
                        u, v = float(u), float(v)
                    except ValueError:
                        u, v = x[j], y[j]
                compare_value(u, v, bounds, result, (name, i, j, key), discrete(key))
    else:
        def read(p):
            return json.loads(gzip.decompress(p.read_bytes())) if name.endswith(".json.gz") else load(p)
        compare_value(read(left), read(right), bounds, result, (name,),
                      name in {"frozen_config.json", "inherited_q2_design.json", "inherited_parameters.json"})
    result.update(file=name, reference_sha256=sha(left), candidate_sha256=sha(right))
    result["bitwise_equal"] = result["reference_sha256"] == result["candidate_sha256"]
    result["status"] = "byte_equal" if result["bitwise_equal"] else "scientifically_equivalent"
    return result


def scientific_names(manifest, kind="q3"):
    names = set(manifest["outputs"])
    if kind == "diagnostic":
        return sorted(names - DIAGNOSTIC_METADATA)
    return sorted(n for n in names if
        (n.endswith(".csv") and "/" not in n and n != "gaps_and_conflicts.csv") or n in Q3_JSON or
        n.startswith(("cases/", "events/", "plans/", "sensitivity_locks/")))


def compare_outputs(left, right, left_manifest, right_manifest, bounds, kind="q3"):
    names = scientific_names(left_manifest, kind)
    require(names == scientific_names(right_manifest, kind), "Scientific file inventory differs")
    require(bool(names), "No scientific files to compare")
    files = [compare_file(Path(left) / n, Path(right) / n, bounds, n) for n in names]
    return dict(status="passed", tolerances=bounds, files=files, file_count=len(files),
                byte_equal_files=sum(f["bitwise_equal"] for f in files),
                numeric_leaves=sum(f["numeric_leaves"] for f in files),
                numeric_differences=sum(f["numeric_differences"] for f in files),
                project_records=sum(f["project_records"] for f in files),
                exact_choices_and_embedded_hashes=True)


def run_identity(folder, manifest):
    return dict(run_id=manifest["run_id"], manifest_sha256=sha(folder / "run_manifest.json"),
                latest_attempt_sha256=sha(folder.parent / (folder.name + ".latest-attempt.json")),
                code_hashes=manifest["code_hashes"], input_hashes=manifest["input_hashes"],
                output_hashes=manifest["outputs"])


def compare_runs(reference, candidate):
    from run_q3 import verify_latest
    reference, candidate = Path(reference).resolve(), Path(candidate).resolve()
    a, b = verify_latest(reference), verify_latest(candidate)
    for folder, m in ((reference, a), (candidate, b)):
        require(m["status"] == "conditional_experiments_completed" and m["exit_code"] == 0,
                "Complete successful Q3 run required")
        require(set(m["outputs"]) == {p.relative_to(folder).as_posix() for p in folder.rglob("*")
                                     if p.is_file() and p.name != "run_manifest.json"},
                "Q3 output file inventory changed")
    for key in ("code_hashes", "input_hashes"):
        require(a[key] == b[key], "Scientific model/input fingerprints differ: " + key)
    result = compare_outputs(reference, candidate, a, b, tolerances(load(reference / "frozen_config.json")))
    result.update(reference=run_identity(reference, a), candidate=run_identity(candidate, b),
                  comparator_sha256=sha(__file__))
    return result


def admit_source(source, protocol):
    """Bind an intact new run to the immutable original, never refresh its hashes."""
    source = Path(source).resolve()
    profile_path = ROOT / protocol["reproduction_protocol"]
    require(sha(profile_path) == protocol["reproduction_protocol_sha256"], "Reproduction protocol changed")
    profile = load(profile_path)
    reference = ROOT / profile["reference_output"]
    require(sha(reference / "run_manifest.json") == profile["reference_manifest_sha256"],
            "Frozen reference manifest changed")
    for name, expected in protocol["source_files"].items():
        require(sha(reference / name) == expected, "Frozen reference scientific evidence changed: " + name)
    evidence = compare_runs(reference, source)
    require(evidence["candidate"]["code_hashes"] == protocol["model_code_hashes"] and
            evidence["candidate"]["input_hashes"] == protocol["input_hashes"], "Frozen diagnostic model or inputs changed")
    require(evidence["tolerances"] == profile["tolerances"], "Comparison protocol tolerance mismatch")
    evidence.update(reproduction_protocol_sha256=sha(profile_path))
    return evidence
