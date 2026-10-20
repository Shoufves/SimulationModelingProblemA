"""Explicit policy adapter between nominal public finance and model real cash.

All inputs are supplied by the caller; there is no invented national eligibility,
default budget, default tax rate or replacement of missing years. Energy tariffs
must exclude the subsidy booked here and be expressed per gross model MWh in
2024 CNY. A deployment must separately reconcile its physical metering basis.
"""
from copy import deepcopy
from math import fsum,isfinite

from .q2_subsidies import SupportTerms,SubsidyFund,accrue,nonnegative
from .q2_support_investment import NewProjectSupport


class AnnualRevenuePolicy:
    def __init__(self, *, energy_tariffs, annual_funding, support_rates,
                 positions, opening_cash_cny, opening_payables, initial_year,
                 real_2024_per_nominal, metering_fraction, evidence, new_support=None):
        if not isinstance(evidence,str) or not evidence.strip():
            raise ValueError("Revenue policy requires explicit evidence/assumptions")
        self.evidence=evidence
        self.energy_tariffs=deepcopy(energy_tariffs)
        self.annual_funding=deepcopy(annual_funding)
        self.support_rates=deepcopy(support_rates)
        self.deflators=deepcopy(real_2024_per_nominal)
        self.metering_fraction=deepcopy(metering_fraction)
        self.positions=deepcopy(positions)
        if new_support is not None and not isinstance(new_support,NewProjectSupport):
            raise ValueError("Expected explicit new-project support programme")
        self.new_support=deepcopy(new_support)
        self.fund=SubsidyFund(opening_cash_cny=opening_cash_cny,
                              opening_payables=opening_payables,initial_year=initial_year)
        self.history=[]
        ids=set()
        for position in self.positions:
            if set(position)!={"terms","prior_lifetime_mwh"} or not isinstance(position["terms"],SupportTerms):
                raise ValueError("Support positions require terms and explicit lifetime history")
            terms=position["terms"]
            if terms.project in ids:
                raise ValueError("Duplicate supported project")
            ids.add(terms.project)
            nonnegative(position["prior_lifetime_mwh"],"initial metered lifetime output")
        for year,values in self.energy_tariffs.items():
            for tech,value in values.items():
                nonnegative(value,f"energy tariff {year}/{tech}")
        for year,value in self.deflators.items():
            if nonnegative(value,f"deflator {year}")==0:
                raise ValueError("Deflator must be positive")
        for year,values in self.metering_fraction.items():
            for tech,value in values.items():
                if nonnegative(value,f"meter fraction {year}/{tech}")>1:
                    raise ValueError("Metered export fraction exceeds gross generation")

    def energy_tariff(self,year,tech):
        try:
            return self.energy_tariffs[year][tech]
        except KeyError as exc:
            raise ValueError(f"Missing energy-only real gross-output tariff {year}/{tech}") from exc

    def export_fraction(self,year,tech):
        """Shared physical/billing boundary: all output net of station own use.

        Self-supply and distinct contract meters need separate explicit inputs;
        they cannot silently be treated as station auxiliaries by this adapter.
        """
        try:
            return self.metering_fraction[year][tech]
        except KeyError as exc:
            raise ValueError(f"Missing station export fraction {year}/{tech}") from exc

    def investment_value(self,model,tech,*,full_load_hours=None):
        if self.new_support is None:
            return 0.0
        from .q2_national import LEAD,LIFE
        hours=model.new_project_cf(tech)*8760 if full_load_hours is None else full_load_hours
        exposure=getattr(model,"annual_exposure",None)
        return self.new_support.pv_per_mw(year=model.year,tech=tech,lead=LEAD[tech],
            life=LIFE[tech],gross_full_load_hours=hours,discount_rate=model.a["discount_rate"],
            first_year_fraction=exposure.first_year_fraction if exposure else 1.0)

    def limit_awards(self,year,proposals,capacities):
        return capacities if self.new_support is None else self.new_support.limit(year,proposals,capacities)

    def register_project(self,project):
        if self.new_support is None:
            return
        position=self.new_support.register(project)
        if position:
            self.positions.append(position)

    def settle(self,model,outputs,*,cohort_outputs=None):
        """Pay once before debt service and investment, preserving counterparties.

        Actual receipts improve sponsor liquidity. They are deliberately NOT
        added to the old fleet's perpetual operating-margin forecast: a new
        project's eligibility cannot be inherited from an old subsidised plant.
        """
        year=model.year
        try:
            funding=self.annual_funding[year]
            factor=self.deflators[year]
            fractions=self.metering_fraction[year]
        except KeyError as exc:
            raise ValueError(f"Missing fiscal/meter/deflation input for {year}") from exc
        if set(funding)!={"levy_receipts_cny","treasury_transfer_cny","expenditure_limit_cny"}:
            raise ValueError("Funding must separate receipts, treasury transfer and expenditure authority")
        active={c["id"]:c for c in model.cohorts if c["status"]=="active"}
        weights={cid:1.0 for cid in active}
        if getattr(model,"annual_exposure",None) is not None:
            weighted=[(c,w) for tech in outputs for c,w in model.generation_assets(tech,year)]
            active={c["id"]:c for c,_ in weighted}
            weights={c["id"]:w for c,w in weighted}
        known={c["id"]:c for c in [*getattr(model,"projects",[]),*model.cohorts]}
        if any(c.actor not in model.generators for c in self.fund.payables):
            raise ValueError("Initial subsidy payable has an unknown generator owner")
        capacities={t:fsum(c["capacity_mw"]*weights[cid] for cid,c in active.items() if c["tech"]==t) for t in outputs}
        if cohort_outputs is not None:
            expected={cid for cid,c in active.items() if c["tech"] in {"wind","solar"}}
            if set(cohort_outputs)!=expected:
                raise ValueError("Renewable output allocation must cover exactly the active cohorts")
            for cid,value in cohort_outputs.items():
                nonnegative(value,"cohort gross output")
                if value>active[cid]["capacity_mw"]*weights[cid]*8760+1e-5:
                    raise ValueError("Cohort output exceeds annual operating exposure bound")
            for tech in ("wind","solar"):
                total=fsum(cohort_outputs[cid] for cid in expected if active[cid]["tech"]==tech)
                if abs(total-outputs[tech])>max(1e-5,outputs[tech]*1e-12):
                    raise ValueError("Cohort output differs from actual technology output")
        claims,closing=[],[]
        for position in self.positions:
            terms=position["terms"]
            if terms.actor not in model.generators:
                raise ValueError("Subsidy owner is not a model generator")
            if terms.project not in known or known[terms.project]["online_year"]!=terms.commissioned_year:
                raise ValueError("Supported project/commissioning date is absent or inconsistent")
            cohort=active.get(terms.project)
            metered=0.
            if cohort:
                if cohort["tech"]!=terms.actor or abs(cohort["capacity_mw"]-terms.capacity_mw)>max(1e-8,terms.capacity_mw*1e-12):
                    raise ValueError("Supported project capacity/owner differs from physical asset")
                fraction=nonnegative(fractions[terms.actor],"metering fraction")
                if fraction>1:
                    raise ValueError("Metered output exceeds gross output")
                # The offer freezes an EXPECTED export fraction for decision
                # NPV, not the plant's future measured auxiliary consumption.
                # Actual output uses the same annual meter as the physical bus.
                # The full lifetime-MWh cap and premium cap still bound the
                # commitment, even when actual exports exceed the expectation.
                gross=(cohort_outputs[terms.project] if cohort_outputs is not None and terms.actor in {"wind","solar"}
                       else (outputs[terms.actor]*cohort["capacity_mw"]*weights[terms.project]/capacities[terms.actor]
                             if capacities[terms.actor] else 0.0))
                metered=gross*fraction
            eligible=(terms.eligible and metered>0 and year>=max(terms.commissioned_year,terms.policy_start_year)
                      and year<terms.commissioned_year+terms.eligible_years)
            if eligible:
                if self.new_support and terms.project in self.new_support.awards:
                    rates=self.new_support.rates(year,terms.project)
                else:
                    try:
                        rates=self.support_rates[year][terms.project]
                    except KeyError as exc:
                        raise ValueError(f"Missing supported/reference tariff and VAT for {year}/{terms.project}") from exc
            else:
                # No entitlement outside eligibility; outstanding historical
                # receivables remain in the fund and may still receive cash.
                rates=dict(supported_tariff_cny_per_mwh=0,reference_tariff_cny_per_mwh=0,vat_rate=0)
            entitlement=accrue(terms,year=year,metered_mwh=metered,
                               prior_lifetime_mwh=position["prior_lifetime_mwh"],**rates)
            claims.append(entitlement["claim"])
            closing.append(entitlement["closing_lifetime_mwh"])
        # Validate cash origins before allowing the fund to mutate.
        levy=nonnegative(funding["levy_receipts_cny"],"levy receipts")*factor
        retail=fsum(r.get("retail_revenue_cny",0) for r in model.finance if r["year"]==year and r["kind"]=="grid_operation")
        if levy>retail+max(.01,retail*1e-12):
            raise ValueError("Levy component exceeds collected retail bills")
        # Work on a copy so later adapter validation cannot consume a year.
        candidate=deepcopy(self.fund)
        result=candidate.settle(year=year,claims=claims,**funding)
        paid={t:fsum(p["paid_cny"] for p in result["payments"] if p["actor"]==t)*factor for t in model.generators}
        if any(not isfinite(value) for value in paid.values()):
            raise ValueError("Non-finite deflated subsidy payment")
        journal=[]
        for item in result["journal"]:
            actor="grid" if item["actor"]=="levy_payers" else item["actor"]
            journal.append(dict(year=year,kind="subsidy_cash_transfer",actor=actor,
                cash_delta_cny=item["cash_delta_cny"]*factor,nominal_cash_delta_cny=item["cash_delta_cny"],
                resource_cost_cny=0,price_basis="2024_CNY",funding_basis="levy_is_component_of_existing_retail_bill",
                evidence=self.evidence))
        if any(not isfinite(r["cash_delta_cny"]) for r in journal):
            raise ValueError("Non-finite deflated counterparty transfer")
        closing_cash={t:model.generators[t].cash+value for t,value in paid.items()}
        if any(not isfinite(model.generators[t].cash) or not isfinite(value) for t,value in closing_cash.items()):
            raise ValueError("Non-finite generator closing cash")
        try:
            paid_real_total=fsum(paid.values())
            journal_residual=fsum(r["cash_delta_cny"] for r in journal)
        except OverflowError as exc:
            raise ValueError("Non-finite subsidy transfer aggregate") from exc
        if not isfinite(paid_real_total) or not isfinite(journal_residual):
            raise ValueError("Non-finite subsidy transfer aggregate")
        # Commit only after all adapter validations have passed.
        self.fund=candidate
        for position,lifetime in zip(self.positions,closing):
            position["prior_lifetime_mwh"]=lifetime
        for tech,value in closing_cash.items():
            model.generators[tech].cash=value
        model.finance.extend(journal)
        self.history.append(result)
        return dict(subsidy_entitlement_nominal_cny=result["new_entitlement_cny"],
                    subsidy_paid_nominal_cny=result["paid_cny"],
                    subsidy_arrears_nominal_cny=result["closing_arrears_cny"],
                    subsidy_fund_cash_nominal_cny=result["closing_cash_cny"],
                    subsidy_cash_transfer_residual_cny=journal_residual,
                    subsidy_paid_real_cny=paid_real_total)
