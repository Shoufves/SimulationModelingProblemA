"""Source-initialised national aggregate experiment, with explicit reconstructions.

This is a conditional research model, not a plant census or an official forecast.
It reuses the independently tested chronological LP but has its own asset/device
cohorts, finance envelopes, output-based allowance accounting and statistical
bridges. Observations after initial_year never enter endogenous physical state.
"""
from copy import deepcopy
from math import exp, sqrt, log, fsum

from mesa import Agent, Model

from .q2_operations import Q2Error, operate
from .q2_finance import financing_limit, fund_project, service_debt, debt

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
            elif (k.endswith(("_mwh","_mw")) and "_per_" not in k) or k in {"ramp_mw_per_hour", "budget_cny"}:
                result[k] = [x/scale for x in v] if isinstance(v,list) else v/scale
            else:
                result[k] = deepcopy(v)
        return result
    result = operate(scaled(operation))
    for key in ("resource_cost","max_residual","dispatch_objective","policy_signal_cost"):
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
        self.loans, self.arrears = [], 0.0

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
        limit = max(m.initial_additions[self.name],self.initial_capacity*(.35 if self.name in {"wind","solar"} else .025))
        limit *= (m.gdp/m.gdp0)**m.variant.get("construction_elasticity",a["construction_gdp_elasticity"])
        if self.name == "solar":
            # Construction-sector growth is calibrated on training years,
            # independent of commissioned fleet. Post-2024 growth converges.
            tau = a["manufacturing_growth_decay_years"]
            years = max(0,min(m.year,2024)-m.initial_year)
            years += tau*(1-exp(-max(0,m.year-2024)/tau))
            limit *= exp(m.theta.get("solar_construction_growth",0)*years)
        amount = limit*m.theta["investment_response"] if npv > 0 and m.investment else 0
        if self.name == "wind":
            amount *= m.theta["renewable_mix_response"]
        elif self.name == "solar":
            amount *= 2-m.theta["renewable_mix_response"]
        if self.name in {"wind","solar"}:
            amount *= max(0,1-m.last_curtailment[self.name])**2
        finance_cap = financing_limit(self,capex)
        amount = min(amount,finance_cap)
        marginal = None
        if self.name in {"wind","solar"} and amount>0 and m.last_operation is not None:
            # Audit a candidate's incremental sales, not the old fleet's
            # average sales. Forecast uses only current demand and committed
            # assets; it is not a future realised-observation oracle.
            for _ in range(a["marginal_investment_halvings"]+1):
                marginal = m.marginal_renewable_margin(self.name,amount)
                prospective = min(self.margin,marginal)*annuity/(1+r)**(lead-1)-pv_cost
                if prospective>0:
                    break
                amount *= .5
            else:
                amount = 0.0
        self.log("investment_proposal",npv_cny_per_mw=npv,expected_margin_cny_per_mw=self.margin,
                 capacity_mw=self.capacity,requested_mw=amount,capex_cny_per_mw=capex,
                 construction_limit_mw=limit,finance_limit_mw=finance_cap,cash_cny=self.cash,debt_cny=debt(self),
                 marginal_margin_cny_per_mw=marginal)
        return dict(actor=self.name,tech=self.name,amount=amount,capex=capex,lead=lead,life=life)


