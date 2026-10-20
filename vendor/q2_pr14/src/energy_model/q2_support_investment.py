"""Explicit new-project offers and finite lifetime support commitments.

Offers are announced decision-year scenarios, not inferred national eligibility.
Nominal commitment authority is NOT cash and never funds construction. Actual
cash remains constrained by SubsidyFund at payment time. No future realised
price, output or payment observation is read when an investor forms an NPV.
"""
from copy import deepcopy
from dataclasses import dataclass
from math import fsum, isfinite

from .q2_subsidies import SupportTerms, integer, nonnegative
from .q2_exposure import AnnualExposure


@dataclass(frozen=True)
class SupportOffer:
    technology: str
    decision_year: int
    announced_year: int
    commissioning_deadline: int
    eligible_years: int
    lifetime_hours: float
    premium_cap_nominal_cny_per_mwh: float
    expected_premium_nominal_cny_per_mwh: float
    metering_fraction: float  # Decision-time expected net/gross ratio, not a fixed future meter.
    expected_collection_fraction: float
    expected_payment_delay_years: int
    expected_real_2024_per_nominal: float
    priority: int
    evidence: str

    def __post_init__(self):
        if not self.technology or not self.evidence:
            raise ValueError("Offer needs a technology and evidence/assumption")
        for name in ("decision_year", "announced_year", "commissioning_deadline",
                     "eligible_years", "expected_payment_delay_years", "priority"):
            integer(getattr(self, name), name)
        if self.announced_year > self.decision_year:
            raise ValueError("Future announcement cannot inform an earlier investment")
        if self.commissioning_deadline <= self.decision_year or self.eligible_years <= 0:
            raise ValueError("Invalid offer time window")
        if self.expected_payment_delay_years < 0 or self.priority < 0:
            raise ValueError("Invalid payment delay or priority")
        for name in ("lifetime_hours", "premium_cap_nominal_cny_per_mwh",
                     "metering_fraction", "expected_real_2024_per_nominal"):
            if nonnegative(getattr(self, name), name) == 0:
                raise ValueError("Offer parameter must be positive: " + name)
        nonnegative(self.expected_collection_fraction, "expected_collection_fraction")
        nonnegative(self.expected_premium_nominal_cny_per_mwh, "expected_premium")
        if self.expected_premium_nominal_cny_per_mwh > self.premium_cap_nominal_cny_per_mwh:
            raise ValueError("Expected premium exceeds authorised ceiling")
        if self.metering_fraction > 1 or self.expected_collection_fraction > 1:
            raise ValueError("Meter/collection fractions exceed one")
        if not isfinite(self.reserve_per_mw):
            raise ValueError("Non-finite nominal lifetime commitment")

    @property
    def reserve_per_mw(self):
        # This conservative entitlement ceiling is independent of optimistic
        # utilisation or assumed cash-payment fraction in the investment NPV.
        return self.lifetime_hours * self.premium_cap_nominal_cny_per_mwh

    def pv_per_mw(self, *, lead, life, gross_full_load_hours, discount_rate, first_year_fraction=1.0):
        integer(lead, "lead"); integer(life, "life")
        hours = nonnegative(gross_full_load_hours, "gross_full_load_hours")
        discount = nonnegative(discount_rate, "discount_rate")
        if lead <= 0 or life <= 0 or hours > 8760:
            raise ValueError("Invalid project life/lead/utilisation")
        exposure=AnnualExposure(first_year_fraction,self.evidence)
        if self.decision_year + lead > self.commissioning_deadline:
            return 0.0
        remaining = self.lifetime_hours
        discounted = []
        for age in range(min(life+1, self.eligible_years)):
            weight=exposure.weight(dict(online_year=0,exit_year=life),age)
            quantity = min(hours*self.metering_fraction*weight, remaining)
            remaining -= quantity
            discounted.append(quantity*self.expected_premium_nominal_cny_per_mwh
                *self.expected_collection_fraction*self.expected_real_2024_per_nominal
                /(1+discount)**(lead+age+self.expected_payment_delay_years))
        result = fsum(discounted)
        if not isfinite(result):
            raise ValueError("Non-finite support investment value")
        return result


