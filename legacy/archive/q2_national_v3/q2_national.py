"""Source-initialised national aggregate experiment, with explicit reconstructions.

This is a conditional research model, not a plant census or an official forecast.
It reuses the independently tested chronological LP but has its own asset/device
cohorts, finance envelopes, output-based allowance accounting and statistical
bridges. Observations after initial_year never enter endogenous physical state.
"""
from copy import deepcopy
from math import exp, sqrt, log

from mesa import Agent, Model

from .q2_operations import Q2Error, operate

TCE_MWH = 29.3076 / 3.6
FUELS = ("coal", "oil", "gas")
TECHS = ("coal", "gas", "oil", "biomass", "hydro", "nuclear", "wind", "solar")
EF = dict(coal=.34056, oil=.26388, gas=.20196, biomass=0.0)  # IPCC NCV defaults t/MWh
LIFE = dict(coal=40, gas=30, oil=30, biomass=25, hydro=80, nuclear=60, wind=25, solar=25)
LEAD = dict(coal=4, gas=3, oil=2, biomass=4, hydro=5, nuclear=7, wind=1, solar=1)


def operate_national(operation):
    """Condition large national LPs in GWh/GW; restore ALL public results to MWh.

    This is a uniform numerical change of variables, not an energy conversion.
    Prices/efficiencies and time are unchanged. Cost and objective values scale
    back with energy. It avoids false infeasibility of tightly frozen shortage
    optima at national magnitudes. Existing small-unit engineering LP unchanged.
    """
    scale = 1000.0
    def scaled(obj):
        result = {}
        for k,v in obj.items():
            if isinstance(v,dict):
                result[k] = scaled(v)
            elif (k.endswith(("_mwh","_mw")) and "_per_" not in k) or k == "ramp_mw_per_hour":
                result[k] = [x/scale for x in v] if isinstance(v,list) else v/scale
            else:
                result[k] = deepcopy(v)
        return result
    result = operate(scaled(operation))
    for key in ("resource_cost","max_residual"):
        result[key] *= scale
    for group in ("fuel","generation","demand","storage","balances","stages"):
        for row in result[group]:
            for key,value in list(row.items()):
                if key.endswith("_mwh") or key in {"combustion_co2_t","residual","objective","max_residual"}:
                    row[key] = value*scale
    return result


def observations(rows):
    data = {(int(r["year"]),r["metric"]):float(r["value"]) for r in rows}
    if len(data) != len(rows):
        raise Q2Error("invalid_input", "Duplicate national observation")
    for y in range(2009,2025):
        data[y,"wind_plus_solar_capacity_mw"] = data[y,"wind_capacity_mw"]+data[y,"solar_capacity_mw"]
    return data


def get(data, year, metric):
    try:
        return data[year,metric]
    except KeyError as exc:
        raise Q2Error("missing_input", f"Missing {year} {metric}; never imputed zero") from exc


class NationalActor(Agent):
    def __init__(self, model, name):
        super().__init__(model)
        self.name = name
        self.cash = 0.0

    def log(self, kind, **kw):
        self.model.behavior.append(dict(year=self.model.year,actor=self.name,kind=kind,**kw))


class NationalSupplier(NationalActor):
    def __init__(self, model, name, annual, price):
        super().__init__(model,name)
        self.annual, self.price = annual,price
        self.utilisation = .7

    def offer(self):
        m,a = self.model,self.model.a
        # Finite delivery envelope follows an explicit exogenous development path.
        # The headroom converts an annual average into a RESEARCH peak bound.
        growth = (1+a["fuel_supply_annual_growth"])**(m.year-m.initial_year)
        power = self.annual/8760*growth*a["fuel_supply_headroom"]
        imported = a["fuel_import_fraction"][self.name]
        tank = self.annual/365*a["fuel_inventory_days"]
        self.log("offer",price_cny_per_mwh=self.price,domestic_mw=power*(1-imported),
                 import_mw=power*imported,lagged_utilisation=self.utilisation)
        return dict(domestic_mw=[power*(1-imported)]*4,import_mw=[power*imported]*4,
            domestic_cost_per_mwh=self.price,import_cost_per_mwh=self.price*1.05,
            tank_mwh=tank,initial_mwh=tank*a["fuel_inventory_initial_fraction"],
            injection_mw=power*.2,withdrawal_mw=power*.2,emission_t_per_mwh=EF[self.name])


