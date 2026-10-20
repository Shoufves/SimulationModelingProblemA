"""Conditional retirement timing and paid infrastructure on the inherited Q2 ABM.

No measured permit or financial identity is implied. Q3 authorisations are
explicit experiment assumptions; technical life is an absolute bound. The
fixed-project experiment replays a comparator's approved applications, revealed
only in their decision year. An unaffordable replay is a failed experiment, not
a modified project set silently described as a timing effect.
"""
from copy import deepcopy
from math import fsum, isclose

from .q2_national import NationalModel, operate_national, FUELS
from .q2_operations import Q2Error, number
from .q2_finance import financing_limit, fund_project


RULES = ("fixed_schedule", "cost_order", "service_ready", "anticipatory")


def service_id(row):
    # Material fuel inputs are distinct services, not substitutable energy.
    return row["sector"]+("/"+row["carrier"] if row["sector"]=="nonenergy_feedstock" else "")


def service_totals(rows, repeats=1):
    groups = {}
    for row in rows:
        name = service_id(row)
        group = groups.setdefault(name, dict(requested_service_mwh=0., unmet_service_mwh=0.))
        for key in group:
            group[key] += row[key]*repeats
    return [dict(sector=k, **v, unmet_fraction=v["unmet_service_mwh"]/v["requested_service_mwh"]
                 if v["requested_service_mwh"] else 0.) for k,v in sorted(groups.items())]


def worst_shortage(result):
    return max(r["unmet_fraction"] for r in service_totals(result["demand"]))


def schedule_retirements(cohorts, annual_limit, start, end, window, rule):
    """Split only initial coal cohorts, preserving capacity and original lifetime."""
    out = deepcopy(cohorts)
    for c in out:
        c["technical_exit_year"] = c["exit_year"]
        c["scheduled_exit_year"] = c["exit_year"]
    candidates = [c for c in out if c["tech"]=="coal" and c["status"]=="active"]
    for year in range(start,end+1):
        eligible = [c for c in candidates if c["capacity_mw"]>1e-9 and
                    c["technical_exit_year"]-window <= year < c["technical_exit_year"]]
        # In this aggregate model coal O&M is uniform. Book-cost-based holding
        # expense can differ, otherwise cost order correctly ties with oldest first.
        if rule == "cost_order":
            eligible.sort(key=lambda c:(-c["book_cost_cny_per_mw"],c["technical_exit_year"],c["id"]))
        else:
            eligible.sort(key=lambda c:(c["technical_exit_year"],c["id"]))
        remaining = annual_limit
        for c in eligible:
            amount = min(remaining,c["capacity_mw"])
            if amount <= 1e-9:
                break
            part = {**c, "id":c["id"]+f"/early/{year}", "capacity_mw":amount,
                    "scheduled_exit_year":year}
            out.append(part)
            c["capacity_mw"] -= amount
            remaining -= amount
    return [c for c in out if c["capacity_mw"]>1e-9]


def frozen_pressure(operation, event, channel_fraction):
    """Announced plateau stress for planning, NOT a chronological event result."""
    op = deepcopy(operation)
    op["fuels"]["gas"]["import_mw"] = [v*(1-channel_fraction*event["gas_channel_loss"])
                                            for v in op["fuels"]["gas"]["import_mw"]]
    for tech in ("wind","solar"):
        op["plants"][tech]["availability"] = [v*(1-event["renewable_loss"]) for v in op["plants"][tech]["availability"]]
    op["plants"]["hydro"]["window_energy_budget_mwh"] *= 1-event["renewable_loss"]
    return op


