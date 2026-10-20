"""Read-only workspace inspection and synthetic experiment adapters for the local UI."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

from .agents import numeric, simulate
from .operations import simulate_operation_window, summarize_operation_window

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from workflow_status import local_file, make_report, read_json, sha256

AGENT_DEFAULTS = {
    "carbon_multiplier": 1.0, "renewable_capex_multiplier": 1.0,
    "import_capacity_multiplier": 1.0, "grid_capacity_multiplier": 1.0,
}
OPERATION_DEFAULTS = {
    "storage_capacity_mwh": 40.0, "charge_limit_mw": 20.0, "discharge_limit_mw": 12.0,
    "load_multiplier": 1.0, "carbon_multiplier": 1.0, "grid_capacity_multiplier": 1.0,
}
AGENT_LABELS = {
    "full_feedback": "完整反馈", "frozen_equipment": "冻结设备替代",
    "frozen_generation_investment": "冻结发电投资",
}
WINDOW_LABELS = {
    "normal_variability": "常规波动", "persistent_low_wind_solar": "持续低风光",
    "grid_bottleneck": "送出受限",
}
OPERATION_LABELS = {"with_storage": "有储能", "without_storage": "无储能"}


def _parameters(values, defaults, bounds):
    if values is None:
        values = {}
    if not isinstance(values, dict) or set(values) - set(defaults):
        raise ValueError("Unknown experiment parameter")
    result = {**defaults, **values}
    for name, value in result.items():
        low, high = bounds[name]
        numeric(value, name, minimum=low, maximum=high)
    return result


def _canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _record(root, kind, source_path, config, parameters, cases, summaries):
    code = ["src/energy_model/workbench.py", "src/energy_model/agents.py",
            "src/energy_model/accounting.py", "src/energy_model/operations.py"]
    code_hashes = {path: sha256(root / path) for path in code}
    configuration_hash = hashlib.sha256(_canonical_bytes(config)).hexdigest()
    identity = {"kind": kind, "configuration_sha256": configuration_hash, "code": code_hashes,
                "case_names": list(cases)}
    return {
        "schema_version": "1.0", "mode": "synthetic", "kind": kind,
        "warning": config["warning"],
        "run_id": hashlib.sha256(_canonical_bytes(identity)).hexdigest()[:12],
        "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "parameters": parameters, "configuration": config,
        "configuration_sha256": configuration_hash,
        "source_configuration_path": source_path,
        "source_configuration_sha256": sha256(root / source_path),
        "implementation_sha256": code_hashes,
        "cases": cases, "summaries": summaries,
        "validation_status": "synthetic_mechanisms_only",
        "national_forecast": None, "historical_calibration": None,
        "annual_reliability": None,
    }


def _agent_summary(run):
    rows = run["rows"]
    return {
        "unserved_service_su": sum(s["unserved_service"] for row in rows for s in row["services"].values()),
        "synthetic_emissions": sum(row["energy_related_synthetic_emissions"] for row in rows),
        "equipment_investment_cu": sum(d["investment"] for row in rows for d in row["decisions"]
                                       if d["kind"] == "equipment_substitution"),
        "generation_investment_cu": sum(d["investment"] for row in rows for d in row["decisions"]
                                        if d["kind"] == "generation_investment"),
        "max_abs_balance_residual_eu": max(abs(v) for row in rows for v in row["balance_residuals"].values()),
        "pending_capacity_units": sum(p["capacity_units"] for projects in run["final_projects"].values()
                                       for p in projects if p["online_step"] > rows[-1]["step"]),
    }


def run_agent_experiment(parameters=None, root=ROOT):
    values = _parameters(parameters, AGENT_DEFAULTS, {
        "carbon_multiplier": (0, 3), "renewable_capex_multiplier": (0.25, 2.5),
        "import_capacity_multiplier": (0, 1.5), "grid_capacity_multiplier": (0.1, 1.5),
    })
    path = "examples/synthetic_agents.json"
    config = deepcopy(read_json(root / path))
    config["policy"]["carbon_price_by_step"] = [
        price * values["carbon_multiplier"] for price in config["policy"]["carbon_price_by_step"]
    ]
    config["generation"]["renewable"]["capex"] *= values["renewable_capex_multiplier"]
    for fuel in config["fuels"].values():
        fuel["import_limit"] *= values["import_capacity_multiplier"]
    config["grid"]["generation_transfer_limit"] *= values["grid_capacity_multiplier"]
    cases = {
        "full_feedback": simulate(config),
        "frozen_equipment": simulate(config, substitution=False),
        "frozen_generation_investment": simulate(config, investment=False),
    }
    return _record(root, "agents", path, config, values, cases,
                   {name: _agent_summary(run) for name, run in cases.items()})


def run_operation_experiment(window_name="normal_variability", parameters=None, root=ROOT):
    values = _parameters(parameters, OPERATION_DEFAULTS, {
        "storage_capacity_mwh": (0, 120), "charge_limit_mw": (0, 40),
        "discharge_limit_mw": (0, 40), "load_multiplier": (0.5, 1.5),
        "carbon_multiplier": (0, 3), "grid_capacity_multiplier": (0.1, 1.5),
    })
    path = "examples/synthetic_operation_windows.json"
    config = deepcopy(read_json(root / path))
    if window_name not in config["windows"]:
        raise ValueError("Unknown operation window")
    config["storage"].update(
        capacity_mwh=values["storage_capacity_mwh"], initial_energy_mwh=0,
        charge_limit_mw=values["charge_limit_mw"], discharge_limit_mw=values["discharge_limit_mw"],
    )
    config["policy"]["carbon_price"] *= values["carbon_multiplier"]
    config["grid"]["transfer_limit_mw"] *= values["grid_capacity_multiplier"]
    for period in config["windows"][window_name]["steps"]:
        period["demand_mw"] *= values["load_multiplier"]
    # Export the exact simulated window, rather than unrelated presets.
    config["windows"] = {window_name: config["windows"][window_name]}
    cases = {
        "with_storage": simulate_operation_window(config, window_name),
        "without_storage": simulate_operation_window(config, window_name, storage_enabled=False),
    }
    return _record(root, "operations", path, config, {"window_name": window_name, **values}, cases,
                   {name: summarize_operation_window(run) for name, run in cases.items()})


def workspace_snapshot(root=ROOT):
    """Recheck hashes now, without rewriting catalog, evidence, or workflow state."""
    report = make_report(root)
    formal = report["formal_input_check"]
    accepted = ({item["dataset_path"]: item for item in formal["accepted_inputs"]}
                if formal["passed"] else {})
    reviews = {r["review_id"]: r for r in read_json(root / "data/evidence_reviews.json")["reviews"]}
    declared = {item["dataset_path"] for item in read_json(root / "workflow/model_inputs.json")["inputs"]}
    entries = []
    for item in report["observation_inventory"]:
        path = item["path"]
        data = read_json(root / path)
        admission = accepted.get(path)
        review = reviews[admission["review_id"]] if admission else None
        years = ([r[data["columns"].index("year")] for r in data["rows"]]
                 if "rows" in data and "year" in data["columns"] else [data.get("year")])
        entries.append({
            **item, "years": sorted({year for year in years if year is not None}),
            "admission": "reviewed_scoped_subset" if review else
                         ("evidence_check_failed" if path in declared else "candidate_not_admitted"),
            "review_id": review["review_id"] if review else None,
            "restriction": review.get("usage_restriction", "") if review else
                           ("本次证据检查未通过" if path in declared else "候选，未获正式用途准入"),
            "evidence_files": review["evidence_files"] if review else [],
        })
    return {
        "checked_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "report": report, "datasets": entries,
        "reviewed_measurements": sum(item["measurements"] for item in entries if item["review_id"]),
        "sources": read_json(root / "data/sources.json")["sources"],
    }


def read_observation(path, root=ROOT):
    resolved = local_file(root, path)
    if resolved.parent != (root / "data/observations").resolve() or resolved.suffix != ".json":
        raise ValueError("Only registered observation-directory JSON files can be inspected")
    return read_json(resolved)
