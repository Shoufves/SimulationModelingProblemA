"""Offline Q1 research calculations. No model admission or missing-value imputation."""
import csv
import hashlib
import json
import math
import statistics
from pathlib import Path


class Q1Error(ValueError):
    """An input cannot support the requested calculation."""


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def review_snapshot(inputs, sources):
    """Bind semantic review to exact bytes, sources and permitted input uses."""
    fields = ("path", "sha256", "source_keys", "coverage", "boundary",
              "allowed_use", "blocked_use")
    return dict(inputs={r["id"]: {key: r[key] for key in fields} for r in inputs},
                sources=sources)


def write_json(path, value):
    Path(path).write_bytes((json.dumps(value, ensure_ascii=False, indent=2,
                                      allow_nan=False) + "\n").encode("utf-8"))


def write_csv(path, rows, fields):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def inside(root, relative):
    """Reject traversal, private inputs and symlink escapes before opening bytes."""
    root = Path(root).resolve()
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise Q1Error("Expected repository-relative path: " + str(relative))
    path = (root / rel).resolve()
    try:
        parts = path.relative_to(root).parts
    except ValueError as exc:
        raise Q1Error("Path escapes repository: " + str(relative)) from exc
    if tuple(p.lower() for p in parts[:2]) == ("data", "restricted"):
        raise Q1Error("Restricted content is excluded: " + str(relative))
    return path


def number(value):
    if value is None or value == "":
        return None
    result = float(value)
    if not math.isfinite(result):
        raise Q1Error("Non-finite input")
    return result


def ratio_records(imports, exports, consumption):
    """All three are from the same fuel ledger, year, unit, region and boundary."""
    for field in ("year", "region", "unit", "source_id", "boundary"):
        if len({r[field] for r in (imports, exports, consumption)}) != 1:
            raise Q1Error("Net import dependency mismatch: " + field)
    values = [number(r["value"]) for r in (imports, exports, consumption)]
    if any(v is None for v in values):
        return None
    if values[0] < 0 or values[1] < 0 or values[2] <= 0:
        raise Q1Error("Invalid trade or consumption amount")
    return 100 * (values[0] - values[1]) / values[2]


def concentration(rows):
    """Reported bins HHI and conservative country HHI interval (not risk scores).

    For unresolved, mutually exclusive geographic bins, known-country squared
    shares give an infimum; treating each bin as one country gives the upper bound.
    No country count is assumed for an unresolved bin.
    """
    if not rows:
        raise Q1Error("Empty trade table")
    for field in ("year", "destination", "unit", "source_id"):
        if len({r[field] for r in rows}) != 1:
            raise Q1Error("Trade concentration mismatch: " + field)
    totals = [r for r in rows if r["row_type"] == "total"]
    origins = [r for r in rows if r["row_type"] == "origin"]
    if len(totals) != 1 or len({r["origin"] for r in origins}) != len(origins):
        raise Q1Error("Trade total or origin uniqueness")
    total = number(totals[0]["value"])
    values = [number(r["value"]) for r in origins]
    if total is None or total <= 0 or any(v is None or v < 0 for v in values):
        raise Q1Error("Invalid trade values")
    if not math.isclose(sum(values), total, rel_tol=1e-8, abs_tol=1e-8):
        raise Q1Error("Origin amounts do not exhaust reported total")
    grouped = {"Europe", "Other CIS", "Other Africa", "Other Asia Pacific", "Rest of World"}
    unresolved = [r["origin"].startswith("Other") or r["origin"] in grouped for r in origins]
    shares = [v / total for v in values]
    bins = sum(s*s for s in shares)
    lower = sum(s*s for s, unknown in zip(shares, unresolved) if not unknown)
    return dict(total=total, reported_bin_hhi=bins, country_hhi_lower_infimum=lower,
                country_hhi_upper=bins, unresolved_share=sum(
                    s for s, unknown in zip(shares, unresolved) if unknown),
                exact_country_hhi=math.isclose(lower, bins, abs_tol=1e-14))


def price_volatility(rows, start=2015, end=2024):
    """Sample SD of adjacent annual log changes; never bridges missing years."""
    if not rows:
        raise Q1Error("Empty price series")
    for field in ("unit", "variable", "source_id", "region"):
        if len({r[field] for r in rows}) != 1:
            raise Q1Error("Price series mismatch: " + field)
    levels = {}
    for row in rows:
        year, value = int(row["year"]), number(row["value"])
        if year in levels:
            raise Q1Error("Duplicate price year")
        if value is not None and value <= 0:
            raise Q1Error("Non-positive price")
        levels[year] = value
    pairs, changes = [], []
    for year in range(start + 1, end + 1):
        if levels.get(year-1) is not None and levels.get(year) is not None:
            pairs.append([year-1, year])
            changes.append(math.log(levels[year] / levels[year-1]))
    return dict(value=statistics.stdev(changes) if len(changes) >= 2 else None,
                valid_pairs=pairs, observations=len(changes),
                covered_level_years=[y for y in range(start, end+1) if levels.get(y) is not None],
                missing_years=[y for y in range(start, end+1) if levels.get(y) is None])


