"""Optional regional two-way mechanism settlement, separate from subsidies.

No national parameters, eligibility inference, investment expectations or model
integration. Dates are actual dates; period ends are exclusive. Decimal amounts
are nominal CNY without an invented rounding or automatic netting rule.
"""
from dataclasses import dataclass
from calendar import monthrange
from datetime import date
from decimal import Decimal, DecimalException
from re import fullmatch
from types import MappingProxyType
from typing import Mapping


ZERO = Decimal("0")
DIRECTIONS = ("system_to_producer", "producer_to_system")


def _number(value, name, *, signed=False):
    if isinstance(value, bool):
        raise ValueError(name + " must be a finite number")
    try:
        result = +Decimal(str(value))
    except (DecimalException, ValueError, TypeError):
        raise ValueError(name + " must be a finite number") from None
    if not result.is_finite() or (not signed and result < 0):
        raise ValueError(name + " must be finite" + ("" if signed else " and nonnegative"))
    return result


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + " must be explicit")
    return value


def _date(value, name):
    if type(value) is not date:
        raise ValueError(name + " must be a date, not a promised date or timestamp")
    return value


def _month(value):
    if not isinstance(value, str) or not fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise ValueError("Quota month must be YYYY-MM")
    date.fromisoformat(value + "-01")
    return value


@dataclass(frozen=True)
class PriceBasis:
    """Both prices must use exactly the same currency, VAT and energy boundary."""
    currency: str
    tax_basis: str
    vat_rate: Decimal
    energy_basis: str

    def __post_init__(self):
        if self.currency != "nominal_CNY_per_MWh":
            raise ValueError("Explicit nominal_CNY_per_MWh prices required; convert kWh externally")
        if self.tax_basis not in {"vat_inclusive", "vat_exclusive"}:
            raise ValueError("Explicit VAT inclusion/exclusion required")
        rate = _number(self.vat_rate, "VAT rate")
        if rate > 1:
            raise ValueError("VAT rate must be a fraction")
        object.__setattr__(self, "vat_rate", rate)
        if self.energy_basis != "actual_net_export":
            raise ValueError("Only actual_net_export energy prices and metering are supported")


@dataclass(frozen=True)
class CfdContract:
    project_id: str
    producer_id: str
    region: str
    technology: str
    eligible: bool
    eligibility_evidence: str
    actual_commissioning_date: date | None
    commissioning_evidence: str
    mechanism_start: date
    mechanism_end_exclusive: date
    mechanism_price_cny_per_mwh: Decimal
    price_basis: PriceBasis
    market_reference_method: str
    negative_market_price_rule: str
    negative_price_rule_evidence: str
    annual_caps_mwh: Mapping[int, Decimal]
    monthly_caps_mwh: Mapping[str, Decimal]

    def __post_init__(self):
        for key in ("project_id", "producer_id", "region", "eligibility_evidence",
                    "market_reference_method", "negative_price_rule_evidence"):
            _text(getattr(self, key), key)
        if self.technology not in {"wind", "solar"} or type(self.eligible) is not bool:
            raise ValueError("Explicit wind/solar eligibility required")
        if self.actual_commissioning_date is not None:
            _date(self.actual_commissioning_date, "actual commissioning")
            _text(self.commissioning_evidence, "actual commissioning evidence")
        _date(self.mechanism_start, "mechanism start")
        _date(self.mechanism_end_exclusive, "mechanism end")
        if self.mechanism_start >= self.mechanism_end_exclusive:
            raise ValueError("Mechanism term must be a nonempty date interval")
        if not isinstance(self.price_basis, PriceBasis):
            raise ValueError("Explicit price basis required")
        object.__setattr__(self, "mechanism_price_cny_per_mwh",
                           _number(self.mechanism_price_cny_per_mwh, "mechanism price"))
        if self.negative_market_price_rule not in {"allow_signed", "reject_negative"}:
            raise ValueError("Negative-price rule must explicitly allow or reject signed prices")
        if not isinstance(self.annual_caps_mwh, Mapping) or not isinstance(self.monthly_caps_mwh, Mapping):
            raise ValueError("Explicit annual and monthly volume schedules required")
        annual = {}
        for year, cap in self.annual_caps_mwh.items():
            if type(year) is not int or not 1 <= year <= 9999:
                raise ValueError("Calendar-year quotas require integer years")
            annual[year] = _number(cap, "annual cap")
        monthly = {}
        for month, cap in self.monthly_caps_mwh.items():
            _month(month)
            if int(month[:4]) not in annual:
                raise ValueError("Every monthly quota requires an explicit annual quota")
            monthly[month] = _number(cap, "monthly cap")
        # Own immutable schedules: mutating a caller's dictionary cannot revise
        # already accrued rights or silently change the contract.
        object.__setattr__(self, "annual_caps_mwh", MappingProxyType(annual))
        object.__setattr__(self, "monthly_caps_mwh", MappingProxyType(monthly))


