"""Full-window CONDITIONAL support experiment; unknown prices stay assumptions.

2014-2018 NEA tariff/auxiliary observations and 2015-2024 MOF accounts are
verified against originals. 2019-2024 technology prices/auxiliaries are explicit
2018-persistence scenarios, NOT reconstructed observations. No acceptance claim,
no parameter selection using the already-seen evaluation window, no forecasts.
"""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from math import fsum,isfinite
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"scripts"));sys.path.insert(0,str(ROOT/"src"))
from run_q2_empirical_support import (preflight,scope_inputs,tariff_inputs,
    fiscal_observations,csv_rows,sha,extract,CODE,INPUTS)
from energy_model.q2_national import NationalModel,TECHS,LIFE,LEAD
from energy_model.q2_subsidies import SupportTerms
from energy_model.q2_support_investment import SupportOffer,NewProjectSupport

YEARS=tuple(range(2015,2025))
EVIDENCE="docs/sources/q2_historical_support_experiment.md"
SUPPORTED=("wind","solar","biomass")


def policy_inputs(data,design,*,cash_fraction,gas_price_factor,new_support,
                  collection_fraction=.75,payment_delay=2,authority_multiple=5,
                  resource_zone="lower",premium_factor=1):
    """Contemporaneous-price support expectations, explicitly bounded by cash.

    The representative support spread is not a plant-level statutory tariff.
    Its annual lifetime authority (multiple of CURRENT published annual budget)
    is a scenario, not an observed legal national commitment authorisation.
    """
    if resource_zone not in {"lower","upper"}:
        raise ValueError("Resource-zone bound must be lower or upper")
    for value in (cash_fraction,gas_price_factor,collection_fraction,authority_multiple,premium_factor):
        if type(value) not in (int,float) or not isfinite(value):
            raise ValueError("Scenario scalars must be finite numbers")
    for name,value in (("cash fraction",cash_fraction),("collection",collection_fraction)):
        if not 0<=value<=1:raise ValueError("Invalid "+name)
    if gas_price_factor<=0 or authority_multiple<0 or premium_factor<0:
        raise ValueError("Invalid historical support scenario")
    policy,cells,tax=tariff_inputs(data,design,mode="finite")
    fiscal=fiscal_observations(YEARS)
    rows=[]
    for y in (2014,*YEARS):
        observed=y<=2018
        source_year=y if observed else 2018
        if y==2019:tax[y]=3/12/1.16+9/12/1.13
        elif y>=2020:tax[y]=1/1.13
        policy.deflators[y]=data[2024,"cpi"]/data[y,"cpi"]
        if not observed:
            for t in TECHS:
                if t=="oil":continue
                for metric in ("feed_in_tariff","auxiliary_own_use"):
                    value=cells[2018,t,metric]
                    if t=="gas" and metric=="feed_in_tariff":value*=gas_price_factor
                    cells[y,t,metric]=value
        policy.energy_tariffs[y]={}
        policy.metering_fraction[y]={}
        for t in TECHS:
            meter_t="coal" if t=="oil" else t
            energy_t="coal" if t in {*SUPPORTED,"oil"} else t
            meter=1-cells[y,meter_t,"auxiliary_own_use"]/100
            policy.metering_fraction[y][t]=meter
            policy.energy_tariffs[y][t]=cells[y,energy_t,"feed_in_tariff"]*tax[y]*policy.deflators[y]*meter
            rows.append(dict(year=y,technology=t,energy_price_nominal_vat_inclusive_per_export_mwh=cells[y,energy_t,"feed_in_tariff"],
                all_in_price_nominal_vat_inclusive_per_export_mwh=cells[y,meter_t,"feed_in_tariff"],
                export_fraction=meter,energy_tariff_real_2024_per_gross_mwh=policy.energy_tariffs[y][t],
                status="NEA_observation_with_explicit_coal_reference_proxy" if observed else "2018_nominal_price_and_meter_persistence_assumption",
                source_year=source_year,oil_proxy=t=="oil"))
        if y in YEARS:
            policy.annual_funding[y]=dict(
                levy_receipts_cny=float(fiscal[y,"revenue"]["actual"])*1e8,
                treasury_transfer_cny=0.,
                expenditure_limit_cny=float(fiscal[y,"expenditure"]["actual"])*1e8*cash_fraction)
            policy.support_rates[y]={}
    # Fixed ceiling of 1000 nominal CNY/MWh is an explicit reserve assumption,
    # not the maximum of realised FUTURE rates. Actual rates must fit it.
    offers=[]
    actual={y:{t:rates(cells,tax,y,t,premium_factor) for t in SUPPORTED} for y in YEARS}
    authority={y:float(fiscal[y,"expenditure"]["budget"])*1e8*authority_multiple for y in YEARS}
    if new_support:
        for y in YEARS:
            for t in SUPPORTED:
                # Onshore/nonhousehold representative only; no cancellation
                # of accrued or existing-project rights in the 2021 change.
                if y>=2021 and t in {"wind","solar"}:continue
                duration,hours=(lifetime_limits(t,resource_zone) if y>=2021 else (LIFE[t],LIFE[t]*8760))
                current=actual[y][t]
                premium=max(0,current["supported_tariff_cny_per_mwh"]-current["reference_tariff_cny_per_mwh"])/(1+current["vat_rate"])
                offers.append(SupportOffer(technology=t,decision_year=y,announced_year=y,
                    commissioning_deadline=y+LEAD[t],eligible_years=duration,lifetime_hours=hours,
                    premium_cap_nominal_cny_per_mwh=1000,expected_premium_nominal_cny_per_mwh=premium,
                    metering_fraction=policy.export_fraction(y,t),expected_collection_fraction=collection_fraction,
                    expected_payment_delay_years=payment_delay,expected_real_2024_per_nominal=policy.deflators[y],
                    priority=0,evidence=EVIDENCE))
        policy.new_support=NewProjectSupport(offers=offers,commitment_authority_cny=authority,
            actual_rates=actual,evidence=EVIDENCE)
    policy.evidence=EVIDENCE
    return policy,cells,tax,rows,actual,authority


