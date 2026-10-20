"""Declared generator commissioning timing, separate from year-end MW.

A scalar MW-year approximation cannot recover seasonal commissioning/resource
correlation or peak adequacy. The same anniversary is used at retirement so a
project with life L contributes exactly L full-capacity operating years.
"""
from dataclasses import dataclass
from math import fsum, isfinite


@dataclass(frozen=True)
class AnnualExposure:
    first_year_fraction: float
    evidence: str

    def __post_init__(self):
        if (isinstance(self.first_year_fraction, bool)
                or not isinstance(self.first_year_fraction, (int, float))
                or not isfinite(self.first_year_fraction)
                or not 0 <= self.first_year_fraction <= 1):
            raise ValueError("First operating-year fraction must be in [0,1]")
        if not isinstance(self.evidence, str) or not self.evidence.strip():
            raise ValueError("Annual exposure requires explicit evidence/assumptions")

    def weight(self, asset, year):
        online, exit_year = asset["online_year"], asset["exit_year"]
        if any(type(v) is not int for v in (online, exit_year, year)) or exit_year <= online:
            raise ValueError("Invalid operating lifetime/calendar year")
        if year < online or year > exit_year:
            return 0.0
        if year == online:
            return self.first_year_fraction
        if year == exit_year:
            return 1-self.first_year_fraction
        return 1.0

    def energy_pv_factor(self, *, lead, life, discount_rate):
        if (type(lead) is not int or type(life) is not int or lead < 1 or life < 1
                or not isfinite(discount_rate) or discount_rate < 0):
            raise ValueError("Invalid project life/lead/discount rate")
        asset = dict(online_year=0, exit_year=life)
        return fsum(self.weight(asset, age)/(1+discount_rate)**(lead+age)
                    for age in range(life+1))
