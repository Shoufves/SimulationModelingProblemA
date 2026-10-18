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
    shortages = {}
    for fuel, p in sorted(fuels.items()):
        capacity = number(p["tank_mwh"], fuel + ".tank")
        initial = number(p["initial_mwh"], fuel + ".initial", 0, capacity)
        number(p["emission_t_per_mwh"], fuel + ".emission")
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
    for name, p in sorted(plants.items()):
        efficiency = number(p["efficiency"], name + ".efficiency", 1e-9, 1)
        fuel, out = p["input"], p["output"]
        if out not in carriers or (fuel is not None and fuel not in carriers) or fuel == out:
            raise Q2Error("invalid_input", "Invalid converter carriers: " + name)
        number(p["capacity_mw"], name + ".capacity")
        number(p["minimum_fraction"], name + ".minimum", 0, 1)
        number(p["ramp_mw_per_hour"], name + ".ramp")
        for t, h in enumerate(hours):
            available = number(p["availability"][t], name + ".availability", 0, 1)
            cap = p["capacity_mw"] * h * available
            i = lp.var(f"generation/{name}/{t}", cap, p["variable_cost_per_mwh"] * weight,
                       cap * p["minimum_fraction"])
            g[name, t] = i
            add(out, t, i, 1)
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
            lp.eq({x: efficiency, unmet: 1}, requested, f"service/{name}/{t}")
            add(p["carrier"], t, x, -1/eta_grid if p["carrier"] == "electricity" else -1)
            shortages.setdefault(p["priority"], []).append(unmet)
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
    for (carrier, t), terms in bal.items():
        lp.eq(terms, 0, f"carrier/{carrier}/{t}")
    stages = []
    for priority, indices in sorted(shortages.items()):
        objective = np.zeros(len(lp.names))
        objective[indices] = 1
        result, residual = lp.solve(objective, solver)
        optimum = float(sum(result.x[j] for j in indices))
        lp.eq({j: 1 for j in indices}, optimum, f"fixed-shortage/{priority}")
        stages.append({"stage": f"service-priority-{priority}", "objective": optimum,
                       "status": int(result.status), "max_residual": residual})
    result, residual = lp.solve(lp.cost, solver)
    x = result.x
    stages.append({"stage": "resource-cost", "objective": float(result.fun),
                   "status": int(result.status), "max_residual": residual})
    if any(min(x[c[t]], x[d[t]]) > 1e-6 for t in range(n)):
        raise Q2Error("unsupported_operation", "Simultaneous battery charge/discharge; requires MILP")
    fuel_rows, generation_rows, demand_rows, storage_rows, balance_rows = [], [], [], [], []
    for (fuel, t), indices in supply.items():
        p = fuels[fuel]
        direct = sum(x[inputs[name, t]] for name, a in demands.items() if a["carrier"] == fuel)
        converted = sum(x[g[name, t]] / a["efficiency"] for name, a in plants.items() if a["input"] == fuel)
        domestic, imported, fill, take = [float(x[j]) for j in indices]
        fuel_rows.append(dict(fuel=fuel, period=t, domestic_mwh=domestic, import_mwh=imported,
                              fill_mwh=fill, withdrawal_mwh=take, closing_mwh=float(x[tanks[fuel,t]]),
                              direct_mwh=float(direct), conversion_mwh=float(converted),
                              combustion_co2_t=float((direct + converted) * p["emission_t_per_mwh"])))
    for (name, t), i in g.items():
        generation_rows.append(dict(plant=name, period=t, output=plants[name]["output"],
                                    output_mwh=float(x[i]), input_mwh=float(x[i]/plants[name]["efficiency"])
                                    if plants[name]["input"] else 0.0))
    for (name, t), i in inputs.items():
        p = demands[name]
        demand_rows.append(dict(device=name, sector=p["sector"], period=t, carrier=p["carrier"],
                               input_mwh=float(x[i]), requested_service_mwh=p["service_mwh"][t],
                               served_service_mwh=float(x[i] * p["efficiency"]), unmet_service_mwh=float(x[u[name,t]])))
    for t in range(n):
        storage_rows.append(dict(period=t, opening_mwh=soc if t == 0 else float(x[s[t-1]]),
                                 charge_mwh=float(x[c[t]]), discharge_mwh=float(x[d[t]]), closing_mwh=float(x[s[t]])))
    for terms, rhs, name in lp.equalities:
        balance_rows.append(dict(constraint=name, residual=float(sum(x[i]*v for i,v in terms.items())-rhs)))
    return dict(status="optimal", annual_repeats=weight, resource_cost=float(result.fun),
                fuel=fuel_rows, generation=generation_rows, demand=demand_rows, storage=storage_rows,
                balances=balance_rows, stages=stages, max_residual=residual)