def rates(cells,tax,year,tech,premium_factor=1):
    reference=cells[year,"coal","feed_in_tariff"]
    supported=reference+max(0,cells[year,tech,"feed_in_tariff"]-reference)*premium_factor
    return dict(supported_tariff_cny_per_mwh=supported,
        reference_tariff_cny_per_mwh=reference,vat_rate=1/tax[year]-1)


def lifetime_limits(tech,zone):
    if tech=="biomass":return 15,82500
    return 20,({"wind":36000,"solar":22000} if zone=="lower" else {"wind":48000,"solar":32000})[tech]


def add_initial_support(model,actual,*,pipeline=True):
    """Broad conditional entitlement set, not observed project-directory data.

    Includes declared inherited construction when requested. Its support is
    never earned before actual commissioning; no promise becomes construction
    cash. Historical cumulative exports are reconstructed, never reset.
    """
    policy=model.revenue_policy
    candidates=[c for c in model.cohorts if c["status"]=="active"]
    if pipeline:candidates += [p for p in model.projects if p["initial_reconstruction"]]
    for c in candidates:
        t,online=c["tech"],c["online_year"]
        if t not in SUPPORTED or online<2006:continue
        terms=SupportTerms(project=c["id"],actor=t,eligible=True,commissioned_year=online,
            policy_start_year=max(2015,online),eligible_years=LIFE[t],capacity_mw=c["capacity_mw"],
            lifetime_hours=LIFE[t]*8760,priority=0,evidence=EVIDENCE)
        prior=c["capacity_mw"]*model.generators[t].reference_cf*8760*max(0,2015-online)*policy.export_fraction(2014,t)
        policy.positions.append(dict(terms=terms,prior_lifetime_mwh=prior))
        for y in YEARS:policy.support_rates[y][terms.project]=actual[y][t]


def apply_announced_lifetime_limits(model,*,zone):
    """2021 first-full-year approximation of the October 2020 announcement.

    This is deliberately not Jan-2020 knowledge. Entitlement stock is changed,
    but past metered generation, receivables and reserved commitments survive.
    Pre-announcement expected NPV is never recalculated using the new rule.
    """
    if model.year<2021:raise ValueError("Cannot backdate announced lifetime limits")
    changes=[]
    for p in model.revenue_policy.positions:
        old=p["terms"]
        duration,hours=lifetime_limits(old.actor,zone)
        current=replace(old,eligible_years=min(old.eligible_years,duration),
            lifetime_hours=min(old.lifetime_hours,hours))
        if current!=old:
            p["terms"]=current
            changes.append(dict(year=model.year,project=old.project,old_eligible_years=old.eligible_years,
                eligible_years=current.eligible_years,old_lifetime_hours=old.lifetime_hours,
                lifetime_hours=current.lifetime_hours,unchanged_prior_metered_mwh=p["prior_lifetime_mwh"]))
    return changes


