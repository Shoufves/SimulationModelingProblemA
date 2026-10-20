"""Audit the saved diagnostic evidence without its aggregation helpers.

This is an author review, not approval by another team member. It never changes
the model, its frozen runs, or the diagnostic runs being reviewed.
"""
import argparse
from collections import defaultdict
from copy import deepcopy
import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
from math import fsum, isclose
from pathlib import Path
from q3_scientific_equivalence import admit_source, compare_outputs, tolerances
from run_q3 import verify_latest

ROOT = Path(__file__).resolve().parents[1]
EF = dict(coal=.34056, oil=.26388, gas=.20196, biomass=0.)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8-sig"))


def unpack(p):
    return json.loads(gzip.decompress(Path(p).read_bytes()))


def csv_read(p):
    with Path(p).open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def close(a, b, label, absolute=.05):
    if not isclose(float(a), float(b), abs_tol=absolute, rel_tol=1e-10):
        raise ValueError(f"{label}: {a} != {b}")


def require(condition, label):
    if not condition:
        raise ValueError(label)


def service(row):
    return row["sector"] + ("/" + row["carrier"] if row["sector"] == "nonenergy_feedstock" else "")


def totals(result):
    values = defaultdict(lambda: [0., 0.])
    for row in result["demand"]:
        values[service(row)][0] += row["requested_service_mwh"]
        values[service(row)][1] += row["unmet_service_mwh"]
    return values


def differences(a, b, path=()):
    """Changed leaves, retaining array identity and refusing removed keys."""
    numeric = type(a) in (int, float) and type(b) in (int, float)
    require(numeric or type(a) is type(b), "Control schema changed: " + "/".join(path))
    if isinstance(a, dict):
        require(a.keys() == b.keys(), "Control keys changed")
        return {k: v for key in a for k, v in differences(a[key], b[key], path + (key,)).items()}
    return {} if a == b else {path: (a, b)}


def verify_probe_inputs(baseline, changed, probe, fraction):
    """Check declared interventions only; all other leaves must be identical."""
    delta = differences(baseline, changed)
    for path, (before, after) in delta.items():
        permitted = False
        if probe == "transport_priority" and path[0] == "demands" and path[-1] == "priority":
            permitted = baseline["demands"][path[1]]["sector"] != "transport_proxy" and after == before + 1
        elif probe == "no_gas_imports":
            permitted = path == ("fuels", "gas", "import_mw") and after == [0.] * len(before)
        else:
            fields = {
                "grid_power": ("grid", "power_mw"),
                "storage_power": ("storage", "power_mw"),
                "storage_energy": ("storage", "energy_mwh"),
                "generation_power": ("plants", "capacity_mw"),
                "generation_energy": ("plants", "window_energy_budget_mwh"),
                "generation_ramps": ("plants", "ramp_mw_per_hour"),
                "hydro_energy": ("plants", "window_energy_budget_mwh"),
                "coal_power": ("plants", "capacity_mw"),
                "gas_power": ("plants", "capacity_mw"),
                "transport_device": ("demands", "input_capacity_mw"),
                "transport_budget": ("spending_limits", "budget_cny"),
                "all_service_budgets": ("spending_limits", "budget_cny"),
            }
            if probe in fields:
                permitted = (path[0], path[-1]) == fields[probe]
                if probe in {"hydro_energy", "coal_power", "gas_power"}:
                    permitted = permitted and path[1] == probe.split("_")[0]
                elif probe == "transport_device":
                    permitted = permitted and baseline["demands"][path[1]]["sector"] == "transport_proxy"
                elif probe == "transport_budget":
                    permitted = permitted and path[1] == "transport_proxy"
            elif probe == "generation_power_and_energy":
                permitted = path[0] == "plants" and path[-1] in {"capacity_mw", "window_energy_budget_mwh"}
            elif probe in {"fuel_deliverability", "gas_domestic", "gas_import"}:
                permitted = path[0] == "fuels" and path[-1] in {"domestic_mw", "import_mw"}
                if probe != "fuel_deliverability":
                    permitted = permitted and path[1] == "gas" and path[-1] == probe.split("_")[1] + "_mw"
            if permitted:
                left, right = (before, after) if isinstance(before, list) else ([before], [after])
                require(len(left) == len(right), "Period count changed")
                for a, b in zip(left, right):
                    close(b, a * (1 + fraction), "Wrong probe magnitude")
        require(permitted, "Unregistered control change: " + probe + "/" + "/".join(path))


