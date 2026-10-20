"""Independent observed-2024 physical opening with disclosed financial priors.

This is a new initial condition, never a correction to the historical run.
National plant ages, thermal subtype stocks, construction commitments, debt and
receivables are partly reconstructed and must not be called observations.
"""
from copy import deepcopy
from math import fsum, sqrt, isfinite

from q2_competition_factory import (verify_policy, verify_history, verified_costs,
    cost_inputs, ThermalVintages, scope_inputs, policy_inputs, RenewableVintages,
    AnnualExposure)
from energy_model.q2_project_competition import ProjectCompetitionModel
from energy_model.q2_boundary import InheritedOperatingBoundary
from energy_model.q2_bioenergy import CompositeBioenergy
from energy_model.q2_subsidies import SubsidyFund, SupportTerms, accrue
from run_q2_historical_support import lifetime_limits
from energy_model.q2_national import TECHS, LIFE, NationalGenerator

EVIDENCE = "docs/sources/q2_current_initial_state.md"
DEFAULTS = dict(initial_age_multiplier=1., future_initial_pipeline_multiplier=1.,
                opening_debt_asset_ratio=.5, opening_cash_capex_fraction=.1,
                opening_subsidy_arrears_multiplier=1.,
                pumped_generation_cf=65.7e6/(58690*8760))

# Reviewed CEC 2024 gross commissioned capacity, in MW. Solar is rounded in the
# report. Conventional hydro excludes the separately reported 7,530 MW pump.
THROUGHPUT_2024 = dict(coal=33100.,gas=18300.,hydro=13790.-7530.,
                       nuclear=3930.,wind=81370.,solar=280000.)


class CurrentGenerator(NationalGenerator):
    def construction_limit(self):
        return super().construction_limit()*self.current_throughput_rebase


