"""Frozen multi-target search, already-seen holdout and paired sensitivities."""
from copy import deepcopy
from itertools import product
import math

from .q2_agents import simulate
from .q2_operations import Q2Error, number


PARAMETERS = {"activity_elasticity", "investment_rate", "replacement_rate", "expectation_rate"}


def validate_model(c):
    if c["scope"] not in {"synthetic_engineering_fixture", "China_mainland_conditional"}:
        raise Q2Error("invalid_input", "Unsupported scope")
    if c["information"] != "known_deterministic_repeated_window_no_weather_probability":
        raise Q2Error("invalid_input", "Information assumption must be explicit")
    if c["primary_accounting"] != "physical_LHV_noncombustion_equivalent_explicit":
        raise Q2Error("invalid_input", "Unimplemented primary-energy accounting")
    if c["carbon_accounting"] != "combustion_only_plus_explicit_bridge_no_CCS":
        raise Q2Error("invalid_input", "Unimplemented carbon accounting")
    if c["scope"] != "synthetic_engineering_fixture":
        # Deliberately fail closed until stock/ETS/primary accounting bridges are implemented.
        raise Q2Error("unsupported_national_model", "National cohort, ETS and statistical accounting bridges not implemented")
    number(c["base_gdp_index"], "base GDP", 1e-9)
    if abs(sum(p["hours"] for p in c["periods"])*c["annual_repeats"]-8760) > 1e-6:
        raise Q2Error("invalid_input", "Annual model requires exactly 8760 weighted hours")
    for name,p in c["generators"].items():
        for field in ("capex_per_mw","lifetime_years","lead_years"):
            number(p[field], name+"."+field, 1e-9)
        for field in ("lifetime_years","lead_years"):
            if type(p[field]) is not int:
                raise Q2Error("invalid_input", "Construction/life years must be integers")
        for field in ("discount_rate","build_limit_mw","fixed_cost_per_mw","initial_expected_margin_per_mw","primary_equivalent_per_output_mwh"):
            number(p[field], name+"."+field)
        if p["operation"]["input"] in c["suppliers"] and p["operation"]["output"] != "electricity":
            raise Q2Error("invalid_input", "Fuel reforming/CCS not implemented; combustion converters output electricity")
    for name,p in c["consumers"].items():
        for field in ("fossil_service_mw","electric_service_mw","base_service_mwh","installation_limit_mw","income_per_service_mwh"):
            number(p[field], name+"."+field)
        for field in ("capex_per_service_mw","device_lifetime_years","payback_years","fuel_efficiency","electric_efficiency"):
            number(p[field], name+"."+field, 1e-9)
        number(p["service_intensity_decline"], "service intensity decline", 0, .5)
        if len(p["shape"]) != len(c["periods"]) or abs(sum(p["shape"])-1) > 1e-9 or min(p["shape"]) < 0:
            raise Q2Error("invalid_input", "Service shape must be nonnegative and sum to 1")
    ids = set()
    for p in c["initial_cohorts"]:
        if p["id"] in ids or p["plant"] not in c["generators"]:
            raise Q2Error("invalid_input", "Duplicate/unknown asset")
        ids.add(p["id"])
        number(p["capacity_mw"], "asset capacity")
        if not p["online_year"] <= c["start_year"] < p["retirement_year"]:
            raise Q2Error("invalid_input", "Initial cohort not present at start")
        if p["legal_exit_year"] < p["online_year"]:
            raise Q2Error("invalid_input", "Invalid legal exit")
    for year,driver in c["drivers"].items():
        number(driver["gdp_index"], year+" GDP", 1e-9)
        number(driver["cost_decline"], "cost decline", 0, .5)
        for field in ("carbon_price","generation_price","retail_price","hydrogen_price"):
            number(driver[field], field)
    for p in c["policies"]:
        if p["effective_year"] < p["published_year"] or not p["basis"]:
            raise Q2Error("invalid_input", "Retroactive/undocumented policy")
        for value in p["coverage"].values():
            number(value,"coverage",0,1)
    for row in c["carbon_bridge"].values():
        number(row["other_positive_t"], "non-energy emissions")
        number(row["net_removals_t"], "net removals")


