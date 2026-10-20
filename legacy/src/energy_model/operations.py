"""Chronological synthetic electricity windows; no national data or annual scaling."""
from copy import deepcopy

from .accounting import EnergyBalance, Storage
from .agents import numeric

TECHNOLOGY_FUELS = {
    "hydro": None, "nuclear": None, "wind": None, "solar": None,
    "coal": "coal", "gas": "gas",
}


def validate_operation_config(config):
    if config.get("mode") != "synthetic" or not config.get("warning"):
        raise ValueError("Only explicitly labelled synthetic operation windows are supported")
    for group in ("generation", "fuels", "storage", "grid", "windows", "policy"):
        meta = config["parameter_groups"][group]
        if meta["basis"] != "synthetic_assumption" or any(
            not isinstance(meta[key], str) or not meta[key].strip()
            for key in ("purpose", "unit", "sensitivity")
        ):
            raise ValueError(f"Unlabelled parameter group: {group}")
    if set(config["generation"]) != set(TECHNOLOGY_FUELS):
        raise ValueError("Six separately identified generation technologies required")
    if set(config["fuels"]) != {"coal", "gas"}:
        raise ValueError("Coal and gas fuel parameters required")
    for name, p in config["generation"].items():
        if p["fuel"] != TECHNOLOGY_FUELS[name]:
            raise ValueError("Technology and fuel boundary do not match")
        numeric(p["capacity_mw"], name + ".capacity")
        numeric(p["variable_cost"], name + ".variable_cost")
        numeric(p["efficiency"], name + ".efficiency", minimum=1e-12, maximum=1)
        if p["fuel"] is None and p["efficiency"] != 1:
            raise ValueError("Non-combustion technology enters at electricity-output boundary")
    for p in config["fuels"].values():
        for key in ("supply_limit_mw_fuel", "price", "emission_factor"):
            numeric(p[key], key)
    p = config["storage"]
    for key in ("capacity_mwh", "initial_energy_mwh", "charge_limit_mw",
                "discharge_limit_mw", "discharge_variable_cost"):
        numeric(p[key], key)
    for key in ("charge_efficiency", "discharge_efficiency"):
        numeric(p[key], key, minimum=1e-12, maximum=1)
    if p["initial_energy_mwh"] > p["capacity_mwh"]:
        raise ValueError("Initial storage exceeds capacity")
    numeric(config["grid"]["transfer_limit_mw"], "grid limit")
    numeric(config["grid"]["delivery_efficiency"], "grid efficiency", minimum=1e-12, maximum=1)
    numeric(config["policy"]["carbon_price"], "carbon price")
    if not config["windows"]:
        raise ValueError("At least one chronological window required")
    for window in config["windows"].values():
        if not window.get("description") or not window["steps"]:
            raise ValueError("Each window requires a description and steps")
        for period in window["steps"]:
            numeric(period["duration_hours"], "duration", minimum=1e-12)
            numeric(period["demand_mw"], "demand")
            numeric(period.get("grid_capacity_multiplier", 1), "grid multiplier")
            numeric(period.get("carbon_price", config["policy"]["carbon_price"]), "period carbon price")
            if set(period["availability"]) != set(TECHNOLOGY_FUELS):
                raise ValueError("Every period requires availability for all technologies")
            for fraction in period["availability"].values():
                numeric(fraction, "availability", maximum=1)