def build(data, design, config, parameters, authority, *, opening_variant=None):
    options = {**DEFAULTS, **(opening_variant or {})}
    if set(options) != set(DEFAULTS):
        raise ValueError("Unknown opening-state option")
    for key, value in options.items():
        if type(value) not in (float, int) or not isfinite(value) or value < 0:
            raise ValueError("Opening-state controls must be finite nonnegative")
    if options["opening_debt_asset_ratio"] > .9 or options["pumped_generation_cf"] > .5:
        raise ValueError("Invalid debt or pumping sensitivity")
    if not .5 <= options["initial_age_multiplier"] <= 1.5:
        raise ValueError("Opening age sensitivity must be in [0.5,1.5]")
    verify_policy()
    verified_costs()
    history_sources = verify_history()
    d, s, p, old_boundary, assumptions, sources = scope_inputs(
        data, design, parameters, recovery_share=.5)
    policy, _, _, prices, actual, _ = policy_inputs(
        d, s, cash_fraction=1, gas_price_factor=1, new_support=True,
        authority_multiple=authority)
    # The initial generator margin is evaluated at first decision year.
    for mapping in (policy.energy_tariffs, policy.metering_fraction,
                    policy.deflators, policy.annual_funding, policy.support_rates):
        mapping[2025] = deepcopy(mapping[2024])
    policy.deflators[2025] = 1.
    policy.history = []
    policy.positions = []
    policy.fund = SubsidyFund(opening_cash_cny=0,opening_payables=[],initial_year=2024)

    history = deepcopy(old_boundary.capacity_history)
    endpoint = dict(coal=1190000., gas=140000., oil=5116., biomass=45970.)
    thermal_2024 = d[2024, "thermal_capacity_mw"]
    # Exact broad totals, approximate rounded coal/gas anchors. The difference
    # stays inactive instead of being silently assigned productive coal.
    thermal_remainder = thermal_2024-fsum(endpoint.values())
    if thermal_remainder < 0:
        raise ValueError("Thermal anchors exceed the observed total")
    for year in range(2015, 2025):
        w = (year-2014)/10
        thermal = d[year, "thermal_capacity_mw"]
        history[year] = {
            t: thermal*((1-w)*history[2014][t]/d[2014, "thermal_capacity_mw"]
                        + w*endpoint[t]/thermal_2024)
            for t in endpoint}
        pump = 22110.+w*(58690.-22110.)
        history[year].update(hydro=d[year, "hydro_capacity_mw"]-pump,
            **{t:d[year,t+"_capacity_mw"] for t in ("nuclear","wind","solar")})
    history[2024].update(endpoint)
    pump_power = 58690.
    # Pump generation is NOT identified by the stock observation. This is an
    # explicit utilisation sensitivity, deducted from the statistical Other
    # residual, and charged with its own pumping energy.
    other_output = d[2024,"unallocated_electricity_mwh"]
    pump_output = pump_power*8760*options["pumped_generation_cf"]
    if pump_output > other_output:
        raise ValueError("Declared pump/Other bridge exceeds the EI Other residual")
    inactive = thermal_remainder+d[2024, "other_capacity_mw"]
    boundary = InheritedOperatingBoundary(initial_year=2024,
        stores={"pumped_hydro":dict(exit_year=2064,
            fixed_om_cny_per_year=pump_power*100000,
            initial_book_value_cny=pump_power*6e6,
            operation=dict(power_mw=pump_power,energy_mwh=pump_power*6,
                initial_mwh=pump_power*3,charge_efficiency=sqrt(.8),
                discharge_efficiency=sqrt(.8),throughput_cost=3))},
        recovery_plants={"unidentified_inactive_stock":dict(exit_year=2049,
            fixed_om_cny_per_year=inactive*100000,initial_book_value_cny=inactive*4e6,
            initial_generation_mwh=0.,energy_tariff_real_cny_per_gross_mwh=0.,
            operation=dict(input="recovered_heat",output="electricity",
                efficiency=.3,capacity_mw=inactive,availability=[0]*4,
                variable_cost_per_mwh=20,minimum_fraction=0,
                ramp_mw_per_hour=0,window_energy_budget_mwh=0))},
        recoveries={"industrial_heat":dict(output="recovered_heat",
            source_input_fractions={s["assumptions"]["demand_fuel_archetypes"]["coal"]+"/coal":0.})},
        initial_pumping_mwh=pump_output/.8,initial_pumped_generation_mwh=pump_output,
        initial_statistical_adjustment_mwh=other_output-pump_output,
        capacity_history=history,evidence=EVIDENCE)
    a = config["bioenergy"]
    initial_waste = d[2024,"biofuel_electricity_mwh"]/.3*p["waste_fuel_fraction"]/a["waste_lhv_mwh_per_t"]
    quantity = {y:min(a["maximum_municipal_waste_delivery_t"],
        initial_waste*a["initial_delivery_headroom"]*(1+p["waste_delivery_growth"])**(y-2024))
        for y in range(2025,2075)}
    fee = a["treatment_fee_real_2024_cny_per_t"]
    bio = CompositeBioenergy(waste_fuel_fraction=p["waste_fuel_fraction"],
        waste_fossil_energy_fraction=a["waste_fossil_energy_fraction"],
        fossil_co2_t_per_mwh_whole_waste=a["fossil_co2_t_per_mwh_whole_waste"],
        waste_lhv_mwh_per_t=a["waste_lhv_mwh_per_t"],waste_delivery_t_by_year=quantity,
        treatment_fee_real_cny_per_t={y:fee for y in quantity},
        municipal_appropriation_real_cny_by_year={y:q*fee*a["municipal_funding_fraction_of_full_service"] for y,q in quantity.items()},
        expected_collection_fraction=a["expected_collection_fraction"],initial_year=2024,evidence=EVIDENCE)
    costs = cost_inputs(d,s)
    mode = config.get("thermal_mode","net58")
    if mode not in {"net55","net58"}:
        raise ValueError("Explicit thermal technical reference required")
    net = dict(coal=.45,gas=.55 if mode=="net55" else .58)
    m = ProjectCompetitionModel(d,s,p,2024,revenue_policy=policy,operating_boundary=boundary,
        variant={k:options[k] for k in ("initial_age_multiplier","future_initial_pipeline_multiplier")},
        detail=True,generation_costs=costs,project_competition=True,
        thermal_vintages=ThermalVintages(new_gross_efficiencies={
            t:e/costs.reference_net_fractions[t] for t,e in net.items()},
            decision_start_year=2025,evidence=EVIDENCE),
        renewable_vintages=RenewableVintages(new_project_cf={
            t:p["new_"+t+"_cf"] for t in ("wind","solar")},evidence=EVIDENCE),
        bioenergy=bio,annual_exposure=AnnualExposure(**config["generator_annual_exposure"]))
    # Rebase construction proxies onto the current observed commissioning
    # scale. Retain response/GDP/time dynamics; do not compound an obsolete
    # 2014-base construction response against the much larger 2024 stock.
    construction_rebase = {}
    for tech,target in THROUGHPUT_2024.items():
        g=m.generators[tech]
        baseline=max(m.initial_additions[tech],
                     g.initial_capacity*(.35 if tech in {"wind","solar"} else .025))
        if tech=="hydro":baseline*=m.theta.get("hydro_construction_response",1)
        if tech=="solar":baseline*=m.theta.get("solar_construction_response",1)
        if baseline<=0:raise ValueError("Nonpositive current construction reference")
        g.__class__=CurrentGenerator
        g.current_throughput_rebase=target/baseline
        construction_rebase[tech]=dict(reference_commissioned_mw=target,
            unrebased_initial_limit_mw=baseline,multiplier=target/baseline,
            evidence="CEC 2024 gross commissioning proxy; solar rounded; not measured maximum throughput")
    # Reconstruct lifetime meters by allocating each observed annual technology
    # output across the reconstructed cohorts then present. Include output
    # before 2015; the 2024 opening never restarts lifetime-hour allowances.
    prior = {c["id"]:0. for c in m.cohorts}
    annual_meters = {}
    for year in range(1970,2025):
        for tech in ("wind","solar","biomass"):
            alive = [c for c in m.cohorts if c["tech"]==tech
                     and c["online_year"]<=year<c["exit_year"]]
            weights = {c["id"]:c["capacity_mw"]*(.5 if c["online_year"]==year else 1.)
                       for c in alive}
            total = fsum(weights.values())
            # Pre-available-data production is explicitly CF reconstructed.
            gross = d.get((year,("biofuel" if tech=="biomass" else tech)+"_electricity_mwh"))
            if gross is None:
                gross = total*m.generators[tech].reference_cf*8760
            meter = m.revenue_policy.export_fraction(max(2014,year),tech)
            for c in alive:
                annual_meters[year,c["id"]] = gross*meter*weights[c["id"]]/total if total else 0.
    policy = m.revenue_policy
    terms = {}
    for c in m.cohorts:
        tech,online = c["tech"],c["online_year"]
        if tech not in ("wind","solar","biomass") or online<2006 or c["capacity_mw"]<=0:
            continue
        duration,hours = lifetime_limits(tech,"lower")
        terms[c["id"]] = SupportTerms(project=c["id"],actor=tech,
            eligible=not(tech in {"wind","solar"} and online>=2021),
            commissioned_year=online,policy_start_year=max(2015,online),
            eligible_years=duration,capacity_mw=c["capacity_mw"],lifetime_hours=hours,
            priority=0,evidence=EVIDENCE)
        prior[c["id"]] = fsum(v for (year,cid),v in annual_meters.items()
                             if cid==c["id"] and year<2015)
    fund = SubsidyFund(opening_cash_cny=0,opening_payables=[],initial_year=2014)
    replay = []
    from dataclasses import replace
    for year in range(2015,2025):
        claims = []
        for cid,term in terms.items():
            historical_term = term
            if year < 2021:
                duration = (20 if term.actor=="solar" and term.commissioned_year>=2014
                            else LIFE[term.actor])
                historical_term = replace(term,eligible_years=duration,
                    lifetime_hours=duration*8760)
            result = accrue(historical_term,year=year,metered_mwh=annual_meters.get((year,cid),0.),
                prior_lifetime_mwh=prior[cid],**actual[year][term.actor])
            claims.append(result["claim"])
            prior[cid] = result["closing_lifetime_mwh"]
        replay.append(fund.settle(year=year,claims=claims,**policy.annual_funding[year]))
    payables = [replace(c,amount_cny=c.amount_cny*options["opening_subsidy_arrears_multiplier"])
                for c in fund.payables]
    policy.fund = SubsidyFund(opening_cash_cny=fund.cash,opening_payables=payables,initial_year=2024)
    policy.positions = [dict(terms=term,prior_lifetime_mwh=prior[cid]) for cid,term in terms.items()]
    for year in (2024,2025):
        policy.support_rates[year] = {cid:deepcopy(actual[2024][term.actor]) for cid,term in terms.items()}
    # Separate initial journal, not a 2025 income transfer. Assets have explicit
    # lender/shareholder counterparties and construction escrow is restricted.
    opening = []
    for tech,g in m.generators.items():
        book = fsum(c["capacity_mw"]*c["book_cost_cny_per_mw"]*
            max(0,(c["exit_year"]-2024)/(c["exit_year"]-c["online_year"]))
            for c in m.cohorts if c["tech"]==tech and c["status"]=="active")
        queue = fsum(q["cost"]-q["remaining"] for q in m.projects if q["tech"]==tech)
        escrow = fsum(q["remaining"] for q in m.projects if q["tech"]==tech)
        g.cash = g.initial_capacity*g.capex_2024*options["opening_cash_capex_fraction"]
        receivable = fsum(c.amount_cny for c in payables if c.actor==tech)
        principal = (book+queue+escrow)*options["opening_debt_asset_ratio"]
        g.loans = [dict(project="opening/2024/"+tech,remaining=principal,
            annual_principal=principal/m.a["loan_term_years"],due=2025,
            overdue=0.,interest_overdue=0.)] if principal else []
        assets = book+queue+escrow+g.cash+receivable
        opening.append(dict(actor=tech,active_book_cny=book,
            construction_work_in_progress_cny=queue,restricted_construction_cash_cny=escrow,
            unrestricted_cash_cny=g.cash,subsidy_receivable_cny=receivable,
            debt_cny=principal,opening_equity_cny=assets-principal,
            assets_cny=assets,balance_residual_cny=assets-principal-(assets-principal)))
    m.opening_balance_sheet = opening
    m.opening_subsidy_replay = replay
    m.opening_state_assumptions = dict(options,
        subsidy_history="observed annual generation allocated to reconstructed cohorts; finite actual 2015-2024 fiscal budgets replayed; eligibility proxy, not project register",
        support_2021="no wind/solar eligibility for reconstructed online cohorts from 2021; pre-2021 grandfathering proxy",
        opening_finance="book-value debt ratio and gross-cost liquidity priors; residual explicitly owned shareholder equity",
        queue="each lead-year receives 2021-2024 mean net stock addition times disclosed multiplier; costs funded in opening WIP plus restricted escrow",
        construction="2024 stock and 2021-2024 net additions seed capacity; solar manufacturing growth elapsed historical years reset to zero",
        construction_throughput_rebase=construction_rebase,
        municipal_arrears="zero opening municipal payable assumption",
        other="thermal remainder plus Other stock inactive; Other generation split pump utilisation sensitivity and statistical adjustment",
        thermal_subtypes="coal/gas rounded 2024 CEC anchors; oil fixed at 2014 5116MW; annual subtype shares interpolated, not observations",
        asset_age="2009 residual uniform ages plus positive stock increments to 2024, normalized to exact endpoint; not gross commissioning register")
    assumptions.update(current_initial_state=m.opening_state_assumptions,
        starting_state="independent observed 2024 physical snapshot with explicitly reconstructed financial opening",
        total_initial_capacity_mw=d[2024,"total_capacity_mw"],
        inactive_thermal_remainder_mw=thermal_remainder,opening_balance_sheet=opening,
        recovery_share_of_other_after_pump=0.,
        recovery_fraction_of_direct_coal_input=0.,
        unidentified_inactive_capacity_mw=inactive,
        initial_statistical_adjustment_mwh=other_output-pump_output,
        initial_pumped_generation_mwh=pump_output,
        extra_free_cash_or_assets=False,
        observation_fit="opening match is an initial condition, never historical-fit validation")
    sources += [*history_sources,"scripts/q2_current_factory.py",EVIDENCE,
        "data/raw/q2_technology_scope/cec_annual2025_release.txt",
        "data/raw/q2_technology_scope/technology_capacity_generation_anchors.csv",
        "data/raw/q2_scope_components/source_manifest.json",
        "data/raw/q2_scope_components/visual_pdf_anchors.json",
        "data/raw/q2_scope_components/hydrochina_renewables_2024.pdf",
        "data/processed/q2/national_observations.csv"]
    return m,assumptions,list(dict.fromkeys(sources))
