"""Bind a predeclared thermal scenario for training and identical Q3 rebuilds."""
from q2_thermal_factory import build as thermal_build


def build(data, design, config, parameters, authority, *, end_year, **options):
    if config.get("model_factory") != "q2_thermal_configured_factory:build":
        raise ValueError("Thermal scenario requires an explicitly bound design")
    mode = config.get("thermal_mode")
    if mode not in {"net55", "net58"}:
        raise ValueError("A predeclared thermal reference is required")
    model, assumptions, prices, changes, sources = thermal_build(data, design, config,
        parameters, authority, end_year=end_year, thermal_mode=mode, **options)
    return model, assumptions, prices, changes, [*sources, "scripts/q2_thermal_configured_factory.py"]
