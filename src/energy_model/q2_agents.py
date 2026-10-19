"""Mesa staged annual economy, coupled to the Q2 chronological LP.

This engine does not supply Chinese defaults. All budgets, prices, initial
cohorts and policies must be supplied by a separately admitted experiment.
"""
from copy import deepcopy
from math import isfinite

from mesa import Agent, Model

from .q2_operations import Q2Error, number, operate


class Actor(Agent):
    def __init__(self, model, name, parameters):
        super().__init__(model)
        self.name, self.p = name, deepcopy(parameters)
        self.cash = number(parameters["initial_cash"], name + ".initial cash")
        self.reserved = 0.0

    def log(self, kind, **fields):
        self.model.behavior.append(dict(year=self.model.year, actor=self.name, kind=kind,
                                       information_cutoff=self.model.year, **fields))


class FuelSupplier(Actor):
    def offer(self):
        # Only lagged utilisation affects supplier markup; capacity paths are exogenous.
        p = deepcopy(self.p["operation"])
        margin = 1 + self.p["markup"] * self.model.previous_utilisation.get(self.name, 0)
        self.price = min(p["domestic_cost_per_mwh"], p["import_cost_per_mwh"]) * margin
        self.log("fuel_offer", price=self.price, lagged_utilisation=self.model.previous_utilisation.get(self.name, 0))
        return p


class Generator(Actor):
    def __init__(self, model, name, parameters):
        super().__init__(model, name, parameters)
        self.margin = parameters["initial_expected_margin_per_mw"]

    def propose(self, observed_margin):
        m, p = self.model, self.p
        self.margin = (1-m.theta["expectation_rate"])*self.margin + m.theta["expectation_rate"]*observed_margin
        capex = p["capex_per_mw"] * (1-m.current["cost_decline"]) ** (m.year-m.config["price_year"])
        rate, life, lead = p["discount_rate"], p["lifetime_years"], p["lead_years"]
        annuity = life if rate == 0 else (1-(1+rate)**(-life))/rate
        # Equal instalments at decision year .. online year-1; no terminal salvage.
        pv_cost = sum(capex/lead/(1+rate)**k for k in range(lead))
        npv = self.margin*annuity/(1+rate)**(lead-1)-pv_cost
        maximum = min(p["build_limit_mw"], max(0, self.cash-self.reserved)/capex)
        amount = maximum*m.theta["investment_rate"] if npv > 0 and m.investment else 0.0
        self.log("generation_application", npv_per_mw=npv, requested_mw=amount,
                 expected_margin=self.margin, capex_per_mw=capex)
        return dict(actor=self.name, kind="plant", amount=amount, unit_cost=capex,
                    lead=lead, life=life)


class Consumer(Actor):
    def __init__(self, model, name, parameters):
        super().__init__(model, name, parameters)
        self.fossil_mw = parameters["fossil_service_mw"]
        self.electric_mw = parameters["electric_service_mw"]

    def demand(self):
        m, p = self.model, self.p
        service = p["base_service_mwh"] * (m.current["gdp_index"]/m.config["base_gdp_index"]) ** m.theta["activity_elasticity"]
        service *= (1-p["service_intensity_decline"])**(m.year-m.config["start_year"])
        self.requested = service
        total = self.fossil_mw + self.electric_mw
        if total <= 0:
            raise Q2Error("missing_input", "No service device stock: " + self.name)
        rows = {}
        for kind, capacity, carrier, efficiency in (
                ("fossil", self.fossil_mw, p["fuel"], p["fuel_efficiency"]),
                ("electric", self.electric_mw, "electricity", p["electric_efficiency"])):
            rows[self.name+"/"+kind] = dict(sector=self.name, carrier=carrier, efficiency=efficiency,
                input_capacity_mw=capacity/efficiency, priority=p["priority"],
                service_mwh=[service*capacity/total*f/m.config["annual_repeats"] for f in p["shape"]])
        return rows

    def propose(self):
        m, p = self.model, self.p
        fuel_price = m.suppliers[p["fuel"]].price
        fuel_price += m.current["carbon_price"]*m.coverage(self.name)*m.suppliers[p["fuel"]].p["operation"]["emission_t_per_mwh"]
        electric_price = m.current["retail_price"]
        saving = fuel_price/p["fuel_efficiency"] - electric_price/p["electric_efficiency"]
        annual_hours = sum(v["hours"] for v in m.config["periods"])*m.config["annual_repeats"]
        # Rotating stock replacement approximation, explicitly not a fitted age census.
        eligible = self.fossil_mw/p["device_lifetime_years"]
        expansion = max(0, self.requested/annual_hours-self.fossil_mw-self.electric_mw)
        cost = p["capex_per_service_mw"]
        replace = min(eligible, p["installation_limit_mw"], max(0,self.cash-self.reserved)/cost)
        replace *= m.theta["replacement_rate"] if saving*annual_hours*p["payback_years"] > cost and m.substitution else 0
        expand = min(expansion, max(0,p["installation_limit_mw"]-replace),
                     max(0,self.cash-self.reserved-replace*cost)/cost) if m.investment else 0
        self.log("device_application", replacement_mw=replace, expansion_mw=expand, saving_per_service_mwh=saving)
        return dict(actor=self.name, kind="device", amount=replace+expand, replacement=replace,
                    unit_cost=cost, lead=1, life=p["device_lifetime_years"])