def validate_design(c):
    if c["training_years"] != list(range(2015,2022)) or c["evaluation_years"] != [2022,2023,2024]:
        raise Q2Error("invalid_input", "Frozen 2015–2021 / 2022–2024 windows required")
    if c["evaluation_identity"] != "already_seen_not_blind":
        raise Q2Error("invalid_input", "Holdout must retain already-seen identity")
    if set(c["parameter_grid"]) != PARAMETERS or not c["frozen_before_evaluation"]:
        raise Q2Error("invalid_input", "Frozen parameter grid required")
    grid = c["parameter_grid"]
    for name,values in grid.items():
        if not values or len(values) != len(set(values)):
            raise Q2Error("invalid_input", "Empty/duplicate parameter grid")
        for v in values:
            number(v,name,0,2 if name == "activity_elasticity" else 1)
    if math.prod(map(len,grid.values())) != c["search_budget"]:
        raise Q2Error("invalid_input", "Declared search budget differs from grid")
    families = {t["family"] for t in c["targets"]}
    if not {"demand","structure","capacity_generation","emissions"}.issubset(families):
        raise Q2Error("missing_input", "Multi-target calibration lacks required families")
    if len({t["metric"] for t in c["targets"]}) != len(c["targets"]):
        raise Q2Error("invalid_input", "Duplicate calibration target")
    for target in c["targets"]:
        number(target["scale"],"target scale",1e-9)
        number(target["weight"],"target weight",1e-9)
    if c["peak_persistence_years"] < 1:
        raise Q2Error("invalid_input", "Positive peak persistence required")
    if set(c["sensitivity"]) != {"gdp_growth_delta","cost_decline_delta","carbon_price_multiplier"}:
        raise Q2Error("missing_input", "All three sensitivity factors required")
    if sum(len(v) for v in c["sensitivity"].values()) != c["sensitivity_budget"]:
        raise Q2Error("invalid_input", "Sensitivity budget mismatch")
    for key,values in c["sensitivity"].items():
        if len(values) < 2 or len(values) != len(set(values)):
            raise Q2Error("invalid_input", "At least two distinct sensitivity values per factor")
        for value in values:
            number(value,key,0 if key == "carbon_price_multiplier" else -.5,10 if key == "carbon_price_multiplier" else .5)


def losses(paths, observations, design, years):
    simulated = {int(r["year"]):r for r in paths}
    components, fitted = [], []
    for target in design["targets"]:
        metric = target["metric"]
        valid = [r for r in observations if r["metric"] == metric and int(r["year"]) in years and r["value"] is not None]
        if not valid:
            raise Q2Error("missing_input", f"No comparable observations: {metric}, {years}")
        errors = []
        for r in valid:
            predicted = simulated[int(r["year"])][metric]
            if predicted is None:
                raise Q2Error("missing_input", "Missing model metric: "+metric)
            observed = number(r["value"],"observed",0)
            error = predicted-observed
            errors.append((error/target["scale"])**2)
            fitted.append(dict(year=int(r["year"]),metric=metric,observed=observed,simulated=predicted,
                residual=error,scaled_residual=error/target["scale"],source_ref=r["source_ref"]))
        components.append(dict(metric=metric,n=len(errors),missing_years=sorted(set(years)-{int(r["year"]) for r in valid}),
            scale=target["scale"],weight=target["weight"],weighted_loss=target["weight"]*sum(errors)/len(errors)))
    return sum(c["weighted_loss"] for c in components),components,fitted