class NationalConsumer(NationalActor):
    """Carrier-specific service proxy; replacement affects only next-year stock."""
    def __init__(self, model, fuel, service):
        super().__init__(model,"existing_electric_services" if fuel == "electricity" else model.a["demand_fuel_archetypes"][fuel])
        self.fuel, self.base_service = fuel,service
        self.cohorts = [dict(carrier=fuel,capacity=service/8760/.6/model.a["device_lifetime_years"],
            online=model.initial_year-i,exit=model.initial_year+model.a["device_lifetime_years"]-i,status="active")
            for i in range(model.a["device_lifetime_years"])]
        self.queue = []
        a = model.a
        unit_energy = (a["retail_price_cny_per_mwh"] if fuel == "electricity" else
                       model.suppliers[fuel].price/model.variant.get("fuel_price_multiplier",1)/a["direct_fuel_efficiency"][fuel])
        renewal = a["device_capex_cny_per_service_mw"]/8760/.6/a["device_lifetime_years"]
        # Reconstructed external income, fixed at initial real unit costs; it
        # does not increase to reimburse actual bills or unserved demand.
        self.income_per_service = unit_energy*a["consumer_income_headroom"]+renewal
        self.cash = service/8760/.6*a["device_capex_cny_per_service_mw"]*a["consumer_initial_cash_fraction"]

    def service_request(self):
        return self.base_service*(self.model.electric_activity if self.fuel == "electricity" else self.model.activity_factor())

    def endowment(self, requested):
        return requested*self.income_per_service*self.model.variant.get("consumer_income_multiplier",1)

    def demands_for(self, year, requested):
        m,a = self.model,self.model.a
        carriers = ("electricity",) if self.fuel == "electricity" else (self.fuel,"electricity")
        # Queued equipment contributes only after its paid commissioning date.
        stock = self.cohorts+[p for p in self.queue if p["online"]>m.year]
        amounts = {c:sum(p["capacity"] for p in stock if p["online"]<=year<p["exit"] and p["carrier"]==c) for c in carriers}
        total = sum(amounts.values())
        rows = {}
        for carrier,cap in amounts.items():
            efficiency = (1 if self.fuel == "electricity" else a["direct_fuel_efficiency"][self.fuel]
                          if carrier == self.fuel else a["electric_service_efficiency"][self.fuel])
            fraction = cap/total if total else (1 if carrier == self.fuel else 0)
            price = (a["retail_price_cny_per_mwh"] if carrier=="electricity" else
                     m.suppliers[carrier].price+m.direct_carbon_cost(carrier))
            key = self.name if self.fuel=="electricity" else self.name+"/"+carrier
            rows[key] = dict(sector=self.name,carrier=carrier,efficiency=efficiency,
                input_capacity_mw=cap/efficiency,priority=0,budget_group=self.name,purchase_price_per_mwh=price,
                service_mwh=[requested*f/365*fraction for f in a["load_shape"]])
        return rows

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
        self.requested = self.service_request()
        return self.demands_for(self.model.year,self.requested)

    def proposal(self):
        m,a = self.model,self.model.a
        total = sum(c["capacity"] for c in self.cohorts if c["status"] == "active")
        retiring_next = sum(c["capacity"] for c in self.cohorts if c["status"] == "active" and c["exit"] == m.year+1)
        next_service = self.requested*m.expected_service_growth(self.fuel,1)
        required = max(0,next_service/8760/.6-(total-retiring_next))
        fossil_unit = (a["retail_price_cny_per_mwh"] if self.fuel=="electricity" else
                      (m.suppliers[self.fuel].price+m.direct_carbon_cost(self.fuel))/a["direct_fuel_efficiency"][self.fuel])
        electric_unit = a["retail_price_cny_per_mwh"]/(1 if self.fuel=="electricity" else a["electric_service_efficiency"][self.fuel])
        annualized_device = a["device_capex_cny_per_service_mw"]/8760/.6/a["device_lifetime_years"]
        # Only eligible renewal and expansion; never instant switching of old devices.
        share = m.theta["replacement_adoption"] if electric_unit+annualized_device < fossil_unit+annualized_device and m.substitution else 0
        self.log("device_proposal",eligible_mw=required,retiring_next_mw=retiring_next,
                 electric_fraction=share,fossil_service_cost=fossil_unit,electric_service_cost=electric_unit,
                 cash_cny=self.cash,finance_limit_mw=max(0,self.cash)/a["device_capex_cny_per_service_mw"])
        return dict(actor=self.name,amount=min(required,max(0,self.cash)/a["device_capex_cny_per_service_mw"]),
                    electric_fraction=share,capex=a["device_capex_cny_per_service_mw"])


