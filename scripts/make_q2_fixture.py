"""Explicitly regenerate SYNTHETIC engineering inputs; never Chinese observations.

This manual developer command is deliberately separate from run.py q2.
"""
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from energy_model.q2_agents import simulate
from energy_model.q2_experiments import validate_model


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def make_model(start):
    units = dict(coal=(10,.38,35,0.34),gas=(8,.52,55,.20),oil=(1,.4,75,.26),
                 biomass=(1,.3,45,.0),hydro=(3,1,0,0),nuclear=(4,1,0,0),wind=(8,1,0,0),solar=(10,1,0,0))
    c = dict(scope="synthetic_engineering_fixture",seed=20261018,start_year=start,price_year=start,
        information="known_deterministic_repeated_window_no_weather_probability",
        primary_accounting="physical_LHV_noncombustion_equivalent_explicit",
        carbon_accounting="combustion_only_plus_explicit_bridge_no_CCS",
        base_gdp_index=100,periods=[{"hours":6} for _ in range(4)],annual_repeats=365,
        grid=dict(efficiency=.95,power_mw=35),
        storage=dict(power_mw=3,energy_mwh=12,initial_mwh=6,charge_efficiency=.9,
                     discharge_efficiency=.9,throughput_cost=.5,terminal_mwh=6),
        network=dict(initial_cash=1e12,grid_capex_per_mw=40000,storage_capex_per_mw=100000,
                     storage_hours=4,build_limit_mw=2,lead_years=2,lifetime_years=30),
        government=dict(initial_cash=0,plant_permit_mw_per_year=3),
        suppliers={},generators={},consumers={},initial_cohorts=[],policies=[],drivers={},carbon_bridge={})
    for name,(capacity,eta,price,ef) in units.items():
        fuel = name if name in {"coal","gas","oil","biomass"} else None
        if fuel:
            c["suppliers"][name] = dict(initial_cash=1e12,markup=.1,nonfossil=name=="biomass",operation=dict(
                domestic_mw=[80 if name != "biomass" else 5]*4,import_mw=[10 if name != "biomass" else 0]*4,
                domestic_cost_per_mwh=price,import_cost_per_mwh=price*1.2,emission_t_per_mwh=ef,
                tank_mwh=80,initial_mwh=40,injection_mw=10,withdrawal_mw=10))
        name_plant = name+"_plant"
        availability = {"solar":[0,.6,.8,0],"wind":[.5,.3,.4,.5]}.get(name,[.8]*4)
        c["generators"][name_plant] = dict(initial_cash=1e12,initial_expected_margin_per_mw=5000,
            capex_per_mw=180000 if fuel else 240000,lifetime_years=25,lead_years=2 if fuel else 3,
            discount_rate=.05,build_limit_mw=1,fixed_cost_per_mw=2000,
            primary_equivalent_per_output_mwh=1,nonfossil=fuel is None or name=="biomass",
            operation=dict(input=fuel,output="electricity",efficiency=eta,capacity_mw=capacity,
                availability=availability,variable_cost_per_mwh=3,minimum_fraction=0,ramp_mw_per_hour=10,
                window_energy_budget_mwh=50 if name=="hydro" else 1e6))
        c["initial_cohorts"].append(dict(id="fixture/"+name,plant=name_plant,capacity_mw=capacity,
            online_year=start-5,retirement_year=start+20,legal_exit_year=start+20,status="active"))
    for name,inp,out,eta in (("electrolyser","electricity","hydrogen",.7),("fuel_cell","hydrogen","electricity",.5)):
        c["generators"][name] = dict(initial_cash=1e12,initial_expected_margin_per_mw=0,
            capex_per_mw=1000000,lifetime_years=20,lead_years=2,discount_rate=.05,build_limit_mw=.2,
            fixed_cost_per_mw=100,primary_equivalent_per_output_mwh=0,nonfossil=False,
            operation=dict(input=inp,output=out,efficiency=eta,capacity_mw=.2,
                availability=[1]*4,variable_cost_per_mwh=2,minimum_fraction=0,ramp_mw_per_hour=10,
                window_energy_budget_mwh=1e6))
        c["initial_cohorts"].append(dict(id="fixture/"+name,plant=name,capacity_mw=.2,
            online_year=start-2,retirement_year=start+18,legal_exit_year=start+18,status="active"))
    for name,fuel,service,priority in (("industry","coal",100000,1),("transport","oil",60000,2),("buildings","gas",80000,0)):
        c["consumers"][name] = dict(initial_cash=1e12,fuel=fuel,fossil_service_mw=12,electric_service_mw=4,
            base_service_mwh=service,shape=[.2,.3,.3,.2],fuel_efficiency=.8,electric_efficiency=1.0,
            service_intensity_decline=.005,priority=priority,device_lifetime_years=15,
            capex_per_service_mw=60000,installation_limit_mw=1,payback_years=8,income_per_service_mwh=500)
    c["policies"] = [dict(id="fixture-net-charge",published_year=start,effective_year=start,basis="SYNTHETIC net carbon charge, NOT China ETS/free allowances",
        coverage={name:1 for name in [*c["generators"],*c["consumers"]]})]
    for y in range(start,2061):
        c["drivers"][str(y)] = dict(gdp_index=100*1.025**(y-start),cost_decline=.02,
            carbon_price=50,generation_price=90,retail_price=110,hydrogen_price=160)
        c["carbon_bridge"][str(y)] = dict(other_positive_t=1000,net_removals_t=100,
            basis="SYNTHETIC constants, not inventories or forecasts; biomass zero EF is fixture convention")
    return c