def _dispatch_period(config, period, store, storage_enabled, index):
    """Only this period and the opening SOC are visible; no future records accepted."""
    hours = period["duration_hours"]
    efficiency = config["grid"]["delivery_efficiency"]
    grid_limit_mw = config["grid"]["transfer_limit_mw"] * period.get("grid_capacity_multiplier", 1)
    requested = period["demand_mw"] * hours
    target = min(requested / efficiency, grid_limit_mw * hours)
    remaining = target
    carbon = period.get("carbon_price", config["policy"]["carbon_price"])
    technologies = config["generation"]
    potentials = {
        name: p["capacity_mw"] * period["availability"][name] * hours
        for name, p in technologies.items()
    }
    dispatched = {name: 0.0 for name in technologies}
    maximum_charge = min(
        store.charge_limit_mw * hours,
        max(0.0, store.capacity_mwh - store.energy_mwh) / store.charge_efficiency,
    ) if storage_enabled else 0.0
    charge = 0.0
    for name in sorted(
        (name for name, p in technologies.items() if p["fuel"] is None),
        key=lambda name: (technologies[name]["variable_cost"], name),
    ):
        to_load = min(remaining, potentials[name])
        remaining = max(0.0, remaining - to_load)
        to_storage = min(
            max(0.0, maximum_charge - charge),
            max(0.0, potentials[name] - to_load),
        )
        dispatched[name] = to_load + to_storage
        charge += to_storage

    # Charging only occurs after non-combustion generation has met the bus target.
    discharge = min(remaining, store.discharge_limit_mw * hours,
                    store.energy_mwh * store.discharge_efficiency) if storage_enabled and charge == 0 else 0.0
    remaining = max(0.0, remaining - discharge)
    fuel_used = {fuel: 0.0 for fuel in config["fuels"]}
    fuel_limits = {
        fuel: p["supply_limit_mw_fuel"] * hours for fuel, p in config["fuels"].items()
    }
    costs = {}
    for name, p in technologies.items():
        fuel = p["fuel"]
        costs[name] = p["variable_cost"] + (
            (config["fuels"][fuel]["price"] + carbon * config["fuels"][fuel]["emission_factor"])
            / p["efficiency"] if fuel else 0
        )
    for name in sorted(
        (name for name, p in technologies.items() if p["fuel"] is not None),
        key=lambda name: (costs[name], name),
    ):
        p = technologies[name]
        fuel = p["fuel"]
        amount = min(remaining, potentials[name],
                     max(0.0, fuel_limits[fuel] - fuel_used[fuel]) * p["efficiency"])
        dispatched[name] = amount
        fuel_used[fuel] += amount / p["efficiency"]
        remaining = max(0.0, remaining - amount)

    next_store = store.step(
        min(store.charge_limit_mw, charge / hours),
        min(store.discharge_limit_mw, discharge / hours),
        hours,
    )
    generation = sum(dispatched.values())
    grid_input = generation + discharge - charge
    served = grid_input * efficiency
    unserved = max(0.0, requested - served)
    grid_loss = grid_input * (1 - efficiency)
    charge_loss = charge * (1 - store.charge_efficiency)
    discharge_loss = discharge * (1 / store.discharge_efficiency - 1)
    storage_loss = charge_loss + discharge_loss
    noncombustion = sum(dispatched[name] for name in technologies if technologies[name]["fuel"] is None)
    thermal_output = generation - noncombustion
    conversion_loss = sum(fuel_used.values()) - thermal_output
    electricity_balance = EnergyBalance(
        production=noncombustion, conversion_output=thermal_output, opening_stock=store.energy_mwh,
        requested_final_demand=requested, unserved_final_demand=unserved,
        losses=grid_loss + storage_loss, closing_stock=next_store.energy_mwh,
    )
    electricity_balance.require_closed()
    interface_balance = EnergyBalance(
        # These are external inputs to the electricity/fuel interface, not national primary production.
        imports=noncombustion + sum(fuel_used.values()), opening_stock=store.energy_mwh,
        requested_final_demand=requested, unserved_final_demand=unserved,
        losses=grid_loss + storage_loss + conversion_loss, closing_stock=next_store.energy_mwh,
    )
    interface_balance.require_closed()
    emissions = sum(
        amount * config["fuels"][fuel]["emission_factor"] for fuel, amount in fuel_used.items()
    )
    fuel_cost = sum(amount * config["fuels"][fuel]["price"] for fuel, amount in fuel_used.items())
    om_cost = sum(amount * technologies[name]["variable_cost"] for name, amount in dispatched.items())
    storage_cost = discharge * config["storage"]["discharge_variable_cost"]
    return {
        "period": index, "information_cutoff_period": index,
        "duration_hours": hours, "demand_mw": period["demand_mw"],
        "availability_observed": dict(period["availability"]), "carbon_price": carbon,
        "available_generation_mwh": potentials, "generation_mwh": dispatched,
        "unused_noncombustion_mwh": {
            name: max(0.0, potentials[name] - dispatched[name])
            for name, p in technologies.items() if p["fuel"] is None
        },
        "fuel_input_mwh_lhv": fuel_used, "fuel_supply_limit_mwh_lhv": fuel_limits,
        "grid_limit_mw": grid_limit_mw, "grid_input_mwh": grid_input,
        "electricity_requested_mwh": requested, "electricity_served_mwh": served,
        "unserved_electricity_mwh": unserved, "grid_loss_mwh": grid_loss,
        "thermal_conversion_loss_mwh": conversion_loss,
        "storage": {
            "opening_energy_mwh": store.energy_mwh, "closing_energy_mwh": next_store.energy_mwh,
            "charge_input_mwh": charge, "discharge_output_mwh": discharge,
            "charge_loss_mwh": charge_loss, "discharge_loss_mwh": discharge_loss,
            "rule": "current_noncombustion_surplus_then_discharge_before_fossil",
            "location": "generation_side",
        },
        "energy_related_synthetic_emissions": emissions,
        "costs_cu": {
            "fuel": fuel_cost, "generation_variable_om": om_cost, "storage_variable": storage_cost,
            "resource_variable_total": fuel_cost + om_cost + storage_cost,
            "carbon_payment": carbon * emissions,
        },
        "balance_residuals_mwh": {
            "electricity_with_storage": electricity_balance.residual(),
            "electricity_fuel_interface": interface_balance.residual(),
        },
    }, next_store


