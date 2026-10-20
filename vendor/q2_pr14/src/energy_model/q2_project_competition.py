"""Project investment under competition for the same finite dispatched sales.

New projects receive a slice of the LP's actual forecast output. Incumbents
receive the remainder. Private viability need not raise aggregate sector profit.
Finance remains a representative sector pool; this is not firm ownership data.
The inherited aggregate-owner screening stays available as an exact control.
"""
from math import fsum, isfinite

from .q2_national import EF, LEAD, LIFE, operate_national
from .q2_thermal_vintages import ThermalNationalModel


class ProjectCompetitionModel(ThermalNationalModel):
    def __init__(self, *args, project_competition=False, **kwargs):
        if type(project_competition) is not bool:
            raise ValueError("Project competition must be explicitly true or false")
        self.project_competition = project_competition
        self.project_forecasts = []
        self.project_operation_accounts = []
        super().__init__(*args, **kwargs)
        if project_competition and (self.thermal_vintages is None or
                not all(self.thermal_vintages.available(self.year,t) for t in ("coal","gas"))):
            raise ValueError("Competition requires both thermal project screens active from the first decision year")

    def step(self):
        start = len(self.behavior)
        super().step()
        if self.project_competition:
            for row in self.behavior[start:]:
                if row["kind"] == "thermal_marginal_proposal":
                    row["rule"] = "private project return on allocated LP sales; finite construction and finance"

    def candidate_operation(self, tech, amount, portfolio):
        if type(amount) not in (int, float) or not isfinite(amount) or amount <= 0:
            raise ValueError("Candidate capacity must be positive and finite")
        offset = int(self.annual_exposure is not None and self.annual_exposure.first_year_fraction == 0)
        horizon = LEAD[tech] + offset
        year = self.year + horizon
        def weight(t):
            return self.annual_exposure.weight(dict(online_year=self.year+LEAD[t],
                exit_year=self.year+LEAD[t]+LIFE[t]), year) if self.annual_exposure else 1.
        op = self.planning_operation(horizon)
        for other, capacity in (portfolio or {}).items():
            if other != tech and capacity > 0 and LEAD[other] <= horizon:
                self.add_renewable_candidate(other, op["plants"][other], capacity*weight(other))
        effective = amount*weight(tech)
        self.add_renewable_candidate(tech, op["plants"][tech], effective)
        return op, operate_national(op), effective

    def project_economics(self, tech, amount, portfolio=None):
        op, result, effective = self.candidate_operation(tech, amount, portfolio)
        plant = op["plants"][tech]
        total = fsum(r["output_mwh"] for r in result["generation"] if r["plant"] == tech)*365
        if self.renewable_vintages and tech in {"wind", "solar"}:
            hours = self.renewable_vintages.candidate_hours(self, tech, plant, result)
        else:
            hours = total/plant["capacity_mw"]
        candidate = effective*hours
        if candidate > total+max(1e-5,total*1e-12) or not 0 <= hours <= 8760+1e-6:
            raise ValueError("Candidate and incumbents cannot sell more than LP output")
        hours = min(hours,8760.)
        fuel = 0.
        margin = hours*(self.tariff(tech)-self.variable_om(tech))-self.fixed_om_per_mw(tech)
        eta = None
        if tech in {"coal", "gas"}:
            eta = (self.thermal_vintages.new_gross_efficiencies[tech]
                   if self.thermal_vintages and self.thermal_vintages.available(self.year,tech)
                   else self.efficiency[tech])
            fuel = candidate/eta
            margin -= hours/eta*self.suppliers[tech].price
            if self.year >= 2021:
                benchmarks = self.a["ets_2026_benchmarks"] if self.year >= 2027 else self.a["ets_2021_2025_proxy"]
                margin -= hours*self.carbon*(EF[tech]/eta-benchmarks[tech])
        if not isfinite(margin):
            raise ValueError("Nonfinite project operating margin")
        self.project_forecasts.append(dict(decision_year=self.year, tech=tech,
            capacity_mw=amount, candidate_operating_mw_year=effective,
            total_same_technology_generation_mwh=total, candidate_generation_mwh=candidate,
            incumbent_generation_mwh=max(0.,total-candidate), candidate_gross_efficiency=eta,
            candidate_fuel_mwh=fuel, annualised_project_hours=hours,
            annualised_operating_margin_cny_per_mw=margin,
            perspective="project_private_return; displaced incumbent sales retained as incumbent loss"))
        return margin,hours

    def marginal_renewable_economics(self,tech,amount,portfolio=None):
        if not self.project_competition:
            return super().marginal_renewable_economics(tech,amount,portfolio)
        return self.project_economics(tech,amount,portfolio)

    def thermal_candidate_npv(self,tech,amount,portfolio=None,*,support_fraction=1.):
        if not self.project_competition:
            return super().thermal_candidate_npv(tech,amount,portfolio,support_fraction=support_fraction)
        if type(support_fraction) not in (int,float) or not isfinite(support_fraction) or not 0<=support_fraction<=1:
            raise ValueError("Invalid thermal support fraction")
        margin,hours = self.project_economics(tech,amount,portfolio)
        expected = min(self.generators[tech].expected_project_margin(),margin)
        support = (self.revenue_policy.investment_value(self,tech,full_load_hours=hours)
                   if self.revenue_policy else 0.)*support_fraction
        r = self.a["discount_rate"]
        cost = fsum(self.capex(tech)/LEAD[tech]/(1+r)**k for k in range(LEAD[tech]))
        return expected*self.energy_pv_factor(lead=LEAD[tech],life=LIFE[tech])-cost+support

    def settle(self,op,result):
        row,margins = super().settle(op,result)
        if not self.project_competition:
            return row,margins
        thermal = {(r["tech"],r["cohort"]):r for r in self.thermal_fuel_ledger if r["year"]==self.year}
        renewable = self.renewable_vintages.allocate_actual(self,op,result) if self.renewable_vintages else {}
        for tech in ("coal","gas","wind","solar"):
            actual = row[tech+"_generation_mwh"]
            accounts = []
            for asset,weight in self.generation_assets(tech,self.year):
                effective = asset["capacity_mw"]*weight
                heat = thermal.get((tech,asset["id"]))
                energy = (heat["generation_mwh"] if heat is not None else renewable.get(asset["id"],
                    actual*effective/op["plants"][tech]["capacity_mw"] if op["plants"][tech]["capacity_mw"] else 0.))
                fuel = heat["fuel_mwh"] if heat is not None else (energy/self.efficiency[tech] if tech in {"coal","gas"} else 0.)
                revenue = energy*self.tariff(tech)
                fuel_bill = fuel*self.suppliers[tech].price if tech in {"coal","gas"} else 0.
                om = energy*self.variable_om(tech)+effective*self.fixed_om_per_mw(tech)
                ets = 0.
                if tech in {"coal","gas"} and self.year>=2021:
                    benchmarks = self.a["ets_2026_benchmarks"] if self.year>=2027 else self.a["ets_2021_2025_proxy"]
                    ets = self.carbon*(fuel*EF[tech]-energy*benchmarks[tech])
                accounts.append(dict(year=self.year,tech=tech,cohort=asset["id"],
                    generation_mwh=energy,fuel_mwh=fuel,revenue_cny=revenue,fuel_bill_cny=fuel_bill,
                    om_cny=om,ets_transfer_cny=-ets,operating_profit_before_support_cny=revenue-fuel_bill-om-ets))
            ledger = next(r for r in self.finance if r["year"]==self.year and r["kind"]=="generator_operation" and r["actor"]==tech)
            for field,expected in (("generation_mwh",actual),("revenue_cny",ledger["revenue_cny"]),
                ("fuel_bill_cny",ledger["fuel_bill_cny"]),("om_cny",ledger["om_cny"]),
                ("ets_transfer_cny",ledger["ets_transfer_cny"])):
                if abs(fsum(a[field] for a in accounts)-expected)>max(.01,abs(expected)*1e-12):
                    raise ValueError("Project and sector accounts disagree: "+tech+"/"+field)
            self.project_operation_accounts.extend(accounts)
        return row,margins