class NationalGenerator(NationalActor):
    def __init__(self, model, name, capacity, cf, capex, om):
        super().__init__(model,name)
        self.initial_capacity, self.reference_cf = capacity,cf
        self.capex_2024,self.om = capex,om
        self.margin = cf*8760*(model.tariff(name)-om)
        if name == "wind":
            self.margin -= 29*model.fx*1000
        elif name in {"solar","hydro"}:
            self.margin -= .015*capex
        if name in FUELS:
            self.margin -= cf*8760*model.suppliers[name].price/model.efficiency[name]
        if name == "biomass":
            self.margin -= cf*8760*model.suppliers[name].price/.3
        self.cash = capacity*capex*.1

    @property
    def capacity(self):
        return sum(c["capacity_mw"] for c in self.model.cohorts if c["tech"] == self.name and c["status"] == "active")

    def proposal(self, realised_margin):
        m,a = self.model,self.model.a
        self.margin = (1-m.theta["expectation_rate"])*self.margin + m.theta["expectation_rate"]*realised_margin
        r,life,lead = a["discount_rate"],LIFE[self.name],LEAD[self.name]
        capex = m.capex(self.name)
        annuity = (1-(1+r)**(-life))/r
        pv_cost = sum(capex/lead/(1+r)**t for t in range(lead))
        npv = self.margin*annuity/(1+r)**(lead-1)-pv_cost
        # Construction capability is a bounded adjustment of lagged/current scale.
        limit = max(m.initial_additions[self.name],self.capacity*(.35 if self.name in {"wind","solar"} else .025))
        amount = limit*m.theta["investment_response"] if npv > 0 and m.investment else 0
        if self.name == "wind":
            amount *= m.theta["renewable_mix_response"]
        elif self.name == "solar":
            amount *= 2-m.theta["renewable_mix_response"]
        self.log("investment_proposal",npv_cny_per_mw=npv,expected_margin_cny_per_mw=self.margin,
                 capacity_mw=self.capacity,requested_mw=amount,capex_cny_per_mw=capex)
        return dict(actor=self.name,tech=self.name,amount=amount,capex=capex,lead=lead,life=life)


class NationalConsumer(NationalActor):
    """Carrier-specific service proxy; replacement affects only next-year stock."""
    def __init__(self, model, fuel, service):
        super().__init__(model,model.a["demand_fuel_archetypes"][fuel])
        self.fuel, self.base_service = fuel,service
        self.cohorts = [dict(carrier=fuel,capacity=service/8760/.6/model.a["device_lifetime_years"],
            online=model.initial_year-i,exit=model.initial_year+model.a["device_lifetime_years"]-i,status="active")
            for i in range(model.a["device_lifetime_years"])]
        self.queue = []

    def prepare(self):
        m = self.model
        self.retired = 0.0
        for c in self.cohorts:
            if c["status"] == "active" and c["exit"] <= m.year:
                self.retired += c["capacity"]
                c["status"] = "retired"
        for c in self.queue:
            if c["online"] == m.year:
                self.cohorts.append({**c,"status":"active"})

    def demand(self):
        m,a = self.model,self.model.a
        requested = self.base_service*m.activity_factor()
        amounts = {c:sum(p["capacity"] for p in self.cohorts if p["status"] == "active" and p["carrier"] == c)
                   for c in (self.fuel,"electricity")}
        total = sum(amounts.values())
        # Unreplaced capacity loss must remain unmet service, not disappear.
        self.requested = requested
        rows = {}
        for carrier, cap in amounts.items():
            efficiency = a["direct_fuel_efficiency"][self.fuel] if carrier == self.fuel else a["electric_service_efficiency"][self.fuel]
            fraction = cap/total if total else (1 if carrier == self.fuel else 0)
            rows[self.name+"/"+carrier] = dict(sector=self.name,carrier=carrier,efficiency=efficiency,
                input_capacity_mw=cap/efficiency,priority=0,
                service_mwh=[requested*f/365*fraction for f in a["load_shape"]])
        return rows

    def proposal(self):
        m,a = self.model,self.model.a
        total = sum(c["capacity"] for c in self.cohorts if c["status"] == "active")
        retiring_next = sum(c["capacity"] for c in self.cohorts if c["status"] == "active" and c["exit"] == m.year+1)
        next_service = self.requested*(1+m.current_growth)**m.theta["activity_elasticity"]*(1-a["service_intensity_decline"])
        required = max(0,next_service/8760/.6-(total-retiring_next))
        fossil_unit = m.suppliers[self.fuel].price/a["direct_fuel_efficiency"][self.fuel]
        electric_unit = a["retail_price_cny_per_mwh"]/a["electric_service_efficiency"][self.fuel]
        annualized_device = a["device_capex_cny_per_service_mw"]/8760/.6/a["device_lifetime_years"]
        # Only eligible renewal and expansion; never instant switching of old devices.
        share = m.theta["replacement_adoption"] if electric_unit+annualized_device < fossil_unit+annualized_device and m.substitution else 0
        self.log("device_proposal",eligible_mw=required,retiring_next_mw=retiring_next,
                 electric_fraction=share,fossil_service_cost=fossil_unit,electric_service_cost=electric_unit)
        return dict(actor=self.name,amount=required,electric_fraction=share,capex=a["device_capex_cny_per_service_mw"])


