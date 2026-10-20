"""Declared forward scenarios continuing the reviewed historical state.

This does not repair historical fit or reconstruct an observed 2024 balance
sheet. Fiscal/tariff persistence is a counterfactual boundary, not a claim that
all post-2024 Chinese policy has been represented. No stock or cash is reset.
"""
from copy import deepcopy
from dataclasses import replace
from math import fsum, isfinite

from .q2_national import NationalSupplier, LEAD
from .q2_project_competition import ProjectCompetitionModel


class ForwardSupplier(NationalSupplier):
    def offer(self, year=None, *, record=True):
        result = super().offer(year, record=record)
        model = self.model
        # Investors persist the CURRENT shock; no future realised recovery is
        # injected into their planning operations.
        factor = model.forward_import_factor if self.name == "gas" else 1.0
        result["import_mw"] = [v*factor for v in result["import_mw"]]
        if record and factor != 1:
            self.log("forward_import_constraint", import_multiplier=factor,
                     information="current condition persists in project planning")
        return result


class ForwardModel(ProjectCompetitionModel):
    def drivers(self):
        super().drivers()
        spec = self.forward_spec
        event = spec.get("event", {})
        active = event.get("start_year", 9999) <= self.year <= event.get("end_year", 0)
        self.forward_import_factor = event.get("gas_import_multiplier", 1.0) if active else 1.0
        self.forward_hydro_factor = event.get("hydro_energy_multiplier", 1.0) if active else 1.0
        self.variant["renewable_availability_multiplier"] = (
            self.forward_variant.get("renewable_availability_multiplier", 1.0)
            * (event.get("renewable_availability_multiplier", 1.0) if active else 1.0))
        for fuel, supplier in self.suppliers.items():
            factor = self.forward_variant.get("fuel_price_multiplier", 1.0)
            if fuel == "gas" and active:
                factor *= event.get("gas_price_multiplier", 1.0)
            supplier.price = self.forward_base_prices[fuel]*factor

    def make_operation(self):
        op = super().make_operation()
        op["plants"]["hydro"]["window_energy_budget_mwh"] *= self.forward_hydro_factor
        return op

    def planning_operation(self, lead):
        op = super().planning_operation(lead)
        # Parent rebuilds the hydro energy budget from the surviving fleet.
        op["plants"]["hydro"]["window_energy_budget_mwh"] *= self.forward_hydro_factor
        return op