def carbon(result):
    # The model's exported CO2 totals and the diagnostic's helpers are not used.
    return fsum((r["direct_mwh"] + r["conversion_mwh"] -
                 fsum(d["input_mwh"] for d in result["demand"]
                      if d["period"] == r["period"] and d["carrier"] == r["fuel"]
                      and d["sector"] == "nonenergy_feedstock")) * EF[r["fuel"]]
                for r in result["fuel"])


def operation_checks(op, result):
    """Independent continuity, energy, terminal boundary and budget checks."""
    require(result["status"] == "optimal", "Unsuccessful control")
    stocks = {f: s["initial_mwh"] for f, s in op["fuels"].items()}
    battery = op["storage"]
    soc = battery["initial_mwh"]
    for i, period in enumerate(op["periods"]):
        h = period["hours"]
        demand = [r for r in result["demand"] if r["period"] == i]
        fuel = [r for r in result["fuel"] if r["period"] == i]
        generation = [r for r in result["generation"] if r["period"] == i]
        b = next(r for r in result["storage"] if r["period"] == i)
        close(b["opening_mwh"], soc, "SOC continuity")
        soc += b["charge_mwh"] * battery["charge_efficiency"] - b["discharge_mwh"] / battery["discharge_efficiency"]
        close(b["closing_mwh"], soc, "SOC equation")
        require(-.05 <= soc <= battery["energy_mwh"] + .05, "SOC capacity")
        require(max(b["charge_mwh"], b["discharge_mwh"]) <= battery["power_mw"] * h + .05, "Battery power")
        electric = fsum(r["input_mwh"] for r in demand if r["carrier"] == "electricity") / op["grid"]["efficiency"]
        close(fsum(r["output_mwh"] for r in generation) + b["discharge_mwh"] - b["charge_mwh"], electric, "Electricity balance")
        require(electric <= op["grid"]["power_mw"] * h + .05, "Grid power")
        for row in demand:
            spec = op["demands"][row["device"]]
            close(row["requested_service_mwh"], spec["service_mwh"][i], "Unchanged demand")
            close(row["input_mwh"] * spec["efficiency"] + row["unmet_service_mwh"], spec["service_mwh"][i], "Service balance")
            require(row["input_mwh"] <= spec["input_capacity_mw"] * h + .05, "Device capacity")
        for row in generation:
            spec = op["plants"][row["plant"]]
            require(row["output_mwh"] <= spec["capacity_mw"] * spec["availability"][i] * h + .05, "Generation power")
        for row in fuel:
            f, spec = row["fuel"], op["fuels"][row["fuel"]]
            stocks[f] += row["fill_mwh"] - row["withdrawal_mwh"]
            close(row["closing_mwh"], stocks[f], "Fuel inventory continuity")
            close(row["domestic_mwh"] + row["import_mwh"] - row["fill_mwh"] + row["withdrawal_mwh"], row["direct_mwh"] + row["conversion_mwh"], "Fuel balance")
            for label in ("domestic", "import"):
                require(row[label + "_mwh"] <= spec[label + "_mw"][i] * h + .05, "Fuel delivery")
    close(soc, battery.get("terminal_mwh", battery["initial_mwh"]), "Terminal SOC")
    for f, spec in op["fuels"].items():
        close(stocks[f], spec.get("terminal_mwh", spec["initial_mwh"]), "Terminal fuel stock")
    for group, limit in op.get("spending_limits", {}).items():
        spent = fsum(r["input_mwh"] * op["demands"][r["device"]]["purchase_price_per_mwh"]
                     for r in result["demand"] if op["demands"][r["device"]].get("budget_group") == group)
        require(spent <= limit["budget_cny"] + .1, "Budget exceeded")


