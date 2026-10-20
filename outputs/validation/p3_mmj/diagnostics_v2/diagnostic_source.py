"""Reproduce and explain frozen Q3 gas, shortage and carbon results.

Capacity probes are controlled diagnostic operations, not funded policies. The
frozen original run and its model files are never edited. All service results
remain separate, including adverse effects of changing service priorities.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
from math import fsum, isclose
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from energy_model.q2_national import operate_national, EF
from energy_model.q3_events import run_event, safety_metrics
from energy_model.q3_transition import service_id
from run_q2_national import csv_write
from run_q3 import verify_latest


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def unpack(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def close(a, b, label, absolute=.05):
    if not isclose(a, b, abs_tol=absolute, rel_tol=1e-10):
        raise ValueError(f"{label}: {a} != {b}")


def grouped_result(rows):
    return {kind: [row for row in rows if row["kind"] == kind]
            for kind in ("fuel", "demand", "generation", "storage")}


def service_metrics(result):
    totals = defaultdict(lambda: [0., 0.])
    for row in result["demand"]:
        key = service_id(row)
        totals[key][0] += row["requested_service_mwh"]
        totals[key][1] += row["unmet_service_mwh"]
    return {key: dict(requested_service_mwh=req, unmet_service_mwh=unmet,
                      unmet_fraction=unmet / req if req else None)
            for key, (req, unmet) in totals.items()}


def carbon_components(result, weight=1):
    """Calculate from physical fuel inputs; independent of exported CO2 fields."""
    rows = []
    for fuel in EF:
        direct = fsum(r["direct_mwh"] for r in result["fuel"] if r["fuel"] == fuel)
        material = fsum(r["input_mwh"] for r in result["demand"]
                        if r["sector"] == "nonenergy_feedstock" and r["carrier"] == fuel)
        conversion = fsum(r["conversion_mwh"] for r in result["fuel"] if r["fuel"] == fuel)
        rows.append(dict(fuel=fuel, direct_combustion_mwh=(direct - material) * weight,
                         conversion_input_mwh=conversion * weight,
                         direct_co2_t=(direct - material) * EF[fuel] * weight,
                         conversion_co2_t=conversion * EF[fuel] * weight))
    return rows


def emissions(result, weight=1):
    return fsum(r["direct_co2_t"] + r["conversion_co2_t"] for r in carbon_components(result, weight))


def suffix_operation(run):
    """Reconstruct the actual suffix using the saved prefix, not a new forecast."""
    original = run["operation"]
    start = run["calendar"][0]["event_start_hour"]
    count = next(i for i, row in enumerate(run["calendar"]) if row["start_hour"] == start)
    if count == 0:
        return deepcopy(original), 0
    before = {kind: [r for r in run["result"][kind] if r["period"] < count]
              for kind in ("fuel", "generation", "demand", "storage")}
    op = deepcopy(original)
    op["periods"] = op["periods"][count:]
    for fuel, spec in op["fuels"].items():
        for key in ("domestic_mw", "import_mw"):
            spec[key] = spec[key][count:]
        spec["initial_mwh"] = next(r["closing_mwh"] for r in reversed(before["fuel"]) if r["fuel"] == fuel)
    for name, spec in op["plants"].items():
        spec["availability"] = spec["availability"][count:]
        used = fsum(r["output_mwh"] for r in before["generation"] if r["plant"] == name)
        spec["window_energy_budget_mwh"] = max(0, spec["window_energy_budget_mwh"] - used)
        last = next(r["output_mwh"] for r in reversed(before["generation"]) if r["plant"] == name)
        spec["initial_period_hours"] = original["periods"][count - 1]["hours"]
        spec["initial_power_mw"] = last / spec["initial_period_hours"]
    for spec in op["demands"].values():
        spec["service_mwh"] = spec["service_mwh"][count:]
    for group, limit in op.get("spending_limits", {}).items():
        spent = fsum(r["input_mwh"] * original["demands"][r["device"]]["purchase_price_per_mwh"]
                     for r in before["demand"] if original["demands"][r["device"]].get("budget_group") == group)
        if spent > limit["budget_cny"] + .01:
            raise ValueError("Saved prefix overspent its window budget")
        limit["budget_cny"] = max(0, limit["budget_cny"] - spent)
    op["storage"]["initial_mwh"] = before["storage"][-1]["closing_mwh"]
    if "discharge_limit_mwh" in op["storage"]:
        op["storage"]["discharge_limit_mwh"] = op["storage"]["discharge_limit_mwh"][count:]
    return op, count


def probe_operation(original, name, fraction):
    op = deepcopy(original)
    factor = 1 + fraction
    if name == "baseline":
        pass
    elif name == "no_gas_imports":
        op["fuels"]["gas"]["import_mw"] = [0.] * len(op["periods"])
    elif name == "grid_power":
        op["grid"]["power_mw"] *= factor
    elif name in {"storage_power", "storage_energy"}:
        op["storage"]["power_mw" if name.endswith("power") else "energy_mwh"] *= factor
    elif name in {"generation_power", "generation_energy", "generation_power_and_energy", "generation_ramps"}:
        keys = {"generation_power": ["capacity_mw"], "generation_energy": ["window_energy_budget_mwh"],
                "generation_power_and_energy": ["capacity_mw", "window_energy_budget_mwh"],
                "generation_ramps": ["ramp_mw_per_hour"]}[name]
        for plant in op["plants"].values():
            for key in keys:
                plant[key] *= factor
    elif name in {"hydro_energy", "coal_power", "gas_power"}:
        tech, kind = name.split("_")
        op["plants"][tech]["window_energy_budget_mwh" if kind == "energy" else "capacity_mw"] *= factor
    elif name in {"fuel_deliverability", "gas_domestic", "gas_import"}:
        for fuel, spec in op["fuels"].items():
            if name != "fuel_deliverability" and fuel != "gas":
                continue
            keys = ["domestic_mw", "import_mw"] if name == "fuel_deliverability" else [name.split("_")[1] + "_mw"]
            for key in keys:
                spec[key] = [v * factor for v in spec[key]]
    elif name == "transport_device":
        for spec in op["demands"].values():
            if spec["sector"] == "transport_proxy":
                spec["input_capacity_mw"] *= factor
    elif name in {"transport_budget", "all_service_budgets"}:
        for group, spec in op["spending_limits"].items():
            if name == "all_service_budgets" or group == "transport_proxy":
                spec["budget_cny"] *= factor
    elif name == "transport_priority":
        for spec in op["demands"].values():
            if spec["sector"] != "transport_proxy":
                spec["priority"] += 1
    else:
        raise ValueError("Unregistered diagnostic: " + name)
    return op


def compare_services(a, b, label):
    left, right = service_metrics(a), service_metrics(b)
    if set(left) != set(right):
        raise ValueError("Service identities changed")
    for key in left:
        for metric in ("requested_service_mwh", "unmet_service_mwh"):
            close(left[key][metric], right[key][metric], label + "/" + key + "/" + metric)


def combine_prefix(run, suffix, count):
    return {kind: [r for r in run["result"][kind] if r["period"] < count] +
            [{**r, "period": r["period"] + count} for r in suffix[kind]]
            for kind in ("fuel", "generation", "demand", "storage")}


def gas_record(op, result, **identity):
    rows = [r for r in result["fuel"] if r["fuel"] == "gas"]
    spec = op["fuels"]["gas"]
    hours = [p["hours"] for p in op["periods"]]
    domestic = fsum(r["domestic_mwh"] for r in rows)
    capacity = fsum(h * v for h, v in zip(hours, spec["domestic_mw"]))
    return dict(**identity, domestic_mwh=domestic, domestic_capacity_mwh=capacity,
                domestic_utilisation=domestic / capacity,
                max_period_domestic_utilisation=max(r["domestic_mwh"] / (hours[r["period"]] * spec["domestic_mw"][r["period"]]) for r in rows),
                import_mwh=fsum(r["import_mwh"] for r in rows),
                import_capacity_mwh=fsum(h * v for h, v in zip(hours, spec["import_mw"])),
                direct_mwh=fsum(r["direct_mwh"] for r in rows),
                conversion_mwh=fsum(r["conversion_mwh"] for r in rows),
                initial_stock_mwh=spec["initial_mwh"], final_stock_mwh=rows[-1]["closing_mwh"],
                domestic_cost_cny_per_mwh=spec["domestic_cost_per_mwh"],
                import_cost_cny_per_mwh=spec["import_cost_per_mwh"])


def event_constraints(op, result, policy):
    rows = []
    for i, period in enumerate(op["periods"]):
        h = period["hours"]
        demand = [r for r in result["demand"] if r["period"] == i]
        for tech, plant in op["plants"].items():
            actual = next(r["output_mwh"] for r in result["generation"] if r["period"] == i and r["plant"] == tech)
            cap = plant["capacity_mw"] * plant["availability"][i] * h
            rows.append(dict(policy=policy, period=i, kind="plant_power", name=tech, actual_mwh=actual, limit_mwh=cap))
        for row in demand:
            spec = op["demands"][row["device"]]
            rows.append(dict(policy=policy, period=i, kind="device_input", name=row["device"],
                             actual_mwh=row["input_mwh"], limit_mwh=spec["input_capacity_mw"] * h,
                             priority=spec["priority"], efficiency=spec["efficiency"],
                             requested_service_mwh=row["requested_service_mwh"], unmet_service_mwh=row["unmet_service_mwh"]))
        flow = fsum(r["input_mwh"] for r in demand if r["carrier"] == "electricity") / op["grid"]["efficiency"]
        rows.append(dict(policy=policy, period=i, kind="grid", name="electricity", actual_mwh=flow, limit_mwh=op["grid"]["power_mw"] * h))
    for tech, plant in op["plants"].items():
        rows.append(dict(policy=policy, kind="plant_window_energy", name=tech,
                         actual_mwh=fsum(r["output_mwh"] for r in result["generation"] if r["plant"] == tech),
                         limit_mwh=plant["window_energy_budget_mwh"]))
    for group, spec in op["spending_limits"].items():
        spent = fsum(r["input_mwh"] * op["demands"][r["device"]]["purchase_price_per_mwh"] for r in result["demand"]
                     if op["demands"][r["device"]].get("budget_group") == group)
        rows.append(dict(policy=policy, kind="service_budget", name=group, actual_cny=spent, limit_cny=spec["budget_cny"]))
    return rows


def run_diagnostics(source, out, protocol):
    config = load(source / "frozen_config.json")
    snapshot = load(source / "event_initial_state.json")
    gas, gas_checks, gas_details = [], [], []
    for event in config["events"]:
        for scenario in ("S0", "SW"):
            reference = run_event(snapshot, event, scenario, config["transition"]["channel_fraction"])
            closed = deepcopy(snapshot)
            closed["fuels"]["gas"]["import_mw"] = [0.] * len(closed["periods"])
            repeated = run_event(closed, event, scenario, config["transition"]["channel_fraction"])
            compare_services(reference["result"], repeated["result"], "all-import closure")
            close(reference["result"]["resource_cost"], repeated["result"]["resource_cost"], "gas closure resource cost", 1.)
            for name, run in (("baseline", reference), ("all_imports_closed", repeated)):
                gas.append(gas_record(run["operation"], run["result"], event=event["id"], scenario=scenario, control=name))
                gas_details.append(dict(event=event["id"], scenario=scenario, control=name, run=run))
            gas_checks.append(dict(event=event["id"], scenario=scenario, all_service_metrics_unchanged=True,
                                   cost_unchanged=True, gas_imports_before=gas[-2]["import_mwh"]))
    csv_write(out / "gas_import_diagnostics.csv", gas)
    save(out / "gas_closure_checks.json", gas_checks)
    (out / "gas_control_details.json.gz").write_bytes(gzip.compress(json.dumps(gas_details, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(), mtime=0))

    effects, constraints, raw = [], [], []
    failures = []
    for target in protocol["event_targets"]:
        policy = target["policy"]
        runs = unpack(source / f"events/policy_{policy}-test.json.gz")
        run = next(r for r in runs if r["year"] == target["year"] and r["scenario"] == target["scenario"])
        original, count = suffix_operation(run)
        baseline = None
        for probe in protocol["probes"]:
            print(f"Diagnostic event {policy}: {probe}", flush=True)
            op = probe_operation(original, probe, protocol["relative_capacity_probe"])
            try:
                result = operate_national(op)
                full = combine_prefix(run, result, count)
                if probe == "baseline":
                    compare_services(run["result"], full, "saved suffix reproduction")
                    close(emissions(run["result"]), emissions(full), "saved suffix carbon")
                    baseline = service_metrics(full)
                    constraints.extend(event_constraints(op, result, policy))
                metrics = service_metrics(full)
                for sector, values in metrics.items():
                    close(values["requested_service_mwh"], baseline[sector]["requested_service_mwh"], "probe must preserve demand")
                    effects.append(dict(policy=policy, probe=probe, sector=sector, status="completed", **values,
                                        delta_unmet_service_mwh=values["unmet_service_mwh"] - baseline[sector]["unmet_service_mwh"],
                                        carbon_t=emissions(full)))
                raw.append(dict(target=target, probe=probe, changed_operation=op, suffix_result=result,
                                preserved_prefix_periods=count))
            except Exception as exc:
                if probe == "baseline":
                    raise
                failure = dict(target=target, probe=probe, error=type(exc).__name__ + ": " + str(exc))
                failures.append(failure)
                effects.append(dict(policy=policy, probe=probe, status="failed", error=failure["error"]))
    csv_write(out / "event_probe_effects.csv", effects)
    csv_write(out / "event_active_constraints.csv", constraints)
    (out / "event_probe_details.json.gz").write_bytes(gzip.compress(json.dumps(raw, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(), mtime=0))
    save(out / "diagnostic_failures.json", failures)

    cases = {name: unpack(source / f"cases/policy_{name}.json.gz") for name in ("none", "storage")}
    carbon, swaps, generation, electricity, capital = [], [], [], [], []
    swap_details, unavailable_swaps = [], []
    for year in range(2025, 2061):
        originals = {}
        for policy, case in cases.items():
            op = case["operation_specs"][str(year)]
            result = grouped_result([r for r in case["operations"] if r["year"] == year])
            originals[policy] = (op, result)
            carbon.extend(dict(policy=policy, year=year, **r) for r in carbon_components(result, 365))
            for tech in op["plants"]:
                generation.append(dict(policy=policy, year=year, technology=tech,
                    capacity_mw=op["plants"][tech]["capacity_mw"],
                    output_mwh=365 * fsum(r["output_mwh"] for r in result["generation"] if r["plant"] == tech)))
            delivered = fsum(r["input_mwh"] for r in result["demand"] if r["carrier"] == "electricity") / op["grid"]["efficiency"]
            loss = fsum(r["charge_mwh"] - r["discharge_mwh"] for r in result["storage"])
            generated = fsum(r["output_mwh"] for r in result["generation"])
            close(generated, delivered + loss, "annual electricity identity")
            electricity.append(dict(policy=policy, year=year, generated_mwh=365 * generated,
                                    delivered_at_bus_mwh=365 * delivered, storage_loss_mwh=365 * loss))
        for receiving, donating in (("none", "storage"), ("storage", "none")):
            op, original_result = originals[receiving]
            op = deepcopy(op)
            for field in ("power_mw", "energy_mwh"):
                op["storage"][field] = originals[donating][0]["storage"][field]
            if op["storage"]["initial_mwh"] > op["storage"]["energy_mwh"]:
                unavailable = dict(year=year, receiving_case=receiving, storage_from=donating,
                                   status="unavailable_initial_SOC_exceeds_swapped_capacity",
                                   initial_soc_mwh=op["storage"]["initial_mwh"], swapped_energy_mwh=op["storage"]["energy_mwh"])
                unavailable_swaps.append(unavailable)
                swaps.append(unavailable)
                continue
            result = operate_national(op)
            # Same resources, prices, demand, non-storage assets and original SOC.
            actual = emissions(original_result, 365)
            counterfactual = emissions(result, 365)
            swaps.append(dict(year=year, receiving_case=receiving, storage_from=donating, status="completed",
                              actual_co2_t=actual, swap_co2_t=counterfactual,
                              controlled_storage_delta_co2_t=counterfactual - actual))
            swap_details.append(dict(year=year, receiving_case=receiving, storage_from=donating,
                                     operation=op, result=result))
        if year % 5 == 0:
            print(f"Diagnostic carbon decomposition: {year}", flush=True)
    for policy, case in cases.items():
        for project in case["projects"]:
            capital.append(dict(policy=policy, **project))
        total = fsum(r["direct_co2_t"] + r["conversion_co2_t"] for r in carbon if r["policy"] == policy)
        close(total, case["terminal_accounts"]["cumulative_combustion_co2_t"], "full horizon carbon", .1)
    csv_write(out / "annual_carbon_components.csv", carbon)
    csv_write(out / "annual_generation.csv", generation)
    csv_write(out / "annual_electricity_identity.csv", electricity)
    csv_write(out / "annual_storage_swaps.csv", swaps)
    csv_write(out / "generation_projects.csv", capital)
    save(out / "unavailable_annual_controls.json", unavailable_swaps)
    (out / "annual_swap_details.json.gz").write_bytes(gzip.compress(json.dumps(swap_details, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(), mtime=0))
    return dict(gas_closure_cases=len(gas_checks), event_probe_attempts=len(raw) + len(failures),
                event_probe_failures=len(failures), annual_dispatch_controls=len(swap_details),
                annual_controls_requested=len(swaps), unavailable_annual_controls=len(unavailable_swaps),
                new_empirical_data=False, original_model_changed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="outputs/q3/p3_mmj_v5")
    parser.add_argument("--config", default="workflow/q3_diagnostics_v2.json")
    parser.add_argument("--output-dir", default="outputs/validation/p3_mmj/diagnostics_v2")
    args = parser.parse_args()
    source, out = (ROOT / args.source).resolve(), (ROOT / args.output_dir).resolve()
    if not out.is_relative_to(ROOT / "outputs/validation") or out.exists():
        raise ValueError("Use a new output directory inside outputs/validation")
    protocol = load(ROOT / args.config)
    original = verify_latest(source)
    if original["code_hashes"] != protocol["model_code_hashes"] or original["input_hashes"] != protocol["input_hashes"]:
        raise ValueError("Frozen diagnostic model or inputs changed")
    for name, expected in protocol["source_files"].items():
        if sha(source / name) != expected:
            raise ValueError("Frozen scientific evidence changed: " + name)
    out.mkdir(parents=True)
    record = dict(status="running", started_at_utc=datetime.now(timezone.utc).isoformat(),
                  source_run_id=original["run_id"], source_manifest_sha256=sha(source / "run_manifest.json"),
                  protocol_path=args.config, protocol_sha256=sha(ROOT / args.config),
                  script_sha256=sha(__file__), source_code_hashes=original["code_hashes"],
                  source_input_hashes=original["input_hashes"], scope=protocol["identity"])
    save(out / "run_manifest.json", record)
    save(out / "frozen_protocol.json", protocol)
    (out / "diagnostic_source.py").write_bytes(Path(__file__).read_bytes())
    started = time.perf_counter()
    code = 0
    try:
        record["completion"] = run_diagnostics(source, out, protocol)
        verify_latest(source)
        if record["script_sha256"] != sha(__file__) or record["protocol_sha256"] != sha(ROOT / args.config):
            raise ValueError("Diagnostic code or protocol changed during execution")
        record["status"] = "diagnostics_completed" if not record["completion"]["event_probe_failures"] else "diagnostics_with_failures"
        if record["completion"]["event_probe_failures"]:
            code = 2
    except Exception as exc:
        record.update(status="failed", error=type(exc).__name__ + ": " + str(exc))
        code = 1
    record.update(elapsed_seconds=time.perf_counter() - started, exit_code=code,
                  outputs={p.relative_to(out).as_posix(): sha(p) for p in sorted(out.rglob("*")) if p.is_file() and p.name != "run_manifest.json"})
    save(out / "run_manifest.json", record)
    print(json.dumps(record.get("completion", record.get("error"))), flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