def activate_forward(model, config, spec, *, end_year=2060):
    """Continue a completed 2015--2024 run; extend only explicitly named inputs."""
    if type(model) is not ProjectCompetitionModel or model.year != 2025:
        raise ValueError("Forward continuation requires the exact competition model at end-2024")
    if model.fuel_prices is not None:
        raise ValueError("A historical fuel series needs a separate explicit forward path")
    if not 2025 <= end_year <= 2060:
        raise ValueError("Unsupported projection horizon")
    allowed = {"name", "kind", "variant", "event", "retirement_acceleration_years",
               "infrastructure_delay_years", "infrastructure_budget_multiplier",
               "freeze_new_gas", "fiscal_multiplier", "description", "replacement_adoption"}
    if set(spec)-allowed:
        raise ValueError("Unknown scenario controls: "+str(set(spec)-allowed))
    for key in ("retirement_acceleration_years", "infrastructure_delay_years"):
        if type(spec.get(key, 0)) is not int or not 0 <= spec.get(key, 0) <= 10:
            raise ValueError("Invalid scenario years")
    for key in ("infrastructure_budget_multiplier", "fiscal_multiplier"):
        value = spec.get(key, 1.0)
        if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 3:
            raise ValueError("Invalid budget factor")
    event = spec.get("event", {})
    if event:
        if set(event)-{"start_year", "end_year", "gas_import_multiplier", "gas_price_multiplier",
                       "renewable_availability_multiplier", "hydro_energy_multiplier"}:
            raise ValueError("Unknown event field")
        if not 2025 <= event["start_year"] <= event["end_year"] <= end_year:
            raise ValueError("Invalid event window")
        for key in ("gas_import_multiplier", "renewable_availability_multiplier", "hydro_energy_multiplier"):
            value = event.get(key, 1.0)
            if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= 1:
                raise ValueError("Invalid availability bound")
        value = event.get("gas_price_multiplier", 1.0)
        if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= 5:
            raise ValueError("Invalid fuel price shock")
    policy = model.revenue_policy
    terminal = end_year+max(LEAD.values())+2
    for year in range(2025, terminal+1):
        policy.energy_tariffs[year] = deepcopy(policy.energy_tariffs[2024])
        policy.metering_fraction[year] = deepcopy(policy.metering_fraction[2024])
        # Forward money is constant 2024 CNY: nominal index is held at one.
        policy.deflators[year] = 1.0
        policy.annual_funding[year] = {
            k: v*spec.get("fiscal_multiplier", 1.0)
            for k, v in policy.annual_funding[2024].items()}
        policy.support_rates[year] = deepcopy(policy.support_rates[2024])
        support = policy.new_support
        if support is not None:
            support.actual_rates[year] = deepcopy(support.actual_rates[2024])
            support.authority[year] = support.authority[2024]*spec.get("fiscal_multiplier", 1.0)
            # Explicit legacy-program continuation; no new wind/solar award
            # is invented, and old award caps and all arrears are retained.
            for (decision, tech), offer in list(support.offers.items()):
                if decision == 2024:
                    support.offers[year, tech] = replace(offer, decision_year=year, announced_year=year,
                        commissioning_deadline=year+LEAD[tech], expected_real_2024_per_nominal=1.0)
    bio = model.bioenergy
    if bio is not None:
        a = config["bioenergy"]
        start = model.data[2014,"biofuel_electricity_mwh"]/.3*model.theta["waste_fuel_fraction"]/a["waste_lhv_mwh_per_t"]
        for year in range(2025, terminal+1):
            q = min(a["maximum_municipal_waste_delivery_t"],
                    start*a["initial_delivery_headroom"]*(1+model.theta["waste_delivery_growth"])**(year-2014))
            bio.delivery[year] = q
            bio.fees[year] = a["treatment_fee_real_2024_cny_per_t"]
            bio.funding[year] = q*bio.fees[year]*a["municipal_funding_fraction_of_full_service"]
    variant = deepcopy(spec.get("variant", {}))
    for key, value in variant.items():
        if type(value) not in (int, float) or not isfinite(value):
            raise ValueError("Finite scenario variants required")
    model.__class__ = ForwardModel
    model.forward_spec = deepcopy(spec)
    model.forward_variant = variant
    model.variant.update(variant)
    if "replacement_adoption" in spec:
        value = spec["replacement_adoption"]
        if type(value) not in (int, float) or not isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Invalid device adoption response")
        model.theta["replacement_adoption"] = value
    model.forward_import_factor = model.forward_hydro_factor = 1.0
    model.forward_base_prices = {f:s.price for f,s in model.suppliers.items()}
    for supplier in model.suppliers.values():
        supplier.__class__ = ForwardSupplier
    for key in ("project_equity_fraction", "grid_build_fraction"):
        if key in variant:
            model.a[key] = variant[key]
    for key in ("grid_lead_years", "storage_lead_years"):
        model.a[key] += spec.get("infrastructure_delay_years", 0)
    for key in ("grid_budget_gdp_fraction", "storage_budget_gdp_fraction"):
        model.a[key] *= spec.get("infrastructure_budget_multiplier", 1.0)
    retirement = []
    speed = spec.get("retirement_acceleration_years", 0)
    if speed:
        for cohort in model.cohorts:
            if cohort["tech"] == "coal" and cohort["status"] == "active":
                old = cohort["exit_year"]
                cohort["exit_year"] = max(2025, old-speed)
                retirement.append(dict(project=cohort["id"],old_exit_year=old,new_exit_year=cohort["exit_year"],
                                       capacity_mw=cohort["capacity_mw"]))
        # Existing loans and paid construction are NOT erased or refunded.
    if spec.get("freeze_new_gas", False):
        generator = model.generators["gas"]
        original = generator.proposal
        def frozen(*args, **kwargs):
            proposal = original(*args, **kwargs)
            generator.log("new_gas_investment_frozen", rejected_request_mw=proposal["amount"],
                          existing_and_committed_assets_retained=True)
            proposal["amount"] = 0.0
            return proposal
        generator.proposal = frozen
    model.forward_assumptions = dict(
        starting_state="unaltered simulated end-2024 balance sheet; historical capacity bias retained",
        tariffs="2024 real energy-only tariff and auxiliary fractions held constant",
        public_funding="2024 real receipts and expenditure authority held constant times disclosed factor; no extra treasury cash",
        support="existing rights, arrears and caps retained; 2024 biomass programme continued; no new wind/solar subsidy offers",
        policy_scope="legacy-policy continuation counterfactual; post-2024 national CfD and capacity-revenue transition incomplete",
        biological_service="existing bounded delivery scenario extended; no observed future waste series",
        initial_statistics="2014 training-fitted bridge retained; no hidden 2024 reanchoring",
        information="current fuel/availability condition persists for investment planning; recovery not known in advance",
        weather="annual representative-day stress, not an observed meteorological event or seasonal reliability claim",
        scope="mainland aggregate CO2, no all-GHG neutrality certification", retirement_changes=retirement)
    return model


def forward_summary(model):
    rows = [p for p in model.paths if p["year"] >= 2025]
    discount = model.a["discount_rate"]
    return dict(
        discounted_resource_cost_cny=fsum(r["resource_cost_cny"]/(1+discount)**(r["year"]-2024) for r in rows),
        cumulative_positive_co2_t=fsum(r["positive_co2_t"] for r in rows),
        cumulative_unmet_service_mwh=fsum(r["unmet_service_mwh"] for r in rows),
        maximum_annual_unmet_fraction=max(r["unmet_service_mwh"]/r["requested_service_mwh"] for r in rows),
        infrastructure_approved_cny=fsum(p["cost"] for p in model.grid.queue if p["decision"]>=2025),
        generation_approved_cny=fsum(p["cost"] for p in model.projects if p["decision_year"]>=2025),
        max_physical_residual=max(abs(r["max_residual"]) for r in rows),
        max_cash_residual_cny=max(abs(r["cash_balance_residual_cny"]) for r in rows),
        max_construction_fund_residual_cny=max(abs(r["construction_fund_residual_cny"]) for r in rows),
        max_financing_transfer_residual_cny=max(abs(r["financing_transfer_residual_cny"]) for r in rows),
        terminal_unpaid_generation_construction_cny=model.construction_fund,
        terminal_unpaid_infrastructure_construction_cny=model.grid.reserved,
        terminal_capacity_mw=rows[-1]["total_capacity_mw"])