def calibrate(model, observations, design):
    validate_model(model)
    validate_design(design)
    keys, seen = sorted(design["parameter_grid"]), set()
    for r in observations:
        key = (int(r["year"]),r["metric"])
        if key in seen or not r["source_ref"]:
            raise Q2Error("invalid_input", "Duplicate/unreferenced observation")
        seen.add(key)
    trials = []
    for values in product(*(design["parameter_grid"][k] for k in keys)):
        theta = dict(zip(keys,values))
        try:
            path = simulate(model,theta,2021).paths
            loss,components,_ = losses(path,observations,design,design["training_years"])
            trials.append(dict(parameters=theta,loss=loss,status="success",components=components))
        except Q2Error as exc:
            trials.append(dict(parameters=theta,loss=None,status=exc.status,error=str(exc)))
    valid = sorted((r for r in trials if r["loss"] is not None),key=lambda r:r["loss"])
    if not valid:
        raise Q2Error("calibration_failed", "All parameter candidates failed; first: "+trials[0].get("error",""))
    best = valid[0]
    # Evaluation is reached only AFTER the winner is selected using training records.
    fitted_model = simulate(model,best["parameters"],2024)
    fit = []
    quality = {}
    for split,years in (("training",design["training_years"]),("already_seen_evaluation",design["evaluation_years"])):
        loss,parts,rows = losses(fitted_model.paths,observations,design,years)
        quality[split] = dict(loss=loss,components=parts)
        fit += [dict(split=split,method="coupled_agents",**r) for r in rows]
    # Simple persistence baseline uses the last TRAINING observation, never holdout fitting.
    persistence = []
    for year in range(2015,2025):
        row = {"year":year}
        for target in design["targets"]:
            source = sorted([r for r in observations if r["metric"] == target["metric"] and int(r["year"]) <= min(year-1,2021)],
                            key=lambda r:int(r["year"]))
            if not source:
                source = [r for r in observations if r["metric"] == target["metric"] and int(r["year"]) == 2015]
            row[target["metric"]] = source[-1]["value"]
        persistence.append(row)
    base_loss,_,rows = losses(persistence,observations,design,design["evaluation_years"])
    fit += [dict(split="already_seen_evaluation",method="training_last_value",**r) for r in rows]
    alternative = simulate(model,best["parameters"],2024,investment=False,substitution=False)
    alt_loss,_,rows = losses(alternative.paths,observations,design,design["evaluation_years"])
    fit += [dict(split="already_seen_evaluation",method="frozen_investment_and_substitution",**r) for r in rows]
    bound = best["loss"]+design["equivalent_absolute_tolerance"]+abs(best["loss"])*design["equivalent_relative_tolerance"]
    return dict(best=best,quality=quality,trials=trials,
                equivalent_parameters=[r["parameters"] for r in valid if r["loss"] <= bound],
                baseline_loss=base_loss,alternative_rule_loss=alt_loss,
                evaluation_identity=design["evaluation_identity"],
                acceptance="engineering_only" if model["scope"] == "synthetic_engineering_fixture" else "not_team_accepted"),fit


def peak_check(paths, persistence):
    rows = sorted(paths,key=lambda r:int(r["year"]))
    if not rows or any(r.get("positive_co2_t") is None for r in rows):
        return dict(status="missing_same_scope_emissions",year=None,value=None)
    if any(int(b["year"]) != int(a["year"])+1 for a,b in zip(rows,rows[1:])):
        return dict(status="missing_years",year=None,value=None)
    maximum = max(r["positive_co2_t"] for r in rows)
    maxima = [i for i,r in enumerate(rows) if abs(r["positive_co2_t"]-maximum) <= 1e-8]
    index = maxima[-1]
    after = rows[index+1:]
    first = rows[index:index+persistence+1]
    sustained = (len(after) >= persistence and all(r["positive_co2_t"] < maximum-1e-8 for r in after)
                 and all(b["positive_co2_t"] <= a["positive_co2_t"]+1e-8 for a,b in zip(first,first[1:])))
    return dict(status="sustained_in_simulated_horizon" if sustained else "not_confirmed",year=rows[index]["year"] if sustained else None,
                value=maximum,observed_max_year=rows[index]["year"],persistence=persistence)