def run_case(data,design,theta,*,new_support=True,gas_price_factor=1,cash_fraction=1,
             pipeline=True,resource_zone="lower",collection_fraction=.75,payment_delay=2,
             authority_multiple=5,premium_factor=1,generation_costs=None,renewable_vintages=None,end_year=2024,bioenergy=None,annual_exposure=None):
    d,s,p,b,assumptions,source_paths=scope_inputs(data,design,theta,recovery_share=.5)
    policy,cells,tax,price_rows,actual,authority=policy_inputs(d,s,cash_fraction=cash_fraction,
        gas_price_factor=gas_price_factor,new_support=new_support,resource_zone=resource_zone,
        collection_fraction=collection_fraction,payment_delay=payment_delay,
        authority_multiple=authority_multiple,premium_factor=premium_factor)
    if end_year not in range(2015,2025):raise ValueError("Historical endpoint must be 2015--2024")
    model=NationalModel(d,s,p,2014,revenue_policy=policy,operating_boundary=b,detail=True,
        generation_costs=generation_costs,renewable_vintages=renewable_vintages,bioenergy=bioenergy,annual_exposure=annual_exposure)
    add_initial_support(model,actual,pipeline=pipeline)
    changes=[]
    for y in range(2015,end_year+1):
        if y>=2021:changes.extend(apply_announced_lifetime_limits(model,zone=resource_zone))
        model.run(y)
    assumptions.update(new_project_support=new_support,initial_construction_support=pipeline,
        unknown_2019_2024_tariffs="2018_nominal_prices_with_explicit_gas_multiplier",
        unknown_2019_2024_auxiliary_use="2018_constant_fraction",
        post2018_gas_price_multiplier=gas_price_factor,cash_spending_fraction=cash_fraction,
        expected_collection_fraction=collection_fraction,expected_payment_delay_years=payment_delay,
        commitment_authority_multiple_of_current_budget=authority_multiple,resource_zone_bound=resource_zone,
        representative_premium_multiplier=premium_factor,initial_cash=0,initial_arrears=0,
        known_extra_treasury_transfer=0,missing_fund_origins="not_inferred_from_spending_minus_revenue",
        lifetime_2020_rule_application="2021_first_full_year_approximation",
        new_wind_solar_stop="2021_onshore_nonhousehold_representative_not_all_renewables",
        eligibility="broad_reconstructed_cohorts_not_actual_project_directory",
        bio_support="aggregate_effective_spread_not_750_or_650_statutory_tariff_for_all_bio",
        generation_cost_evidence=generation_costs.evidence if generation_costs else "legacy_combined_om",
        renewable_new_project_yields=renewable_vintages.__dict__ if renewable_vintages else None,
        bioenergy_composition_evidence=bioenergy.evidence if bioenergy else None,
        generator_annual_exposure=annual_exposure.__dict__ if annual_exposure else None)
    return model,assumptions,price_rows,changes,source_paths


def metrics(model,references):
    result={}
    for tech in TECHS:
        category={"biomass":"geothermal_biomass_other_renewables","hydro":"hydro_primary"}.get(tech,tech)
        rows=[]
        for row in model.paths:
            y=row["year"];observed=references[y,category]
            rows.append(dict(year=y,model_mwh=row[tech+"_generation_mwh"],observed_mwh=observed,
                relative_error=row[tech+"_generation_mwh"]/observed-1,
                capacity_mw=row[tech+"_capacity_mw"],
                utilisation_hours=row[tech+"_generation_mwh"]/row[tech+"_capacity_mw"] if row[tech+"_capacity_mw"] else None,
                utilisation_denominator="year_end_capacity_not_average_capacity",
                operating_exposure_mw_year=row[tech+"_operating_exposure_mw_year"],
                exposure_normalised_hours=(row[tech+"_generation_mwh"]/row[tech+"_operating_exposure_mw_year"]
                    if row[tech+"_operating_exposure_mw_year"] else None)))
        result[tech]={"years":rows}
        for split,years in (("training",range(2015,2022)),("already_seen_evaluation",range(2022,2025))):
            errors=[abs(r["relative_error"]) for r in rows if r["year"] in years]
            result[tech][split]=dict(mape=fsum(errors)/len(errors),max_absolute_relative_error=max(errors))
        projects=[p for p in model.projects if p["tech"]==tech and not p["initial_reconstruction"]]
        result[tech].update(autonomous_projects=len(projects),commissioned_autonomous_projects=sum(p["status"]=="commissioned" for p in projects))
    return result


