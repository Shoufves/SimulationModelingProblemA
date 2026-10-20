"""Separate inherited thermal units from explicitly specified new technology.

Within a technology, cohorts share utilisation. The resulting harmonic
efficiency conserves fuel; this is not unit-level economic dispatch.
"""
from copy import deepcopy
from math import fsum, isfinite

from .q2_fuel_prices import FuelPriceNationalModel
from .q2_national import EF, LEAD, LIFE, operate_national


class ThermalVintages:
    def __init__(self, *, new_gross_efficiencies, decision_start_year, evidence):
        if not new_gross_efficiencies or not set(new_gross_efficiencies).issubset({"coal", "gas"}):
            raise ValueError("Explicit coal/gas new-technology efficiencies required")
        for value in new_gross_efficiencies.values():
            if type(value) not in (int, float) or not isfinite(value) or not 0 < value <= 1:
                raise ValueError("Invalid gross thermal efficiency")
        if type(decision_start_year) is not int or decision_start_year < 1900:
            raise ValueError("Invalid technology availability year")
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("Thermal technology evidence/assumptions required")
        self.new_gross_efficiencies = dict(new_gross_efficiencies)
        self.decision_start_year = decision_start_year
        self.evidence = evidence

    def available(self, year, tech):
        return tech in self.new_gross_efficiencies and year >= self.decision_start_year


class ThermalBeliefs:
    """Compose candidate learning with the existing actor, preserving its identity."""
    def __init__(self, generator):
        self.generator = generator
        self.fleet_learn = generator.learn_margin
        self.old_expected = generator.expected_project_margin
        self.old_proposal = generator.proposal
        self.project_margin = None
        m, tech = generator.model, generator.name
        if m.thermal_vintages.available(m.year, tech):
            self.project_margin = generator.margin + generator.reference_cf * 8760 * m.suppliers[tech].price * (
                1 / m.initial_thermal_efficiencies[tech] - 1 / m.thermal_vintages.new_gross_efficiencies[tech])

    def expected(self, *, additional_capacity_mw=0):
        g, m = self.generator, self.generator.model
        if not m.thermal_vintages.available(m.year, g.name):
            return self.old_expected(additional_capacity_mw=additional_capacity_mw)
        if self.project_margin is None:
            return g.margin
        return self.project_margin

    def learn(self, realised_margin, *, operation=None, result=None):
        g, m = self.generator, self.generator.model
        tech = g.name
        if not m.thermal_vintages.available(m.year, tech) or operation is None or result is None:
            return self.fleet_learn(realised_margin, operation=operation, result=result)
        plant = operation["plants"][tech]
        cap = plant["capacity_mw"]
        if cap <= 0:
            return self.fleet_learn(realised_margin, operation=operation, result=result)
        eta_new = m.thermal_vintages.new_gross_efficiencies[tech]
        marginal_fuel = m.suppliers[tech].price + (m.carbon * EF[tech] if m.year >= 2021 else 0)
        heat_difference = 1 / plant["efficiency"] - 1 / eta_new
        if self.project_margin is None:
            # Technology becomes available now; assess it using the inherited
            # fleet belief and current prices, never a future realised margin.
            self.project_margin = g.margin + g.reference_cf * 8760 * marginal_fuel * heat_difference
        hours = fsum(r["output_mwh"] for r in result["generation"] if r["plant"] == tech) * 365 / cap
        candidate_sample = realised_margin + hours * marginal_fuel * heat_difference
        rate = m.theta["expectation_rate"]
        self.project_margin = (1 - rate) * self.project_margin + rate * candidate_sample
        self.fleet_learn(realised_margin, operation=operation, result=result)
        g.log("thermal_candidate_learning", fleet_efficiency=plant["efficiency"],
              candidate_efficiency=eta_new, observed_full_load_hours=hours,
              candidate_margin_sample_cny_per_mw=candidate_sample,
              candidate_expected_margin_cny_per_mw=self.project_margin)

    def proposal(self, realised_margin, *, operation=None, result=None):
        p = self.old_proposal(realised_margin, operation=operation, result=result)
        m, tech = self.generator.model, self.generator.name
        if not m.thermal_vintages.available(m.year, tech) or not p["amount"] or m.last_operation is None:
            return p
        original = p["amount"]
        for attempt in range(m.a["marginal_investment_halvings"] + 1):
            if m.thermal_candidate_npv(tech, p["amount"]) > 0:
                break
            p["amount"] *= .5
        else:
            p["amount"] = 0.
        self.generator.log("thermal_marginal_proposal", original_requested_mw=original,
                           requested_mw=p["amount"], rule="incremental fleet profit; finite construction and finance")
        return p


