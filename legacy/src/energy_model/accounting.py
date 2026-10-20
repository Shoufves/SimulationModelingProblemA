"""Physical accounting only; no uncalibrated behavioral parameters."""

from dataclasses import dataclass
from math import isfinite


def nonnegative(**values: float) -> None:
    for name, value in values.items():
        if not isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and nonnegative")


@dataclass(frozen=True)
class CapacityProject:
    capacity_gw: float
    online_year: int
    retirement_year: int | None = None

    def __post_init__(self) -> None:
        nonnegative(capacity_gw=self.capacity_gw)
        if self.retirement_year is not None:
            if self.retirement_year <= self.online_year:
                raise ValueError("Retirement must follow commissioning")

    def available_gw(self, year: int) -> float:
        if year < self.online_year:
            return 0.0
        if self.retirement_year is not None and year >= self.retirement_year:
            return 0.0
        return self.capacity_gw


@dataclass(frozen=True)
class EnergyBalance:
    """All quantities must use one common energy unit for one carrier."""

    production: float = 0.0
    imports: float = 0.0
    conversion_output: float = 0.0
    opening_stock: float = 0.0
    requested_final_demand: float = 0.0
    unserved_final_demand: float = 0.0
    conversion_input: float = 0.0
    exports: float = 0.0
    losses: float = 0.0
    closing_stock: float = 0.0

    def __post_init__(self) -> None:
        nonnegative(**vars(self))
        if self.unserved_final_demand > self.requested_final_demand:
            raise ValueError("Unserved demand exceeds requested demand")

    def residual(self) -> float:
        supply = (
            self.production + self.imports
            + self.conversion_output + self.opening_stock
        )
        uses = (
            self.requested_final_demand - self.unserved_final_demand
            + self.conversion_input + self.exports + self.losses + self.closing_stock
        )
        return supply - uses

    def require_closed(self, tolerance: float = 1e-8) -> None:
        nonnegative(tolerance=tolerance)
        if abs(self.residual()) > tolerance:
            raise ValueError(f"Energy balance is not closed: {self.residual()}")


@dataclass(frozen=True)
class Storage:
    energy_mwh: float
    capacity_mwh: float
    charge_limit_mw: float
    discharge_limit_mw: float
    charge_efficiency: float
    discharge_efficiency: float

    def __post_init__(self) -> None:
        nonnegative(**vars(self))
        if self.energy_mwh > self.capacity_mwh:
            raise ValueError("Initial stored energy exceeds capacity")
        for efficiency in (self.charge_efficiency, self.discharge_efficiency):
            if not 0 < efficiency <= 1:
                raise ValueError("Efficiency must be in (0, 1]")

    def step(self, charge_mw: float, discharge_mw: float, hours: float) -> "Storage":
        nonnegative(charge_mw=charge_mw, discharge_mw=discharge_mw, hours=hours)
        if hours == 0:
            raise ValueError("Duration must be positive")
        if charge_mw > 0 and discharge_mw > 0:
            raise ValueError("Simultaneous charging and discharging is forbidden")
        if charge_mw > self.charge_limit_mw or discharge_mw > self.discharge_limit_mw:
            raise ValueError("Storage power limit exceeded")
        energy = (
            self.energy_mwh + charge_mw * self.charge_efficiency * hours
            - discharge_mw / self.discharge_efficiency * hours
        )
        if energy < -1e-9 or energy > self.capacity_mwh + 1e-9:
            raise ValueError("Storage energy limit exceeded")
        return Storage(
            energy_mwh=min(self.capacity_mwh, max(0.0, energy)),
            capacity_mwh=self.capacity_mwh,
            charge_limit_mw=self.charge_limit_mw,
            discharge_limit_mw=self.discharge_limit_mw,
            charge_efficiency=self.charge_efficiency,
            discharge_efficiency=self.discharge_efficiency,
        )


def carbon_account(
    gross_energy_co2: float,
    industrial_process_co2: float,
    captured_energy_co2: float,
    verified_removals_co2: float,
) -> dict:
    """Common mass unit; captured fossil CO2 is deducted exactly once."""
    nonnegative(
        gross_energy_co2=gross_energy_co2,
        industrial_process_co2=industrial_process_co2,
        captured_energy_co2=captured_energy_co2,
        verified_removals_co2=verified_removals_co2,
    )
    if captured_energy_co2 > gross_energy_co2:
        raise ValueError("Captured fossil CO2 exceeds gross energy CO2")
    positive = gross_energy_co2 - captured_energy_co2 + industrial_process_co2
    return {
        "positive_co2_after_capture": positive,
        "net_co2": positive - verified_removals_co2,
        "neutralization_ratio": verified_removals_co2 / positive if positive else None,
    }
