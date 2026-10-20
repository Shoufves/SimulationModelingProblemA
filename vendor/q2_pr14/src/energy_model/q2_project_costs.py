"""Explicit technical-cost interface. Fixed O&M never enters merit order.

Net-nameplate conversion is frozen at the initial reference meter. Annual
variable costs use the actual annual net/gross meter. Neither is fuel efficiency.
Applying a new-plant reference to old assets is an explicit scenario assumption.
"""
from copy import deepcopy
from math import isfinite


class GenerationCosts:
    def __init__(self, *, parameters, reference_net_fractions, evidence):
        if not evidence or set(parameters) != set(reference_net_fractions):
            raise ValueError("Cost assumptions need evidence and all net-nameplate conversions")
        if not parameters or not set(parameters).issubset({"coal","gas","nuclear"}):
            raise ValueError("This reviewed cost interface supports coal, gas and nuclear only")
        self.parameters = deepcopy(parameters)
        self.reference_net_fractions = dict(reference_net_fractions)
        self.evidence = evidence
        required = {"fixed_real_cny_per_net_mw_year", "variable_real_cny_per_net_mwh",
                    "overnight_real_cny_per_net_mw"}
        for tech, row in self.parameters.items():
            if set(row) != required:
                raise ValueError("Cost components must be explicit")
            for value in row.values():
                if not isinstance(value, (float, int)) or not isfinite(value) or value < 0:
                    raise ValueError("Invalid technical cost")
            fraction = self.reference_net_fractions[tech]
            if not isfinite(fraction) or not 0 < fraction <= 1:
                raise ValueError("Invalid reference net/gross nameplate fraction")

    def contains(self, tech):
        return tech in self.parameters

    def capex(self, tech):
        return self.parameters[tech]["overnight_real_cny_per_net_mw"]*self.reference_net_fractions[tech]

    def fixed_per_mw(self, tech):
        return self.parameters[tech]["fixed_real_cny_per_net_mw_year"]*self.reference_net_fractions[tech]

    def variable_per_gross_mwh(self, tech, actual_net_fraction):
        if not isfinite(actual_net_fraction) or not 0 < actual_net_fraction <= 1:
            raise ValueError("Invalid annual export fraction for net-output costs")
        return self.parameters[tech]["variable_real_cny_per_net_mwh"]*actual_net_fraction