def verify_receipt(folder):
    manifest = load(folder / "run_manifest.json")
    require(manifest["status"] == "diagnostics_completed" and manifest["exit_code"] == 0, "Incomplete diagnostic run")
    require(set(manifest["outputs"]) == {p.name for p in folder.iterdir() if p.is_file() and p.name != "run_manifest.json"}, "Evidence file set changed")
    for name, expected in manifest["outputs"].items():
        require(sha(folder / name) == expected, "Changed evidence: " + name)
    require(sha(folder / "diagnostic_source.py") == manifest["script_sha256"], "Code receipt")
    require(sha(folder / "frozen_protocol.json") == manifest["protocol_sha256"], "Protocol receipt")
    return manifest


def review(source, folder, independent=None, independent_source=None):
    manifest = verify_receipt(folder)
    protocol = load(folder / "frozen_protocol.json")
    require(sha(source / "run_manifest.json") == manifest["source_manifest_sha256"], "Source receipt changed")
    original = verify_latest(source)
    require(original["run_id"] == manifest["source_run_id"], "Source run identity changed")
    for names in (protocol["model_code_hashes"], protocol["input_hashes"]):
        for name, expected in names.items():
            require(sha(ROOT / name) == expected, "Frozen model/input changed: " + name)
    if protocol.get("version") == 3:
        require(sha(folder / "scientific_equivalence_source.py") == manifest["equivalence_code_sha256"], "Comparison code receipt")
        require(sha(folder / "frozen_reproduction_protocol.json") == protocol["reproduction_protocol_sha256"], "Comparison protocol receipt")
        require(load(folder / "source_equivalence.json") == admit_source(source, protocol), "Source equivalence evidence differs")
    else:
        for name, expected in protocol["source_files"].items():
            require(sha(source / name) == expected, "Source evidence changed: " + name)
    require(load(folder / "diagnostic_failures.json") == [], "Probe failures require individual review")

    gas = unpack(folder / "gas_control_details.json.gz")
    require(len(gas) == 8, "Gas controls incomplete")
    for event in load(source / "frozen_config.json")["events"]:
        for scenario in ("S0", "SW"):
            pair = {r["control"]: r["run"] for r in gas if r["event"] == event["id"] and r["scenario"] == scenario}
            a, b = pair["baseline"], pair["all_imports_closed"]
            expected = deepcopy(a["operation"])
            expected["fuels"]["gas"]["import_mw"] = [0.] * len(expected["periods"])
            require(expected == b["operation"], "Import control changed other inputs")
            require(a["calendar"] == b["calendar"], "Calendar changed")
            for run in (a, b):
                operation_checks(run["operation"], run["result"])
            ta, tb = totals(a["result"]), totals(b["result"])
            require(ta.keys() == tb.keys(), "Service dropped")
            for key in ta:
                for j in (0, 1):
                    close(ta[key][j], tb[key][j], "Import closure service effect")
            close(a["result"]["resource_cost"], b["result"]["resource_cost"], "Import closure cost")

    probes = unpack(folder / "event_probe_details.json.gz")
    require(len(probes) == 38, "Missing event probes")
    effects = {(r["policy"], r["probe"], r["sector"]): r for r in csv_read(folder / "event_probe_effects.csv")}
    require(len(effects) == 304, "Incomplete service effects")
    for policy in ("none", "storage"):
        original = next(r for r in unpack(source / f"events/policy_{policy}-test.json.gz") if r["year"] == 2060 and r["scenario"] == "SGW")
        records = [r for r in probes if r["target"]["policy"] == policy]
        require({r["probe"] for r in records} == set(protocol["probes"]), "Probe identities")
        reference_op = next(r["changed_operation"] for r in records if r["probe"] == "baseline")
        baseline = totals(original["result"])
        for record in records:
            op, result, count = record["changed_operation"], record["suffix_result"], record["preserved_prefix_periods"]
            verify_probe_inputs(reference_op, op, record["probe"], protocol["relative_capacity_probe"])
            require(count > 0 and original["calendar"][count]["start_hour"] == original["calendar"][0]["event_start_hour"], "Wrong event split")
            close(op["storage"]["initial_mwh"], original["result"]["storage"][count - 1]["closing_mwh"], "Prefix SOC preserved")
            for f, spec in op["fuels"].items():
                close(spec["initial_mwh"], next(r["closing_mwh"] for r in original["result"]["fuel"] if r["period"] == count - 1 and r["fuel"] == f), "Prefix fuel stock preserved")
            for tech, spec in op["plants"].items():
                previous = next(r["output_mwh"] for r in original["result"]["generation"] if r["period"] == count - 1 and r["plant"] == tech)
                close(spec["initial_power_mw"], previous / original["operation"]["periods"][count - 1]["hours"], "Ramp boundary preserved")
                if record["probe"] == "baseline":
                    used = fsum(r["output_mwh"] for r in original["result"]["generation"] if r["period"] < count and r["plant"] == tech)
                    close(spec["window_energy_budget_mwh"], max(0, original["operation"]["plants"][tech]["window_energy_budget_mwh"] - used), "Remaining energy budget")
            if record["probe"] == "baseline":
                for group, spec in op["spending_limits"].items():
                    spent = fsum(r["input_mwh"] * original["operation"]["demands"][r["device"]]["purchase_price_per_mwh"] for r in original["result"]["demand"] if r["period"] < count and original["operation"]["demands"][r["device"]].get("budget_group") == group)
                    close(spec["budget_cny"], original["operation"]["spending_limits"][group]["budget_cny"] - spent, "Remaining spending budget")
            operation_checks(op, result)
            full = {k: [r for r in original["result"][k] if r["period"] < count] + [{**r, "period": r["period"] + count} for r in result[k]] for k in ("fuel", "demand", "generation", "storage")}
            for key, (requested, unmet) in totals(full).items():
                row = effects[policy, record["probe"], key]
                close(requested, baseline[key][0], "Requested service fixed")
                close(row["requested_service_mwh"], requested, "CSV demand")
                close(row["unmet_service_mwh"], unmet, "CSV loss")
                close(row["unmet_fraction"], unmet / requested, "CSV ratio", 1e-10)
                close(row["delta_unmet_service_mwh"], unmet - baseline[key][1], "CSV effect")
                close(row["carbon_t"], carbon(full), "CSV carbon")

    cases = {p: unpack(source / f"cases/policy_{p}.json.gz") for p in ("none", "storage")}
    actual = {}
    components = {(r["policy"], int(r["year"]), r["fuel"]): r for r in csv_read(folder / "annual_carbon_components.csv")}
    electric = {(r["policy"], int(r["year"])): r for r in csv_read(folder / "annual_electricity_identity.csv")}
    require(len(components) == 288 and len(electric) == 72, "Incomplete annual components")
    for policy, case in cases.items():
        for year in range(2025, 2061):
            rows = [r for r in case["operations"] if r["year"] == year]
            result = {k: [r for r in rows if r["kind"] == k] for k in ("fuel", "demand", "generation", "storage")}
            actual[policy, year] = carbon(result) * 365
            for fuel, factor in EF.items():
                direct = fsum(r["input_mwh"] for r in result["demand"] if r["carrier"] == fuel and r["sector"] != "nonenergy_feedstock") * 365
                conversion = fsum(r["input_mwh"] for r in result["generation"] if case["operation_specs"][str(year)]["plants"][r["plant"]]["input"] == fuel) * 365
                row = components[policy, year, fuel]
                for field, expected in (("direct_combustion_mwh", direct), ("conversion_input_mwh", conversion), ("direct_co2_t", direct * factor), ("conversion_co2_t", conversion * factor)):
                    close(row[field], expected, "Fuel component")
            row = electric[policy, year]
            generated = fsum(r["output_mwh"] for r in result["generation"]) * 365
            delivered = fsum(r["input_mwh"] for r in result["demand"] if r["carrier"] == "electricity") * 365 / case["operation_specs"][str(year)]["grid"]["efficiency"]
            loss = fsum(r["charge_mwh"] - r["discharge_mwh"] for r in result["storage"]) * 365
            close(generated, delivered + loss, "Annual electricity identity")
            for field, expected in (("generated_mwh", generated), ("delivered_at_bus_mwh", delivered), ("storage_loss_mwh", loss)):
                close(row[field], expected, "Electricity CSV")
        close(fsum(actual[policy, y] for y in range(2025, 2061)), case["terminal_accounts"]["cumulative_combustion_co2_t"], "Annual carbon sum")
    swaps = csv_read(folder / "annual_storage_swaps.csv")
    require(len(swaps) == 72 and len({(r["receiving_case"], r["year"]) for r in swaps}) == 72, "Missing or duplicate requested controls")
    details = {(r["receiving_case"], r["year"]): r for r in unpack(folder / "annual_swap_details.json.gz")}
    unavailable = load(folder / "unavailable_annual_controls.json")
    require(len(details) == 71 and len(unavailable) == 1, "Wrong control availability")
    for row in swaps:
        policy, other, year = row["receiving_case"], row["storage_from"], int(row["year"])
        expected = deepcopy(cases[policy]["operation_specs"][str(year)])
        for key in ("power_mw", "energy_mwh"):
            expected["storage"][key] = cases[other]["operation_specs"][str(year)]["storage"][key]
        if row["status"] != "completed":
            require((policy, year) == ("storage", 2032), "Unexpected unavailable control")
            require(expected["storage"]["initial_mwh"] > expected["storage"]["energy_mwh"], "Unavailable reason not true")
            require(not row["controlled_storage_delta_co2_t"] and (policy, year) not in details, "Missing result filled in")
            continue
        detail = details[policy, year]
        require(detail["operation"] == expected, "Storage swap changed other resources, demand or SOC")
        operation_checks(expected, detail["result"])
        close(row["actual_co2_t"], actual[policy, year], "Control reference carbon")
        close(row["swap_co2_t"], carbon(detail["result"]) * 365, "Control carbon")
        close(row["controlled_storage_delta_co2_t"], carbon(detail["result"]) * 365 - actual[policy, year], "Storage-only effect")
    delta = fsum(actual["storage", y] - actual["none", y] for y in range(2025, 2061))
    forward = fsum(float(r["controlled_storage_delta_co2_t"]) for r in swaps if r["receiving_case"] == "none")
    summary = dict(total_delta_co2_t=delta, forward_storage_only_delta_co2_t=forward,
                   remaining_path_and_interaction_delta_co2_t=delta-forward,
                   reverse_complete_horizon_available=False)
    compared = None
    if independent is not None:
        independent_manifest = verify_receipt(independent)
        require(independent_manifest["source_run_id"] != manifest["source_run_id"], "Not an independently executed source run")
        require(independent_manifest["protocol_sha256"] == manifest["protocol_sha256"], "Independent diagnostic protocol differs")
        require(independent_manifest["script_sha256"] == manifest["script_sha256"], "Independent diagnostic code differs")
        independent_source = independent_source or independent_manifest.get("source_path")
        require(independent_source is not None, "Supply the independent source run directory")
        review(Path(independent_source), independent)
        compared = compare_outputs(folder, independent, manifest, independent_manifest,
                                   tolerances(load(source / "frozen_config.json")), kind="diagnostic")
    return dict(status="passed", gas_pairs=4, probes=38, annual_controls=71,
                unavailable_controls=unavailable, carbon_decomposition=summary,
                independent_scientific_comparison=compared, team_approval=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default="outputs/q3/p3_mmj_v5")
    parser.add_argument("--diagnostics", default="outputs/validation/p3_mmj/diagnostics_v3")
    parser.add_argument("--independent")
    parser.add_argument("--independent-source")
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args()
    receipt = (ROOT / args.receipt).resolve()
    require(receipt.is_relative_to(ROOT / "outputs/validation") and not receipt.exists(), "Use a new validation receipt")
    folder, source = ROOT / args.diagnostics, ROOT / args.source
    record = dict(created_at_utc=datetime.now(timezone.utc).isoformat(), script_sha256=sha(__file__),
                  diagnostic_manifest_sha256=sha(folder / "run_manifest.json"), source_run_manifest_sha256=sha(source / "run_manifest.json"))
    code = 0
    try:
        record.update(review(source, folder, Path(args.independent) if args.independent else None,
                             Path(args.independent_source) if args.independent_source else None))
    except Exception as exc:
        record.update(status="failed", error=type(exc).__name__ + ": " + str(exc))
        code = 1
    receipt.write_text(json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
