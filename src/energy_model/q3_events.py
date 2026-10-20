"""Finite conditional events on a cloned Q2 state; never annual probabilities.

Shapes are repeated *inputs* over elapsed time, not cyclic state boundaries.
Every event uses annual_repeats=1. Pre-event dispatch is common and unaware of
the shock. At event onset all cases receive the same finite forecast horizon.
"""
from copy import deepcopy
from math import fsum

from .q2_national import operate_national, EF
from .q2_operations import Q2Error, number
from .q3_transition import service_id

EVENT_SCENARIOS = ("S0", "SG", "SW", "SGW")


def event_calendar(event, hours):
    start = number(event["start_hour"], "event start")
    duration = number(event["duration_hours"], "event duration", 1)
    recovery = number(event["recovery_hours"], "event recovery", 1)
    elapsed, rows = 0.0, []
    end = start + duration
    restored = end + recovery
    # Integrate the piecewise-linear event exactly within each interval.
    def integral(t):
        if t <= start:
            return 0.0
        if t <= end:
            return t-start
        z = min(t-end, recovery)
        return duration + z-z*z/(2*recovery)
    for i, h in enumerate(hours):
        rows.append(dict(period=i, start_hour=elapsed, end_hour=elapsed+h,
                         event_start_hour=start,
                         exposure=(integral(elapsed+h)-integral(elapsed))/h,
                         forcing_recovered=elapsed >= restored))
        elapsed += h
    if restored > elapsed:
        raise Q2Error("invalid_input", "Event forcing recovery lies beyond the window")
    return rows


def make_event_operation(snapshot, event, scenario, channel_fraction):
    if scenario not in EVENT_SCENARIOS:
        raise Q2Error("invalid_input", "Unknown event scenario")
    number(channel_fraction, "import channel fraction", 0, 1)
    day = [p["hours"] for p in snapshot["periods"]]
    if abs(sum(day)-24) > 1e-9:
        raise Q2Error("invalid_input", "Q2 snapshot must describe one 24-hour input shape")
    days = event["window_days"]
    if type(days) is not int or not 1 <= days <= 30:
        raise Q2Error("invalid_input", "Finite event requires 1..30 chronological days")
    gas_loss = number(event["gas_channel_loss"], "gas loss", 0, 1)
    weather_loss = number(event["renewable_loss"], "weather loss", 0, 1)
    op = deepcopy(snapshot)
    op.update(periods=deepcopy(snapshot["periods"])*days, annual_repeats=1, cyclic=False)
    hours = day*days
    calendar = event_calendar(event, hours)
    for fuel in op["fuels"].values():
        fuel["domestic_mw"] *= days
        fuel["import_mw"] *= days
        # Equal terminal stocks prevent obtaining free fuel from the boundary.
        fuel["terminal_mwh"] = fuel["initial_mwh"]
    channel = []
    for i, row in enumerate(calendar):
        original = op["fuels"]["gas"]["import_mw"][i]
        selected = original*channel_fraction
        other = original-selected
        selected *= 1-gas_loss*row["exposure"] if scenario in ("SG", "SGW") else 1
        op["fuels"]["gas"]["import_mw"][i] = selected+other
        channel.append(dict(period=i, selected_capacity_mw=selected,
                            other_import_capacity_mw=other,
                            domestic_capacity_mw=op["fuels"]["gas"]["domestic_mw"][i]))
    for tech, plant in op["plants"].items():
        plant["availability"] *= days
        plant["window_energy_budget_mwh"] *= days
        if scenario in ("SW", "SGW") and tech in ("wind", "solar"):
            plant["availability"] = [v*(1-weather_loss*c["exposure"])
                                     for v, c in zip(plant["availability"], calendar)]
        if scenario in ("SW", "SGW") and tech == "hydro":
            exposure = sum(c["exposure"]*h for c, h in zip(calendar, hours))/sum(hours)
            plant["window_energy_budget_mwh"] *= 1-weather_loss*exposure
    for demand in op["demands"].values():
        demand["service_mwh"] *= days
    for limit in op.get("spending_limits", {}).values():
        limit["budget_cny"] *= days
    op["storage"]["terminal_mwh"] = op["storage"]["initial_mwh"]
    return op, calendar, channel


