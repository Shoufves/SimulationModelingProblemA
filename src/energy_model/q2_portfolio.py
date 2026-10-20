"""Renewable portfolio screening that retains jointly viable technologies.

Explicit model version for paired research. The previous NationalModel remains
unchanged so frozen experiments continue to reproduce their original behavior.
"""
from math import isfinite

from .q2_national import NationalModel, LEAD, LIFE


class PortfolioNationalModel(NationalModel):
    def audit_renewable_portfolio(self, approved, *, support_fractions=None):
        result = dict(approved)
        renewable = [t for t in ("wind", "solar") if result.get(t, 0) > 0]
        if self.last_operation is None or not renewable:
            return result
        fractions = {t: 1.0 if support_fractions is None else support_fractions.get(t, 1.0)
                     for t in renewable}
        for fraction in fractions.values():
            if not isinstance(fraction, (int, float)) or not isfinite(fraction) or not 0 <= fraction <= 1:
                raise ValueError("Invalid support fraction for portfolio audit")

        def screen(attempt, phase):
            active = [t for t in renewable if result[t] > 0]
            economics = {t: self.marginal_renewable_economics(t, result[t], result) for t in active}
            r = self.a["discount_rate"]
            npvs = {}
            for t in active:
                margin, hours = economics[t]
                support = (self.revenue_policy.investment_value(self, t, full_load_hours=hours)
                           if self.revenue_policy else 0.0) * fractions[t]
                npvs[t] = (min(self.generators[t].expected_project_margin(), margin)
                           * self.energy_pv_factor(lead=LEAD[t], life=LIFE[t])
                           - sum(self.capex(t) / LEAD[t] / (1 + r)**k for k in range(LEAD[t]))
                           + support)
            if any(not isfinite(v) for v in npvs.values()):
                raise ValueError("Nonfinite renewable portfolio NPV")
            failed = [t for t in active if npvs[t] <= 0]
            self.government.log("joint_renewable_audit", attempt=attempt, phase=phase,
                strategy="shrink_failed_then_rescreen", approved=not failed,
                capacities_mw={t: result[t] for t in active}, incremental_npvs_cny_per_mw=npvs)
            return failed

        halvings = self.a["marginal_investment_halvings"]
        for attempt in range(halvings + 1):
            failed = screen(attempt, "shrink")
            if not failed:
                return result
            if attempt < halvings:
                for t in failed:
                    result[t] *= .5

        # No untested fallback: removing one technology changes the joint market.
        # At least one candidate is removed each pass, so this terminates without
        # relaxing the positive-NPV requirement or increasing a prior approval.
        for removal in range(len(renewable)):
            for t in failed:
                result[t] = 0.0
            failed = screen(halvings + 1 + removal, "remove_and_rescreen")
            if not failed:
                return result
        raise RuntimeError("Portfolio removal did not terminate")