@dataclass(frozen=True)
class MeteredPeriod:
    project_id: str
    region: str
    start: date
    end_exclusive: date
    actual_net_export_mwh: Decimal
    eligible_net_export_mwh: Decimal
    claimed_mechanism_mwh: Decimal
    meter_evidence: str
    market_reference_cny_per_mwh: Decimal
    market_reference_month: str
    market_reference_method: str
    price_basis: PriceBasis
    green_certificate_revenue_on_claim_cny: Decimal
    other_difference_settlement_on_claim_cny: Decimal


def quote_settlement(contract, meter):
    """Pure accrual quote; cumulative quota and duplicate checks are in ledger."""
    if not isinstance(contract, CfdContract) or not isinstance(meter, MeteredPeriod):
        raise ValueError("CfdContract and MeteredPeriod required")
    if meter.project_id != contract.project_id or meter.region != contract.region:
        raise ValueError("Project and regional contract must match")
    if not contract.eligible or contract.actual_commissioning_date is None:
        raise ValueError("Verified eligibility and actual commissioning required")
    _date(meter.start, "meter start")
    _date(meter.end_exclusive, "meter end")
    if meter.start >= meter.end_exclusive:
        raise ValueError("Meter period must be nonempty")
    month = meter.start.strftime("%Y-%m")
    last_day = date.fromordinal(meter.end_exclusive.toordinal()-1)
    if last_day.strftime("%Y-%m") != month:
        raise ValueError("Split metering at calendar-month boundaries")
    if (meter.start < max(contract.mechanism_start, contract.actual_commissioning_date)
            or meter.end_exclusive > contract.mechanism_end_exclusive):
        raise ValueError("Meter interval lies outside actual commissioning or mechanism term")
    if month not in contract.monthly_caps_mwh or meter.start.year not in contract.annual_caps_mwh:
        raise ValueError("Missing explicit annual/monthly mechanism quota")
    if meter.price_basis != contract.price_basis:
        raise ValueError("Reference and mechanism prices require identical VAT, units and energy boundary")
    if (meter.market_reference_method != contract.market_reference_method
            or meter.market_reference_month != month):
        raise ValueError("Market reference methodology and month must match the contract")
    _text(meter.meter_evidence, "actual meter evidence")
    actual = _number(meter.actual_net_export_mwh, "actual net export")
    eligible = _number(meter.eligible_net_export_mwh, "eligible net export")
    volume = _number(meter.claimed_mechanism_mwh, "claimed mechanism volume")
    if not volume <= eligible <= actual:
        raise ValueError("Claim must not exceed eligible actual net export")
    if volume > min(contract.monthly_caps_mwh[month], contract.annual_caps_mwh[meter.start.year]):
        raise ValueError("Claim exceeds an annual/monthly mechanism quota")
    certificates = _number(meter.green_certificate_revenue_on_claim_cny, "certificate income on claim")
    other = _number(meter.other_difference_settlement_on_claim_cny, "other difference settlement", signed=True)
    if volume and (certificates or other):
        raise ValueError("Claimed mechanism volume cannot duplicate green-certificate or other difference income")
    market = _number(meter.market_reference_cny_per_mwh, "market reference price", signed=True)
    if market < 0 and contract.negative_market_price_rule == "reject_negative":
        raise ValueError("Contract has no authority to settle negative market reference prices")
    try:
        amount = _number((contract.mechanism_price_cny_per_mwh-market)*volume,
                         "mechanism difference", signed=True)
    except DecimalException:
        raise ValueError("Mechanism amount must be finite") from None
    return dict(project_id=contract.project_id, producer_id=contract.producer_id,
        region=contract.region, start=meter.start, end_exclusive=meter.end_exclusive,
        month=month, year=meter.start.year, actual_net_export_mwh=actual,
        eligible_net_export_mwh=eligible, mechanism_volume_mwh=volume,
        mechanism_price_cny_per_mwh=contract.mechanism_price_cny_per_mwh,
        market_reference_cny_per_mwh=market, signed_producer_accrual_cny=amount,
        direction="system_to_producer" if amount >= 0 else "producer_to_system",
        amount_cny=abs(amount), meter_evidence=meter.meter_evidence,
        market_reference_method=contract.market_reference_method,
        price_basis=contract.price_basis, negative_market_price_rule=contract.negative_market_price_rule,
        accounting_kind="regional_system_operating_cost_cfd_not_fiscal_subsidy")