def constraint_diagnosis(op, result):
    """Binding flags are local diagnostics, not a proof of a unique causal bottleneck."""
    tol = 1e-7
    grid = any(sum(r["input_mwh"] for r in result["demand"] if r["period"]==i and r["carrier"]=="electricity")
               >= op["grid"]["power_mw"]*p["hours"]*op["grid"]["efficiency"]*(1-tol)
               for i,p in enumerate(op["periods"]))
    empty = any(r["closing_mwh"]<=max(.001,op["storage"]["energy_mwh"]*tol) for r in result["storage"])
    fuel = any(r["domestic_mwh"]+r["import_mwh"] >=
               (op["fuels"][r["fuel"]]["domestic_mw"][r["period"]]+op["fuels"][r["fuel"]]["import_mw"][r["period"]])*
               op["periods"][r["period"]]["hours"]*(1-tol) for r in result["fuel"])
    return dict(grid_binding=grid,storage_empty=empty,fuel_delivery_binding=fuel)


class TransitionModel(NationalModel):
    def __init__(self, data, design, theta, config, *, vR, vE, delay, rule,
                 epsilon=None, fixed_plan=None, actions=(), variant=None):
        self.q3 = deepcopy(config)
        self.spec = self.q3["transition"]
        self.rule,self.delay,self.fixed_plan = rule,delay,deepcopy(fixed_plan)
        self.vR,self.vE = vR,vE
        self.epsilon = self.spec["epsilon_candidates"][0] if epsilon is None else epsilon
        if rule not in RULES or type(delay) is not int or delay<0:
            raise Q2Error("invalid_input","Unknown retirement rule or delay")
        number(vR,"vR",0,1);number(vE,"vE",0,1);number(self.epsilon,"epsilon",0,1)
        self.actions = tuple(actions)
        if set(actions)-{"grid","storage","gas_release"}:
            raise Q2Error("invalid_input","Unsupported paid policy action")
        d = deepcopy(design)
        for kind in ("grid","storage"):
            d["assumptions"][kind+"_lead_years"] += delay
        pars = {**theta,"replacement_adoption":vE}
        super().__init__(data,d,pars,config["initial_year"],variant=variant)
        self.cohorts = schedule_retirements(self.cohorts,self.initial_capacities["coal"]*vR,
            self.year,config["end_year"],self.spec["early_exit_window_years"],rule)
        self.policy_queue,self.decisions,self.public_ledger,self.annual_services = [],[],[],[]
        self.forecasts,self.snapshot_states,self.application_log = [],{},[]
        self.operation_specs = {}
        self.public_escrow = 0.
        self.policy_gas_power = 0.
        self.public_committed = 0.
        self.retention_cost = 0.
        self._planned_options = []
        self._pressure = next(e for e in config["events"] if e["split"]=="selection")
        self.channel_fraction = config["transition"]["channel_fraction"]

    def public_commit(self, amount, kind, actor, project=""):
        if amount < 0 or amount>max(0,self.public_limit-self.public_committed)+.01:
            raise Q2Error("budget_failure","Public appropriation exceeded")
        self.public_committed += amount
        self.public_ledger.append(dict(year=self.year,kind=kind,actor=actor,project=project,
            appropriation_cny=amount,public_payment_cny=0.,recipient_receipt_cny=0.,resource_cost_cny=0.))

    def public_payment(self, amount, kind, actor, project=""):
        self.public_ledger.append(dict(year=self.year,kind=kind,actor=actor,project=project,
            appropriation_cny=0.,public_payment_cny=-amount,recipient_receipt_cny=amount,resource_cost_cny=amount))

    def mature(self):
        self.public_limit = self.gdp_cny*self.spec["public_budget_fraction_gdp"]
        self.public_committed,self.retention_cost = 0.,0.
        self.public_maintenance = 0.
        self._planned_options = []
        super().mature()
        # Projects share the inherited stock records and never add initial fuel/SOC.
        for p in self.policy_queue:
            if p["online"] == self.year:
                if p["remaining"]>.01:
                    raise Q2Error("accounting_failure","Unpaid Q3 project commissioning")
                if p["kind"]=="grid":
                    self.grid.network.append(dict(power=p["power"],online=p["online"],exit=p["exit"]))
                elif p["kind"]=="storage":
                    self.storage_cohorts.append(dict(power=p["power"],energy=p["energy"],online=p["online"],exit=p["exit"]))
                p["status"] = "active"
            if p["exit"]<=self.year:
                p["status"] = "retired"
        self.policy_gas_power = fsum(p["power"] for p in self.policy_queue if p["kind"]=="gas_release" and p["online"]<=self.year<p["exit"])
        maintenance = fsum(p["cost"]*self.spec["annual_public_asset_maintenance_fraction"]
                           for p in self.policy_queue if p["online"]<=self.year<p["exit"])
        # Existing contractual maintenance is paid first; an unfundable programme
        # is an explicit budget failure rather than free continued operation.
        self.public_commit(maintenance,"maintenance_authorisation","infrastructure_operators")
        self.public_payment(maintenance,"maintenance_payment","infrastructure_operators")
        self.public_maintenance = maintenance
        self.previous_storage_energy = self.grid.capacity()[1]
        # Evaluate the committed-only future BEFORE approving today's exit.
        # Otherwise a safe current day can conceal a shortage just after exit.
        forecast_risk = self.forecast_and_plan() if self.rule=="anticipatory" else 0.
        due = [c for c in self.cohorts if c["status"]=="active" and c.get("scheduled_exit_year",c["exit_year"])<=self.year<c["exit_year"]]
        if due:
            operation = self.make_operation()
            removed = fsum(c["capacity_mw"] for c in due)
            trial = deepcopy(operation)
            self.reduce_coal(trial,removed)
            risk = 0.
            if self.rule in ("service_ready","anticipatory"):
                risk = worst_shortage(operate_national(trial))
                if self.rule=="anticipatory":
                    risk = max(risk,forecast_risk,worst_shortage(operate_national(frozen_pressure(trial,self._pressure,self.channel_fraction))))
            for c in due:
                cost = c["capacity_mw"]*c["book_cost_cny_per_mw"]*self.spec["annual_retention_cost_fraction"]
                hold = self.rule in ("service_ready","anticipatory") and risk>self.epsilon and self.year<self.q3["end_year"]
                affordable = cost<=max(0,self.public_limit-self.public_committed)+.01
                if hold and affordable:
                    self.public_commit(cost,"retention_authorisation","coal_operator",c["id"])
                    self.public_payment(cost,"retention_service_payment","coal_operator_and_maintenance",c["id"])
                    self.retention_cost += cost
                    decision = "retain_within_technical_life"
                else:
                    c["status"] = "retired"
                    c["actual_exit_year"] = self.year
                    decision = "retire_budget_exhausted" if hold else "retire"
                    if self.year==self.q3["end_year"]:decision="retire_terminal_deadline"
                self.decisions.append(dict(year=self.year,cohort=c["id"],capacity_mw=c["capacity_mw"],
                    scheduled_exit_year=c["scheduled_exit_year"],technical_exit_year=c["exit_year"],
                    decision=decision,screened_worst_shortage=risk,forecast_worst_shortage=forecast_risk,
                    retention_cost_cny=cost if decision.startswith("retain_") else 0.))

    def forecast_and_plan(self):
        """Use only current information, before the current retirement approval."""
        saved = self.last_operation
        self.last_operation = self.make_operation()
        self.planning_cache = {}
        worst = 0.
        try:
            for lead in range(1,self.spec["information_horizon_years"]+1):
                if self.year+lead>self.q3["end_year"]:break
                op = self.planning_operation(lead)
                stress = frozen_pressure(op,self._pressure,self.channel_fraction)
                result = operate_national(stress)
                risk = worst_shortage(result)
                worst = max(worst,risk)
                flags = constraint_diagnosis(stress,result)
                self.forecasts.append(dict(year=self.year,target_year=self.year+lead,worst_service_fraction=risk,
                    threshold=self.epsilon,**flags,information="current_state_and_committed_queues_plus_frozen_plateau"))
                if risk>self.epsilon:
                    for kind,flag in (("grid",flags["grid_binding"]),("storage",flags["storage_empty"])):
                        if flag and self.a[kind+"_lead_years"]<=lead:self._planned_options.append(kind)
        finally:
            self.last_operation = saved
            self.planning_cache = {}
        return worst

    @staticmethod
    def reduce_coal(op, amount):
        plant = op["plants"]["coal"]
        before = plant["capacity_mw"]
        after = max(0,before-amount)
        plant["capacity_mw"] = after
        plant["ramp_mw_per_hour"] = after*.2
        plant["window_energy_budget_mwh"] *= after/before if before else 0

    def make_operation(self):
        op = super().make_operation()
        # Paid release/injection equipment alters throughput only. The gas tank,
        # opening inventory, domestic supply and import sources are unchanged.
        extra = getattr(self,"policy_gas_power",0.)
        op["fuels"]["gas"]["injection_mw"] += extra
        op["fuels"]["gas"]["withdrawal_mw"] += extra
        return op

    def planning_operation(self, lead):
        op = super().planning_operation(lead)
        future = self.year+lead
        retiring = fsum(c["capacity_mw"] for c in self.cohorts if c["tech"]=="coal" and c["status"]=="active"
                       and c.get("scheduled_exit_year",c["exit_year"])<=future<c["exit_year"])
        self.reduce_coal(op,retiring)
        # Committed public assets have already reserved their full funding.
        for p in self.policy_queue:
            if self.year<p["online"]<=future<p["exit"]:
                if p["kind"]=="grid":op["grid"]["power_mw"] += p["power"]
                elif p["kind"]=="storage":
                    op["storage"]["power_mw"] += p["power"]
                    op["storage"]["energy_mwh"] += p["energy"]
        gas = fsum(p["power"] for p in self.policy_queue if p["kind"]=="gas_release" and p["online"]<=future<p["exit"])
        for key in ("injection_mw","withdrawal_mw"):
            op["fuels"]["gas"][key] += gas
        return op

    def approve_investments(self, margins):
        if self.fixed_plan is None:
            super().approve_investments(margins)
            return
        # No future plan is made available to the decision/forecast code.
        plan = self.fixed_plan.get(str(self.year),dict(generation=[],devices=[],infrastructure=[]))
        for source in plan["generation"]:
            p = deepcopy(source)
            actor = self.generators[p["tech"]]
            capex = p["cost"]/p["capacity_mw"]
            if p["capacity_mw"]>min(actor.construction_limit(),financing_limit(actor,capex))+.001:
                raise Q2Error("fixed_schedule_infeasible",f"{self.year} {p['id']}: fixed investment cannot be financed/built")
            fund_project(actor,p["cost"],p["id"])
            p.update(status="construction",remaining=p["cost"])
            self.projects.append(p)
            self.construction_fund += p["cost"]
            self.finance.append(dict(year=self.year,kind="financing_commitment",actor=p["tech"],amount_cny=p["cost"],resource_cost_cny=0,project=p["id"]))
        for p in plan["devices"]:
            consumer = self.consumer_by_name[p["actor"]]
            cost = p["paid_cost_cny"]
            if cost>max(0,consumer.cash)+.01:
                raise Q2Error("fixed_schedule_infeasible",f"{self.year} {p['actor']}: fixed devices cannot be paid")
            consumer.cash -= cost
            consumer.queue.append({k:v for k,v in p.items() if k!="actor"})
            self.construction_cost += cost
            self.finance.append(dict(year=self.year,kind="device_finance_and_construction",actor=consumer.name,
                amount_cny=cost,resource_cost_cny=cost,actor_cash_transfer_cny=-cost,construction_receipt_cny=cost))
        self.application_log.append(dict(year=self.year,kind="fixed_plan_replayed",generation=len(plan["generation"]),devices=len(plan["devices"])))

    def approve_infrastructure(self, op, result, curtailed):
        if self.fixed_plan is None:
            super().approve_infrastructure(op,result,curtailed)
        else:
            plan = self.fixed_plan.get(str(self.year),dict(infrastructure=[]))
            for source in plan["infrastructure"]:
                p = deepcopy(source)
                p["remaining"] = p["cost"]
                self.grid.queue.append(p)
                self.grid.reserved += p["cost"]
                self.finance.append(dict(year=self.year,kind="infrastructure_financing",actor=p["kind"],amount_cny=p["cost"],resource_cost_cny=0))
        # Fixed-project timing experiments cannot add new projects; retention is
        # a paid service, not new capital. Full response may change the portfolio.
        if self.fixed_plan is None:
            choices = sorted(set(self.actions)|set(self._planned_options))
            allowance = max(0,self.public_limit-self.public_committed)
            shares = allowance/len(choices) if choices else 0.
            for kind in choices:
                self.request_public_project(kind,shares)
        for p in self.policy_queue:
            if p["decision"]<=self.year<p["online"]:
                paid = min(p["instalment"],p["remaining"])
                p["remaining"] -= paid
                self.public_escrow -= paid
                self.construction_cost += paid
                self.public_payment(paid,"public_construction",p["kind"],p["id"])

    def request_public_project(self, kind, allowance):
        spec = self.spec
        if kind in ("grid","storage"):
            capex = self.a[kind+"_capex_cny_per_"+("mw" if kind=="grid" else "mwh")]
            if kind=="storage":capex *= self.a["storage_duration_hours"]
            lead,life = self.a[kind+"_lead_years"],self.a[kind+"_lifetime_years"]
            limit = self.a[kind+"_build_fraction"]*self.grid.initial_power*self.gdp/self.gdp0
            already = fsum(p["power"] for p in self.grid.queue if p["kind"]==kind and p["decision"]==self.year)
        else:
            capex,lead,life = spec["gas_release_capex_cny_per_mw"],spec["gas_release_lead_years"]+self.delay,spec["gas_release_lifetime_years"]
            limit = self.suppliers["gas"].annual/8760*spec["gas_release_build_fraction"]
            already = 0.
        already += fsum(p["power"] for p in self.policy_queue if p["kind"]==kind and p["decision"]==self.year)
        requested = self.grid.initial_power*spec["public_project_power_fraction"] if kind!="gas_release" else limit
        amount = min(requested,max(0,limit-already),max(0,allowance)/capex)
        if self.year+lead>self.q3["end_year"] or amount<=1e-9:
            self.application_log.append(dict(year=self.year,kind=kind,decision="denied_budget_build_limit_or_horizon",requested_power_mw=requested,approved_power_mw=0.))
            return
        cost = amount*capex
        pid = f"q3/{kind}/{self.year}/{len(self.policy_queue)}"
        self.public_commit(cost,"public_project_appropriation",kind,pid)
        self.public_escrow += cost
        self.policy_queue.append(dict(id=pid,kind=kind,power=amount,energy=amount*self.a["storage_duration_hours"] if kind=="storage" else 0.,
            decision=self.year,online=self.year+lead,exit=self.year+lead+life,cost=cost,remaining=cost,instalment=cost/lead,status="construction"))
        self.application_log.append(dict(year=self.year,kind=kind,decision="approved_conditional_research_authorisation",
            requested_power_mw=requested,approved_power_mw=amount,cost_cny=cost,online_year=self.year+lead))

    def step(self):
        year = self.year
        super().step()
        row = self.paths[-1]
        row["resource_cost_cny"] += self.retention_cost+self.public_maintenance
        row["operating_resource_cost_cny"] += self.retention_cost+self.public_maintenance
        row.update(public_appropriation_cny=self.public_committed,public_budget_cny=self.public_limit,
                   retention_cost_cny=self.retention_cost,public_maintenance_cny=self.public_maintenance,public_escrow_cny=self.public_escrow,
                   public_escrow_residual_cny=self.public_escrow-fsum(p["remaining"] for p in self.policy_queue))
        if abs(row["public_escrow_residual_cny"])>max(.01,abs(self.public_escrow)*1e-12):
            raise Q2Error("accounting_failure","Q3 public escrow mismatch")
        if self.public_committed>self.public_limit+.01:
            raise Q2Error("budget_failure","Q3 annual public budget exceeded")
        demand = [r for r in self.operations if r["year"]==year and r["kind"]=="demand"]
        self.annual_services.extend(dict(year=year,**r) for r in service_totals(demand,365))
        self.operation_specs[year] = deepcopy(self.last_operation)
        if year in self.q3["transition"]["evaluation_years"]:
            self.snapshot_states[year] = deepcopy(self.last_operation)

    def export_plan(self):
        result = {str(y):dict(generation=[],devices=[],infrastructure=[]) for y in range(self.initial_year+1,self.q3["end_year"]+1)}
        for p in self.projects:
            if not p["initial_reconstruction"]:
                result[str(p["decision_year"])]["generation"].append(deepcopy(p))
        for c in self.consumers.values():
            for p in c.queue:
                result[str(p["decision"])]["devices"].append(dict(actor=c.name,**p))
        for p in self.grid.queue:
            result[str(p["decision"])]["infrastructure"].append(deepcopy(p))
        return result

    def terminal_accounts(self):
        end = self.q3["end_year"]
        residual = lambda cost,online,exit:cost*max(0,min(1,(exit-end)/(exit-online)))
        generation = fsum(residual(c["capacity_mw"]*c["book_cost_cny_per_mw"],c["online_year"],c["exit_year"])
                         for c in self.cohorts if c["status"]=="active")
        devices = fsum(residual(c["capacity"]*self.a["device_capex_cny_per_service_mw"],c["online"],c["exit"])
                      for a in self.consumers.values() for c in a.cohorts if c["status"]=="active")
        # Grid/storage initial book values are conditional engineering costs,
        # identical across cases. Commissioned public assets are already in stock.
        grid = fsum(residual(c["power"]*self.a["grid_capex_cny_per_mw"],c["online"],c["exit"])
                    for c in self.grid.network if c["online"]<=end<c["exit"])
        storage = fsum(residual(c["energy"]*self.a["storage_capex_cny_per_mwh"],c["online"],c["exit"])
                      for c in self.storage_cohorts if c["online"]<=end<c["exit"])
        gas = fsum(residual(p["cost"],p["online"],p["exit"]) for p in self.policy_queue if p["kind"]=="gas_release" and p["online"]<=end<p["exit"])
        construction = fsum(p["cost"]-p["remaining"] for p in self.projects if p["status"]=="construction")
        construction += fsum(p["cost"]-p["remaining"] for p in self.grid.queue+self.policy_queue if p["online"]>end)
        paid_devices = fsum(p["paid_cost_cny"] for consumer in self.consumers.values() for p in consumer.queue if p["online"]>end)
        construction += paid_devices
        terminal = generation+devices+grid+storage+gas+construction
        r = self.a["discount_rate"]
        gross = fsum(p["resource_cost_cny"]/(1+r)**(p["year"]-self.initial_year) for p in self.paths)
        return dict(terminal_asset_value_cny=terminal,terminal_generation_value_cny=generation,
                    terminal_device_value_cny=devices,terminal_grid_value_cny=grid,
                    terminal_storage_value_cny=storage,terminal_gas_release_value_cny=gas,
                    terminal_paid_device_value_cny=paid_devices,
                    terminal_paid_construction_value_cny=construction,
                    discounted_resource_cost_cny=gross,net_resource_cost_cny=gross-terminal/(1+r)**(end-self.initial_year),
                    cumulative_combustion_co2_t=fsum(p["combustion_co2_t"] for p in self.paths),
                    cumulative_retention_cost_cny=fsum(p["retention_cost_cny"] for p in self.paths),
                    cumulative_public_appropriation_cny=fsum(p["public_appropriation_cny"] for p in self.paths),
                    worst_annual_service_fraction=max(p["unmet_fraction"] for p in self.annual_services))