def spatial_difference(generation, demand, expected_regions):
    if set(generation) != set(expected_regions) or set(demand) != set(expected_regions):
        raise Q1Error("Regional coverage mismatch")
    rows = list(generation.values()) + list(demand.values())
    for field in ("year", "unit"):
        if len({r[field] for r in rows}) != 1:
            raise Q1Error("Regional mismatch: " + field)
    g = {k: number(r["value"]) for k, r in generation.items()}
    d = {k: number(r["value"]) for k, r in demand.items()}
    if any(v is None or v < 0 for v in [*g.values(), *d.values()]):
        raise Q1Error("Missing or negative regional amount")
    sg, sd = sum(g.values()), sum(d.values())
    if min(sg, sd) <= 0:
        raise Q1Error("Empty regional denominator")
    regional = [dict(region=k, generation=g[k], consumption=d[k],
                     generation_share=g[k]/sg, consumption_share=d[k]/sd,
                     share_difference=g[k]/sg-d[k]/sd) for k in expected_regions]
    return dict(value=.5*sum(abs(r["share_difference"]) for r in regional),
                generation_sum=sg, consumption_sum=sd, regions=regional)


def screening_lcoe(capex, om, cf, life, real_wacc):
    """Constant annual output, end-of-year O&M/output; unfirmed plant-gate kWh."""
    if (not all(math.isfinite(x) for x in (capex, om, cf, life, real_wacc))
            or capex <= 0 or om < 0 or not 0 < cf <= 1 or life <= 0 or real_wacc < 0):
        raise Q1Error("Invalid cost assumptions")
    crf = (1/life if real_wacc == 0 else
           real_wacc / (1-(1+real_wacc)**(-life)))
    return (capex*crf + om) / (8760*cf)


def identity(values, terms, target):
    """Missing terms stay unknown, and the observed target is never adjusted."""
    missing = [k for k in (*terms, target) if values.get(k) is None]
    computed = None if missing else sum(values[k]*sign for k, sign in terms.items())
    return dict(terms=terms, target=target, target_value=values.get(target),
                computed=computed,
                residual=None if computed is None else values[target]-computed,
                missing=missing)


def balance_table(rows, source, year):
    selected = [r for r in rows if r["source_id"] == source and int(r["year"]) == year]
    if not selected or len({r["unit"] for r in selected}) != 1:
        raise Q1Error("Absent or mixed-unit balance")
    values = {}
    for r in selected:
        if r["variable"] in values:
            raise Q1Error("Duplicate balance term")
        values[r["variable"]] = number(r["value"])
    production = {"03": "primary_production", "04": "production_crude_oil",
                  "05": "production_raw_coal", "06": "production"}[source[-2:]]
    imp = "imports_oil_products_inclusive" if source.endswith("04") else "imports"
    exp = "exports_oil_products_inclusive" if source.endswith("04") else "exports"
    supply = {production: 1, imp: 1, exp: -1}
    if not source.endswith("06"):
        supply["inventory_opening_minus_closing"] = 1
    use = ({"final_consumption": 1, "conversion_losses": 1,
            "recovered_energy_deducted": -1, "losses": 1} if source.endswith("03")
           else {"final_consumption": 1, "transformation_input": 1, "losses": 1}
           if source.endswith("04")
           else {"final_consumption": 1, "transformation_input": 1}
           if source.endswith("05")
           else {"final_consumption": 1, "transmission_distribution_losses": 1})
    difference = (None if any(values.get(k) is None for k in ("available_supply", "consumption"))
                  else values["available_supply"]-values["consumption"])
    return dict(source=source, year=year, unit=selected[0]["unit"], observed=values,
                supply=identity(values, supply, "available_supply"),
                use=identity(values, use, "consumption"),
                supply_minus_consumption=difference,
                published_difference=values.get("balance_difference"),
                difference_rounding_residual=(
                    None if difference is None or values.get("balance_difference") is None
                    else difference-values["balance_difference"]),
                nested_terms_not_added=["power_generation_input", "heat_input"],
                status="published_checkpoint_not_forced_closed")