class NewProjectSupport:
    """Pro-rata commitments across simultaneous eligible technology requests.

    Missing offers mean explicitly no award for that decision-year/technology.
    An offered year must have a stated finite commitment authority. No unused
    annual authority is carried forward; existing nominal commitments persist.
    Realised rates are separate from decision-time offers and must be supplied
    for every supported production year; a shortfall in cash does not erase debt.
    """
    def __init__(self, *, offers, commitment_authority_cny, actual_rates, evidence):
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError("New-project support requires evidence")
        self.evidence = evidence
        self.offers = {}
        self.authority = deepcopy(commitment_authority_cny)
        self.actual_rates = deepcopy(actual_rates)
        self.awards = {}
        self.reserved = {}
        for year, amount in self.authority.items():
            integer(year, "commitment year")
            nonnegative(amount, "commitment authority")
        for offer in offers:
            if not isinstance(offer, SupportOffer):
                raise ValueError("Expected explicit SupportOffer")
            key = offer.decision_year, offer.technology
            if key in self.offers or offer.decision_year not in self.authority:
                raise ValueError("Duplicate offer or missing commitment authority")
            self.offers[key] = offer

    def offer(self, year, tech, lead):
        integer(year, "decision year")
        integer(lead, "construction lead")
        if lead <= 0:
            raise ValueError("New-project support requires positive construction lead")
        found = self.offers.get((year, tech))
        return found if found and year+lead <= found.commissioning_deadline else None

    def pv_per_mw(self, *, year, tech, lead, life, gross_full_load_hours, discount_rate, first_year_fraction=1.0):
        offer = self.offer(year, tech, lead)
        if offer is None or self.authority[year] <= self.reserved.get(year, 0):
            return 0.0
        return offer.pv_per_mw(lead=lead, life=life,
            gross_full_load_hours=gross_full_load_hours, discount_rate=discount_rate,
            first_year_fraction=first_year_fraction)

    def limit(self, year, proposals, capacities):
        result = dict(capacities)
        quotes = {p["tech"]: self.offer(year, p["tech"], p["lead"]) for p in proposals}
        if len(quotes) != len(proposals):
            raise ValueError("Duplicate technology in simultaneous award requests")
        requested = fsum(nonnegative(result[t], "requested capacity")*o.reserve_per_mw
                         for t, o in quotes.items() if o)
        if not isfinite(requested):
            raise ValueError("Non-finite requested commitment")
        if not requested:
            return result
        available = max(0, self.authority[year]-self.reserved.get(year, 0))
        fraction = min(1, available/requested)
        for tech, offer in quotes.items():
            if offer:
                result[tech] *= fraction
        return result

    def register(self, project):
        year, tech = project["decision_year"], project["tech"]
        integer(project["online_year"], "commissioning year")
        offer = self.offer(year, tech, project["online_year"]-year)
        if "support_eligible" in project and type(project["support_eligible"]) is not bool:
            raise ValueError("Explicit support election must be boolean")
        if project.get("support_eligible") is False:
            return None
        if offer is None:
            return None
        project_id = project["id"]
        if project_id in self.awards:
            raise ValueError("Duplicate new-project support award")
        amount = nonnegative(project["capacity_mw"], "award capacity")*offer.reserve_per_mw
        closing = self.reserved.get(year, 0)+amount
        if not isfinite(closing) or closing > self.authority[year]+max(.000001, self.authority[year]*1e-12):
            raise ValueError("New subsidy promises exceed lifetime commitment authority")
        terms = SupportTerms(project_id, tech, True, project["online_year"],
            project["online_year"], offer.eligible_years, project["capacity_mw"],
            offer.lifetime_hours, offer.priority, offer.evidence)
        self.awards[project_id] = dict(offer=offer, reserved_nominal_cny=amount)
        self.reserved[year] = closing
        return dict(terms=terms, prior_lifetime_mwh=0.0)

    def rates(self, year, project):
        offer = self.awards[project]["offer"]
        try:
            rates = self.actual_rates[year][offer.technology]
        except KeyError as exc:
            raise ValueError(f"Missing actual support rates {year}/{offer.technology}") from exc
        required = {"supported_tariff_cny_per_mwh", "reference_tariff_cny_per_mwh", "vat_rate"}
        if set(rates) != required:
            raise ValueError("Actual support rates must explicitly state both tariffs and VAT")
        for name, value in rates.items():
            nonnegative(value, name)
        premium = max(0, rates["supported_tariff_cny_per_mwh"]-rates["reference_tariff_cny_per_mwh"])/(1+rates["vat_rate"])
        if premium > offer.premium_cap_nominal_cny_per_mwh+1e-9:
            raise ValueError("Actual premium exceeds reserved commitment; explicit reauthorisation required")
        return rates
