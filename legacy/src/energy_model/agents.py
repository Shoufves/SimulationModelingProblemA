"""Synthetic sequential agents. No China data, calibration or national forecasts."""
from copy import deepcopy
from dataclasses import dataclass, field
from math import isfinite

from .accounting import EnergyBalance


def numeric(value, name, minimum=0, maximum=None, integer=False):
    if type(value) not in (int, float) or not isfinite(value) or value < minimum:
        raise ValueError(f"Invalid {name}")
    if maximum is not None and value > maximum:
        raise ValueError(f"Invalid {name}")
    if integer and type(value) is not int:
        raise ValueError(f"Expected integer {name}")
    return value


def validate(config):
    if config.get("mode") != "synthetic" or not config.get("warning"):
        raise ValueError("Only explicitly labelled synthetic configurations are supported")
    for group in ("run", "policy", "fuels", "generation", "demand", "grid"):
        metadata = config["parameter_groups"][group]
        if metadata["basis"] != "synthetic_assumption" or any(
                not isinstance(metadata[key], str) or not metadata[key].strip()
                for key in ("purpose", "basis", "unit", "sensitivity")):
            raise ValueError(f"Unlabelled parameter group: {group}")
    steps = numeric(config["run"]["steps"], "steps", minimum=1, integer=True)
    numeric(config["run"]["initial_electricity_price"], "initial price")
    path = config["policy"]["carbon_price_by_step"]
    if len(path) != steps:
        raise ValueError("One policy value required for each step")
    for price in path:
        numeric(price, "carbon price")
    if set(config["fuels"]) != {"coal", "oil", "gas"}:
        raise ValueError("Synthetic prototype requires coal, oil and gas")
    for name, values in config["fuels"].items():
        for key in ("domestic_limit", "import_limit", "base_price", "scarcity_markup", "emission_factor"):
            numeric(values[key], f"{name}.{key}")
    if not config["generation"] or not config["demand"]:
        raise ValueError("Generation and demand agents required")
    for name, values in config["generation"].items():
        if values["fuel"] is not None and values["fuel"] not in config["fuels"]:
            raise ValueError("Unknown generation fuel")
        for key in ("initial_capacity", "variable_cost", "budget", "max_build_per_step", "discount_rate"):
            numeric(values[key], f"{name}.{key}")
        for key in ("energy_per_capacity", "capex"):
            numeric(values[key], f"{name}.{key}", minimum=1e-12)
        numeric(values["efficiency"], "generation efficiency", minimum=1e-12, maximum=1)
        numeric(values["expected_sales_floor"], "expected sales", maximum=1)
        for key in ("lead_steps", "life_steps", "initial_retirement_step"):
            numeric(values[key], f"{name}.{key}", minimum=1, integer=True)
    for name, values in config["demand"].items():
        if values["fuel"] not in config["fuels"]:
            raise ValueError("Unknown demand fuel")
        numeric(values["growth"], "service growth", minimum=-0.999999)
        for key in ("service", "budget", "replacement_limit"):
            numeric(values[key], f"{name}.{key}")
        numeric(values["electric_share"], "electric share", maximum=1)
        numeric(values["replacement_limit"], "replacement share", maximum=1)
        for key in ("fuel_efficiency", "electric_efficiency", "switch_cost_per_share", "payback_steps"):
            numeric(values[key], f"{name}.{key}", minimum=1e-12)
    numeric(config["grid"]["delivery_efficiency"], "grid efficiency", minimum=1e-12, maximum=1)
    numeric(config["grid"]["generation_transfer_limit"], "grid limit")
    numeric(config["grid"]["scarcity_price"], "scarcity price")
    for step, event in config.get("events_by_step", {}).items():
        if not str(step).isdigit() or not 1 <= int(step) <= steps:
            raise ValueError("Event step outside run")
        if set(event) - {"fuel_capacity_multiplier", "grid_capacity_multiplier"}:
            raise ValueError("Unknown event field")
        for fuel, multiplier in event.get("fuel_capacity_multiplier", {}).items():
            if fuel not in config["fuels"]:
                raise ValueError("Unknown event fuel")
            numeric(multiplier, "fuel shock")
        numeric(event.get("grid_capacity_multiplier", 1), "grid shock")