class ThermalNationalModel(FuelPriceNationalModel):
    def __init__(self, *args, thermal_vintages=None, **kwargs):
        if thermal_vintages is not None and not isinstance(thermal_vintages, ThermalVintages):
            raise ValueError("Expected explicit thermal-vintage assumptions")
        self.thermal_vintages = deepcopy(thermal_vintages)
        self.thermal_fuel_ledger = []
        super().__init__(*args, **kwargs)
        self.initial_thermal_efficiencies = dict(self.efficiency)
        self.thermal_beliefs = {}
        if self.thermal_vintages:
            for tech in self.thermal_vintages.new_gross_efficiencies:
                generator = self.generators[tech]
                belief = ThermalBeliefs(generator)
                self.thermal_beliefs[tech] = belief
                generator.learn_margin = belief.learn
                generator.expected_project_margin = belief.expected
                generator.proposal = belief.proposal

    def mixed_efficiency(self, tech, year, *, physical=False):
        weights = [(asset["capacity_mw"] * weight,
                    asset.get("gross_thermal_efficiency", self.initial_thermal_efficiencies[tech]))
                   for asset, weight in self.generation_assets(tech, year, physical=physical)]
        weights = [(cap, eta) for cap, eta in weights if cap > 0]
        if not weights:
            return self.initial_thermal_efficiencies[tech]
        if any(type(eta) not in (int, float) or not isfinite(eta) or not 0 < eta <= 1 for _, eta in weights):
            raise ValueError("Invalid persisted cohort efficiency")
        if all(eta == weights[0][1] for _, eta in weights):
            return weights[0][1]  # preserve exact original floating behaviour
        return fsum(cap for cap, _ in weights) / fsum(cap / eta for cap, eta in weights)

    def mature(self):
        super().mature()
        if self.thermal_vintages:
            efficiencies = {p["id"]: p["gross_thermal_efficiency"] for p in self.projects if "gross_thermal_efficiency" in p}
            for cohort in self.cohorts:
                if cohort["id"] in efficiencies:
                    cohort["gross_thermal_efficiency"] = efficiencies[cohort["id"]]

    def make_operation(self):
        if self.thermal_vintages:
            for tech in self.thermal_vintages.new_gross_efficiencies:
                self.efficiency[tech] = self.mixed_efficiency(tech, self.year)
        op = super().make_operation()
        if self.thermal_vintages and "fossil_allocation_score" in op:
            for tech in self.thermal_vintages.new_gross_efficiencies:
                op["fossil_allocation_score"]["plants"][tech]["initial_marginal_cost"] = (
                    self.variable_om(tech, year=self.initial_year)
                    + self.reference_fuel_prices[tech] / self.initial_thermal_efficiencies[tech])
        return op

    def _operation_efficiency(self, op, tech, eta):
        old = op["plants"][tech]["efficiency"]
        if self.year >= 2021:
            op["plants"][tech]["policy_cost_per_mwh"] += self.carbon * EF[tech] * (1 / eta - 1 / old)
        op["plants"][tech]["efficiency"] = eta

    def planning_operation(self, lead):
        op = super().planning_operation(lead)
        if self.thermal_vintages:
            for tech in self.thermal_vintages.new_gross_efficiencies:
                self._operation_efficiency(op, tech, self.mixed_efficiency(tech, self.year + lead))
        return op

    def year_end_operation(self):
        op = super().year_end_operation()
        if self.thermal_vintages:
            for tech in self.thermal_vintages.new_gross_efficiencies:
                # Snapshot policy belongs to the completed year, not self.year
                # which is already advanced by step(). Preserve that signal.
                year = self.paths[-1]["year"]
                old = op["plants"][tech]["efficiency"]
                eta = self.mixed_efficiency(tech, year, physical=True)
                if year >= 2021:
                    op["plants"][tech]["policy_cost_per_mwh"] += self.carbon * EF[tech] * (1 / eta - 1 / old)
                op["plants"][tech]["efficiency"] = eta
        return op

    def add_renewable_candidate(self, tech, plant, amount):
        # The inherited joint audit also calls this hook for OTHER technologies.
        if self.thermal_vintages and self.thermal_vintages.available(self.year, tech) and amount > 0:
            old, eta = plant["capacity_mw"], plant["efficiency"]
            new_eta = self.thermal_vintages.new_gross_efficiencies[tech]
            mixed = (old + amount) / (old / eta + amount / new_eta)
            if self.year >= 2021:
                plant["policy_cost_per_mwh"] += self.carbon * EF[tech] * (1 / mixed - 1 / eta)
            plant["efficiency"] = mixed
        if tech in {"wind", "solar"}:
            return super().add_renewable_candidate(tech, plant, amount)
        plant["capacity_mw"] += amount
        plant["ramp_mw_per_hour"] += amount * .2
        factor = self.generators[tech].reference_cf if tech in {"hydro", "nuclear", "biomass"} else 1.
        plant["window_energy_budget_mwh"] += amount * 24 * factor

    def thermal_candidate_npv(self, tech, amount, portfolio=None, *, support_fraction=1.):
        if amount <= 0:
            raise ValueError("Thermal candidate must have positive capacity")
        if type(support_fraction) not in (int, float) or not isfinite(support_fraction) or not 0 <= support_fraction <= 1:
            raise ValueError("Invalid thermal support fraction")
        offset = int(self.annual_exposure is not None and self.annual_exposure.first_year_fraction == 0)
        horizon = LEAD[tech] + offset
        year = self.year + horizon
        def weight(t):
            return self.annual_exposure.weight(dict(online_year=self.year + LEAD[t],
                exit_year=self.year + LEAD[t] + LIFE[t]), year) if self.annual_exposure else 1.
        op = self.planning_operation(horizon)
        for other, cap in (portfolio or {}).items():
            if other != tech and cap > 0 and LEAD[other] <= horizon:
                self.add_renewable_candidate(other, op["plants"][other], cap * weight(other))
        before = operate_national(op)
        before_eta = op["plants"][tech]["efficiency"]
        self.add_renewable_candidate(tech, op["plants"][tech], amount * weight(tech))
        after = operate_national(op)
        def energy(result):
            return fsum(r["output_mwh"] for r in result["generation"] if r["plant"] == tech) * 365
        e0, e1 = energy(before), energy(after)
        delta_energy = e1 - e0
        delta_fuel = e1 / op["plants"][tech]["efficiency"] - e0 / before_eta
        contribution = delta_energy * (self.tariff(tech) - self.variable_om(tech)) - delta_fuel * self.suppliers[tech].price
        if self.year >= 2021:
            benchmarks = self.a["ets_2026_benchmarks"] if self.year >= 2027 else self.a["ets_2021_2025_proxy"]
            contribution -= self.carbon * (EF[tech] * delta_fuel - benchmarks[tech] * delta_energy)
        marginal = contribution / (amount * weight(tech)) - self.fixed_om_per_mw(tech)
        expected = min(self.generators[tech].expected_project_margin(), marginal)
        marginal_hours = max(0., delta_energy) / (amount * weight(tech))
        support = (self.revenue_policy.investment_value(self, tech, full_load_hours=marginal_hours)
                   if self.revenue_policy else 0.) * support_fraction
        cost = sum(self.capex(tech) / LEAD[tech] / (1 + self.a["discount_rate"]) ** k for k in range(LEAD[tech]))
        npv = expected * self.energy_pv_factor(lead=LEAD[tech], life=LIFE[tech]) - cost + support
        if not isfinite(npv):
            raise ValueError("Nonfinite thermal candidate NPV")
        return npv

    def audit_renewable_portfolio(self, approved, *, support_fractions=None):
        if not self.thermal_vintages or self.last_operation is None:
            return super().audit_renewable_portfolio(approved, support_fractions=support_fractions)
        result = dict(approved)
        halvings = self.a["marginal_investment_halvings"]
        for attempt in range(halvings + 3):
            result = super().audit_renewable_portfolio(result, support_fractions=support_fractions)
            candidates = [t for t, cap in result.items() if cap > 0 and self.thermal_vintages.available(self.year, t)]
            npvs = {t: self.thermal_candidate_npv(t, result[t], result,
                    support_fraction=1. if support_fractions is None else support_fractions.get(t, 1.))
                    for t in candidates}
            failed = [t for t in candidates if npvs[t] <= 0]
            if candidates:
                self.government.log("joint_thermal_audit", attempt=attempt, capacities_mw={t: result[t] for t in candidates},
                                    incremental_npvs_cny_per_mw=npvs, approved=not failed)
            if not failed:
                return result
            for tech in failed:
                result[tech] = result[tech] * .5 if attempt < halvings else 0.
        raise RuntimeError("Thermal portfolio removal failed to terminate")

    def settle(self, op, result):
        row, margins = super().settle(op, result)
        if self.thermal_vintages:
            for tech in self.thermal_vintages.new_gross_efficiencies:
                cap = op["plants"][tech]["capacity_mw"]
                output = row[tech + "_generation_mwh"]
                entries = []
                for asset, weight in self.generation_assets(tech, self.year):
                    exposure = asset["capacity_mw"] * weight
                    eta = asset.get("gross_thermal_efficiency", self.initial_thermal_efficiencies[tech])
                    energy = output * exposure / cap if cap else 0.
                    entries.append(dict(year=self.year, tech=tech, cohort=asset["id"], operating_mw_year=exposure,
                        gross_efficiency=eta, generation_mwh=energy, fuel_mwh=energy / eta, combustion_co2_t=energy / eta * EF[tech]))
                fuel = fsum(r["fuel_mwh"] for r in entries)
                actual = output / op["plants"][tech]["efficiency"]
                if abs(fuel - actual) > max(1e-5, actual * 1e-12):
                    raise ValueError("Thermal cohort fuel does not close")
                self.thermal_fuel_ledger.extend(entries)
        return row, margins

    def step(self):
        super().step()
        if self.thermal_vintages:
            for project in self.projects:
                if (not project["initial_reconstruction"] and "gross_thermal_efficiency" not in project
                        and self.thermal_vintages.available(project["decision_year"], project["tech"])):
                    project["gross_thermal_efficiency"] = self.thermal_vintages.new_gross_efficiencies[project["tech"]]