@dataclass(frozen=True)
class OpeningObligation:
    obligation_id: str
    project_id: str
    direction: str
    amount_cny: Decimal
    accrued_on: date
    evidence: str


class CfdLedger:
    """Cash-limited gross obligations; no automatic writeoff or cross-netting.

    Caller chooses payment order and supplies documented system-cost collections
    or producer liquidity. This is an accounting mechanism, not a tariff, funding
    forecast, or assumed public fiscal appropriation.
    """
    def __init__(self, *, region, opening_date, contracts, opening_system_cash_cny,
                 opening_producer_cash_cny, opening_obligations,
                 opening_year_used_mwh, opening_month_used_mwh):
        self.region = _text(region, "ledger region")
        self.opening_date = self.as_of = _date(opening_date, "opening date")
        self._contracts = {}
        for contract in contracts:
            if (not isinstance(contract, CfdContract) or contract.region != region
                    or contract.project_id in self._contracts):
                raise ValueError("Contracts must be unique projects in the ledger region")
            self._contracts[contract.project_id] = contract
        owners = {c.producer_id for c in self._contracts.values()}
        if "system" in owners:
            raise ValueError("Producer identity cannot be the reserved system counterparty")
        if set(opening_producer_cash_cny) != owners:
            raise ValueError("Opening producer balances must exactly cover contract owners")
        self._system_cash = _number(opening_system_cash_cny, "system opening cash")
        self._producer_cash = {k: _number(v, "producer opening cash")
                               for k, v in opening_producer_cash_cny.items()}
        self._obligations, self._settlements, self._cash_events, self._payments = {}, [], [], []
        self._annual_used, self._monthly_used = {}, {}
        projects = set(self._contracts)
        if (not isinstance(opening_year_used_mwh, Mapping)
                or not isinstance(opening_month_used_mwh, Mapping)
                or set(opening_year_used_mwh) != projects or set(opening_month_used_mwh) != projects):
            raise ValueError("Explicit opening year/month used volumes must cover every project exactly")
        year, month = opening_date.year, opening_date.strftime("%Y-%m")
        year_start = date(year, 1, 1)
        month_start = opening_date.replace(day=1)
        for project, c in self._contracts.items():
            a = _number(opening_year_used_mwh[project], "opening year used volume")
            m = _number(opening_month_used_mwh[project], "opening month used volume")
            if (m > a or a > c.annual_caps_mwh.get(year, ZERO)
                    or m > c.monthly_caps_mwh.get(month, ZERO)):
                raise ValueError("Opening usage exceeds year/month quotas or monthly usage exceeds year total")
            active_start = (max(c.mechanism_start, c.actual_commissioning_date)
                            if c.actual_commissioning_date is not None else None)
            if a and (active_start is None or min(c.mechanism_end_exclusive, opening_date)
                      <= max(active_start, year_start)):
                raise ValueError("Opening year usage predates actual commissioning or mechanism operation")
            if m and (active_start is None or min(c.mechanism_end_exclusive, opening_date)
                      <= max(active_start, month_start)):
                raise ValueError("Opening month usage has no elapsed eligible metering interval")
            prior_caps = ZERO
            for key, cap in c.monthly_caps_mwh.items():
                if int(key[:4]) != year or key >= month or active_start is None:
                    continue
                start = date.fromisoformat(key+"-01")
                last = date(year, start.month, monthrange(year, start.month)[1])
                if last >= active_start and start < c.mechanism_end_exclusive:
                    prior_caps += cap
            if a > prior_caps+m:
                raise ValueError("Opening year usage cannot exceed preceding month quotas plus current month usage")
            self._annual_used[project, year] = a
            self._monthly_used[project, month] = m
        self._opening_total_cash = _number(self._system_cash+sum(self._producer_cash.values(), ZERO),
                                           "total opening cash")
        self._external_cash = ZERO
        for claim in opening_obligations:
            if not isinstance(claim, OpeningObligation):
                raise ValueError("Explicit historical OpeningObligation required")
            _text(claim.obligation_id, "opening obligation id")
            if claim.project_id not in self._contracts or claim.obligation_id in self._obligations:
                raise ValueError("Unknown project or duplicate opening obligation")
            if claim.direction not in DIRECTIONS:
                raise ValueError("Unknown obligation direction")
            if _date(claim.accrued_on, "opening accrual") > opening_date:
                raise ValueError("Opening obligations cannot include future accruals")
            _text(claim.evidence, "opening obligation evidence")
            amount = _number(claim.amount_cny, "opening obligation")
            self._obligations[claim.obligation_id] = dict(
                project_id=claim.project_id, direction=claim.direction, accrued_on=claim.accrued_on,
                original_cny=amount, paid_cny=ZERO, outstanding_cny=amount, evidence=claim.evidence)

    def _time(self, on):
        if _date(on, "posting date") < self.as_of:
            raise ValueError("Ledger postings must be chronological")

    def accrue(self, meter, *, posting_date):
        """Recognise full obligation even when the payer has insufficient cash."""
        self._time(posting_date)
        if not isinstance(meter, MeteredPeriod) or meter.project_id not in self._contracts:
            raise ValueError("Unknown project or missing metered period")
        quote = quote_settlement(self._contracts[meter.project_id], meter)
        if posting_date < meter.end_exclusive or meter.start < self.opening_date:
            raise ValueError("Final metering must precede posting and not precede ledger opening")
        for old in self._settlements:
            if (old["project_id"] == meter.project_id
                    and meter.start < old["end_exclusive"] and old["start"] < meter.end_exclusive):
                raise ValueError("Duplicate or overlapping project metering interval")
        annual = (meter.project_id, quote["year"])
        monthly = (meter.project_id, quote["month"])
        volume = quote["mechanism_volume_mwh"]
        a = _number(self._annual_used.get(annual, ZERO)+volume, "annual used volume")
        m = _number(self._monthly_used.get(monthly, ZERO)+volume, "monthly used volume")
        contract = self._contracts[meter.project_id]
        if a > contract.annual_caps_mwh[quote["year"]] or m > contract.monthly_caps_mwh[quote["month"]]:
            raise ValueError("Cumulative annual/monthly mechanism quota exceeded")
        obligation_id = f"settlement/{meter.project_id}/{meter.start.isoformat()}/{meter.end_exclusive.isoformat()}"
        if obligation_id in self._obligations:
            raise ValueError("Duplicate obligation id")
        record = dict(quote, obligation_id=obligation_id, accrued_on=posting_date)
        self._annual_used[annual], self._monthly_used[monthly] = a, m
        self._settlements.append(record)
        self._obligations[obligation_id] = dict(project_id=meter.project_id,
            direction=quote["direction"], accrued_on=posting_date,
            original_cny=quote["amount_cny"], paid_cny=ZERO,
            outstanding_cny=quote["amount_cny"], evidence=meter.meter_evidence)
        self.as_of = posting_date
        return dict(record)

    def add_cash(self, *, party, amount_cny, on, evidence):
        """External liquidity, never inferred from a mechanism award or invoice."""
        self._time(on)
        _text(evidence, "cash source evidence")
        amount = _number(amount_cny, "cash receipt")
        if party != "system" and party not in self._producer_cash:
            raise ValueError("Unknown cash counterparty")
        opening = self._system_cash if party == "system" else self._producer_cash[party]
        closing = _number(opening+amount, "closing cash")
        external = _number(self._external_cash+amount, "cumulative external cash")
        if party == "system":
            self._system_cash = closing
        else:
            self._producer_cash[party] = closing
        self._external_cash = external
        self.as_of = on
        self._cash_events.append(dict(party=party, amount_cny=amount, on=on, evidence=evidence))
        return self.balances()

    def pay(self, obligation_id, *, requested_cny, on):
        self._time(on)
        if obligation_id not in self._obligations:
            raise ValueError("Unknown payment obligation")
        claim = self._obligations[obligation_id]
        requested = _number(requested_cny, "requested payment")
        if requested > claim["outstanding_cny"]:
            raise ValueError("Payment request exceeds outstanding obligation")
        owner = self._contracts[claim["project_id"]].producer_id
        to_producer = claim["direction"] == "system_to_producer"
        payer = self._system_cash if to_producer else self._producer_cash[owner]
        paid = min(requested, payer)
        system = _number(self._system_cash+(-paid if to_producer else paid), "system cash")
        producer = _number(self._producer_cash[owner]+(paid if to_producer else -paid), "producer cash")
        cumulative = _number(claim["paid_cny"]+paid, "cumulative paid")
        outstanding = _number(claim["outstanding_cny"]-paid, "outstanding obligation")
        self._system_cash, self._producer_cash[owner] = system, producer
        claim["paid_cny"], claim["outstanding_cny"] = cumulative, outstanding
        self.as_of = on
        record = dict(obligation_id=obligation_id, direction=claim["direction"], on=on,
                    paid_cny=paid, outstanding_cny=outstanding,
                    system_cash_delta_cny=-paid if to_producer else paid,
                    producer_cash_delta_cny=paid if to_producer else -paid)
        self._payments.append(record)
        return dict(record)

    def balances(self):
        producers = {p: dict(cash_cny=c, receivable_cny=ZERO, payable_cny=ZERO)
                     for p, c in self._producer_cash.items()}
        for claim in self._obligations.values():
            owner = self._contracts[claim["project_id"]].producer_id
            field = "receivable_cny" if claim["direction"] == "system_to_producer" else "payable_cny"
            producers[owner][field] += claim["outstanding_cny"]
        receivable = sum((p["payable_cny"] for p in producers.values()), ZERO)
        payable = sum((p["receivable_cny"] for p in producers.values()), ZERO)
        cash = self._system_cash+sum(self._producer_cash.values(), ZERO)
        return dict(as_of=self.as_of,
            system=dict(cash_cny=self._system_cash, receivable_cny=receivable, payable_cny=payable),
            producers=producers, external_cash_receipts_cny=self._external_cash,
            cash_conservation_residual_cny=cash-self._opening_total_cash-self._external_cash,
            fiscal_subsidy_accrual_cny=ZERO,
            accounting_kind="regional_system_operating_cost_cfd_not_fiscal_subsidy")

    @property
    def volume_usage(self):
        return dict(
            annual=tuple(dict(project_id=p, year=y, used_mwh=v)
                         for (p, y), v in sorted(self._annual_used.items())),
            monthly=tuple(dict(project_id=p, month=m, used_mwh=v)
                          for (p, m), v in sorted(self._monthly_used.items())))

    @property
    def obligations(self):
        return {k: dict(v) for k, v in self._obligations.items()}

    @property
    def settlements(self):
        return tuple(dict(row) for row in self._settlements)

    @property
    def payments(self):
        return tuple(dict(row) for row in self._payments)

    @property
    def cash_events(self):
        return tuple(dict(row) for row in self._cash_events)