@dataclass
class DemandAgent:
    name: str
    parameters: dict
    electric_share: float

    def request(self, step):
        p = self.parameters
        service = p["service"] * (1 + p["growth"]) ** (step - 1)
        return {"service": service, "electric_share": self.electric_share,
                "electricity": service * self.electric_share / p["electric_efficiency"],
                "direct_fuel": service * (1 - self.electric_share) / p["fuel_efficiency"],
                "fuel": p["fuel"]}

    def decide(self, step, service, electricity_price, fuel_user_price, enabled):
        p = self.parameters
        electric_cost = electricity_price / p["electric_efficiency"]
        direct_cost = fuel_user_price / p["fuel_efficiency"]
        annual_saving_per_share = abs(direct_cost - electric_cost) * service
        profitable = annual_saving_per_share * p["payback_steps"] > p["switch_cost_per_share"]
        direction = 1 if direct_cost > electric_cost else -1
        available = 1 - self.electric_share if direction > 0 else self.electric_share
        delta = min(available, p["replacement_limit"], p["budget"] / p["switch_cost_per_share"])
        if not enabled or not profitable:
            delta = 0.0
        before = self.electric_share
        self.electric_share = min(1.0, max(0.0, before + direction * delta))
        return {
            "step": step, "actor": self.name, "kind": "equipment_substitution",
            "information_cutoff_step": step, "effective_step": step + 1,
            "electric_share_before": before, "electric_share_next": self.electric_share,
            "share_change": self.electric_share - before,
            "investment": delta * p["switch_cost_per_share"], "budget": p["budget"],
            "electric_cost_per_service": electric_cost, "fuel_cost_per_service": direct_cost,
            "saving_per_full_share_per_step": annual_saving_per_share,
            "reason": "mechanism_disabled" if not enabled else
                      ("payback_passed" if profitable else "payback_failed"),
        }


@dataclass
class GenerationProject:
    capacity_units: float
    online_step: int
    retirement_step: int

    def capacity(self, step):
        return self.capacity_units if self.online_step <= step < self.retirement_step else 0.0


@dataclass
class GeneratorAgent:
    name: str
    parameters: dict
    projects: list = field(default_factory=list)

    def capacity(self, step):
        return sum(project.capacity(step) for project in self.projects)

    def offer_cost(self, fuel_prices, carbon_price, fuel_parameters):
        p = self.parameters
        fuel = p["fuel"]
        fuel_cost = 0 if fuel is None else (
            fuel_prices[fuel] + carbon_price * fuel_parameters[fuel]["emission_factor"]) / p["efficiency"]
        return p["variable_cost"] + fuel_cost

    def decide(self, step, price, cost, dispatched, potential, enabled):
        p = self.parameters
        realized_utilization = dispatched / potential if potential > 0 else 0
        expected_sales = min(1.0, max(p["expected_sales_floor"], realized_utilization))
        annual_profit = p["energy_per_capacity"] * expected_sales * (price - cost)
        rate, life = p["discount_rate"], p["life_steps"]
        annuity = life if rate == 0 else (1 - (1 + rate) ** -life) / rate
        # Both construction lag and operating-life cash flow are discounted.
        npv = annual_profit * annuity / (1 + rate) ** (p["lead_steps"] - 1) - p["capex"]
        amount = min(p["budget"] / p["capex"], p["max_build_per_step"]) if enabled and npv > 0 else 0.0
        if amount > 0:
            online = step + p["lead_steps"]
            self.projects.append(GenerationProject(amount, online, online + life))
        return {
            "step": step, "actor": self.name, "kind": "generation_investment",
            "information_cutoff_step": step, "observed_generation_price": price,
            "observed_variable_cost": cost, "expected_sales_fraction": expected_sales,
            "npv_per_capacity_unit": npv, "capacity_ordered": amount,
            "investment": amount * p["capex"], "budget": p["budget"],
            "online_step": step + p["lead_steps"] if amount else None,
            "reason": "mechanism_disabled" if not enabled else
                      ("positive_npv" if npv > 0 else "nonpositive_npv"),
        }