class GridStorage(Actor):
    def propose(self, shortage):
        m, p = self.model, self.p
        # Deficit-responsive regulated asset rule, evaluated with observed shortage only.
        needed = min(p["build_limit_mw"], shortage / 8760)
        cost = p["grid_capex_per_mw"] + p["storage_capex_per_mw"]
        amount = min(needed, max(0,self.cash-self.reserved)/cost) if m.investment else 0
        self.log("network_application", requested_mw=amount, observed_service_shortage=shortage)
        return dict(actor=self.name, kind="network", amount=amount, unit_cost=cost,
                    lead=p["lead_years"], life=p["lifetime_years"])


class Government(Actor):
    def approve(self, applications):
        m = self.model
        requests = [a for a in applications if a["amount"] > 1e-12]
        # Common proportional approval: no first-visited firm grabs shared permits.
        plant_total = sum(a["amount"] for a in requests if a["kind"] == "plant")
        fraction = min(1.0, self.p["plant_permit_mw_per_year"]/plant_total) if plant_total else 1.0
        for a in requests:
            actor = m.by_name[a["actor"]]
            amount = a["amount"]*(fraction if a["kind"] == "plant" else 1)
            price = amount*a["unit_cost"]
            if price > actor.cash-actor.reserved+1e-7:
                raise Q2Error("accounting_failure", "Project exceeds uncommitted cash")
            project = dict(id=f"{m.year}/{a['actor']}/{len(m.projects)}", actor=a["actor"], kind=a["kind"],
                           amount=amount, replacement=a.get("replacement",0), decision_year=m.year,
                           online_year=m.year+a["lead"], retirement_year=m.year+a["lead"]+a["life"],
                           cost=price, instalment=price/a["lead"], remaining=price,
                           status="construction", permit_known_year=m.year)
            actor.reserved += price
            m.projects.append(project)
            m.pay_instalment(project)
            self.log("approval", project=project["id"], approved_mw=amount,
                     online_year=project["online_year"], shared_permit_fraction=fraction)