def run_event(snapshot, event, scenario, channel_fraction, *, discharge_reference=None):
    op, calendar, channel = make_event_operation(snapshot, event, scenario, channel_fraction)
    starts = [r["start_hour"] for r in calendar]
    if event["start_hour"] not in starts:
        raise Q2Error("invalid_input", "Event onset must be on a period boundary for the shared pre-event state")
    prefix_length = starts.index(event["start_hour"])
    if discharge_reference is not None:
        if len(discharge_reference) != len(calendar):
            raise Q2Error("invalid_input", "Frozen response must match the event calendar")
        # Restrict an action, not physical power, energy, resource or service.
        op["storage"]["discharge_limit_mwh"] = list(discharge_reference)
    if not prefix_length:
        result = operate_national(op)
    else:
        # Solve the same unshocked prefix independently of all future shocks.
        # This closes the otherwise hidden anticipatory-stock confound.
        prefix = deepcopy(snapshot)
        prefix.update(periods=deepcopy(op["periods"][:prefix_length]), annual_repeats=1, cyclic=True)
        prefix_hours = sum(p["hours"] for p in prefix["periods"])
        for fuel in prefix["fuels"].values():
            fuel["domestic_mw"] = (fuel["domestic_mw"]*event["window_days"])[:prefix_length]
            fuel["import_mw"] = (fuel["import_mw"]*event["window_days"])[:prefix_length]
        for plant in prefix["plants"].values():
            plant["availability"] = (plant["availability"]*event["window_days"])[:prefix_length]
            plant["window_energy_budget_mwh"] *= prefix_hours/24
        for demand in prefix["demands"].values():
            demand["service_mwh"] = (demand["service_mwh"]*event["window_days"])[:prefix_length]
        for limit in prefix.get("spending_limits",{}).values():
            limit["budget_cny"] *= prefix_hours/24
        before = operate_national(prefix)
        suffix = deepcopy(op)
        suffix["periods"] = suffix["periods"][prefix_length:]
        for fuel, spec in suffix["fuels"].items():
            spec["domestic_mw"] = spec["domestic_mw"][prefix_length:]
            spec["import_mw"] = spec["import_mw"][prefix_length:]
            spec["initial_mwh"] = [r["closing_mwh"] for r in before["fuel"] if r["fuel"]==fuel][-1]
        for name, plant in suffix["plants"].items():
            plant["availability"] = plant["availability"][prefix_length:]
            used = fsum(r["output_mwh"] for r in before["generation"] if r["plant"]==name)
            plant["window_energy_budget_mwh"] = max(0,plant["window_energy_budget_mwh"]-used)
            opening = [r["output_mwh"] for r in before["generation"] if r["plant"]==name][-1]
            plant["initial_period_hours"] = prefix["periods"][-1]["hours"]
            plant["initial_power_mw"] = opening/plant["initial_period_hours"]
        for demand in suffix["demands"].values():
            demand["service_mwh"] = demand["service_mwh"][prefix_length:]
        for group, limit in suffix.get("spending_limits",{}).items():
            spent = fsum(r["input_mwh"]*snapshot["demands"][r["device"]]["purchase_price_per_mwh"]
                         for r in before["demand"] if snapshot["demands"][r["device"]].get("budget_group")==group)
            if spent > limit["budget_cny"]+.01:
                raise Q2Error("accounting_failure", "Common pre-event spending exceeds window budget")
            limit["budget_cny"] = max(0,limit["budget_cny"]-spent)
        suffix["storage"]["initial_mwh"] = before["storage"][-1]["closing_mwh"]
        if discharge_reference is not None:
            suffix["storage"]["discharge_limit_mwh"] = list(discharge_reference[prefix_length:])
        after = operate_national(suffix)
        result = dict(after)
        for name in ("resource_cost","dispatch_objective","policy_signal_cost","actual_dispatch_cost","behavioral_score","reference_fossil_mwh"):
            if name in before and name in after:
                result[name] = before[name]+after[name]
        result["max_residual"] = max(before["max_residual"],after["max_residual"])
        for kind in ("fuel","generation","demand","storage"):
            result[kind] = before[kind]+[{**r,"period":r["period"]+prefix_length} for r in after[kind]]
        for kind in ("balances","stages"):
            result[kind] = [dict(phase="common_pre_event",**r) for r in before[kind]]+[dict(phase="post_event",**r) for r in after[kind]]
    # Q2 settlement normally separates non-energy fuel. Short events do so here.
    for row in result["fuel"]:
        material = sum(d["input_mwh"] for d in result["demand"]
                       if d["sector"] == "nonenergy_feedstock" and d["carrier"] == row["fuel"]
                       and d["period"] == row["period"])
        row["nonenergy_mwh"] = material
        row["combustion_co2_t"] -= material*EF[row["fuel"]]
    for row in channel:
        actual = next(r for r in result["fuel"] if r["fuel"] == "gas" and r["period"] == row["period"])
        h = op["periods"][row["period"]]["hours"]
        # Equal source prices: declared deterministic accounting tie-break.
        other = min(actual["import_mwh"], row["other_import_capacity_mw"]*h)
        row.update(other_import_mwh=other, selected_import_mwh=actual["import_mwh"]-other,
                   allocation_identity="equal_cost_other_sources_first_accounting_convention")
    return dict(operation=op, result=result, calendar=calendar, sources=channel)