class NationalGovernment(NationalActor):
    def approve(self, generation, devices):
        m,a = self.model,self.model.a
        self.approve_devices(devices)
        m.planning_cache = {}
        # Full commitments reserved against this year's financing authorisation.
        # Total capital commitments include sponsor cash, shareholder equity and
        # loans. The national envelope is not fabricated government tax revenue.
        total = sum(p["amount"]*p["capex"] for p in generation)
        budget = m.gdp_cny*a["investment_budget_gdp_fraction"]
        ratio = min(1,budget/total) if total else 1
        approved = {p["tech"]:min(p["amount"]*ratio,financing_limit(m.generators[p["tech"]],p["capex"])) for p in generation}
        approved = m.audit_renewable_portfolio(approved)
        for p in generation:
            generator = m.generators[p["tech"]]
            amount = approved[p["tech"]]
            if amount <= 0:
                continue
            cost = amount*p["capex"]
            project = dict(id=f"{m.year}/{p['tech']}/{len(m.projects)}",tech=p["tech"],capacity_mw=amount,
                decision_year=m.year,online_year=m.year+p["lead"],exit_year=m.year+p["lead"]+p["life"],
                cost=cost,instalment=cost/p["lead"],remaining=cost,status="construction",initial_reconstruction=False)
            m.projects.append(project)
            fund_project(generator,cost,project["id"])
            m.construction_fund += cost
            m.finance.append(dict(year=m.year,kind="financing_commitment",actor=p["tech"],amount_cny=cost,
                                  resource_cost_cny=0,project=project["id"]))
            self.log("approval",project=project["id"],approved_mw=amount,online_year=project["online_year"],common_budget_ratio=ratio)

    def approve_devices(self, devices):
        m,a = self.model,self.model.a
        requested = sum(p["amount"]*p["capex"] for p in devices)
        device_budget = m.gdp_cny*a["device_budget_gdp_fraction"]
        fraction = min(1,device_budget/requested) if requested else 1
        for p in devices:
            consumer = m.consumer_by_name[p["actor"]]
            amount = min(p["amount"]*fraction,max(0,consumer.cash)/p["capex"]) if m.investment else 0
            opening = consumer.cash
            cost = amount*p["capex"]
            consumer.cash -= cost
            for carrier,part in ((consumer.fuel,1-p["electric_fraction"]),("electricity",p["electric_fraction"])):
                if amount*part:
                    consumer.queue.append(dict(carrier=carrier,capacity=amount*part,online=m.year+1,
                        exit=m.year+1+a["device_lifetime_years"],decision=m.year,paid_cost_cny=cost*part))
            m.construction_cost += cost
            m.finance.append(dict(year=m.year,kind="device_finance_and_construction",actor=consumer.name,
                amount_cny=cost,resource_cost_cny=cost,opening_cash_cny=opening,closing_cash_cny=consumer.cash,
                actor_cash_transfer_cny=-cost,construction_receipt_cny=cost,device_cash_balance_residual_cny=opening-cost-consumer.cash))


class NationalGrid(NationalActor):
    def __init__(self,model,name):
        super().__init__(model,name)
        a = model.a
        peak = model.base_electric/365*max(a["load_shape"])/6/a["grid_efficiency"]
        self.initial_power = peak*a["grid_initial_headroom"]
        self.network = [dict(power=self.initial_power,online=model.initial_year,exit=model.initial_year+a["grid_lifetime_years"])]
        self.queue, self.reserved = [], 0.0

    def network_power(self):
        return sum(c["power"] for c in self.network if c["online"] <= self.model.year < c["exit"])

    def mature(self):
        m = self.model
        for p in self.queue:
            if p["online"] == m.year:
                if p["remaining"] > .01:
                    raise Q2Error("accounting_failure","Unpaid infrastructure commissioning")
                if p["kind"] == "grid":
                    self.network.append(dict(power=p["power"],online=p["online"],exit=p["exit"]))
                else:
                    m.storage_cohorts.append(dict(power=p["power"],energy=p["energy"],online=p["online"],exit=p["exit"]))

    def capacity(self):
        m = self.model
        live = [c for c in m.storage_cohorts if c["online"] <= m.year < c["exit"]]
        return sum(c["power"] for c in live),sum(c["energy"] for c in live)

    def propose(self, op, result, curtailed):
        m,a = self.model,self.model.a
        power,energy = self.capacity()
        lead = a["grid_lead_years"]
        peak = max(sum(d["service_mwh"][i]/d["efficiency"] for d in op["demands"].values() if d["carrier"] == "electricity")/6/a["grid_efficiency"] for i in range(4))
        future = sum(c["power"] for c in self.network if c["exit"]>m.year+lead)
        future += sum(p["power"] for p in self.queue if p["kind"]=="grid" and p["online"]>m.year)
        desired = peak*(1+max(0,m.current_growth))**lead*a["grid_initial_headroom"]
        request = min(max(0,desired-future),self.initial_power*a["grid_build_fraction"]*m.gdp/m.gdp0)
        self.enqueue("grid",request,a["grid_capex_cny_per_mw"],a["grid_budget_gdp_fraction"],lead,a["grid_lifetime_years"])
        # Observed surplus creates a candidate for intraday shifting; physical
        # shortfall increases priority, but cannot create free energy/capacity.
        future_storage = sum(c["power"] for c in m.storage_cohorts if c["exit"]>m.year+a["storage_lead_years"])
        future_storage += sum(p["power"] for p in self.queue if p["kind"]=="storage" and p["online"]>m.year)
        surplus_power = curtailed/365/a["storage_duration_hours"]
        unmet = sum(r["unmet_service_mwh"] for r in result["demand"] if r["carrier"]=="electricity")
        desired_storage = min(surplus_power,power+a["storage_peak_fraction"]*peak+unmet/a["storage_duration_hours"])
        request = min(max(0,desired_storage-future_storage),a["storage_build_fraction"]*self.initial_power*m.gdp/m.gdp0)
        amount = self.enqueue("storage",request,a["storage_duration_hours"]*a["storage_capex_cny_per_mwh"],
                              a["storage_budget_gdp_fraction"],a["storage_lead_years"],a["storage_lifetime_years"])
        self.log("storage_proposal",power_mw=amount,previous_curtailment_mwh=curtailed,
                 unmet_electric_input_service_mwh=unmet,rule="observed surplus and peak/shortage; finite construction and earmarked budget")

    def enqueue(self,kind,request,capex,budget_fraction,lead,life):
        m = self.model
        amount = min(request,m.gdp_cny*budget_fraction/capex) if m.investment else 0
        if amount <= 0:
            return 0.0
        cost = amount*capex
        self.queue.append(dict(kind=kind,power=amount,energy=amount*m.a["storage_duration_hours"] if kind=="storage" else 0,
            decision=m.year,online=m.year+lead,exit=m.year+lead+life,cost=cost,remaining=cost,instalment=cost/lead))
        self.reserved += cost
        m.finance.append(dict(year=m.year,kind="infrastructure_financing",actor=kind,amount_cny=cost,resource_cost_cny=0))
        self.log("infrastructure_approval",infrastructure=kind,power_mw=amount,online_year=m.year+lead,cost_cny=cost)
        return amount

    def pay(self):
        m = self.model
        for p in self.queue:
            if p["decision"] <= m.year < p["online"]:
                paid = min(p["instalment"],p["remaining"])
                p["remaining"] -= paid
                self.reserved -= paid
                m.construction_cost += paid
                m.finance.append(dict(year=m.year,kind="infrastructure_construction",actor=p["kind"],amount_cny=-paid,resource_cost_cny=paid))