def target_rows(paths, design, *, peak_history=()):
    years = {int(r["year"]):r for r in paths}
    all_rows = {int(r["year"]):r for r in peak_history}
    all_rows.update(years)
    peak = peak_check(list(all_rows.values()),design["peak_persistence_years"])
    rows = []
    for year in (2030,2060):
        p = years[year]
        for metric,unit in (("primary_energy_mwh","MWh LHV/equivalent"),("nonfossil_primary_share","fraction"),
                            ("positive_co2_t","t CO2"),("net_removals_t","t CO2"),("net_co2_t","t CO2"),
                            ("neutralisation_ratio","R/P"),("energy_intensity","MWh/GDP index"),
                            ("carbon_intensity","t CO2/GDP index")):
            value = p[metric]
            rows.append(dict(year=year,metric=metric,value=value,unit=unit,scope=p["scope"],
                target=None,judgement="engineering_only" if value is not None else "missing_input",basis="No official-accounting equivalence established"))
        rows.append(dict(year=year,metric="peak_year",value=peak["year"],unit="year",scope=p["scope"],
                         target=2030,judgement=peak["status"],basis="Full supplied history plus projection; no future certainty"))
        for base_year in (2005,2025):
            for metric in ("energy_intensity","carbon_intensity"):
                base = all_rows.get(base_year,{}).get(metric)
                value = 1-p[metric]/base if base is not None and base > 0 and p[metric] is not None else None
                rows.append(dict(year=year,metric=f"{metric}_reduction_vs_{base_year}",value=value,unit="fraction",scope=p["scope"],
                    target=None,judgement="engineering_only" if value is not None else "missing_comparable_base",basis=f"Explicit {base_year} base"))
    return rows,peak


def forecast(model,theta,design,equivalent_parameters):
    validate_model(model)
    if model["start_year"] != 2024:
        raise Q2Error("invalid_input", "Forecast requires separate 2024 initialization")
    baseline = simulate(model,theta,2060)
    sensitivity,scenarios = [],[]
    for factor in ("gdp_growth_delta","cost_decline_delta","carbon_price_multiplier"):
        for value in design["sensitivity"][factor]:
            c = deepcopy(model)
            for y in range(2025,2061):
                d = c["drivers"][str(y)]
                if factor == "gdp_growth_delta":
                    # Perturb the annual growth factor, not the GDP level by a fixed percent.
                    previous = model["drivers"][str(y-1)]["gdp_index"]
                    growth = model["drivers"][str(y)]["gdp_index"]/previous-1
                    d["gdp_index"] = c["drivers"][str(y-1)]["gdp_index"]*(1+growth+value)
                elif factor == "cost_decline_delta":
                    d["cost_decline"] += value
                else:
                    d["carbon_price"] *= value
            scenarios.append((f"{factor}={value}",factor,value,c,theta))
    for index,parameters in enumerate(equivalent_parameters):
        scenarios.append((f"equivalent-{index}","equivalent_parameter",index,deepcopy(model),parameters))
    for label,factor,value,c,parameters in scenarios:
        try:
            validate_model(c)
            path = simulate(c,parameters,2060).paths
            peak = peak_check(path,design["peak_persistence_years"])
            for p in path:
                if p["year"] not in (2030,2060):
                    continue
                b = next(r for r in baseline.paths if r["year"] == p["year"])
                sensitivity.append(dict(scenario=label,factor=factor,input_value=value,year=p["year"],status="success",
                    primary_energy_mwh=p["primary_energy_mwh"],nonfossil_primary_share=p["nonfossil_primary_share"],
                    combustion_co2_t=p["combustion_co2_t"],delta_co2_t=p["combustion_co2_t"]-b["combustion_co2_t"],
                    unmet_service_mwh=p["unmet_service_mwh"],resource_cost=p["resource_cost"],peak_status=peak["status"],
                    max_residual=p["max_residual"],scope=c["scope"]))
        except Q2Error as exc:
            sensitivity.append(dict(scenario=label,factor=factor,input_value=value,year=None,status=exc.status,error=str(exc)))
    return baseline,sensitivity