def main():
    data,design,_=preflight()
    calibration="outputs/q2/p2_lb_national/calibration.json"
    theta=json.loads((ROOT/calibration).read_text("utf-8"))["best"]["parameters"]
    folder=ROOT/"outputs/q2_historical_support"/datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True)
    refs={(r["year"],r["category"]):r["value_twh"]*1e6 for r in extract()[0]}
    specs={"existing_only_no_initial_pipeline":dict(new_support=False,pipeline=False),
        "existing_and_initial_pipeline":dict(new_support=False),"new_support_central":{},
        "new_support_half_cash":dict(cash_fraction=.5),"new_support_low_gas_price":dict(gas_price_factor=.8),
        "new_support_high_gas_price":dict(gas_price_factor=1.2),
        "new_support_upper_zone":dict(resource_zone="upper"),
        "new_support_prompt_expectation":dict(collection_fraction=1,payment_delay=0),
        "new_support_half_premium":dict(premium_factor=.5),
        "new_support_authority_25":dict(authority_multiple=25),
        "new_support_authority_100":dict(authority_multiple=100),
        "new_support_authority_100_prompt":dict(authority_multiple=100,collection_fraction=1,payment_delay=0)}
    outcomes={};paths=set(CODE+INPUTS+[calibration,__file__,EVIDENCE,
        "scripts/run_q2_empirical_support.py","scripts/build_q2_electricity_scope.py",
        "scripts/build_q2_revenue_evidence.py","data/raw/q2_technology_scope/ei_2025_original.xlsx",
        "data/raw/q2_capacity_detail/research.py","data/raw/q2_capacity_detail/source_manifest.json",
        "data/raw/q2_fiscal/build_fiscal.py","data/raw/q2_fiscal/source_manifest.json",
        "data/raw/q2_fiscal/annual_renewable_levy.csv","data/processed/q2/revenue/nea_tariff_and_auxiliary_use.csv",
        "data/catalog/q2_revenue_review.json"])
    review=json.loads((ROOT/"data/catalog/q2_revenue_review.json").read_text("utf-8"))
    paths.update(review["source_sha256"])
    for row in csv_rows("data/raw/q2_fiscal/annual_renewable_levy.csv"):
        if int(row["year"]) in YEARS and row["scope"]=="national":paths.add("data/raw/q2_fiscal/"+row["source_file"])
    for name,kwargs in specs.items():
        model,assumptions,prices,changes,sources=run_case(data,design,theta,**kwargs)
        paths.update(sources)
        result=dict(assumptions=assumptions,metrics=metrics(model,refs),price_inputs=prices,
            paths=model.paths,projects=model.projects,finance=model.finance,behavior=model.behavior,
            operations=model.operations,balances=model.balances,fund_history=model.revenue_policy.history,
            lifetime_rule_changes=changes,new_project_commitments=(model.revenue_policy.new_support.reserved if model.revenue_policy.new_support else {}))
        (folder/(name+".json")).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+"\n","utf-8")
        outcomes[name]={"metrics":result["metrics"],"end":model.paths[-1],
            "total_paid_nominal_cny":fsum(r["subsidy_paid_nominal_cny"] for r in model.paths)}
        print(name,{t:round(result["metrics"][t]["already_seen_evaluation"]["mape"]*100,2) for t in ("gas","oil","biomass")},flush=True)
    paths={(ROOT/p).resolve().relative_to(ROOT).as_posix() for p in paths}
    report=dict(status="full_window_conditional_mechanism_experiment_not_acceptance",
        years=YEARS,new_calibration=False,evaluation_identity="already_seen_2022_2024_no_selection",
        unknown_prices_are_observations=False,production_default_changed=False,
        source_sha256={p:sha(p) for p in sorted(paths)},results=outcomes)
    (folder/"results.json").write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+"\n","utf-8")
    lines=["# 完整历史窗口的补贴条件实验","","2015—2021训练窗、2022—2024已接触评估；固定V10行为参数。2019以后的价格为明确假设，尚未重新校准或通过科学验收。","",
        "| 条件组 | 气电评估MAPE | 纯油评估MAPE | 复合生物能源评估MAPE | 气/生物自主项目（已投产） | 2024模拟欠款亿元 |",
        "|---|---:|---:|---:|---|---:|"]
    for name,r in outcomes.items():
        m=r["metrics"]
        lines.append(f"| {name} | {100*m['gas']['already_seen_evaluation']['mape']:.2f}% | {100*m['oil']['already_seen_evaluation']['mape']:.2f}% | {100*m['biomass']['already_seen_evaluation']['mape']:.2f}% | {m['gas']['autonomous_projects']}({m['gas']['commissioned_autonomous_projects']}) / {m['biomass']['autonomous_projects']}({m['biomass']['commissioned_autonomous_projects']}) | {r['end']['subsidy_arrears_nominal_cny']/1e8:.2f} |")
    lines.extend(["","每组JSON含逐年物理、资金、项目、输入价格和规则变更。财政实际收支是来源观测，企业资格、到账上限与新项目承诺是条件假设；不能将模拟欠款报告成真实欠款。",
        "","本实验不认证垃圾化石碳、非化石比例或2060结论。后续须统一EI垃圾/Other成对映射，补收益成本拆分，重新训练后按原门槛检验。",""])
    (folder/"report.md").write_text("\n".join(lines),"utf-8")
    print(folder.relative_to(ROOT).as_posix())


if __name__=="__main__":main()