def safety_metrics(run, *, relative_tolerance, absolute_tolerance, recovery_periods):
    op, result, calendar = run["operation"], run["result"], run["calendar"]
    hours = [p["hours"] for p in op["periods"]]
    sectors = sorted({service_id(r) for r in result["demand"]})
    rows = []
    event_start = calendar[0]["event_start_hour"]
    for sector in sectors:
        periods = []
        for i, h in enumerate(hours):
            demand = [r for r in result["demand"] if service_id(r) == sector and r["period"] == i]
            requested = fsum(r["requested_service_mwh"] for r in demand)
            unmet = fsum(r["unmet_service_mwh"] for r in demand)
            periods.append((requested, unmet, unmet > max(absolute_tolerance, relative_tolerance*requested)))
        longest, streak = 0.0, 0.0
        for (_, _, short), h in zip(periods, hours):
            streak = streak+h if short else 0
            longest = max(longest, streak)
        requested = fsum(p[0] for p in periods)
        unmet = fsum(p[1] for p in periods)
        affected = [i for i, p in enumerate(periods) if p[2] and calendar[i]["end_hour"] > event_start]
        if requested == 0:
            status, recovery = "zero_demand", None
        elif not affected:
            status, recovery = "no_service_interruption", 0.0
        else:
            last = max(affected)
            if len(periods)-last-1 >= recovery_periods:
                status, recovery = "recovered", calendar[last+1]["start_hour"]-event_start
            else:
                status, recovery = "not_recovered_or_right_censored", None
        rows.append(dict(sector=sector, unit="MWh_service_proxy", requested_service_mwh=requested,
                         unmet_service_mwh=unmet, unmet_fraction=unmet/requested if requested else None,
                         longest_shortage_hours=longest, recovery_hours=recovery,
                         recovery_status=status, right_censored=bool(periods[-1][2]),
                         time_resolution_hours=max(hours),
                         recovery_identity="last_service_interruption_to_sustained_service; stocks separately reported"))
    return rows


def interaction(rows):
    """Per-service difference-in-differences, never add incompatible services."""
    indexed = {(r["scenario"], r["sector"]): r["unmet_service_mwh"] for r in rows}
    sectors = sorted({r["sector"] for r in rows})
    if len(indexed) != len(rows):
        raise Q2Error("invalid_input", "Duplicate interaction records")
    results = []
    for sector in sectors:
        if any((s, sector) not in indexed for s in EVENT_SCENARIOS):
            raise Q2Error("missing_input", "H02 requires all four matched scenarios")
        values = {s: indexed[s, sector] for s in EVENT_SCENARIOS}
        results.append(dict(sector=sector, unit="MWh_service_proxy",
                            J=values["SGW"]-values["SG"]-values["SW"]+values["S0"], **values))
    return results
