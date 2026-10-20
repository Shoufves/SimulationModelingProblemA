"""Conditional whole-project bioenergy composition and municipal service cash.

The statistical bioenergy bucket is preserved. This interface explicitly assumes
it includes whole MSW plants; it is NOT the alternative renewable-only EI mapping.
One fixed fuel-energy recipe and common conversion efficiency are used. Waste
delivery, contract funding, and paid service are finite. No heat revenue is
credited without a separate useful-heat conversion and customer.
"""
from copy import deepcopy
from math import fsum,isfinite
from .q2_subsidies import SubsidyFund,Claim,nonnegative,integer


class CompositeBioenergy:
    def __init__(self, *, waste_fuel_fraction, waste_fossil_energy_fraction,
                 fossil_co2_t_per_mwh_whole_waste, waste_lhv_mwh_per_t,
                 waste_delivery_t_by_year, treatment_fee_real_cny_per_t,
                 municipal_appropriation_real_cny_by_year, expected_collection_fraction,
                 initial_year, evidence):
        if not evidence:
            raise ValueError("Bioenergy composition requires evidence and assumptions")
        self.evidence=evidence
        self.waste_fraction=nonnegative(waste_fuel_fraction,"waste fuel fraction")
        self.fossil_fraction=nonnegative(waste_fossil_energy_fraction,"waste fossil energy fraction")
        self.ef=nonnegative(fossil_co2_t_per_mwh_whole_waste,"whole waste fossil EF")
        self.lhv=nonnegative(waste_lhv_mwh_per_t,"waste LHV")
        self.expected_collection=nonnegative(expected_collection_fraction,"expected municipal collection")
        if not 0<self.waste_fraction<=1 or self.fossil_fraction>1 or not self.lhv or self.expected_collection>1:
            raise ValueError("Invalid waste fractions or calorific value")
        if self.ef>0 and self.fossil_fraction==0:
            raise ValueError("Positive fossil emissions with zero fossil energy")
        self.delivery=deepcopy(waste_delivery_t_by_year)
        self.fees=deepcopy(treatment_fee_real_cny_per_t)
        self.funding=deepcopy(municipal_appropriation_real_cny_by_year)
        if not self.delivery or set(self.delivery)!=set(self.fees) or set(self.delivery)!=set(self.funding):
            raise ValueError("Every year needs explicit delivery, fee and municipal funding")
        for mapping in (self.delivery,self.fees,self.funding):
            for year,value in mapping.items():integer(year,"year");nonnegative(value,"annual bioenergy input")
        self.fund=SubsidyFund(opening_cash_cny=0,opening_payables=[],initial_year=initial_year)
        self.history=[]

    def annual(self,year):
        try:return self.delivery[year],self.fees[year],self.funding[year]
        except KeyError as exc:raise ValueError(f"Missing municipal service inputs for {year}") from exc

    def expected_margin_per_mw(self,model,*,additional_capacity_mw=0):
        delivery,fee,funding=self.annual(model.year)
        if not delivery or not fee or not funding:return 0.0
        fuel=model.generators["biomass"].reference_cf*8760/model.efficiency["biomass"]
        capacity=nonnegative(model.generators["biomass"].capacity,"existing biomass capacity")
        from .q2_national import LEAD
        commissioning=model.year+LEAD["biomass"]
        if getattr(model,"annual_exposure",None) is not None:
            # Normalise first positive operating-year service to a full MW-year.
            commissioning+=int(model.annual_exposure.first_year_fraction==0)
            capacity=model.generation_capacity("biomass",commissioning)
            weight=model.annual_exposure.first_year_fraction or 1.0
        else:
            capacity+=fsum(nonnegative(p["capacity_mw"],"committed biomass capacity")
                for p in getattr(model,"projects",[]) if p["tech"]=="biomass" and p["status"]=="construction"
                and model.year<p["online_year"]<=commissioning)
            weight=1.0
        capacity+=nonnegative(additional_capacity_mw,"candidate biomass capacity")*weight
        if not capacity:return 0.0
        # Announced annual funding relative to the full deliverable service;
        # investors cannot treat a zero budget as assured service revenue.
        expected=min(self.expected_collection,funding/(delivery*fee))
        # The SAME finite delivery and funding must cover the fleet plus the
        # candidate. A small delivery cannot promise full-load service revenue
        # to every MW. This is a current-information persistence expectation,
        # not permission to consume future unobserved waste or cash.
        tonnes_per_mw=min(fuel*self.waste_fraction/self.lhv,delivery/capacity)
        return tonnes_per_mw*fee*expected

    def apply(self,model,op,*,year=None):
        tonnes,_,_=self.annual(model.year if year is None else year)
        # The supplier price was already blended at initialization. Free waste
        # procurement and its positive service fee must never both be encoded
        # as a negative fuel price plus another positive cash receipt.
        op["fuels"]["biomass"]["emission_t_per_mwh"]=self.waste_fraction*self.ef
        plant=op["plants"]["biomass"]
        bound=tonnes*self.lhv/self.waste_fraction*model.efficiency["biomass"]/365
        plant["window_energy_budget_mwh"]=min(plant["window_energy_budget_mwh"],bound)

    def physical(self,model,gross_mwh):
        total_fuel=gross_mwh/model.efficiency["biomass"]
        waste=total_fuel*self.waste_fraction
        fossil=waste*self.fossil_fraction
        tonnes=waste/self.lhv
        delivery,_,_=self.annual(model.year)
        if tonnes>delivery+max(1e-5,delivery*1e-10):
            raise ValueError("Waste treatment exceeds available physical delivery")
        return dict(bioenergy_fuel_input_mwh=total_fuel,msw_fuel_input_mwh=waste,
            msw_fossil_fuel_input_mwh=fossil,msw_treated_t=tonnes,
            msw_fossil_co2_t=waste*self.ef,
            bioenergy_physical_nonfossil_generation_mwh=gross_mwh*(1-self.waste_fraction*self.fossil_fraction),
            bioenergy_physical_fossil_generation_mwh=gross_mwh*self.waste_fraction*self.fossil_fraction,
            bioenergy_statistical_boundary="whole_project_bucket_with_explicit_internal_composition_assumption")

    def settle(self,model,gross_mwh):
        physical=self.physical(model,gross_mwh)
        _,fee,funding=self.annual(model.year)
        # Dedicated REAL-2024 municipal ledger. Reuse the tested finite-payable
        # machinery; it is not the nominal national renewable subsidy account.
        candidate=deepcopy(self.fund)
        claim=Claim("municipal_waste_treatment","biomass",model.year,0,physical["msw_treated_t"]*fee)
        result=candidate.settle(year=model.year,claims=[claim],levy_receipts_cny=0,
            treasury_transfer_cny=funding,expenditure_limit_cny=funding)
        result["price_basis"]="2024_CNY_municipal_service_not_national_subsidy"
        paid=result["paid_cny"]
        closing=model.generators["biomass"].cash+paid
        if not isfinite(closing):raise ValueError("Non-finite waste service cash")
        journal=[]
        for row in result["journal"]:
            actor={"treasury":"municipal_budget","subsidy_fund":"municipal_service_fund"}.get(row["actor"],row["actor"])
            journal.append(dict(year=model.year,kind="municipal_waste_service_cash",actor=actor,
                cash_delta_cny=row["cash_delta_cny"],resource_cost_cny=0,
                price_basis="2024_CNY",evidence=self.evidence))
        if abs(fsum(r["cash_delta_cny"] for r in journal))>max(.01,funding*1e-12):
            raise ValueError("Unbalanced municipal service cash")
        self.fund=candidate;self.history.append(result)
        model.generators["biomass"].cash=closing
        model.finance.extend(journal)
        return dict(msw_service_entitlement_real_cny=claim.amount_cny,
            msw_service_paid_real_cny=paid,msw_service_arrears_real_cny=result["closing_arrears_cny"],
            msw_municipal_fund_cash_real_cny=result["closing_cash_cny"])
