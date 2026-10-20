"""Explicit inherited recovery/storage assets for a national scope migration.

This adapter does not invent a national Other split. Inputs are declared scenario
assumptions or reviewed observations. Only inherited, paid assets are supported;
no automatic annual additions and no post-initial observations enter operations.
Unresolved statistical differences are reported separately, never generators.
"""
from copy import deepcopy
from math import fsum

from .q2_operations import Q2Error, number


class InheritedOperatingBoundary:
    def __init__(self, *, initial_year, stores, recovery_plants, recoveries,
                 initial_pumping_mwh, initial_statistical_adjustment_mwh,
                 initial_pumped_generation_mwh, capacity_history, evidence):
        if type(initial_year) is not int or not isinstance(evidence,str) or not evidence.strip():
            raise ValueError("Boundary needs initial year and explicit source/assumptions")
        self.initial_year=initial_year
        self.evidence=evidence
        self.stores=deepcopy(stores)
        self.plants=deepcopy(recovery_plants)
        self.recoveries=deepcopy(recoveries)
        self.capacity_history=deepcopy(capacity_history)
        self.initial_pumping_mwh=number(initial_pumping_mwh,"Initial pumping input")
        self.initial_pumped_generation_mwh=number(initial_pumped_generation_mwh,"Initial pumped output")
        if self.initial_pumped_generation_mwh>self.initial_pumping_mwh:
            raise ValueError("Initial cyclic pumping output exceeds charging input")
        self.initial_statistical_adjustment_mwh=number(initial_statistical_adjustment_mwh,
            "Initial statistical adjustment",-float("inf"))
        self.stock={}
        self.retirement_loss=0.0
        carriers={r["output"] for r in self.recoveries.values()}
        for kind,items in (("store",self.stores),("recovery plant",self.plants)):
            for name,p in items.items():
                if (not isinstance(name,str) or not name or name=="main"
                        or type(p["exit_year"]) is not int or p["exit_year"]<=initial_year):
                    raise ValueError("Invalid inherited asset name or exit year")
                number(p["fixed_om_cny_per_year"],name+" fixed OM")
                number(p["initial_book_value_cny"],name+" inherited book value")
                if kind=="store":
                    spec=p["operation"]
                    self.stock[name]=number(spec["initial_mwh"],name+" opening",0,spec["energy_mwh"])
                else:
                    spec=p["operation"]
                    if spec["input"] not in carriers or spec["output"]!="electricity":
                        raise ValueError("Supplementary plant must consume declared recovered energy")
                    number(p["energy_tariff_real_cny_per_gross_mwh"],name+" energy tariff")
                    number(p["initial_generation_mwh"],name+" initial output",0,spec["capacity_mw"]*8760)

    def capacities(self,year,techs):
        if year>self.initial_year:
            raise ValueError("Post-initial capacity observations cannot enter physical state")
        try:values=self.capacity_history[year]
        except KeyError as exc:raise ValueError(f"Missing explicit capacity reconstruction for {year}") from exc
        if set(values)!=set(techs):
            raise ValueError("Capacity reconstruction must cover exactly the model's primary technologies")
        return {t:number(v,f"capacity/{year}/{t}",1e-9) for t,v in values.items()}

    def check_initial(self,model):
        generated=fsum(model.initial_generation.values())+fsum(p["initial_generation_mwh"] for p in self.plants.values())
        total=generated+self.initial_pumped_generation_mwh+self.initial_statistical_adjustment_mwh
        observed=model.data[model.initial_year,"electricity_generation_mwh"]
        if abs(total-observed)>max(1,abs(observed)*1e-10):
            raise ValueError("Initial gross generation components do not close to declared total")
        capacity=fsum(model.initial_capacities.values())+fsum(p["operation"]["capacity_mw"] for p in self.plants.values())
        capacity+=fsum(p["operation"]["power_mw"] for p in self.stores.values())
        if abs(capacity-model.data[model.initial_year,"total_capacity_mw"])>1:
            raise ValueError("Initial capacity overlaps or leaves an undeclared remainder")

    def initial_own_use(self):
        return fsum(p["initial_generation_mwh"]*p["operation"].get("auxiliary_use_fraction",0)
                    for p in self.plants.values())

    def apply(self,op,year,*,planning=False):
        """Inherit stores and retire by declared lifetime; never refill their SOC."""
        if not planning:
            self.retirement_loss=fsum(self.stock[k] for k,p in self.stores.items() if p["exit_year"]==year)
        op["additional_storage"]={}
        for name,p in self.stores.items():
            spec=deepcopy(p["operation"])
            if year>=p["exit_year"]:
                spec.update(power_mw=0,energy_mwh=0,initial_mwh=0)
                if not planning:self.stock[name]=0.0
            else:
                spec["initial_mwh"]=self.stock[name]
            op["additional_storage"][name]=spec
        carriers={r["output"] for r in self.recoveries.values()}
        for carrier in carriers:
            if carrier in op["fuels"]:
                raise Q2Error("invalid_input","Recovered carrier collides with primary supply")
            op["fuels"][carrier]=dict(domestic_mw=[0]*len(op["periods"]),import_mw=[0]*len(op["periods"]),
                domestic_cost_per_mwh=0,import_cost_per_mwh=0,emission_t_per_mwh=0,
                tank_mwh=0,initial_mwh=0,injection_mw=0,withdrawal_mw=0,internal_recovered_carrier=True)
        for name,p in self.plants.items():
            if name in op["plants"]:
                raise Q2Error("invalid_input","Supplementary plant collides with primary generator")
            spec=deepcopy(p["operation"])
            if year>=p["exit_year"]:
                spec.update(capacity_mw=0,window_energy_budget_mwh=0,ramp_mw_per_hour=0)
            op["plants"][name]=spec
        op["recoveries"]=deepcopy(self.recoveries)
        return op

    def refresh_planning(self,op,year):
        # Replace the inherited adapter part rather than duplicating recovery
        # supply or retaining an asset already retired at the forecast date.
        for carrier in {r["output"] for r in self.recoveries.values()}:
            op["fuels"].pop(carrier,None)
        for name in self.plants:op["plants"].pop(name,None)
        return self.apply(op,year,planning=True)

    def settle(self,model,op,result):
        weight=op["annual_repeats"]
        recovery_output=fsum(r["output_mwh"]*weight for r in result["generation"] if r["plant"] in self.plants)
        recovery_revenue=fsum(r["output_mwh"]*weight*self.plants[r["plant"]]["energy_tariff_real_cny_per_gross_mwh"]
                              for r in result["generation"] if r["plant"] in self.plants)
        plant_variable=fsum(r["output_mwh"]*weight*op["plants"][r["plant"]]["variable_cost_per_mwh"]
                            for r in result["generation"] if r["plant"] in self.plants)
        plant_fixed=fsum(p["fixed_om_cny_per_year"] for p in self.plants.values() if model.year<p["exit_year"])
        store_fixed=fsum(p["fixed_om_cny_per_year"] for p in self.stores.values() if model.year<p["exit_year"])
        store_variable=fsum((r["charge_mwh"]+r["discharge_mwh"])*weight*
            op["additional_storage"][r["store"]]["throughput_cost"] for r in result["additional_storage"])
        # Recovery fuel is a paid upstream loss-stream internal transfer at zero
        # incremental commodity price. Its converter still has real OM costs.
        model.finance.append(dict(year=model.year,kind="inherited_recovery_operation",actor="recovery_assets",
            revenue_cny=recovery_revenue,cash_delta_cny=recovery_revenue-plant_variable-plant_fixed,
            resource_cost_cny=plant_variable+plant_fixed,evidence=self.evidence))
        for r in result["additional_storage"]:
            self.stock[r["store"]]=r["closing_mwh"]
        return dict(recovery_generation_mwh=recovery_output,recovery_payments_cny=recovery_revenue,
            supplementary_fixed_om_cny=plant_fixed+store_fixed,
            extra_storage_cost_cny=store_variable+store_fixed,
            pumped_charge_mwh=fsum(r["charge_mwh"]*weight for r in result["additional_storage"]),
            pumped_generation_mwh=fsum(r["discharge_mwh"]*weight for r in result["additional_storage"]),
            pumped_loss_mwh=fsum((r["charging_loss_mwh"]+r["discharging_loss_mwh"])*weight for r in result["additional_storage"]),
            supplementary_storage_retirement_loss_mwh=self.retirement_loss,
            pumped_capacity_mw=fsum(p["operation"]["power_mw"] for p in self.stores.values() if model.year<p["exit_year"]),
            supplementary_capacity_mw=fsum(p["operation"]["capacity_mw"] for p in self.plants.values() if model.year<p["exit_year"])+
                fsum(p["operation"]["power_mw"] for p in self.stores.values() if model.year<p["exit_year"]))