class NationalGovernment(NationalActor):
    def approve(self, generation, devices):
        m,a = self.model,self.model.a
        # Full commitments reserved against this year's financing authorisation.
        # Money is explicitly injected from aggregate savers; not government tax revenue.
        total = sum(p["amount"]*p["capex"] for p in generation)
        budget = m.gdp_cny*a["investment_budget_gdp_fraction"]
        ratio = min(1,budget/total) if total else 1
        for p in generation:
            amount = p["amount"]*ratio
            if amount <= 0:
                continue
            cost = amount*p["capex"]
            project = dict(id=f"{m.year}/{p['tech']}/{len(m.projects)}",tech=p["tech"],capacity_mw=amount,
                decision_year=m.year,online_year=m.year+p["lead"],exit_year=m.year+p["lead"]+p["life"],
                cost=cost,instalment=cost/p["lead"],remaining=cost,status="construction",initial_reconstruction=False)
            m.projects.append(project)
            m.finance.append(dict(year=m.year,kind="financing_commitment",actor=p["tech"],amount_cny=cost,
                                  resource_cost_cny=0,project=project["id"]))
            self.log("approval",project=project["id"],approved_mw=amount,online_year=project["online_year"],common_budget_ratio=ratio)
        requested = sum(p["amount"]*p["capex"] for p in devices)
        device_budget = m.gdp_cny*a["device_budget_gdp_fraction"]
        fraction = min(1,device_budget/requested) if requested else 1
        for p in devices:
            consumer = m.consumer_by_name[p["actor"]]
            amount = p["amount"]*fraction if m.investment else 0
            for carrier,part in ((consumer.fuel,1-p["electric_fraction"]),("electricity",p["electric_fraction"])):
                if amount*part:
                    consumer.queue.append(dict(carrier=carrier,capacity=amount*part,online=m.year+1,
                        exit=m.year+1+a["device_lifetime_years"]))
            m.construction_cost += amount*p["capex"]
            m.finance.append(dict(year=m.year,kind="device_finance_and_construction",actor=consumer.name,
                amount_cny=amount*p["capex"],resource_cost_cny=amount*p["capex"]))


class NationalGrid(NationalActor):
    def capacity(self):
        m = self.model
        live = [c for c in m.storage_cohorts if c["online"] <= m.year < c["exit"]]
        return sum(c["power"] for c in live),sum(c["energy"] for c in live)

    def propose(self, output, curtailed):
        m,a = self.model,self.model.a
        power,energy = self.capacity()
        # A regulated grid proposal, capped by both construction capability and cash envelope.
        desired = .10*(m.generators["wind"].capacity+m.generators["solar"].capacity)
        next_retire = sum(c["power"] for c in m.storage_cohorts if c["exit"] == m.year+1)
        request = min(max(0,desired-power+next_retire),max(2000,.03*desired)) if m.investment else 0
        budget = .001*m.gdp_cny
        amount = min(request,budget/(a["storage_duration_hours"]*a["storage_capex_cny_per_mwh"]))
        m.storage_cohorts.append(dict(power=amount,energy=amount*a["storage_duration_hours"],online=m.year+1,
            exit=m.year+1+a["storage_lifetime_years"]))
        cost = amount*a["storage_duration_hours"]*a["storage_capex_cny_per_mwh"]
        m.construction_cost += cost
        m.finance.append(dict(year=m.year,kind="storage_finance_and_construction",actor="grid",amount_cny=cost,resource_cost_cny=cost))
        self.log("storage_proposal",power_mw=amount,previous_curtailment_mwh=curtailed,
                 rule="10pct wind+solar nameplate connection proxy; finite 0.1pctGDP financing")


