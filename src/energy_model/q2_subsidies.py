"""Finite public subsidy cash and project entitlements, in nominal CNY.

No national eligibility, tax rate, initial arrears or fiscal budget is inferred
here. Callers must provide reviewed data or separately disclosed assumptions.
This module is a settlement mechanism, not evidence that every project qualifies.
Receivables survive retirement/expiry; they are never spendable sponsor cash.
"""
from dataclasses import dataclass, replace
from math import fsum, isfinite, nextafter


def nonnegative(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and nonnegative")
    return float(value)


def integer(value, name):
    if type(value) is not int:
        raise ValueError(f"{name} must be an integer")
    return value


@dataclass(frozen=True)
class SupportTerms:
    project: str
    actor: str
    eligible: bool
    commissioned_year: int
    policy_start_year: int
    eligible_years: int
    capacity_mw: float
    lifetime_hours: float
    priority: int
    evidence: str

    def __post_init__(self):
        if not self.project or not self.actor or not self.evidence:
            raise ValueError("Project, owner and evidence/assumption reference are required")
        if type(self.eligible) is not bool:
            raise ValueError("Eligibility must be explicit")
        for name in ("commissioned_year", "policy_start_year", "eligible_years", "priority"):
            integer(getattr(self, name), name)
        if self.eligible_years <= 0 or self.priority < 0:
            raise ValueError("Invalid duration/priority")
        for name in ("capacity_mw", "lifetime_hours"):
            if nonnegative(getattr(self, name), name) == 0:
                raise ValueError(f"{name} must be positive")
        if not isfinite(self.capacity_mw*self.lifetime_hours):
            raise ValueError("Non-finite lifetime allowance")


@dataclass(frozen=True)
class Claim:
    project: str
    actor: str
    accrued_year: int
    priority: int
    amount_cny: float

    def __post_init__(self):
        if not self.project or not self.actor:
            raise ValueError("A subsidy claim needs a project and recipient")
        integer(self.accrued_year, "accrued_year")
        integer(self.priority, "priority")
        if self.priority < 0:
            raise ValueError("Negative claim priority")
        nonnegative(self.amount_cny, "amount_cny")


def accrue(terms, *, year, metered_mwh, prior_lifetime_mwh,
           supported_tariff_cny_per_mwh, reference_tariff_cny_per_mwh, vat_rate):
    """Accrue under supplied terms, with explicit lifetime history and meter.

    Annual boundary convention: online-year is year 0, expiry-year is excluded.
    The caller must disclose any approximation to actual commissioning dates.
    Count all qualifying-meter output in lifetime history, including output
    before the policy becomes effective. Do not reset it when a rule changes.
    Supported and reference prices both include VAT and use the same price year.
    """
    integer(year, "year")
    output = nonnegative(metered_mwh, "metered_mwh")
    prior = nonnegative(prior_lifetime_mwh, "prior_lifetime_mwh")
    supported = nonnegative(supported_tariff_cny_per_mwh, "supported tariff")
    reference = nonnegative(reference_tariff_cny_per_mwh, "reference tariff")
    vat = nonnegative(vat_rate, "VAT rate")
    if year < terms.commissioned_year and output:
        raise ValueError("Output before commissioning")
    eligible = (terms.eligible and year >= max(terms.policy_start_year,terms.commissioned_year)
                and year < terms.commissioned_year+terms.eligible_years)
    allowance = max(0,terms.capacity_mw*terms.lifetime_hours-prior)
    quantity = min(output,allowance) if eligible else 0.0
    premium = max(0,supported-reference)/(1+vat)
    amount = quantity*premium
    if not isfinite(prior+output) or not isfinite(amount):
        raise ValueError("Non-finite subsidy accrual")
    return dict(claim=Claim(terms.project,terms.actor,year,terms.priority,amount),
                eligible_mwh=quantity,closing_lifetime_mwh=prior+output,
                premium_ex_vat_cny_per_mwh=premium)


def billed_energy_revenue(*, gross_mwh, own_use_fraction, tariff_vat_inclusive, vat_rate):
    """Net exported electricity revenue; excludes any separate subsidy claim.

    Pass the energy/reference tariff, not an all-in subsidised tariff, when
    accruing support separately. Full tax accounting/input credits remain the
    caller's responsibility; this is an explicit ex-VAT comparison convention.
    """
    gross = nonnegative(gross_mwh,"gross_mwh")
    own = nonnegative(own_use_fraction,"own_use_fraction")
    price = nonnegative(tariff_vat_inclusive,"tariff_vat_inclusive")
    vat = nonnegative(vat_rate,"vat_rate")
    if own > 1:
        raise ValueError("Own-use fraction exceeds gross output")
    amount = gross*(1-own)*price/(1+vat)
    if not isfinite(amount):
        raise ValueError("Non-finite billed energy revenue")
    return amount


class SubsidyFund:
    """Cash-limited annual clearing with explicit initial payables.

    Allocation is declared policy priority first, then oldest accrual year,
    then pro-rata within the same tier. This is a research allocation rule,
    not an assertion of the actual nationwide historical payment sequence.
    Nominal arrears are preserved; deflate cash at PAYMENT year in the model.
    """
    def __init__(self, *, opening_cash_cny, opening_payables, initial_year):
        self.cash = nonnegative(opening_cash_cny,"opening_cash_cny")
        integer(initial_year,"initial_year")
        self.last_year = initial_year
        self.payables = list(opening_payables)
        self.history = []
        self._seen = set()
        self._owners = {}
        for claim in self.payables:
            if not isinstance(claim,Claim) or claim.accrued_year > initial_year:
                raise ValueError("Initial payables must be dated historical claims")
            key = (claim.project,claim.accrued_year)
            if key in self._seen:
                raise ValueError("Duplicate initial claim")
            self._seen.add(key)
            self._validate_owner(claim,self._owners)

    @staticmethod
    def _validate_owner(claim,owners):
        identity = (claim.actor,claim.priority)
        if claim.project in owners and owners[claim.project] != identity:
            raise ValueError("Project owner/priority changed without explicit transfer")
        owners[claim.project] = identity

    def settle(self, *, year, claims, levy_receipts_cny, treasury_transfer_cny, expenditure_limit_cny):
        integer(year,"year")
        if year != self.last_year+1:
            raise ValueError("Fund settlements must be consecutive; no repeated/missing year")
        levy = nonnegative(levy_receipts_cny,"levy_receipts_cny")
        treasury = nonnegative(treasury_transfer_cny,"treasury_transfer_cny")
        limit = nonnegative(expenditure_limit_cny,"expenditure_limit_cny")
        incoming = list(claims)
        seen,owners = set(self._seen),dict(self._owners)
        for claim in incoming:
            if not isinstance(claim,Claim) or claim.accrued_year != year:
                raise ValueError("Current claims must belong to this settlement year")
            key = (claim.project,claim.accrued_year)
            if key in seen:
                raise ValueError("Duplicate subsidy accrual")
            seen.add(key)
            self._validate_owner(claim,owners)
        opening_cash, opening_arrears = self.cash,fsum(c.amount_cny for c in self.payables)
        available = opening_cash+levy+treasury
        new_entitlement = fsum(c.amount_cny for c in incoming)
        nonnegative(available,"available cash")
        nonnegative(opening_arrears+new_entitlement,"total entitlement")
        payment_ceiling = min(available,limit)
        remaining_budget = payment_ceiling
        pending, payments = [], []
        all_claims = sorted(self.payables+incoming,key=lambda c:(c.priority,c.accrued_year,c.project))
        tiers = sorted(set((c.priority,c.accrued_year) for c in all_claims))
        for tier in tiers:
            group = [c for c in all_claims if (c.priority,c.accrued_year)==tier]
            total = fsum(c.amount_cny for c in group)
            fraction = min(1,remaining_budget/total) if total else 0
            tier_payments = [min(claim.amount_cny,claim.amount_cny*fraction) for claim in group]
            # Pro-rata floating multiplication can exceed a binding cash or
            # authority ceiling by one ULP. Keep the actual ledger bounded,
            # rather than just relaxing the invariant or clipping its total.
            previous_paid = [p["paid_cny"] for p in payments]
            while fsum(previous_paid+tier_payments)>payment_ceiling:
                excess=fsum(previous_paid+tier_payments)-payment_ceiling
                index=max(range(len(tier_payments)),key=tier_payments.__getitem__)
                tier_payments[index]=max(0,nextafter(tier_payments[index]-excess,0))
            for claim,paid in zip(group,tier_payments):
                if claim.amount_cny-paid > 0:
                    pending.append(replace(claim,amount_cny=claim.amount_cny-paid))
                payments.append(dict(project=claim.project,actor=claim.actor,
                    accrued_year=claim.accrued_year,paid_cny=paid,closing_payable_cny=claim.amount_cny-paid))
            remaining_budget = max(0,payment_ceiling-fsum(p["paid_cny"] for p in payments))
        paid = fsum(p["paid_cny"] for p in payments)
        closing_cash = available-paid
        closing_arrears = fsum(c.amount_cny for c in pending)
        tolerance = max(.000001,available*1e-12,(opening_arrears+new_entitlement)*1e-12)
        if closing_cash < -tolerance or paid > limit+tolerance:
            raise ValueError("Unfunded subsidy payment")
        payable_residual = opening_arrears+new_entitlement-paid-closing_arrears
        if abs(payable_residual)>tolerance:
            raise ValueError("Subsidy payable conservation failed")
        journal = [dict(actor="levy_payers",cash_delta_cny=-levy,resource_cost_cny=0),
                   dict(actor="treasury",cash_delta_cny=-treasury,resource_cost_cny=0),
                   dict(actor="subsidy_fund",cash_delta_cny=levy+treasury-paid,resource_cost_cny=0)]
        recipients = sorted(set(p["actor"] for p in payments))
        journal.extend(dict(actor=actor,cash_delta_cny=fsum(p["paid_cny"] for p in payments if p["actor"]==actor),
                            resource_cost_cny=0) for actor in recipients)
        cash_residual = fsum(r["cash_delta_cny"] for r in journal)
        if abs(cash_residual)>tolerance:
            raise ValueError("Subsidy transfer conservation failed")
        result = dict(year=year,opening_cash_cny=opening_cash,levy_receipts_cny=levy,treasury_transfer_cny=treasury,
            expenditure_limit_cny=limit,opening_arrears_cny=opening_arrears,new_entitlement_cny=new_entitlement,
            paid_cny=paid,closing_cash_cny=closing_cash,closing_arrears_cny=closing_arrears,
            cash_balance_residual_cny=cash_residual,payable_balance_residual_cny=payable_residual,
            payments=payments,journal=journal,price_basis="nominal_CNY_at_accrual_or_payment_year_as_labelled")
        # Commit only after every input and invariant has passed.
        self.cash,self.payables,self.last_year = closing_cash,pending,year
        self._seen,self._owners = seen,owners
        self.history.append(result)
        return result