def simulate_operation_window(config, window_name, *, storage_enabled=True):
    config = deepcopy(config)
    validate_operation_config(config)
    if type(storage_enabled) is not bool:
        raise ValueError("storage_enabled must be boolean")
    window = config["windows"][window_name]
    p = config["storage"]
    store = Storage(p["initial_energy_mwh"], p["capacity_mwh"], p["charge_limit_mw"],
                    p["discharge_limit_mw"], p["charge_efficiency"], p["discharge_efficiency"])
    rows = []
    for index, period in enumerate(window["steps"], 1):
        row, store = _dispatch_period(config, period, store, storage_enabled, index)
        rows.append(row)
    return {
        "mode": "synthetic", "warning": config["warning"],
        "window_name": window_name, "description": window["description"],
        "storage_enabled": storage_enabled, "rows": rows,
        "opening_storage_mwh": p["initial_energy_mwh"],
        "closing_storage_mwh": store.energy_mwh,
        "initial_stock_upstream_cost_and_emissions_included": False,
        "storage_capital_and_fixed_costs_included": False,
        "annual_reliability": None, "national_forecast": None,
    }


def summarize_operation_window(run):
    rows = run["rows"]
    return {
        "window_hours": sum(row["duration_hours"] for row in rows),
        "requested_mwh": sum(row["electricity_requested_mwh"] for row in rows),
        "unserved_mwh": sum(row["unserved_electricity_mwh"] for row in rows),
        "shortage_hours": sum(
            row["duration_hours"] for row in rows if row["unserved_electricity_mwh"] > 1e-8
        ),
        "max_shortage_mw": max(row["unserved_electricity_mwh"] / row["duration_hours"] for row in rows),
        "unused_noncombustion_mwh": sum(sum(row["unused_noncombustion_mwh"].values()) for row in rows),
        "storage_charge_mwh": sum(row["storage"]["charge_input_mwh"] for row in rows),
        "storage_discharge_mwh": sum(row["storage"]["discharge_output_mwh"] for row in rows),
        "storage_loss_mwh": sum(
            row["storage"]["charge_loss_mwh"] + row["storage"]["discharge_loss_mwh"] for row in rows
        ),
        "opening_storage_mwh": run["opening_storage_mwh"],
        "closing_storage_mwh": run["closing_storage_mwh"],
        "energy_related_synthetic_emissions": sum(row["energy_related_synthetic_emissions"] for row in rows),
        "resource_variable_cost_cu": sum(row["costs_cu"]["resource_variable_total"] for row in rows),
        "carbon_payment_cu": sum(row["costs_cu"]["carbon_payment"] for row in rows),
        "max_abs_balance_residual_mwh": max(
            abs(value) for row in rows for value in row["balance_residuals_mwh"].values()
        ),
    }