class NationalModel(Model):
    def __init__(self, data, design, theta, initial_year, *, variant=None, investment=True, substitution=True, detail=True):
        super().__init__(seed=design["seed"])
        self.data,self.design,self.theta = data,deepcopy(design),dict(theta)
        self.a = self.design["assumptions"]
        self.variant = {k:float(v) for k,v in (variant or {}).items()}
        for key in ("project_equity_fraction","grid_initial_headroom","grid_build_fraction"):
            if key in self.variant:
                self.a[key] = self.variant[key]
        self.initial_year,self.year = initial_year,initial_year+1
        self.investment,self.substitution,self.detail = investment,substitution,detail
        self.paths,self.behavior,self.finance,self.assets,self.operations,self.balances,self.stages = [],[],[],[],[],[],[]
        self.cohorts,self.projects,self.storage_cohorts = [],[],[]
        self.construction_cost = 0
        self.last_curtailment = dict(wind=0.0,solar=0.0)
        self.last_operation = None
        self.planning_cache = {}
        self.fuel_stocks = {}
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
        self.construction_fund = sum(p["remaining"] for p in self.projects)
        # Only initial snapshots are used to reconstruct terminal and non-energy inputs.
        self.feedstock = {f:fuel_energy[f]*self.a["nonenergy_fuel_fraction"][f]*self.variant.get("nonenergy_multiplier",1) for f in FUELS}
        self.consumers = {}
        for f in FUELS:
            terminal = fuel_energy[f]-self.initial_generation[f]/self.efficiency[f]-self.feedstock[f]
            if terminal <= 0:
                raise Q2Error("invalid_initial_state",f"Negative residual terminal {f}")
            self.consumers[f] = NationalConsumer(self,f,terminal*self.a["direct_fuel_efficiency"][f])
        self.base_electric = get(data,initial_year,"electricity_generation_mwh")*self.a["grid_efficiency"]
        self.base_export = max(0,-get(data,initial_year,"net_elec_imports_mwh"))
        self.base_electric -= self.base_export
        self.consumers["electricity"] = NationalConsumer(self,"electricity",self.base_electric)
        self.consumer_by_name = {a.name:a for a in self.consumers.values()}
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
        self.storage_soc = storage_energy*self.a["storage_initial_fraction"]
        self.previous_storage_energy = storage_energy
        self.electric_activity = 1.0

    def direct_carbon_cost(self,fuel):
        coverage = self.variant.get("direct_carbon_coverage",self.a["direct_carbon_coverage"][fuel]) if self.year>=2025 else 0
        return self.carbon*coverage*EF[fuel]

    def electricity_elasticity(self, year):
        terminal = self.variant.get("electricity_terminal_elasticity",self.a["electricity_terminal_elasticity"])
        mix = min(1,max(0,(year-2024)/36))
        return self.electric_elasticity*(1-mix)+terminal*mix

    def expected_service_growth(self, carrier, lead):
        # Persistence forecast of GDP growth, with the SAME announced elasticity
        # schedule as actual demand. Never read future realised historical GDP.
        factor = 1.0
        for year in range(self.year+1,self.year+lead+1):
            elasticity = self.electricity_elasticity(year) if carrier=="electricity" else self.theta["activity_elasticity"]
            factor *= (1+self.current_growth)**elasticity*(1-self.a["service_intensity_decline"])
        return factor

    def planning_operation(self, lead):
        future = self.year+lead
        if lead not in self.planning_cache:
            op = deepcopy(self.last_operation)
            for name,d in op["demands"].items():
                if d["sector"] in self.consumer_by_name:
                    continue
                growth = 1 if name=="exports" else self.expected_service_growth(d["carrier"],lead)
                d["service_mwh"] = [v*growth for v in d["service_mwh"]]
                d["input_capacity_mw"] *= growth
            for c in self.consumers.values():
                requested = c.service_request()*self.expected_service_growth(c.fuel,lead)
                op["demands"].update(c.demands_for(future,requested))
                op["spending_limits"][c.name] = dict(budget_cny=max(0,c.cash+c.endowment(requested))/365)
            for t,p in op["plants"].items():
                capacity = sum(c["capacity_mw"] for c in self.cohorts if c["tech"]==t and c["status"]=="active" and c["exit_year"]>future)
                capacity += sum(c["capacity_mw"] for c in self.projects if c["tech"]==t and self.year<c["online_year"]<=future)
                p["window_energy_budget_mwh"] *= capacity/p["capacity_mw"] if p["capacity_mw"] else 0
                p["capacity_mw"] = capacity
                p["ramp_mw_per_hour"] = capacity*.2
            op["grid"]["power_mw"] = sum(c["power"] for c in self.grid.network if c["exit"]>future)
            op["grid"]["power_mw"] += sum(c["power"] for c in self.grid.queue if c["kind"]=="grid" and self.year<c["online"]<=future)
            # Future retired storage is unavailable; inherited SOC may only be
            # disposed with retiring capacity, never replenished for planning.
            live = [c for c in self.storage_cohorts if c["online"]<=future<c["exit"]]
            pending = [p for p in self.grid.queue if p["kind"]=="storage" and self.year<p["online"]<=future<p["exit"]]
            retained = sum(c["energy"] for c in live)
            current = self.grid.capacity()[1]
            op["storage"].update(power_mw=sum(c["power"] for c in live+pending),energy_mwh=retained+sum(c["energy"] for c in pending),
                initial_mwh=self.storage_soc*min(1,retained/current) if current else 0)
            self.planning_cache[lead] = op
        return deepcopy(self.planning_cache[lead])

    def marginal_renewable_margin(self,tech,amount,portfolio=None):
        op = self.planning_operation(LEAD[tech])
        for other,capacity in (portfolio or {}).items():
            if other!=tech and capacity>0 and LEAD[other]<=LEAD[tech]:
                op["plants"][other]["capacity_mw"] += capacity
                op["plants"][other]["ramp_mw_per_hour"] += capacity*.2
                op["plants"][other]["window_energy_budget_mwh"] += capacity*24
        baseline = operate_national(op)
        previous = sum(r["output_mwh"] for r in baseline["generation"] if r["plant"] in {"wind","solar"})*365
        op["plants"][tech]["capacity_mw"] += amount
        op["plants"][tech]["ramp_mw_per_hour"] += amount*.2
        op["plants"][tech]["window_energy_budget_mwh"] += amount*24
        result = operate_national(op)
        # Total renewable incremental sales avoid treating displacement of
        # another zero-cost renewable as newly created market demand.
        added = sum(r["output_mwh"] for r in result["generation"] if r["plant"] in {"wind","solar"})*365-previous
        fixed = 29*self.fx*1000 if tech=="wind" else .015*self.generators[tech].capex_2024
        return max(0,added)/amount*self.tariff(tech)-fixed

    def audit_renewable_portfolio(self, approved):
        result = dict(approved)
        if self.last_operation is None:
            return result
        renewable = [t for t in ("wind","solar") if result.get(t,0)>0]
        if not renewable:
            return result
        r = self.a["discount_rate"]
        for attempt in range(self.a["marginal_investment_halvings"]+1):
            margins = {t:self.marginal_renewable_margin(t,result[t],result) for t in renewable}
            npvs = {t:min(self.generators[t].margin,margins[t])*(1-(1+r)**(-LIFE[t]))/r/(1+r)**(LEAD[t]-1)
                    -sum(self.capex(t)/LEAD[t]/(1+r)**k for k in range(LEAD[t])) for t in renewable}
            passed = all(v>0 for v in npvs.values())
            self.government.log("joint_renewable_audit",attempt=attempt,approved=passed,
                capacities_mw={t:result[t] for t in renewable},incremental_npvs_cny_per_mw=npvs)
            if passed:
                return result
            for t in renewable:
                result[t] *= .5
        # No untested fallback approval: reject after the finite search budget.
        for t in renewable:
            result[t] = 0.0
        return result

    def generator_carbon_cost(self,tech):
        if self.year < 2021 or tech not in {"coal","gas"}:
            return 0.0
        benchmark = (self.a["ets_2026_benchmarks"] if self.year>=2027 else self.a["ets_2021_2025_proxy"])[tech]
        return self.carbon*(EF[tech]/self.efficiency[tech]-benchmark)

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
            span = min(LIFE[t],19) if t == "nuclear" else LIFE[t]
            for index in range(span):
                age = min(span-1,int(index*self.variant.get("initial_age_multiplier",1)))
                self.cohorts.append(dict(id=f"initial/{t}/{index}",tech=t,capacity_mw=first[t]/span,
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
            for c in self.cohorts:
                if c["tech"] == t:
                    historical = (1-self.a["historical_wind_solar_real_cost_decline"])**(self.initial_year-2024) if t in {"wind","solar"} else 1
                    c["book_cost_cny_per_mw"] = self.generators[t].capex_2024*historical
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
        elasticity = self.electricity_elasticity(self.year)
        self.electric_activity *= (1+self.current_growth)**elasticity*(1-self.a["service_intensity_decline"])
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
                    online_year=p["online_year"],exit_year=p["exit_year"],status="active",reconstruction=p["initial_reconstruction"],
                    book_cost_cny_per_mw=p["cost"]/p["capacity_mw"] if p["capacity_mw"] else 0))
        for c in self.cohorts:
            if c["exit_year"] <= self.year:
                c["status"] = "retired"
        for consumer in self.consumers.values():
            consumer.prepare()
        self.grid.mature()
        retired_energy = sum(c["energy"] for c in self.storage_cohorts if c["exit"]==self.year)
        self.storage_retirement_loss = self.storage_soc*min(1,retired_energy/self.previous_storage_energy) if self.previous_storage_energy else 0
        self.storage_soc -= self.storage_retirement_loss
        self.previous_storage_energy = self.grid.capacity()[1]

    def make_operation(self):
        a = self.a
        op = dict(periods=[dict(hours=h) for h in a["operation_period_hours"]],annual_repeats=365,cyclic=True,
            fuels={f:s.offer() for f,s in self.suppliers.items()},plants={},demands={},
            grid=dict(efficiency=a["grid_efficiency"],power_mw=self.grid.network_power()),storage={})
        for f in op["fuels"]:
            op["fuels"][f]["initial_mwh"] = self.fuel_stocks.get(f,op["fuels"][f]["initial_mwh"])
        power,energy = self.grid.capacity()
        op["storage"] = dict(power_mw=power,energy_mwh=energy,initial_mwh=self.storage_soc,
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
            op["plants"][t]["policy_cost_per_mwh"] = self.generator_carbon_cost(t)
        for c in self.consumers.values():
            op["demands"].update(c.demand())
        op["spending_limits"] = {c.name:dict(budget_cny=max(0,c.cash+c.endowment(c.requested))/365)
                                 for c in self.consumers.values()}
        for d in op["demands"].values():
            d["policy_cost_per_mwh"] = self.direct_carbon_cost(d["carrier"]) if d["carrier"] in FUELS else 0
        # Non-energy material inputs do not emit in the combustion ledger.
        for f,value in self.feedstock.items():
            demand = value*self.activity_factor()
            op["demands"]["feedstock/"+f] = dict(sector="nonenergy_feedstock",carrier=f,efficiency=1,
                input_capacity_mw=demand/8760*2,priority=0,service_mwh=[demand/365/4]*4)
        op["demands"]["exports"] = dict(sector="electricity_exports",carrier="electricity",efficiency=1,
            input_capacity_mw=self.base_export/8760*2,priority=0,service_mwh=[self.base_export/365/4]*4)
        return op

    def settle(self, op, result):
        a = self.a
        outputs = {t:sum(r["output_mwh"] for r in result["generation"] if r["plant"] == t)*365 for t in TECHS}
        fuel_use = {f:sum(r["direct_mwh"]+r["conversion_mwh"] for r in result["fuel"] if r["fuel"] == f)*365 for f in self.suppliers}
        materials = {f:sum(r["input_mwh"] for r in result["demand"] if r["sector"] == "nonenergy_feedstock" and r["carrier"] == f)*365 for f in FUELS}
        # Correct the exported physical ledger too, not only the headline total.
        for r in result["fuel"]:
            nonenergy = sum(d["input_mwh"] for d in result["demand"] if d["sector"] == "nonenergy_feedstock" and d["carrier"] == r["fuel"] and d["period"] == r["period"])
            r["nonenergy_mwh"] = nonenergy
            r["combustion_co2_t"] -= nonenergy*EF[r["fuel"]]
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
            benchmark = (a["ets_2026_benchmarks"] if self.year >= 2027 else a["ets_2021_2025_proxy"]).get(t)
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
        direct_payment = sum(r["input_mwh"]*365*self.direct_carbon_cost(r["carrier"])
            for r in result["demand"] if r["carrier"] in FUELS and r["sector"]!="nonenergy_feedstock")
        ets_total += direct_payment
        self.finance.append(dict(year=self.year,kind="direct_ETS",actor="covered_consumers",ets_transfer_cny=-direct_payment,resource_cost_cny=0))
        self.finance.append(dict(year=self.year,kind="ETS_clearing_counterparty",actor="allowance_market",ets_transfer_cny=ets_total,
            amount_cny=ets_total,resource_cost_cny=0,public_tax_revenue_cny=0))
        transfers = [r.get("ets_transfer_cny",0) for r in self.finance if r["year"] == self.year]
        net_transfers = fsum(transfers)
        if abs(net_transfers) > max(.001,sum(abs(v) for v in transfers)*1e-14):
            raise Q2Error("accounting_failure","Unbalanced ETS transfers")
        for f,s in self.suppliers.items():
            supply = sum((op["fuels"][f]["domestic_mw"][i]+op["fuels"][f]["import_mw"][i])*6 for i in range(4))*365
            s.utilisation = fuel_use[f]/supply if supply else 0
            procurement = sum((r["domestic_mwh"]*op["fuels"][f]["domestic_cost_per_mwh"]+
                r["import_mwh"]*op["fuels"][f]["import_cost_per_mwh"])*365 for r in result["fuel"] if r["fuel"] == f)
            receipts = fuel_use[f]*s.price
            self.finance.append(dict(year=self.year,kind="supplier_operation",actor=f,revenue_cny=receipts,
                procurement_cny=procurement,cash_delta_cny=receipts-procurement,resource_cost_cny=procurement))
        # Endowments are explicit external service income. Every domestic energy
        # purchase has a supplier/generator/grid counterpart; not another resource cost.
        bills,retail = {},0.0
        for r in result["demand"]:
            price = a["retail_price_cny_per_mwh"] if r["carrier"] == "electricity" else self.suppliers[r["carrier"]].price
            if r["carrier"] in FUELS and r["sector"]!="nonenergy_feedstock":
                price += self.direct_carbon_cost(r["carrier"])
            payment = r["input_mwh"]*365*price
            bills[r["sector"]] = bills.get(r["sector"],0)+payment
            if r["carrier"] == "electricity":
                retail += payment
        service_income = 0.0
        for name,bill in bills.items():
            consumer = self.consumer_by_name.get(name)
            income = (consumer.endowment(consumer.requested) if consumer else
                      sum(r["served_service_mwh"] for r in result["demand"] if r["sector"] == name)*365*900)
            extra = {}
            if consumer:
                opening = consumer.cash
                consumer.cash += income-bill
                available = max(0,opening+income)
                if bill-available > max(.01,available*1e-10):
                    raise Q2Error("accounting_failure","Consumer spending exceeds funded budget")
                extra = dict(opening_cash_cny=opening,closing_cash_cny=consumer.cash,energy_budget_cny=available,
                    consumer_cash_balance_residual_cny=opening+income-bill-consumer.cash,
                    requested_service_mwh=consumer.requested)
            service_income += income
            self.finance.append(dict(year=self.year,kind="consumer_operation",actor=name,external_service_income_cny=income,
                energy_bill_cny=bill,cash_delta_cny=income-bill,resource_cost_cny=0,**extra))
        generator_payments = sum(outputs[t]*self.tariff(t) for t in TECHS)
        storage_cost = sum((r["charge_mwh"]+r["discharge_mwh"])*365*op["storage"]["throughput_cost"] for r in result["storage"])
        self.finance.append(dict(year=self.year,kind="grid_operation",actor="grid",retail_revenue_cny=retail,
            generator_payments_cny=generator_payments,cash_delta_cny=retail-generator_payments-storage_cost,
            resource_cost_cny=storage_cost))
        # ETS clearing counterpart is part of the financial system, not resource use.
        cash_net = sum(r.get("cash_delta_cny",0) for r in self.finance if r["year"] == self.year)+ets_total
        cash_residual = cash_net-(service_income-resource)
        if abs(cash_residual) > max(.01,resource*1e-12):
            raise Q2Error("accounting_failure",f"Internal energy payment imbalance: {cash_residual}")
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
            cash_balance_residual_cny=cash_residual,external_service_income_cny=service_income,
            max_residual=result["max_residual"],scope="mainland_conditional_CO2_not_all_GHG")
        for t,value in outputs.items():
            row[t+"_generation_mwh"] = value
            row[t+"_capacity_mw"] = self.generators[t].capacity
        clean = sum(outputs[t] for t in ("hydro","nuclear","wind","solar","biomass"))
        direct_equivalent = sum(fuel_use[f] for f in FUELS)+clean
        row.update(clean_generation_mwh=clean,primary_direct_equivalent_tce=direct_equivalent/TCE_MWH,
                   clean_share_direct_equivalent=clean/direct_equivalent,
                   dispatch_policy_signal_cny=result["policy_signal_cost"])
        return row,margins

    def step(self):
        self.drivers()
        self.construction_cost = 0
        self.mature()
        op = self.make_operation()
        result = operate_national(op)
        row,margins = self.settle(op,result)
        self.last_operation = op
        self.planning_cache = {}
        self.storage_soc = result["storage"][-1]["closing_mwh"]
        self.fuel_stocks = {f:next(r["closing_mwh"] for r in reversed(result["fuel"]) if r["fuel"]==f) for f in self.suppliers}
        curtailed = 0.0
        for t in ("wind","solar"):
            potential = sum(op["plants"][t]["availability"][i]*op["plants"][t]["capacity_mw"]*p["hours"]*365 for i,p in enumerate(op["periods"]))
            unused = max(0,potential-row[t+"_generation_mwh"])
            self.last_curtailment[t] = unused/potential if potential else 0
            row[t+"_curtailed_mwh"] = unused
            curtailed += unused
        for g in self.generators.values():
            service_debt(g)
        proposals = [self.generators[t].proposal(margins[t]) for t in TECHS]
        devices = [c.proposal() for c in self.consumers.values()]
        self.government.approve(proposals,devices)
        self.grid.propose(op,result,curtailed)
        self.grid.pay()
        row.update(grid_power_mw=op["grid"]["power_mw"],storage_power_mw=op["storage"]["power_mw"],
                   storage_energy_mwh=op["storage"]["energy_mwh"],storage_opening_mwh=op["storage"]["initial_mwh"],
                   storage_closing_mwh=self.storage_soc,storage_retirement_loss_mwh=self.storage_retirement_loss,
                   infrastructure_reserved_cny=self.grid.reserved,
                   infrastructure_fund_residual_cny=self.grid.reserved-sum(p["remaining"] for p in self.grid.queue),
                   generator_debt_cny=sum(debt(g) for g in self.generators.values()),
                   consumer_cash_cny=sum(c.cash for c in self.consumers.values()),
                   financing_transfer_residual_cny=fsum(r.get("actor_cash_transfer_cny",0)+r.get("lender_transfer_cny",0)+r.get("shareholder_transfer_cny",0)+r.get("escrow_transfer_cny",0)+r.get("construction_receipt_cny",0) for r in self.finance if r["year"]==self.year))
        # Pay each project's scheduled instalment exactly once, including decision year.
        for p in self.projects:
            if p["status"] == "construction" and p["decision_year"] <= self.year < p["online_year"]:
                paid = min(p["instalment"],p["remaining"])
                p["remaining"] -= paid
                self.construction_fund -= paid
                self.construction_cost += paid
                self.finance.append(dict(year=self.year,kind="construction",actor=p["tech"],amount_cny=-paid,
                    resource_cost_cny=paid,remaining_commitment_cny=p["remaining"],project=p["id"]))
        row["construction_cost_cny"] = self.construction_cost
        row["resource_cost_cny"] = row["operating_resource_cost_cny"]+self.construction_cost
        row["queue_mw"] = sum(p["capacity_mw"] for p in self.projects if p["status"] == "construction")
        row["reserved_construction_fund_cny"] = self.construction_fund
        row["construction_fund_residual_cny"] = self.construction_fund-sum(p["remaining"] for p in self.projects)
        if abs(row["construction_fund_residual_cny"]) > max(.1,self.construction_fund*1e-12):
            raise Q2Error("accounting_failure","Reserved construction funds differ from commitments")
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