class NationalModel(Model):
    def __init__(self, data, design, theta, initial_year, *, variant=None, investment=True, substitution=True, detail=True):
        super().__init__(seed=design["seed"])
        self.data,self.design,self.theta = data,deepcopy(design),dict(theta)
        self.a = self.design["assumptions"]
        self.variant = {k:float(v) for k,v in (variant or {}).items()}
        self.initial_year,self.year = initial_year,initial_year+1
        self.investment,self.substitution,self.detail = investment,substitution,detail
        self.paths,self.behavior,self.finance,self.assets,self.operations,self.balances,self.stages = [],[],[],[],[],[],[]
        self.cohorts,self.projects,self.storage_cohorts = [],[],[]
        self.construction_cost = 0
        self.gdp0 = get(data,initial_year,"real_gdp")
        self.gdp = self.gdp0
        self.efficiency = dict(coal=.41,gas=.52,oil=.38,biomass=.30)
        self.cost_conversion = 6.62*get(data,2024,"cpi")/get(data,2018,"cpi")
        self.fx = get(data,2024,"cny_per_usd")
        total_primary = get(data,initial_year,"consumption_10ktce")*1e4*TCE_MWH
        fuel_energy = {f:total_primary*get(data,initial_year,"consumption_"+f+"_pct")/100 for f in FUELS}
        fuel_energy["biomass"] = get(data,initial_year,"biofuel_electricity_mwh")/.3*1.10
        prices = dict(coal=88*self.cost_conversion/(6000*4.1868/3600),
                      gas=9.1*self.cost_conversion/.293071,oil=self.a["oil_cost_cny_per_mwh"],biomass=self.a["biomass_cost_cny_per_mwh"])
        self.suppliers = {f:NationalSupplier(self,f,e,prices[f]*self.variant.get("fuel_price_multiplier",1)) for f,e in fuel_energy.items()}
        self.initial_generation = {t:get(data,initial_year,("biofuel" if t == "biomass" else t)+"_electricity_mwh") for t in TECHS}
        self.initial_capacities = self.capacity_split(initial_year)
        self.initial_additions = {t:max(0,(self.initial_capacities[t]-self.capacity_split(initial_year-3)[t])/3) for t in TECHS}
        self.generators = {}
        capex = dict(coal=800*self.cost_conversion*1000,gas=560*self.cost_conversion*1000,
            nuclear=2500*self.cost_conversion*1000,wind=856*self.fx*1000,solar=591*self.fx*1000,
            hydro=self.a["hydro_capex_cny_per_kw"]*1000,oil=self.a["oil_capex_cny_per_kw"]*1000,
            biomass=self.a["biomass_capex_cny_per_kw"]*1000)
        om = dict(coal=14.97*self.cost_conversion,gas=13.49*self.cost_conversion,
            nuclear=(26.42+10)*self.cost_conversion,wind=0,solar=0,hydro=10,oil=100,biomass=100)
        for t in TECHS:
            cf = min(.9,self.initial_generation[t]/(self.initial_capacities[t]*8760))
            self.generators[t] = NationalGenerator(self,t,self.initial_capacities[t],cf,capex[t],om[t])
        self.build_initial_cohorts()
        # Only initial snapshots are used to reconstruct terminal and non-energy inputs.
        self.feedstock = {f:fuel_energy[f]*self.a["nonenergy_fuel_fraction"][f]*self.variant.get("nonenergy_multiplier",1) for f in FUELS}
        self.consumers = {}
        for f in FUELS:
            terminal = fuel_energy[f]-self.initial_generation[f]/self.efficiency[f]-self.feedstock[f]
            if terminal <= 0:
                raise Q2Error("invalid_initial_state",f"Negative residual terminal {f}")
            self.consumers[f] = NationalConsumer(self,f,terminal*self.a["direct_fuel_efficiency"][f])
        self.consumer_by_name = {a.name:a for a in self.consumers.values()}
        self.base_electric = get(data,initial_year,"electricity_generation_mwh")*self.a["grid_efficiency"]
        self.base_export = max(0,-get(data,initial_year,"net_elec_imports_mwh"))
        self.base_electric -= self.base_export
        # Estimate this structural elasticity strictly from pre-training 2005-2014.
        # Direct-fuel service elasticity remains a separately calibrated parameter.
        x = [log(get(data,y,"real_gdp")/get(data,2005,"real_gdp")) for y in range(2005,2015)]
        z = [log(get(data,y,"electricity_generation_mwh")/get(data,2005,"electricity_generation_mwh"))
             -(y-2005)*log(1-self.a["service_intensity_decline"]) for y in range(2005,2015)]
        self.electric_elasticity = sum(a*b for a,b in zip(x,z))/sum(a*a for a in x)
        self.government,self.grid = NationalGovernment(self,"government"),NationalGrid(self,"grid")
        peo = total_primary*get(data,initial_year,"consumption_primary_electricity_other_pct")/100
        clean_generation = sum(self.initial_generation[t] for t in ("hydro","nuclear","wind","solar","biomass"))
        self.peo_coefficient = peo/clean_generation
        storage_power = self.a["new_storage_2024_power_mw"] if initial_year == 2024 else self.a["new_storage_2014_power_mw"]
        storage_energy = self.a["new_storage_2024_energy_mwh"] if initial_year == 2024 else 0
        for age in range(self.a["storage_lifetime_years"]):
            self.storage_cohorts.append(dict(power=storage_power/self.a["storage_lifetime_years"],
                energy=storage_energy/self.a["storage_lifetime_years"],online=initial_year-age,
                exit=initial_year+self.a["storage_lifetime_years"]-age))

    def capacity_split(self, year):
        d = self.data
        # No post-initial observations: thermal subtypes allocated using that year's generation and explicit duty factors.
        factors = dict(coal=.55,gas=.4,oil=.2,biomass=.6)
        raw = {t:get(d,year,("biofuel" if t == "biomass" else t)+"_electricity_mwh")/(8760*factors[t]) for t in factors}
        thermal = get(d,year,"thermal_capacity_mw")
        result = {t:v/sum(raw.values())*thermal for t,v in raw.items()}
        result.update({t:get(d,year,t+"_capacity_mw") for t in ("hydro","nuclear","wind","solar")})
        return result

    def build_initial_cohorts(self):
        first = self.capacity_split(2009)
        for t in TECHS:
            # Residual lifetime distribution at 2009; later losses are explicit reconstructions.
            for age in range(LIFE[t]):
                self.cohorts.append(dict(id=f"initial/{t}/{age}",tech=t,capacity_mw=first[t]/LIFE[t],
                    online_year=2009-age,exit_year=2009+LIFE[t]-age,status="active",reconstruction=True))
            previous = first[t]
            for year in range(2010,self.initial_year+1):
                value = self.capacity_split(year)[t]
                additions = max(0,value-previous)
                self.cohorts.append(dict(id=f"initial/{t}/{year}",tech=t,capacity_mw=additions,
                    online_year=year,exit_year=year+LIFE[t],status="active",reconstruction=True))
                previous = value
            alive = [c for c in self.cohorts if c["tech"] == t and c["exit_year"] > self.initial_year]
            for c in self.cohorts:
                if c["tech"] == t and c["exit_year"] <= self.initial_year:
                    c["status"] = "retired"
            # Snapshot must be matched exactly, despite unknown gross retirements.
            ratio = self.initial_capacities[t]/sum(c["capacity_mw"] for c in alive)
            for c in alive:
                c["capacity_mw"] *= ratio
            for k in range(1,LEAD[t]+1):
                amount = self.initial_additions[t]
                cost = amount*self.generators[t].capex_2024
                self.projects.append(dict(id=f"pipeline/{t}/{k}",tech=t,capacity_mw=amount,
                    decision_year=self.initial_year+k-LEAD[t],online_year=self.initial_year+k,
                    exit_year=self.initial_year+k+LIFE[t],cost=cost,instalment=cost/LEAD[t],
                    remaining=cost*(k-1)/LEAD[t],status="construction",initial_reconstruction=True))

    def activity_factor(self):
        return (self.gdp/self.gdp0)**self.theta["activity_elasticity"]*(1-self.a["service_intensity_decline"])**(self.year-self.initial_year)

    def capex(self, tech):
        cost = self.generators[tech].capex_2024*self.variant.get("capex_multiplier",1)
        if tech in {"wind","solar"}:
            rate = self.a["wind_solar_cost_decline"]+self.variant.get("cost_decline_delta",0)
            factor = ((1-self.a["historical_wind_solar_real_cost_decline"])**(self.year-2024) if self.year <= 2024
                      else max(self.a["cost_floor_fraction_of_2024"],(1-rate)**(self.year-2024)))
            cost *= factor
        return cost

    def tariff(self, tech):
        price = self.a["generation_price_cny_per_mwh"]
        if tech in {"wind","solar"} and self.year < 2021:
            start = self.a["renewable_tariff_2014_proxy"][tech]*self.variant.get("historical_tariff_multiplier",1)
            price += (start-price)*(2021-self.year)/7
        return price

    def drivers(self):
        previous = self.gdp
        if self.year <= 2024:
            self.gdp = get(self.data,self.year,"real_gdp")
        else:
            decade = "2025_2030" if self.year <= 2030 else "2031_2040" if self.year <= 2040 else "2041_2050" if self.year <= 2050 else "2051_2060"
            growth = self.a["gdp_future"][decade]+self.variant.get("gdp_growth_delta",0)
            self.gdp *= 1+growth
        self.current_growth = self.gdp/previous-1
        self.gdp_cny = self.gdp/get(self.data,2024,"real_gdp")*self.a["gdp_2024_price_level_cny"]
        if self.year < 2021:
            self.carbon = 0
        elif self.year < 2024:
            self.carbon = self.a["historical_carbon_price_proxy_cny"]
        else:
            self.carbon = self.a["carbon_2024_cny_per_t"]*(1+self.a["carbon_future_real_growth"])**(self.year-2024)
        self.carbon *= self.variant.get("carbon_price_multiplier",1)

    def mature(self):
        for p in self.projects:
            if p["status"] == "construction" and p["online_year"] == self.year:
                if p["remaining"] > .01:
                    raise Q2Error("accounting_failure","Unpaid project commissioning")
                p["status"] = "commissioned"
                self.cohorts.append(dict(id=p["id"],tech=p["tech"],capacity_mw=p["capacity_mw"],
                    online_year=p["online_year"],exit_year=p["exit_year"],status="active",reconstruction=p["initial_reconstruction"]))
        for c in self.cohorts:
            if c["exit_year"] <= self.year:
                c["status"] = "retired"
        for consumer in self.consumers.values():
            consumer.prepare()

    def make_operation(self):
        a = self.a
        op = dict(periods=[dict(hours=h) for h in a["operation_period_hours"]],annual_repeats=365,cyclic=True,
            fuels={f:s.offer() for f,s in self.suppliers.items()},plants={},demands={},
            grid=dict(efficiency=a["grid_efficiency"],power_mw=sum(g.capacity for g in self.generators.values())),storage={})
        power,energy = self.grid.capacity()
        op["storage"] = dict(power_mw=power,energy_mwh=energy,initial_mwh=energy*a["storage_initial_fraction"],
            charge_efficiency=sqrt(a["storage_roundtrip_efficiency"]),discharge_efficiency=sqrt(a["storage_roundtrip_efficiency"]),throughput_cost=1)
        for t,g in self.generators.items():
            fuel = t if t in self.suppliers else None
            availability = [(.85 if fuel else g.reference_cf)]*4
            if t in {"wind","solar"}:
                availability = [min(1,g.reference_cf*v*self.variant.get("renewable_availability_multiplier",1)) for v in a[t+"_shape"]]
            budget = g.capacity*24*(g.reference_cf if t in {"hydro","nuclear","biomass"} else 1)
            op["plants"][t] = dict(input=fuel,output="electricity",efficiency=self.efficiency.get(t,1),
                capacity_mw=g.capacity,availability=availability,variable_cost_per_mwh=g.om,
                minimum_fraction=0,ramp_mw_per_hour=g.capacity*.2,window_energy_budget_mwh=budget)
        for c in self.consumers.values():
            op["demands"].update(c.demand())
        # Non-energy material inputs do not emit in the combustion ledger.
        for f,value in self.feedstock.items():
            demand = value*self.activity_factor()
            op["demands"]["feedstock/"+f] = dict(sector="nonenergy_feedstock",carrier=f,efficiency=1,
                input_capacity_mw=demand/8760*2,priority=0,service_mwh=[demand/365/4]*4)
        electric = self.base_electric*(self.gdp/self.gdp0)**self.electric_elasticity*(1-a["service_intensity_decline"])**(self.year-self.initial_year)
        op["demands"]["existing_electric_services"] = dict(sector="existing_electric_services",carrier="electricity",efficiency=1,
            input_capacity_mw=electric/8760*2,priority=0,service_mwh=[electric/365*f for f in a["load_shape"]])
        op["demands"]["exports"] = dict(sector="electricity_exports",carrier="electricity",efficiency=1,
            input_capacity_mw=self.base_export/8760*2,priority=0,service_mwh=[self.base_export/365/4]*4)
        return op

    def settle(self, op, result):
        a = self.a
        outputs = {t:sum(r["output_mwh"] for r in result["generation"] if r["plant"] == t)*365 for t in TECHS}
        fuel_use = {f:sum(r["direct_mwh"]+r["conversion_mwh"] for r in result["fuel"] if r["fuel"] == f)*365 for f in self.suppliers}
        materials = {f:sum(r["input_mwh"] for r in result["demand"] if r["sector"] == "nonenergy_feedstock" and r["carrier"] == f)*365 for f in FUELS}
        combustion = sum((fuel_use[f]-materials[f])*EF[f] for f in FUELS)
        peo = sum(outputs[t] for t in ("hydro","nuclear","wind","solar","biomass"))*self.peo_coefficient*self.variant.get("primary_bridge_multiplier",1)
        # Bioenergy is included in the initial PEO bridge; never add its fuel again.
        primary_mwh = sum(fuel_use[f] for f in FUELS)+peo
        ets_total,net_transfers,resource = 0.0,0.0,result["resource_cost"]
        margins = {}
        for t,g in self.generators.items():
            revenue = outputs[t]*self.tariff(t)
            fuel_bill = outputs[t]/self.efficiency[t]*self.suppliers[t].price if t in self.suppliers else 0
            fixed = g.capacity*(29*self.fx*1000 if t == "wind" else .015*g.capex_2024 if t in {"solar","hydro"} else 0)
            emissions = outputs[t]/self.efficiency[t]*EF[t] if t in self.suppliers else 0
            benchmark = (a["ets_2026_benchmarks"] if self.year >= 2026 else a["ets_2021_2025_proxy"]).get(t)
            allowance = outputs[t]*benchmark if benchmark is not None and self.year >= 2021 else 0
            net_allowances = emissions-allowance if benchmark is not None and self.year >= 2021 else 0
            payment = self.carbon*net_allowances
            ets_total += payment
            delta = revenue-fuel_bill-outputs[t]*g.om-fixed-payment
            g.cash += delta
            margins[t] = delta/g.capacity if g.capacity else 0
            resource += fixed
            self.finance.append(dict(year=self.year,kind="generator_operation",actor=t,revenue_cny=revenue,fuel_bill_cny=fuel_bill,
                om_cny=outputs[t]*g.om+fixed,free_allowances_t=allowance,covered_emissions_t=emissions if benchmark is not None and self.year >= 2021 else 0,
                net_allowances_t=net_allowances,ets_transfer_cny=-payment,cash_delta_cny=delta,cumulative_operating_cash_cny=g.cash,
                resource_cost_cny=outputs[t]*g.om+fixed))
        # Counterparty transfer, NOT a carbon tax or public fiscal revenue.
        self.finance.append(dict(year=self.year,kind="ETS_clearing_counterparty",actor="allowance_market",ets_transfer_cny=ets_total,
            amount_cny=ets_total,resource_cost_cny=0,public_tax_revenue_cny=0))
        net_transfers = sum(r.get("ets_transfer_cny",0) for r in self.finance if r["year"] == self.year)
        if abs(net_transfers) > .001:
            raise Q2Error("accounting_failure","Unbalanced ETS transfers")
        for f,s in self.suppliers.items():
            supply = sum((op["fuels"][f]["domestic_mw"][i]+op["fuels"][f]["import_mw"][i])*6 for i in range(4))*365
            s.utilisation = fuel_use[f]/supply if supply else 0
        # Bridge is a separate same-CO2 accounting scenario, never GCB plus BTR.
        # Historical process values are not injected into decisions or calibration.
        activity = (self.gdp/get(self.data,2021,"real_gdp"))**a["process_activity_elasticity"]
        process = (get(self.data,2021,"btr_process_co2_t")+get(self.data,2021,"btr_waste_co2_t"))*activity
        process *= (1-a["process_decline_per_year"])**(self.year-2021)*self.variant.get("process_multiplier",1)
        removal = get(self.data,2021,"btr_removals_co2_t")*(1+a["removals_annual_growth"])**(self.year-2021)*self.variant.get("removals_multiplier",1)
        positive = combustion+process
        row = dict(year=self.year,gdp_index=self.gdp/get(self.data,2024,"real_gdp"),primary_energy_tce=primary_mwh/TCE_MWH,
            peo_share=peo/primary_mwh,nonfossil_share_proxy=peo/primary_mwh,combustion_co2_t=combustion,
            other_positive_co2_t=process,positive_co2_t=positive,net_removals_t=removal,net_co2_t=positive-removal,
            neutralisation_ratio=removal/positive,energy_intensity=primary_mwh/TCE_MWH/(self.gdp/get(self.data,2024,"real_gdp")),
            carbon_intensity=positive/(self.gdp/get(self.data,2024,"real_gdp")),
            total_capacity_mw=sum(g.capacity for g in self.generators.values()),
            wind_solar_capacity_mw=self.generators["wind"].capacity+self.generators["solar"].capacity,
            electricity_generation_mwh=sum(outputs.values()),unmet_service_mwh=sum(r["unmet_service_mwh"] for r in result["demand"])*365,
            requested_service_mwh=sum(r["requested_service_mwh"] for r in result["demand"])*365,
            operating_resource_cost_cny=resource,ets_net_transfer_cny=ets_total,ets_balance_cny=net_transfers,
            max_residual=result["max_residual"],scope="mainland_conditional_CO2_not_all_GHG")
        for t,value in outputs.items():
            row[t+"_generation_mwh"] = value
            row[t+"_capacity_mw"] = self.generators[t].capacity
        return row,margins

    def step(self):
        self.drivers()
        self.construction_cost = 0
        self.mature()
        op = self.make_operation()
        result = operate_national(op)
        row,margins = self.settle(op,result)
        proposals = [self.generators[t].proposal(margins[t]) for t in TECHS]
        devices = [c.proposal() for c in self.consumers.values()]
        self.government.approve(proposals,devices)
        self.grid.propose(row["electricity_generation_mwh"],0)
        # Pay each project's scheduled instalment exactly once, including decision year.
        for p in self.projects:
            if p["status"] == "construction" and p["decision_year"] <= self.year < p["online_year"]:
                paid = min(p["instalment"],p["remaining"])
                p["remaining"] -= paid
                self.construction_cost += paid
                self.finance.append(dict(year=self.year,kind="construction",actor=p["tech"],amount_cny=-paid,
                    resource_cost_cny=paid,remaining_commitment_cny=p["remaining"],project=p["id"]))
        row["construction_cost_cny"] = self.construction_cost
        row["resource_cost_cny"] = row["operating_resource_cost_cny"]+self.construction_cost
        row["queue_mw"] = sum(p["capacity_mw"] for p in self.projects if p["status"] == "construction")
        self.paths.append(row)
        if self.detail:
            self.assets.extend(dict(year=self.year,**c) for c in self.cohorts)
            for consumer in self.consumers.values():
                self.assets.extend(dict(year=self.year,actor=consumer.name,kind="device",**c) for c in consumer.cohorts)
            for kind in ("fuel","generation","demand","storage"):
                self.operations.extend(dict(year=self.year,kind=kind,**r) for r in result[kind])
            self.balances.extend(dict(year=self.year,**r) for r in result["balances"])
            self.stages.extend(dict(year=self.year,**r) for r in result["stages"])
        else:
            self.behavior.clear(); self.finance.clear()
        self.year += 1

    def run(self, end_year):
        while self.year <= end_year:
            self.step()
        return self
