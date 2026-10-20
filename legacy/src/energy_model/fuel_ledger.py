"""Missing-aware physical fuel ledger; never infer exports/stocks from a gap."""
from dataclasses import dataclass
from math import isfinite


TERMS = ("production", "imports", "exports", "domestic_use_excluding_losses",
         "net_stock_addition", "losses", "statistical_difference")
SIGNED = {"net_stock_addition", "statistical_difference"}


@dataclass(frozen=True)
class FuelLedger:
    """One carrier, year, common quantity unit and explicitly verified boundary.

    domestic_use_excluding_losses includes final combustion, feedstock and
    conversion inputs. Positive net_stock_addition means closing minus opening.
    statistical_difference = supply minus accounted uses, not a balancing plug.
    """
    year: int
    carrier: str
    unit: str
    reference_state: str | None
    common_boundary_verified: bool
    production: float | None = None
    imports: float | None = None
    exports: float | None = None
    domestic_use_excluding_losses: float | None = None
    net_stock_addition: float | None = None
    losses: float | None = None
    statistical_difference: float | None = None

    def __post_init__(self):
        if type(self.year) is not int or self.year <= 0:
            raise ValueError("Invalid year")
        for name in ("carrier", "unit"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"Missing {name}")
        if self.reference_state is not None and (
                not isinstance(self.reference_state, str) or not self.reference_state.strip()):
            raise ValueError("Invalid reference state")
        if type(self.common_boundary_verified) is not bool:
            raise ValueError("Boundary verification must be explicit")
        for name in TERMS:
            value = getattr(self, name)
            if value is None:
                continue
            if type(value) not in (int, float) or not isfinite(value):
                raise ValueError(f"Invalid quantity: {name}")
            if name not in SIGNED and value < 0:
                raise ValueError(f"Negative quantity: {name}")

    def evaluate(self, tolerance=1e-8):
        if type(tolerance) not in (int, float) or not isfinite(tolerance) or tolerance < 0:
            raise ValueError("Invalid tolerance")
        missing = [name for name in TERMS if getattr(self, name) is None]
        boundary_issues = []
        if not self.reference_state:
            boundary_issues.append("quantity_reference_state_missing")
        if not self.common_boundary_verified:
            boundary_issues.append("source_scope_not_bridged")
        result = {"year": self.year, "carrier": self.carrier, "unit": self.unit,
                  "missing_terms": missing, "boundary_issues": boundary_issues,
                  "residual": None, "closed": None,
                  "status": "incomplete" if missing else "boundary_unverified"}
        if missing or boundary_issues:
            return result
        residual = (self.production + self.imports - self.exports
                    - self.domestic_use_excluding_losses - self.net_stock_addition
                    - self.losses - self.statistical_difference)
        result.update(residual=residual, closed=abs(residual) <= tolerance,
                      status="balanced" if abs(residual) <= tolerance else "unbalanced")
        return result

    def require_closed(self, tolerance=1e-8):
        result = self.evaluate(tolerance)
        if result["closed"] is not True:
            raise ValueError(f"Fuel ledger not verified and closed: {result}")
        return result
