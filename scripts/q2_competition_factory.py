"""Versioned private-project screening with the same physical/fiscal inputs."""
from q2_thermal_factory import (verify_policy, verify_history, verified_costs, cost_inputs,
    ThermalVintages, scope_inputs, policy_inputs, apply_solar_duration, RenewableVintages,
    bio_inputs, AnnualExposure, add_initial_support, apply_announced_lifetime_limits)
from energy_model.q2_project_competition import ProjectCompetitionModel


def build(data, design, config, parameters, authority, *, end_year, fuel_prices=None,
          include_bio=True, include_vintages=True, thermal_mode=None, decision_start_year=2015,
          project_competition=True):
    mode = thermal_mode or config.get("thermal_mode", "net58")
    if end_year not in range(2015,2025) or mode not in {"net55","net58","disabled"}:
        raise ValueError("Historical endpoint and explicit technical reference required")
    if project_competition and (mode == "disabled" or decision_start_year>2015):
        raise ValueError("Competition requires both thermal project screens from 2015")
    if fuel_prices is not None:
        fuel_prices.validate_window(2014,end_year)
    verify_policy()
    verified_costs()
    history_sources = verify_history()
    costs = cost_inputs(data,design)
    net = dict(coal=.45,gas=.55 if mode=="net55" else .58)
    thermal = None if mode=="disabled" else ThermalVintages(
        new_gross_efficiencies={t:e/costs.reference_net_fractions[t] for t,e in net.items()},
        decision_start_year=decision_start_year,evidence="docs/sources/q2_thermal_vintages.md")
    d,s,p,boundary,assumptions,sources = scope_inputs(data,design,parameters,recovery_share=.5)
    policy,cells,tax,prices,actual,_ = policy_inputs(d,s,cash_fraction=1,gas_price_factor=1,
        new_support=True,authority_multiple=authority)
    offer_changes = apply_solar_duration(policy)
    model = ProjectCompetitionModel(d,s,p,2014,revenue_policy=policy,operating_boundary=boundary,detail=True,
        generation_costs=costs,fuel_prices=fuel_prices,thermal_vintages=thermal,
        project_competition=project_competition,
        renewable_vintages=RenewableVintages(new_project_cf={t:parameters["new_"+t+"_cf"] for t in ("wind","solar")},
            evidence="docs/sources/q2_revenue_recalibration.md") if include_vintages else None,
        bioenergy=bio_inputs(d,config,parameters) if include_bio else None,
        annual_exposure=AnnualExposure(**config["generator_annual_exposure"]))
    add_initial_support(model,actual)
    initial_changes = apply_solar_duration(model.revenue_policy)
    changes = []
    for year in range(2015,end_year+1):
        if year>=2021:
            changes.extend(apply_announced_lifetime_limits(model,zone="lower"))
        model.run(year)
    assumptions.update(project_competition=project_competition,
        investor_objective="private project return on allocated LP sales" if project_competition else "aggregate technology owner incremental return",
        project_dispatch="common thermal utilisation; common renewable curtailment by available output",
        project_finance="representative sector financing pool; not measured independent firm balance sheets",
        private_and_social_cost="displaced incumbent sales remain in cohort accounts; no extra output or revenue created",
        policy_duration_changes=offer_changes+initial_changes,
        commitment_authority_multiple_of_current_budget=authority,annual_exposure=model.annual_exposure.__dict__,
        thermal_mode=mode,thermal_decision_start_year=decision_start_year,
        thermal_reference_net_efficiencies=net if thermal else None,
        thermal_reference_net_fractions=costs.reference_net_fractions,
        thermal_new_gross_efficiencies=thermal.new_gross_efficiencies if thermal else None,
        thermal_history_scope="technical reference sensitivity, not observed historical new-unit efficiency",
        initial_thermal_fleet_and_pipeline="original efficiencies retained; no free retrofit",
        nonpower_identification="original fixed-efficiency residual identification unchanged",
        thermal_costs="reviewed forward technical assumptions; not historical observations",
        fuel_price_scope="conditional_shared_market_proxy" if fuel_prices else "original_reference",
        extra_free_cash_or_assets=False)
    sources += ["data/raw/q2_solar_entitlement/ndrc_solar_2013_1638.html",
        "data/raw/q2_solar_entitlement/source_manifest.json", "src/energy_model/q2_solar_entitlement.py",
        "src/energy_model/q2_portfolio.py", "src/energy_model/q2_fuel_prices.py",
        "src/energy_model/q2_thermal_vintages.py", "src/energy_model/q2_project_competition.py",
        "scripts/q2_corrected_factory.py", "scripts/q2_fuel_price_factory.py", "scripts/q2_thermal_factory.py",
        "scripts/q2_competition_factory.py", "docs/sources/q2_thermal_vintages.md",
        "docs/sources/q2_project_competition.md", *history_sources]
    return model,assumptions,prices,changes,sources
