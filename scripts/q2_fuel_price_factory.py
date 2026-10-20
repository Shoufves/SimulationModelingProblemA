"""Corrected historical factory plus explicitly scoped fuel-price scenarios."""
from q2_corrected_factory import (verify_policy, scope_inputs, policy_inputs,
    apply_solar_duration, cost_inputs, RenewableVintages, bio_inputs, AnnualExposure,
    add_initial_support, apply_announced_lifetime_limits)
from energy_model.q2_fuel_prices import FuelPriceNationalModel


def build(data, design, config, parameters, authority, *, end_year, fuel_prices=None,
          include_bio=True, include_vintages=True):
    if end_year not in range(2015, 2025):
        raise ValueError("Expected a historical endpoint")
    if fuel_prices is not None:
        fuel_prices.validate_window(2014, end_year)
    verify_policy()
    d, s, p, boundary, assumptions, source_paths = scope_inputs(data, design, parameters, recovery_share=.5)
    policy, cells, tax, prices, actual, _ = policy_inputs(d, s, cash_fraction=1, gas_price_factor=1,
        new_support=True, authority_multiple=authority)
    offer_changes = apply_solar_duration(policy)
    m = FuelPriceNationalModel(d, s, p, 2014, revenue_policy=policy, operating_boundary=boundary, detail=True,
        generation_costs=cost_inputs(data, design), fuel_prices=fuel_prices,
        renewable_vintages=RenewableVintages(new_project_cf={t: parameters["new_"+t+"_cf"] for t in ("wind", "solar")},
                                            evidence="docs/sources/q2_revenue_recalibration.md") if include_vintages else None,
        bioenergy=bio_inputs(d, config, parameters) if include_bio else None,
        annual_exposure=AnnualExposure(**config["generator_annual_exposure"]))
    add_initial_support(m, actual)
    initial_changes = apply_solar_duration(m.revenue_policy)
    changes = []
    for year in range(2015, end_year+1):
        if year >= 2021:
            changes.extend(apply_announced_lifetime_limits(m, zone="lower"))
        m.run(year)
    assumptions.update(portfolio_audit="shrink_failed_then_jointly_rescreen",
        solar_duration_rule="2013_1638_twenty_years_for_known_applicable_cohorts",
        policy_duration_changes=offer_changes+initial_changes,
        commitment_authority_multiple_of_current_budget=authority,
        physical_solar_lifetime_years=25, solar_standard_eligibility_years=20,
        annual_exposure=m.annual_exposure.__dict__, extra_free_cash_or_assets=False,
        fuel_price_scope="conditional_shared_market_proxy" if fuel_prices is not None else "original_reference",
        fuel_price_timing="initial-year prices before generator/consumer priors; annual prices before operation",
        investment_price_information="current price persists; no future realised fuel prices",
        consumer_income="initial real-price reconstruction; never reimbursed for annual price increases",
        delivered_power_index_not_verified_nonpower_price=True,
        supplier_import_premium="inherited 5-percent technical assumption; not measured national landed-price spread")
    source_paths += ["data/raw/q2_solar_entitlement/ndrc_solar_2013_1638.html",
        "data/raw/q2_solar_entitlement/source_manifest.json", "src/energy_model/q2_solar_entitlement.py",
        "src/energy_model/q2_portfolio.py", "src/energy_model/q2_fuel_prices.py",
        "scripts/q2_corrected_factory.py", "scripts/q2_fuel_price_factory.py"]
    return m, assumptions, prices, changes, source_paths