class AnnualModel(Model):
    def __init__(self, config, theta, *, investment=True, substitution=True):
        if config.get("scope") != "synthetic_engineering_fixture":
            raise Q2Error("unsupported_national_model", "This staged engine currently accepts reviewed engineering fixtures only")
        for key in ("activity_elasticity","investment_rate","replacement_rate","expectation_rate"):
            number(theta[key],key,0,2 if key == "activity_elasticity" else 1)
        super().__init__(seed=config["seed"])
        self.config, self.theta = deepcopy(config), deepcopy(theta)
        self.investment, self.substitution = investment, substitution
        self.year = config["start_year"]
        self.previous_utilisation = {}
        self.projects = []
        self.behavior, self.accounts, self.asset_log, self.operation_log = [], [], [], []
        self.paths, self.stage_log, self.balance_log = [], [], []
        self.suppliers = {n: FuelSupplier(self,n,p) for n,p in sorted(config["suppliers"].items())}
        self.generators = {n: Generator(self,n,p) for n,p in sorted(config["generators"].items())}
        self.consumers = {n: Consumer(self,n,p) for n,p in sorted(config["consumers"].items())}
        self.network = GridStorage(self,"grid_storage",config["network"])
        self.government = Government(self,"government",config["government"])
        self.by_name = {a.name:a for a in self.agents}
        if len(self.by_name) != len(self.agents):
            raise Q2Error("invalid_input", "Duplicate agent name")
        self.cohorts = deepcopy(config["initial_cohorts"])
        self.network_cohorts = []
        self.grid_mw = config["grid"]["power_mw"]
        self.storage_power = config["storage"]["power_mw"]
        self.storage_energy = config["storage"]["energy_mwh"]
        self.operations = None

    def coverage(self, actor):
        # Policy event records must be both published and effective by the simulated year.
        events = [p for p in self.config["policies"] if p["published_year"] <= self.year and
                  p["effective_year"] <= self.year and actor in p["coverage"]]
        return sorted(events,key=lambda p:p["effective_year"])[-1]["coverage"][actor] if events else 0.0

    def pay_instalment(self, project):
        actor = self.by_name[project["actor"]]
        amount = min(project["instalment"],project["remaining"])
        actor.cash -= amount
        actor.reserved -= amount
        project["remaining"] -= amount
        self.construction_cost += amount
        self.accounts.append(dict(year=self.year,actor=actor.name,kind="construction",
                                  cash_delta=-amount,resource_cost=amount,transfer=0,
                                  project=project["id"],reserved=actor.reserved,cash=actor.cash))

    def mature(self):
        for q in self.projects:
            if q["status"] != "construction":
                continue
            if q["decision_year"] < self.year < q["online_year"]:
                self.pay_instalment(q)
            if self.year >= q["online_year"]:
                if abs(q["remaining"]) > 1e-6:
                    raise Q2Error("accounting_failure", "Commissioning unpaid commitment")
                q["status"] = "commissioned"
                if q["kind"] == "plant":
                    self.cohorts.append(dict(id=q["id"],plant=q["actor"],capacity_mw=q["amount"],
                        online_year=q["online_year"],retirement_year=q["retirement_year"],
                        legal_exit_year=q["retirement_year"],status="active"))
                elif q["kind"] == "device":
                    a = self.consumers[q["actor"]]
                    a.fossil_mw -= q["replacement"]
                    a.electric_mw += q["amount"]
                else:
                    self.network_cohorts.append(deepcopy(q))
        for c in self.cohorts:
            if self.year >= max(c["retirement_year"],c["legal_exit_year"]):
                c["status"] = "retired"
            if c["status"] not in {"active","standby","stopped","retired"}:
                raise Q2Error("invalid_input", "Unknown asset state")
            self.asset_log.append(dict(year=self.year,**c))
        alive = [q for q in self.network_cohorts if q["online_year"] <= self.year < q["retirement_year"]]
        self.grid_mw = self.config["grid"]["power_mw"] + sum(q["amount"] for q in alive)
        self.storage_power = self.config["storage"]["power_mw"] + sum(q["amount"] for q in alive)
        self.storage_energy = self.config["storage"]["energy_mwh"] + sum(q["amount"] for q in alive)*self.network.p["storage_hours"]

    def make_operation(self):
        cfg = self.config
        operation = dict(periods=cfg["periods"],annual_repeats=cfg["annual_repeats"],cyclic=True,
                         fuels={name:a.offer() for name,a in self.suppliers.items()},plants={},demands={},
                         grid={**cfg["grid"],"power_mw":self.grid_mw},
                         storage={**cfg["storage"],"power_mw":self.storage_power,"energy_mwh":self.storage_energy})
        for name,a in self.generators.items():
            p = deepcopy(a.p["operation"])
            p["capacity_mw"] = sum(c["capacity_mw"] for c in self.cohorts if c["plant"] == name and
                c["status"] == "active" and c["online_year"] <= self.year)
            # Resource budget independent of nameplate capacity (hydro, biomass etc.).
            operation["plants"][name] = p
        for a in self.consumers.values():
            operation["demands"].update(a.demand())
        return operation

    def settle(self, operation, result):
        w = result["annual_repeats"]
        operating_cost = result["resource_cost"]
        carbon = self.current["carbon_price"]
        public_revenue, margins, supplier_revenue = 0.0, {}, {n:0.0 for n in self.suppliers}
        generation_revenue = 0.0
        primary, nonfossil, emissions = 0.0, 0.0, 0.0
        for name,a in self.generators.items():
            p = operation["plants"][name]
            output = sum(r["output_mwh"] for r in result["generation"] if r["plant"] == name)*w
            input_energy = output/p["efficiency"] if p["input"] else 0.0
            revenue = output*self.current["generation_price"] if p["output"] == "electricity" else output*self.current["hydrogen_price"]
            generation_revenue += revenue
            fuel_bill = 0.0
            if p["input"] in self.suppliers:
                fuel_bill = input_energy*self.suppliers[p["input"]].price
                supplier_revenue[p["input"]] += fuel_bill
            elif p["input"] == "electricity":
                fuel_bill = input_energy*self.current["generation_price"]
            elif p["input"] == "hydrogen":
                fuel_bill = input_energy*self.current["hydrogen_price"]
            ef = operation["fuels"][p["input"]]["emission_t_per_mwh"] if p["input"] in self.suppliers else 0.0
            # Explicit net charge on covered emissions. No claim this represents China's ETS.
            tax = input_energy*ef*carbon*self.coverage(name)
            fixed = p["capacity_mw"]*a.p["fixed_cost_per_mw"]
            net = revenue-fuel_bill-output*p["variable_cost_per_mwh"]-fixed-tax
            a.cash += net
            public_revenue += tax
            operating_cost += fixed
            margins[name] = net/p["capacity_mw"] if p["capacity_mw"] > 0 else 0.0
            self.accounts.append(dict(year=self.year,actor=name,kind="operation",cash_delta=net,
                resource_cost=output*p["variable_cost_per_mwh"]+fixed,transfer=tax,cash=a.cash,reserved=a.reserved))
            if p["input"] is None:
                value = output*a.p["primary_equivalent_per_output_mwh"]
                primary += value
                if a.p["nonfossil"]:
                    nonfossil += value
        terminal_electricity, terminal_hydrogen, retail_revenue = 0.0, 0.0, 0.0
        for name,a in self.consumers.items():
            bill, tax = 0.0, 0.0
            for r in result["demand"]:
                if r["sector"] != name:
                    continue
                energy, carrier = r["input_mwh"]*w,r["carrier"]
                if carrier == "electricity":
                    terminal_electricity += energy
                    retail_revenue += energy*self.current["retail_price"]
                    bill += energy*self.current["retail_price"]
                elif carrier == "hydrogen":
                    terminal_hydrogen += energy
                    bill += energy*self.current["hydrogen_price"]
                else:
                    pay = energy*self.suppliers[carrier].price
                    bill += pay
                    supplier_revenue[carrier] += pay
                    tax += energy*operation["fuels"][carrier]["emission_t_per_mwh"]*carbon*self.coverage(name)
            # Exogenous service-income endowment is explicit, not a hidden investment grant.
            income = a.requested*a.p["income_per_service_mwh"]
            delta = income-bill-tax
            a.cash += delta
            public_revenue += tax
            self.accounts.append(dict(year=self.year,actor=name,kind="operation",cash_delta=delta,
                resource_cost=0,transfer=tax,income=income,energy_bill=bill,cash=a.cash,reserved=a.reserved))
        for name,a in self.suppliers.items():
            rows = [r for r in result["fuel"] if r["fuel"] == name]
            used = sum(r["direct_mwh"]+r["conversion_mwh"] for r in rows)*w
            primary += used
            if a.p["nonfossil"]:
                nonfossil += used
            emissions += sum(r["combustion_co2_t"] for r in rows)*w
            cost = sum(r["domestic_mwh"]*a.p["operation"]["domestic_cost_per_mwh"]+
                       r["import_mwh"]*a.p["operation"]["import_cost_per_mwh"] for r in rows)*w
            delta = supplier_revenue[name]-cost
            a.cash += delta
            capacity = sum((operation["fuels"][name]["domestic_mw"][t]+operation["fuels"][name]["import_mw"][t])*p["hours"]
                           for t,p in enumerate(operation["periods"]))*w
            self.previous_utilisation[name] = used/capacity if capacity else 0.0
            self.accounts.append(dict(year=self.year,actor=name,kind="operation",cash_delta=delta,
                resource_cost=cost,transfer=0,cash=a.cash,reserved=a.reserved))
        # Internal converter sales must cancel in the central clearing account.
        converter_payments = sum(r["input_mwh"]*w*(self.current["generation_price"] if operation["plants"][r["plant"]]["input"] == "electricity"
            else self.current["hydrogen_price"]) for r in result["generation"]
            if operation["plants"][r["plant"]]["input"] in {"electricity","hydrogen"})
        storage_cost = sum((r["charge_mwh"]+r["discharge_mwh"])*w*operation["storage"]["throughput_cost"] for r in result["storage"])
        grid_delta = retail_revenue+terminal_hydrogen*self.current["hydrogen_price"]+converter_payments-generation_revenue-storage_cost
        self.network.cash += grid_delta
        self.accounts.append(dict(year=self.year,actor="grid_storage",kind="operation",cash_delta=grid_delta,
                                  resource_cost=storage_cost,transfer=0,cash=self.network.cash,reserved=self.network.reserved))
        self.government.cash += public_revenue
        self.accounts.append(dict(year=self.year,actor="government",kind="operation",cash_delta=public_revenue,
                                  resource_cost=0,transfer=-public_revenue,cash=self.government.cash,reserved=0))
        return primary,nonfossil,emissions,operating_cost,margins

    def step(self):
        self.construction_cost = 0.0
        self.mature()
        # This single current-year record is the entire exogenous information passed to decisions.
        self.current = deepcopy(self.config["drivers"][str(self.year)])
        operation = self.make_operation()
        result = operate(operation)
        self.operations = result
        primary,nonfossil,emissions,cost,margins = self.settle(operation,result)
        shortage = sum(r["unmet_service_mwh"] for r in result["demand"])*result["annual_repeats"]
        applications = [a.propose(margins[n]) for n,a in self.generators.items()]
        applications += [a.propose() for a in self.consumers.values()]
        applications.append(self.network.propose(shortage))
        self.government.approve(applications)
        for a in self.agents:
            if not isfinite(a.cash) or a.reserved < -1e-6:
                raise Q2Error("accounting_failure", "Invalid actor cash/commitment")
            # Insolvency is reported; existing committed projects are fully cash reserved.
            if a.cash < a.reserved-1e-6:
                raise Q2Error("financial_infeasible", f"{a.name} operating loss consumed reserved construction funds in {self.year}")
        for kind in ("fuel","generation","demand","storage"):
            self.operation_log.extend(dict(year=self.year,kind=kind,**row) for row in result[kind])
        self.balance_log.extend(dict(year=self.year,**row) for row in result["balances"])
        self.stage_log.extend(dict(year=self.year,**row) for row in result["stages"])
        bridge = self.config["carbon_bridge"].get(str(self.year))
        positive = emissions+bridge["other_positive_t"] if bridge is not None else None
        removal = bridge["net_removals_t"] if bridge is not None else None
        capacity = sum(p["capacity_mw"] for p in operation["plants"].values() if p["output"] == "electricity")
        gen = sum(r["output_mwh"] for r in result["generation"] if r["output"] == "electricity")*result["annual_repeats"]
        self.paths.append(dict(year=self.year,gdp_index=self.current["gdp_index"],primary_energy_mwh=primary,
            nonfossil_primary_share=nonfossil/primary if primary else None,combustion_co2_t=emissions,
            positive_co2_t=positive,net_removals_t=removal,net_co2_t=positive-removal if bridge else None,
            neutralisation_ratio=removal/positive if positive is not None and positive > 0 else None,
            energy_intensity=primary/self.current["gdp_index"],carbon_intensity=positive/self.current["gdp_index"] if bridge else None,
            capacity_mw=capacity,generation_mwh=gen,unmet_service_mwh=shortage,
            requested_service_mwh=sum(a.requested for a in self.consumers.values()),
            resource_cost=cost+self.construction_cost,construction_cost=self.construction_cost,
            active_queue_mw=sum(p["amount"] for p in self.projects if p["status"] == "construction"),
            max_residual=result["max_residual"],scope=self.config["scope"],status="conditional"))
        self.year += 1

    def run(self, end_year):
        while self.year <= end_year:
            self.step()
        return self


def simulate(config, theta, end_year, **switches):
    return AnnualModel(config,theta,**switches).run(end_year)