def main():
    folder = ROOT/"examples/q2"
    history,forward = make_model(2015),make_model(2024)
    theta = dict(activity_elasticity=1,investment_rate=.5,replacement_rate=.5,expectation_rate=.5)
    design = dict(status="engineering_fixture_only_not_team_scientific_agreement",frozen_before_evaluation=True,
        training_years=list(range(2015,2022)),evaluation_years=[2022,2023,2024],evaluation_identity="already_seen_not_blind",
        parameter_grid=dict(activity_elasticity=[.9,1,1.1],investment_rate=[.25,.5,.75],replacement_rate=[.25,.5,.75],expectation_rate=[.5]),
        search_budget=27,equivalent_absolute_tolerance=1e-7,equivalent_relative_tolerance=.05,
        peak_persistence_years=5,acceptance_thresholds=None,
        scales_basis="Fixed fixture engineering magnitudes, set before generation; no real-data threshold implied",
        targets=[dict(metric="primary_energy_mwh",family="demand",scale=400000,weight=.25),
                 dict(metric="nonfossil_primary_share",family="structure",scale=.5,weight=.25),
                 dict(metric="capacity_mw",family="capacity_generation",scale=50,weight=.125),
                 dict(metric="generation_mwh",family="capacity_generation",scale=200000,weight=.125),
                 dict(metric="combustion_co2_t",family="emissions",scale=100000,weight=.25)],
        sensitivity=dict(gdp_growth_delta=[-.01,.01],cost_decline_delta=[-.01,.01],carbon_price_multiplier=[.5,1.5]),
        sensitivity_basis="Engine perturbations only: +/-1 percentage point, carbon x0.5/x1.5; not empirical uncertainty bounds",
        sensitivity_budget=6,seed=20261018)
    validate_model(history)
    path = simulate(history,theta,2024).paths
    observations = [dict(year=p["year"],metric=t["metric"],value=p[t["metric"]],
                         source_ref="SELF_GENERATED_SYNTHETIC_ENGINEERING_NOT_VALIDATION")
                    for p in path for t in design["targets"]]
    for name,value in (("history_model.json",history),("forecast_model.json",forward),
                       ("design.json",design),("observations.json",observations)):
        dump(folder/name,value)
    inputs = []
    for role,filename in (("history_model","history_model.json"),("forecast_model","forecast_model.json"),
                          ("design","design.json"),("observations","observations.json")):
        inputs.append(dict(role=role,path=f"examples/q2/{filename}",sha256=hashlib.sha256((folder/filename).read_bytes()).hexdigest(),
                           allowed_use="synthetic_engineering",review="Explicit synthetic self-generated fixture; no national data admitted"))
    dump(folder/"config.json",dict(schema_version=1,mode="synthetic_engineering",base_sha="804ec15ee43874303986a7ad91b2cde05c65b124",
        owner="p2/lb",warning="All values are synthetic. Calibration to own generated series proves plumbing only, NOT empirical validity.",
        inputs=inputs,gaps=[],scientific_acceptance=False))
    print("Generated explicit engineering fixture, not national observations")


if __name__ == "__main__":
    main()
