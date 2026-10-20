"""Explicit annual shared-market fuel prices, with no future-price oracle.

The current model has one supplier market per carrier. A power-plant index can
therefore enter only as a disclosed shared-market sensitivity, not a verified
price for industrial/household demand. Old model sources remain reproducible.
"""
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite

from .q2_portfolio import PortfolioNationalModel


@dataclass(frozen=True)
class FuelPriceObservation:
    year: int
    fuel: str
    real_2024_cny_per_mwh: float
    evidence: str
    scope: str

    def __post_init__(self):
        if type(self.year) is not int or self.year < 1900:
            raise ValueError("Invalid fuel-price year")
        if self.fuel not in {"coal", "gas", "oil"}:
            raise ValueError("Unsupported price carrier")
        price = self.real_2024_cny_per_mwh
        if type(price) not in (int, float) or not isfinite(price) or price <= 0:
            raise ValueError("Fuel price must be finite and positive")
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise ValueError("Fuel-price evidence or assumption locator required")
        if self.scope != "conditional_shared_market_proxy":
            raise ValueError("No verified national shared-market fuel series admitted")


class AnnualFuelPrices:
    def __init__(self, observations):
        self.rows = {}
        for row in observations:
            if not isinstance(row, FuelPriceObservation):
                raise ValueError("Expected typed fuel-price observations")
            key = row.year, row.fuel
            if key in self.rows:
                raise ValueError("Duplicate fuel-price year and carrier")
            self.rows[key] = row
        if not self.rows:
            raise ValueError("Empty fuel-price path")
        self.fuels = frozenset(f for _, f in self.rows)

    def for_year(self, year):
        missing = self.fuels - {f for y, f in self.rows if y == year}
        if missing:
            raise ValueError(f"Missing explicit {year} fuel prices: {sorted(missing)}")
        return {f: self.rows[year, f] for f in sorted(self.fuels)}

    def validate_window(self, first, last):
        if type(first) is not int or type(last) is not int or last < first:
            raise ValueError("Invalid fuel-price window")
        for year in range(first, last + 1):
            self.for_year(year)


class FuelPriceNationalModel(PortfolioNationalModel):
    def __init__(self, *args, fuel_prices=None, **kwargs):
        if fuel_prices is not None and not isinstance(fuel_prices, AnnualFuelPrices):
            raise ValueError("Expected an explicit annual fuel-price path")
        self.fuel_prices = deepcopy(fuel_prices)
        self.fuel_price_history = []
        super().__init__(*args, **kwargs)

    @property
    def suppliers(self):
        return self._suppliers

    @suppliers.setter
    def suppliers(self, suppliers):
        # The inherited constructor assigns suppliers before constructing any
        # generator or consumer. Install initial prices here so their margin
        # priors and fixed income reconstruction share the same initial prices.
        # No model source or post-decision cash/asset history is rewritten.
        self._suppliers = suppliers
        if self.fuel_prices is not None:
            self._apply_prices(self.initial_year, initial=True)

    def _apply_prices(self, year, *, initial=False):
        rows = self.fuel_prices.for_year(year)  # validate all before mutation
        multiplier = self.variant.get("fuel_price_multiplier", 1)
        for fuel, row in rows.items():
            price = row.real_2024_cny_per_mwh
            self.suppliers[fuel].price = price * multiplier
            if initial:
                self.reference_fuel_prices[fuel] = price
            self.fuel_price_history.append(dict(year=year, fuel=fuel,
                base_price_real_2024_cny_per_mwh=price,
                effective_price_real_2024_cny_per_mwh=price * multiplier,
                evidence=row.evidence, scope=row.scope,
                phase="initial_beliefs" if initial else "annual_operation",
                future_investment_price_rule="current price persists; no realised future path access"))

    def drivers(self):
        if self.fuel_prices is not None:
            self._apply_prices(self.year)
        super().drivers()

    def run(self, end_year):
        if self.fuel_prices is not None and end_year >= self.year:
            self.fuel_prices.validate_window(self.year, end_year)
        return super().run(end_year)
