"""Chronological, single-node multi-carrier LP; all flow variables are MWh.

Electricity is measured at the generation bus except terminal equipment input.
Fuel/hydrogen energy uses LHV. Time weights NEVER enter stock recurrences.
The deterministic whole-window forecast is an explicit information assumption.
No unit commitment, network security, CCUS or seasonal extrapolation is claimed.
"""
from math import isfinite

import numpy as np
from scipy.optimize import linprog


class Q2Error(ValueError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def number(value, name, low=0, high=float("inf")):
    if type(value) not in (int, float) or not isfinite(value) or not low <= value <= high:
        raise Q2Error("invalid_input", f"{name}: expected finite number in [{low}, {high}]")
    return float(value)


class LP:
    def __init__(self):
        self.names, self.bounds, self.cost = [], [], []
        self.equalities, self.inequalities = [], []

    def var(self, name, upper, cost=0, lower=0):
        i = len(self.names)
        self.names.append(name)
        self.bounds.append((number(lower, name), number(upper, name)))
        self.cost.append(number(cost, name + ".cost"))
        if lower > upper:
            raise Q2Error("invalid_input", "Lower bound exceeds upper bound: " + name)
        return i

    def eq(self, terms, rhs, name):
        self.equalities.append((terms, rhs, name))

    def le(self, terms, rhs, name):
        self.inequalities.append((terms, rhs, name))

    def matrix(self, rows):
        if not rows:
            return None, None
        a = np.zeros((len(rows), len(self.names)))
        for i, (terms, _, _) in enumerate(rows):
            for j, coefficient in terms.items():
                a[i, j] += coefficient
        return a, np.array([r[1] for r in rows], dtype=float)

    def solve(self, costs, solver):
        ae, be = self.matrix(self.equalities)
        au, bu = self.matrix(self.inequalities)
        result = solver(costs, A_eq=ae, b_eq=be, A_ub=au, b_ub=bu,
                        bounds=self.bounds, method="highs",
                        options={"primal_feasibility_tolerance": 1e-8,
                                 "dual_feasibility_tolerance": 1e-8})
        if not result.success:
            raise Q2Error("infeasible" if result.status == 2 else "solver_failure",
                          f"HiGHS status {result.status}: {result.message}")
        if result.x is None or not np.isfinite(result.x).all():
            raise Q2Error("solver_failure", "Nonfinite solver solution")
        residual = max([0.0] + [abs(sum(result.x[j] * v for j, v in terms.items()) - rhs)
                        for terms, rhs, _ in self.equalities] +
                       [sum(result.x[j] * v for j, v in terms.items()) - rhs
                        for terms, rhs, _ in self.inequalities] +
                       [max(lo - result.x[j], result.x[j] - hi)
                        for j, (lo, hi) in enumerate(self.bounds)])
        if residual > 1e-6:
            raise Q2Error("solver_failure", f"Constraint residual {residual} exceeds 1e-6")
        return result, residual


def operate(config, *, solver=linprog):
    """Lexicographic shortages by frozen priority, then resource operating cost.

    Each demand has a fixed device input carrier/efficiency/capacity. Investment
    changes next year's devices, never LP fuel switching. Fuel supply and tanks
    are shared by all direct users and converters, including hydrogen facilities.
    Optional fossil allocation first preserves total fossil net bus output,
    then uses a convex behavioural score to allocate it among selected plants.
    The score is neither a resource expense nor a cash payment.
    """
    periods = config["periods"]
    if not periods:
        raise Q2Error("missing_input", "Empty operating window")
    hours = [number(p["hours"], "hours", 1e-9) for p in periods]
    weight = number(config["annual_repeats"], "annual_repeats", 1)
    cyclic = config["cyclic"]
    if type(cyclic) is not bool or (weight != 1 and not cyclic):
        raise Q2Error("invalid_input", "Repeated windows require cyclic fuel and storage boundaries")
    if weight * sum(hours) > 8760 + 1e-6:
        raise Q2Error("invalid_input", "Annual duration exceeds 8760 hours")
    n = len(periods)
    fuels, plants, demands = config["fuels"], config["plants"], config["demands"]
    if not plants or not demands:
        raise Q2Error("missing_input", "Plants and devices are required")
    displacement = config.get("fossil_displacement_priority_plants", [])
    if (type(displacement) is not list or
            any(type(name) is not str for name in displacement) or
            len(set(displacement)) != len(displacement)):
        raise Q2Error("invalid_input", "Fossil displacement plants must be distinct plant names")
    if any(name not in plants or plants[name]["input"] not in fuels or
           plants[name]["output"] != "electricity" for name in displacement):
        raise Q2Error("invalid_input", "Fossil displacement requires declared fuelled electricity plants")
    allocation = config.get("fossil_allocation_score")
    allocation_specs = {}
    if allocation is not None:
        if (type(allocation) is not dict or
                not {"kappa", "plants"}.issubset(allocation) or
                set(allocation) - {"kappa", "plants", "ratio_step"}):
            raise Q2Error("invalid_input", "Fossil allocation requires kappa and plants")
        kappa = number(allocation["kappa"], "allocation curvature", 1e-9)
        ratio_step = number(allocation.get("ratio_step", .1), "allocation ratio step", .01, 1)
        allocation_specs = allocation["plants"]
        if type(allocation_specs) is not dict or len(allocation_specs) < 2:
            raise Q2Error("invalid_input", "Fossil allocation requires at least two plants")
        for name, spec in allocation_specs.items():
            if (type(name) is not str or name not in plants or
                    plants[name]["input"] not in {"coal", "oil", "gas"} or
                    plants[name]["input"] not in fuels or plants[name]["output"] != "electricity"):
                raise Q2Error("invalid_input", "Allocation requires declared fossil electricity plants")
            if type(spec) is not dict or set(spec) != {"reference_cf", "initial_marginal_cost"}:
                raise Q2Error("invalid_input", "Invalid fossil allocation plant fields")
            number(spec["reference_cf"], name + ".reference CF", 1e-9, 1)
            number(spec["initial_marginal_cost"], name + ".initial marginal cost")
    # A set here changes HiGHS row order with PYTHONHASHSEED and can perturb
    # degenerate optima/roundoff across otherwise identical processes.
    carriers = sorted({"electricity", "hydrogen", *fuels})
    grid = config["grid"]
    eta_grid = number(grid["efficiency"], "grid efficiency", 1e-9, 1)
    grid_power = number(grid["power_mw"], "grid power")
    store = config["storage"]
    eta_c = number(store["charge_efficiency"], "charge efficiency", 1e-9, 1)
    eta_d = number(store["discharge_efficiency"], "discharge efficiency", 1e-9, 1)
    ecap = number(store["energy_mwh"], "storage energy")
    soc = number(store["initial_mwh"], "initial SOC", 0, ecap)
    lp = LP()
    bal = {(c, t): {} for c in carriers for t in range(n)}
    def add(c, t, i, value):
        if c not in carriers:
            raise Q2Error("invalid_input", "Unknown carrier: " + c)
        b = bal[c, t]
        b[i] = b.get(i, 0) + value
    g, inputs, u, supply, tanks, c, d, s = {}, {}, {}, {}, {}, {}, {}, {}
    policy_terms = {}
    auxiliary = {}
    shortages = {}
    for fuel, p in sorted(fuels.items()):
        capacity = number(p["tank_mwh"], fuel + ".tank")
        initial = number(p["initial_mwh"], fuel + ".initial", 0, capacity)
        terminal_minimum = (number(p["minimum_terminal_mwh"], fuel + ".terminal minimum", 0, capacity)
                            if "minimum_terminal_mwh" in p else None)
        if cyclic and terminal_minimum is not None and terminal_minimum > initial:
            raise Q2Error("invalid_input", "Terminal fuel reserve conflicts with cyclic opening stock")
        number(p["emission_t_per_mwh"], fuel + ".emission")
        if p.get("internal_recovered_carrier", False):
            if (fuel in {"coal", "oil", "gas", "biomass"}
                    or any(p[k] for k in ("domestic_cost_per_mwh", "import_cost_per_mwh",
                                          "emission_t_per_mwh", "initial_mwh"))
                    or any(p["domestic_mw"]) or any(p["import_mw"])):
                raise Q2Error("invalid_input", "Recovered carrier requires zero primary supply, opening stock and duplicate carbon")
        for t, h in enumerate(hours):
            domestic = lp.var(f"domestic/{fuel}/{t}", p["domestic_mw"][t] * h,
                              p["domestic_cost_per_mwh"] * weight)
            imported = lp.var(f"import/{fuel}/{t}", p["import_mw"][t] * h,
                              p["import_cost_per_mwh"] * weight)
            fill = lp.var(f"fill/{fuel}/{t}", p["injection_mw"] * h)
            take = lp.var(f"withdraw/{fuel}/{t}", p["withdrawal_mw"] * h)
            tank = lp.var(f"tank/{fuel}/{t}", capacity)
            supply[fuel, t] = (domestic, imported, fill, take)
            tanks[fuel, t] = tank
            terms = {tank: 1, fill: -1, take: 1}
            if t:
                terms[tanks[fuel, t-1]] = -1
            lp.eq(terms, initial if t == 0 else 0, f"inventory/{fuel}/{t}")
            for i, sign in ((domestic, 1), (imported, 1), (fill, -1), (take, 1)):
                add(fuel, t, i, sign)
        if cyclic:
            lp.eq({tanks[fuel, n-1]: 1}, initial, f"terminal/{fuel}")
        elif terminal_minimum is not None:
            lp.le({tanks[fuel, n-1]: -1}, -terminal_minimum, f"terminal-reserve/{fuel}")
    for name, p in sorted(plants.items()):
        efficiency = number(p["efficiency"], name + ".efficiency", 1e-9, 1)
        fuel, out = p["input"], p["output"]
        if out not in carriers or (fuel is not None and fuel not in carriers) or fuel == out:
            raise Q2Error("invalid_input", "Invalid converter carriers: " + name)
        own_use = number(p.get("auxiliary_use_fraction",0),name+".auxiliary use",0,1)
        if own_use and out != "electricity":
            raise Q2Error("invalid_input","Station electricity own use applies only to electrical generators")
        auxiliary[name] = own_use
        number(p["capacity_mw"], name + ".capacity")
        number(p["minimum_fraction"], name + ".minimum", 0, 1)
        number(p["ramp_mw_per_hour"], name + ".ramp")
        decision_ceiling = p.get("decision_ceiling_mwh")
        if "decision_ceiling_mwh" in p:
            if type(decision_ceiling) is not list or len(decision_ceiling) != n:
                raise Q2Error("invalid_input", "Decision ceiling must cover every operating period")
            decision_ceiling = [number(v, name + ".decision ceiling") for v in decision_ceiling]
        for t, h in enumerate(hours):
            available = number(p["availability"][t], name + ".availability", 0, 1)
            cap = p["capacity_mw"] * h * available
            i = lp.var(f"generation/{name}/{t}", cap, p["variable_cost_per_mwh"] * weight,
                       cap * p["minimum_fraction"])
            g[name, t] = i
            if decision_ceiling is not None:
                # Restrict actions without changing physical availability,
                # must-run output or the fossil score's interpolation grid.
                lp.le({i: 1}, decision_ceiling[t], f"decision-ceiling/{name}/{t}")
            adjustment = number(p.get("policy_cost_per_mwh",0),name+".policy",-float("inf"))
            lp.cost[i] += adjustment*weight
            policy_terms[i] = adjustment*weight
            # Capacity, fuel conversion, costs and reported generation are
            # gross. Only output net of station own use enters the bus.
            add(out, t, i, 1-own_use)
            if fuel:
                add(fuel, t, i, -1 / efficiency)
            if t:
                change = {i: 1/h, g[name, t-1]: -1/hours[t-1]}
                # Average power at period centres; no unit commitment is implied.
                limit = p["ramp_mw_per_hour"] * (h + hours[t-1]) / 2
                lp.le(change, limit, f"ramp+/{name}/{t}")
                lp.le({j: -v for j, v in change.items()}, limit, f"ramp-/{name}/{t}")
        if cyclic and n > 1:
            change = {g[name, 0]: 1/hours[0], g[name, n-1]: -1/hours[-1]}
            limit = p["ramp_mw_per_hour"] * (hours[0] + hours[-1]) / 2
            lp.le(change, limit, f"cyclic-ramp+/{name}")
            lp.le({j: -v for j, v in change.items()}, limit, f"cyclic-ramp-/{name}")
        lp.le({g[name, t]: 1 for t in range(n)},
              number(p["window_energy_budget_mwh"], name + ".water/feedstock/energy budget"),
              f"energy-budget/{name}")
    for name, p in sorted(demands.items()):
        efficiency = number(p["efficiency"], name + ".efficiency", 1e-9, 10)
        if type(p["priority"]) is not int or p["priority"] < 0:
            raise Q2Error("invalid_input", "Priority must be nonnegative integer")
        for t, h in enumerate(hours):
            requested = number(p["service_mwh"][t], name + ".service")
            x = lp.var(f"terminal-input/{name}/{t}", p["input_capacity_mw"] * h)
            unmet = lp.var(f"unmet-service/{name}/{t}", requested)
            inputs[name, t], u[name, t] = x, unmet
            adjustment = number(p.get("policy_cost_per_mwh",0),name+".policy",-float("inf"))
            lp.cost[x] += adjustment*weight
            policy_terms[x] = adjustment*weight
            lp.eq({x: efficiency, unmet: 1}, requested, f"service/{name}/{t}")
            add(p["carrier"], t, x, -1/eta_grid if p["carrier"] == "electricity" else -1)
            shortages.setdefault(p["priority"], []).append(unmet)
    # One wallet may fund several device/carrier rows; do not give each row a
    # fresh copy of the same budget. Unaffordable service remains in u above.
    for group, budget in sorted(config.get("spending_limits", {}).items()):
        terms = {}
        for name, p in demands.items():
            if p.get("budget_group") == group:
                price = number(p["purchase_price_per_mwh"], name + ".purchase_price", 0)
                terms.update({inputs[name, t]: price for t in range(n)})
        if not terms:
            raise Q2Error("invalid_input", "Spending limit has no demand: " + group)
        # Positive row scaling keeps currency magnitudes out of the energy LP;
        # this is the same constraint, with unchanged affordability bounds.
        scale = max(1,max(terms.values()))
        lp.le({i:v/scale for i,v in terms.items()}, number(budget["budget_cny"], group + ".budget")/scale, "spending/" + group)
    for name, p in demands.items():
        if "budget_group" in p and p["budget_group"] not in config.get("spending_limits", {}):
            raise Q2Error("invalid_input", "Missing spending limit: " + name)
    # Recover only a bounded part of energy already paid for and consumed by
    # an upstream service. This is an internal transfer from its loss stream,
    # not another coal/oil/gas delivery or another combustion emission charge.
    recovery_specs=config.get("recoveries",{})
    if not isinstance(recovery_specs,dict):
        raise Q2Error("invalid_input","Recoveries must be an explicit mapping")
    recovered_variables={}
    allocated_losses={}
    for name,p in sorted(recovery_specs.items()):
        target=p["output"]
        shares=p["source_input_fractions"]
        if target not in fuels or not isinstance(shares,dict) or not shares:
            raise Q2Error("invalid_input","Recovery needs a carrier and declared upstream services")
        target_spec=fuels[target]
        if not target_spec.get("internal_recovered_carrier",False) or target in {"coal","oil","gas","biomass"}:
            raise Q2Error("invalid_input","Recovered energy cannot be relabelled primary fuel")
        if (any(target_spec[k] for k in ("domestic_cost_per_mwh","import_cost_per_mwh","emission_t_per_mwh"))
                or any(target_spec["domestic_mw"]) or any(target_spec["import_mw"])):
            raise Q2Error("invalid_input","Internal recovered carrier has primary supply, price or duplicate carbon")
        for source,fraction in shares.items():
            number(fraction,name+".recovery fraction",0,1)
            if (source not in demands or demands[source]["carrier"] not in fuels
                    or demands[source]["carrier"]==target or demands[source]["efficiency"]>1
                    or demands[source].get("sector")=="nonenergy_feedstock"
                    or fuels[demands[source]["carrier"]].get("internal_recovered_carrier",False)):
                raise Q2Error("invalid_input","Recovery source must be a distinct fuel service with bounded energy losses")
            allocated_losses[source]=allocated_losses.get(source,0)+fraction
            if allocated_losses[source]>1-demands[source]["efficiency"]+1e-12:
                raise Q2Error("invalid_input","Recoveries exceed upstream service energy losses")
        for t,h in enumerate(hours):
            maximum=sum(demands[k]["input_capacity_mw"]*h*v for k,v in shares.items())
            variable=lp.var(f"recovered/{name}/{t}",maximum)
            terms={variable:1}
            terms.update({inputs[k,t]:-v for k,v in shares.items()})
            lp.le(terms,0,f"available-recovery/{name}/{t}")
            add(target,t,variable,1)
            recovered_variables[name,t]=variable
    for t, h in enumerate(hours):
        c[t] = lp.var(f"charge/{t}", store["power_mw"] * h, store["throughput_cost"] * weight)
        d[t] = lp.var(f"discharge/{t}", store["power_mw"] * h, store["throughput_cost"] * weight)
        s[t] = lp.var(f"SOC/{t}", ecap)
        terms = {s[t]: 1, c[t]: -eta_c, d[t]: 1/eta_d}
        if t:
            terms[s[t-1]] = -1
        lp.eq(terms, soc if t == 0 else 0, f"SOC-balance/{t}")
        lp.le({c[t]: 1, d[t]: 1}, store["power_mw"] * h, f"shared-inverter/{t}")
        add("electricity", t, c[t], -1)
        add("electricity", t, d[t], 1)
        delivery = {inputs[name, t]: 1/eta_grid for name, p in demands.items()
                    if p["carrier"] == "electricity"}
        lp.le(delivery, grid_power * h, f"grid/{t}")
    if cyclic:
        lp.eq({s[n-1]: 1}, soc, "terminal-SOC")
    else:
        lp.eq({s[n-1]: 1}, number(store["terminal_mwh"], "terminal SOC", 0, ecap), "terminal-SOC")
    # Pumped hydro and batteries may share the bus but never share a fictitious
    # pooled SOC or efficiency. Each additional store has its own paid asset,
    # power/energy bounds and explicit initial/terminal stock supplied by caller.
    extra_stores = config.get("additional_storage",{})
    if not isinstance(extra_stores,dict) or any(not isinstance(k,str) or not k or k=="main" for k in extra_stores):
        raise Q2Error("invalid_input","Additional storage must have distinct non-main names")
    extra_variables = {}
    for name,p in sorted(extra_stores.items()):
        power = number(p["power_mw"],name+".power")
        capacity = number(p["energy_mwh"],name+".energy")
        opening = number(p["initial_mwh"],name+".initial",0,capacity)
        charging = number(p["charge_efficiency"],name+".charge efficiency",1e-9,1)
        discharging = number(p["discharge_efficiency"],name+".discharge efficiency",1e-9,1)
        throughput = number(p["throughput_cost"],name+".throughput cost")
        charge,discharge,stock = {},{},{}
        for t,h in enumerate(hours):
            charge[t]=lp.var(f"charge/{name}/{t}",power*h,throughput*weight)
            discharge[t]=lp.var(f"discharge/{name}/{t}",power*h,throughput*weight)
            stock[t]=lp.var(f"SOC/{name}/{t}",capacity)
            terms={stock[t]:1,charge[t]:-charging,discharge[t]:1/discharging}
            if t:terms[stock[t-1]]=-1
            lp.eq(terms,opening if t==0 else 0,f"SOC-balance/{name}/{t}")
            lp.le({charge[t]:1,discharge[t]:1},power*h,f"shared-machine/{name}/{t}")
            add("electricity",t,charge[t],-1)
            add("electricity",t,discharge[t],1)
        terminal=opening if cyclic else number(p["terminal_mwh"],name+".terminal",0,capacity)
        lp.eq({stock[n-1]:1},terminal,f"terminal-SOC/{name}")
        extra_variables[name]=(charge,discharge,stock,opening,charging,discharging)
    for (carrier, t), terms in bal.items():
        lp.eq(terms, 0, f"carrier/{carrier}/{t}")
    behavioral = []
    for name, spec in sorted(allocation_specs.items()):
        anchor = plants[name]["capacity_mw"] * sum(hours) * spec["reference_cf"]
        maximum = min(sum(lp.bounds[g[name, t]][1] for t in range(n)),
                      plants[name]["window_energy_budget_mwh"])
        terms = {g[name, t]: -1 for t in range(n)}
        if anchor > 0 and maximum > 0:
            last = maximum / anchor
            # Fine segments around the anchor; geometric tails bound the number
            # of columns even when the initial observed utilisation is tiny.
            ratios = {0.0, last}
            ratios.update(round(k * ratio_step, 12)
                          for k in range(1, int(min(4, last) / ratio_step) + 1))
            ratios.update(r for r in (1.0, 2.0, 4.0) if r < last)
            tail = 8.0
            while tail < last:
                ratios.add(tail)
                tail *= 2
            knots = sorted(r for r in ratios if r <= last)
            for k, (left, right) in enumerate(zip(knots, knots[1:])):
                j = lp.var(f"allocation/{name}/{k}", anchor * (right - left))
                terms[j] = 1
                slope = -spec["initial_marginal_cost"] + kappa * ((left + right) / 2 - 1)
                behavioral.append((j, slope * weight))
        lp.eq(terms, 0, f"allocation-segments/{name}")
    stages = []
    for priority, indices in sorted(shortages.items()):
        objective = np.zeros(len(lp.names))
        objective[indices] = 1
        result, residual = lp.solve(objective, solver)
        optimum = float(sum(result.x[j] for j in indices))
        lp.eq({j: 1 for j in indices}, optimum, f"fixed-shortage/{priority}")
        stages.append({"stage": f"service-priority-{priority}", "objective": optimum,
                       "status": int(result.status), "max_residual": residual})
    if displacement:
        # Count electricity delivered to the bus. Gross output would rank gas
        # ahead of coal solely because station own-use differs, freezing a
        # fuel-mix preference before costs or allocation can be considered.
        terms = {g[name, t]: 1-plants[name].get("auxiliary_use_fraction",0)
                 for name in sorted(displacement) for t in range(n)}
        objective = np.zeros(len(lp.names))
        for j,value in terms.items():objective[j] = value
        result, residual = lp.solve(objective, solver)
        optimum = float(sum(result.x[j]*value for j,value in terms.items()))
        lp.eq(terms, optimum, "fixed-fossil-displacement")
        stages.append({"stage": "fossil-displacement-priority", "objective": optimum,
                       "energy_basis": "net_bus_output_mwh",
                       "plants": sorted(displacement), "status": int(result.status),
                       "max_residual": residual})
    reference_fossil = None
    if allocation_specs:
        reference, reference_residual = lp.solve(lp.cost, solver)
        terms = {g[name, t]: 1-plants[name].get("auxiliary_use_fraction",0)
                 for name in sorted(allocation_specs) for t in range(n)}
        reference_fossil = float(sum(reference.x[j]*value for j,value in terms.items()))
        lp.eq(terms, reference_fossil, "fixed-reference-fossil-total")
        stages.append({"stage": "reference-resource-cost", "objective": float(reference.fun),
                       "status": int(reference.status), "max_residual": reference_residual})
        generalized = np.array(lp.cost, dtype=float)
        for j, slope in behavioral:
            generalized[j] += slope
        result, residual = lp.solve(generalized, solver)
    else:
        result, residual = lp.solve(lp.cost, solver)
    x = result.x
    stages.append({"stage": "fossil-allocation-score" if allocation_specs else "resource-cost",
                   "objective": float(result.fun),
                   "status": int(result.status), "max_residual": residual})
    if any(min(x[c[t]], x[d[t]]) > 1e-6 for t in range(n)):
        raise Q2Error("unsupported_operation", "Simultaneous battery charge/discharge; requires MILP")
    for name,(charge,discharge,*_) in extra_variables.items():
        if any(min(x[charge[t]],x[discharge[t]])>1e-6 for t in range(n)):
            raise Q2Error("unsupported_operation",f"Simultaneous {name} charge/discharge; requires MILP")
    fuel_rows, generation_rows, demand_rows, storage_rows, balance_rows = [], [], [], [], []
    for (fuel, t), indices in supply.items():
        p = fuels[fuel]
        direct = sum(x[inputs[name, t]] for name, a in demands.items() if a["carrier"] == fuel)
        converted = sum(x[g[name, t]] / a["efficiency"] for name, a in plants.items() if a["input"] == fuel)
        domestic, imported, fill, take = [float(x[j]) for j in indices]
        fuel_rows.append(dict(fuel=fuel, period=t, domestic_mwh=domestic, import_mwh=imported,
                              fill_mwh=fill, withdrawal_mwh=take, closing_mwh=float(x[tanks[fuel,t]]),
                              direct_mwh=float(direct), conversion_mwh=float(converted),
                              recovered_in_mwh=float(sum(x[i] for (name,period),i in recovered_variables.items()
                                  if period==t and recovery_specs[name]["output"]==fuel)),
                              internal_recovered_carrier=bool(p.get("internal_recovered_carrier",False)),
                              combustion_co2_t=float((direct + converted) * p["emission_t_per_mwh"])))
    recovery_rows=[]
    for (name,t),i in recovered_variables.items():
        p=recovery_specs[name]
        potential=float(sum(x[inputs[k,t]]*v for k,v in p["source_input_fractions"].items()))
        recovery_rows.append(dict(recovery=name,period=t,carrier=p["output"],
            available_from_upstream_mwh=potential,recovered_mwh=float(x[i]),
            unrecovered_mwh=potential-float(x[i]),additional_primary_input_mwh=0.0,
            additional_combustion_co2_t=0.0,
            carbon_boundary="source fuel combustion already charged upstream; no second charge"))
    for (name, t), i in g.items():
        generation_rows.append(dict(plant=name, period=t, output=plants[name]["output"],
                                    output_mwh=float(x[i]),auxiliary_use_mwh=float(x[i]*auxiliary[name]),
                                    bus_output_mwh=float(x[i]*(1-auxiliary[name])),
                                    input_mwh=float(x[i]/plants[name]["efficiency"])
                                    if plants[name]["input"] else 0.0))
    for (name, t), i in inputs.items():
        p = demands[name]
        demand_rows.append(dict(device=name, sector=p["sector"], period=t, carrier=p["carrier"],
                               input_mwh=float(x[i]), requested_service_mwh=p["service_mwh"][t],
                               served_service_mwh=float(x[i] * p["efficiency"]), unmet_service_mwh=float(x[u[name,t]])))
    for t in range(n):
        storage_rows.append(dict(period=t, opening_mwh=soc if t == 0 else float(x[s[t-1]]),
                                 charge_mwh=float(x[c[t]]), discharge_mwh=float(x[d[t]]), closing_mwh=float(x[s[t]])))
    extra_storage_rows=[]
    for name,(charge,discharge,stock,opening,charging,discharging) in extra_variables.items():
        for t in range(n):
            extra_storage_rows.append(dict(store=name,period=t,
                opening_mwh=opening if t==0 else float(x[stock[t-1]]),
                charge_mwh=float(x[charge[t]]),discharge_mwh=float(x[discharge[t]]),
                charging_loss_mwh=float(x[charge[t]]*(1-charging)),
                discharging_loss_mwh=float(x[discharge[t]]*(1/discharging-1)),
                closing_mwh=float(x[stock[t]])))
    for terms, rhs, name in lp.equalities:
        balance_rows.append(dict(constraint=name, residual=float(sum(x[i]*v for i,v in terms.items())-rhs)))
    policy_cost = sum(x[i]*v for i,v in policy_terms.items())
    actual_objective = float(np.dot(lp.cost, x)) if allocation_specs else float(result.fun)
    allocation_result = dict(actual_dispatch_cost=actual_objective,
        behavioral_score=float(sum(x[j] * slope for j, slope in behavioral)),
        reference_fossil_mwh=reference_fossil,
        reference_fossil_energy_basis="net_bus_output_mwh") if allocation_specs else {}
    return dict(status="optimal", annual_repeats=weight, resource_cost=actual_objective-policy_cost,
                dispatch_objective=float(result.fun), policy_signal_cost=policy_cost,
                **allocation_result,
                fuel=fuel_rows, generation=generation_rows, demand=demand_rows, storage=storage_rows,
                additional_storage=extra_storage_rows,
                recoveries=recovery_rows,
                balances=balance_rows, stages=stages, max_residual=residual)