def simulate(config, *, substitution=True, investment=True):
    """Sequential, deterministic interaction; future policy/events are not passed to agents."""
    config = deepcopy(config)
    validate(config)
    consumers = [DemandAgent(name, p, p["electric_share"]) for name, p in sorted(config["demand"].items())]
    generators = [GeneratorAgent(name, p, [GenerationProject(
        p["initial_capacity"], 0, p["initial_retirement_step"])])
        for name, p in sorted(config["generation"].items())]
    previous_use = {fuel: 0.0 for fuel in config["fuels"]}
    previous_limit = {fuel: p["domestic_limit"] + p["import_limit"] for fuel, p in config["fuels"].items()}
    rows = []
    for step in range(1, config["run"]["steps"] + 1):
        carbon_price = config["policy"]["carbon_price_by_step"][step - 1]
        event = config.get("events_by_step", {}).get(str(step), {})
        prices, limits, domestic_limits, supplier_logs = {}, {}, {}, []
        for fuel, p in sorted(config["fuels"].items()):
            utilization = previous_use[fuel] / previous_limit[fuel] if previous_limit[fuel] > 0 else 0.0
            prices[fuel] = p["base_price"] * (1 + p["scarcity_markup"] * min(1.0, utilization))
            multiplier = event.get("fuel_capacity_multiplier", {}).get(fuel, 1)
            domestic_limits[fuel] = p["domestic_limit"] * multiplier
            limits[fuel] = (p["domestic_limit"] + p["import_limit"]) * multiplier
            supplier_logs.append({"actor": fuel + "_supplier", "kind": "fuel_offer", "step": step,
                                  "information_cutoff_step": step, "previous_use": previous_use[fuel],
                                  "previous_limit": previous_limit[fuel], "price": prices[fuel],
                                  "capacity": limits[fuel]})
        requests = {agent.name: agent.request(step) for agent in consumers}
        requested_fuel = {fuel: sum(r["direct_fuel"] for r in requests.values() if r["fuel"] == fuel)
                          for fuel in config["fuels"]}
        served_fuel = {fuel: min(limits[fuel], demand) for fuel, demand in requested_fuel.items()}
        remaining_fuel = {fuel: limits[fuel] - served_fuel[fuel] for fuel in limits}
        electricity_requested = sum(r["electricity"] for r in requests.values())
        efficiency = config["grid"]["delivery_efficiency"]
        transfer_limit = config["grid"]["generation_transfer_limit"] * event.get("grid_capacity_multiplier", 1)
        needed = min(electricity_requested / efficiency, transfer_limit)
        costs = {g.name: g.offer_cost(prices, carbon_price, config["fuels"]) for g in generators}
        capacities = {g.name: g.capacity(step) for g in generators}
        potentials = {g.name: capacities[g.name] * g.parameters["energy_per_capacity"] for g in generators}
        dispatch = {g.name: 0.0 for g in generators}
        conversion_input = {fuel: 0.0 for fuel in limits}
        marginal_cost = 0.0
        for g in sorted(generators, key=lambda item: (costs[item.name], item.name)):
            fuel = g.parameters["fuel"]
            fuel_output_limit = remaining_fuel[fuel] * g.parameters["efficiency"] if fuel else needed
            amount = max(0.0, min(needed, potentials[g.name], fuel_output_limit))
            dispatch[g.name] = amount
            needed -= amount
            if amount > 0:
                marginal_cost = costs[g.name]
                if fuel:
                    used = amount / g.parameters["efficiency"]
                    conversion_input[fuel] += used
                    remaining_fuel[fuel] = max(0.0, remaining_fuel[fuel] - used)
        generation = sum(dispatch.values())
        delivered = generation * efficiency
        unmet_electricity = max(0.0, electricity_requested - delivered)
        generation_price = max(marginal_cost, config["grid"]["scarcity_price"]) if unmet_electricity > 1e-8 else marginal_cost
        # No-load price initialization is used only if there is zero power demand.
        if electricity_requested == 0:
            generation_price = config["run"]["initial_electricity_price"] * efficiency
        electricity_price = generation_price / efficiency
        ledgers, fuel_flows = {}, {}
        emissions = 0.0
        for fuel, p in sorted(config["fuels"].items()):
            use = served_fuel[fuel] + conversion_input[fuel]
            domestic = min(domestic_limits[fuel], use)
            imported = max(0.0, use - domestic)
            balance = EnergyBalance(
                production=domestic, imports=imported, requested_final_demand=requested_fuel[fuel],
                unserved_final_demand=requested_fuel[fuel] - served_fuel[fuel],
                conversion_input=conversion_input[fuel])
            balance.require_closed()
            ledgers[fuel] = balance.residual()
            fuel_flows[fuel] = {
                "domestic_production": domestic, "imports": imported, "supply_limit": limits[fuel],
                "direct_requested": requested_fuel[fuel], "direct_served": served_fuel[fuel],
                "generation_input": conversion_input[fuel], "total_burned": use,
                "emissions": use * p["emission_factor"]}
            emissions += use * p["emission_factor"]
            previous_use[fuel] = use
        previous_limit = limits
        renewable = sum(dispatch[g.name] for g in generators if g.parameters["fuel"] is None)
        electric_balance = EnergyBalance(
            production=renewable, conversion_output=generation - renewable,
            requested_final_demand=electricity_requested, unserved_final_demand=unmet_electricity,
            losses=generation - delivered)
        electric_balance.require_closed()
        ledgers["electricity"] = electric_balance.residual()
        service_rows, demand_logs = {}, []
        for agent in consumers:
            request = requests[agent.name]
            fuel = request["fuel"]
            direct_served = request["direct_fuel"] * (
                served_fuel[fuel] / requested_fuel[fuel] if requested_fuel[fuel] else 0)
            electric_served = request["electricity"] * (
                delivered / electricity_requested if electricity_requested else 0)
            service = direct_served * agent.parameters["fuel_efficiency"] + electric_served * agent.parameters["electric_efficiency"]
            service_rows[agent.name] = {
                **request, "direct_fuel_served": direct_served, "electricity_served": electric_served,
                "service_served": service, "unserved_service": max(0.0, request["service"] - service)}
            user_fuel_price = prices[fuel] + carbon_price * config["fuels"][fuel]["emission_factor"]
            demand_logs.append(agent.decide(step, request["service"], electricity_price, user_fuel_price, substitution))
        investment_logs = [g.decide(step, generation_price, costs[g.name], dispatch[g.name],
                                   potentials[g.name], investment) for g in generators]
        conversion_loss = sum(conversion_input.values()) - (generation - renewable)
        if conversion_loss < -1e-8:
            raise ValueError("Conversion creates energy")
        rows.append({
            "step": step, "carbon_price": carbon_price, "event_revealed": event,
            "fuel_prices_before_carbon": prices, "electricity_price_delivered": electricity_price,
            "generation_price": generation_price, "capacity_at_start": capacities,
            "generation": dispatch, "generation_variable_cost": costs,
            "fuel_flows": fuel_flows, "services": service_rows,
            "electricity_requested": electricity_requested, "electricity_served": delivered,
            "unserved_electricity": unmet_electricity, "grid_transfer_limit": transfer_limit,
            "grid_loss": generation - delivered, "thermal_conversion_loss": conversion_loss,
            "energy_related_synthetic_emissions": emissions, "balance_residuals": ledgers,
            "decisions": supplier_logs + demand_logs + investment_logs,
        })
    return {
        "mode": "synthetic", "warning": config["warning"],
        "mechanisms": {"substitution": substitution, "investment": investment},
        "rows": rows,
        "final_projects": {g.name: [
            {"capacity_units": p.capacity_units, "online_step": p.online_step,
             "retirement_step": p.retirement_step} for p in g.projects] for g in generators},
        "national_forecast": None, "national_co2_total": None,
    }
