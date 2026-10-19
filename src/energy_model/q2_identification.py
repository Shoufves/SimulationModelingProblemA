"""Training identification of nonpower fuel residuals, not sector observations."""
from math import log, exp, isfinite

TCE_MWH = 29.3076 / 3.6
FUEL_EFFICIENCIES = dict(coal=.41, oil=.38, gas=.52)


def nonpower_residual(data, year, fuel):
    primary = data[year, "consumption_10ktce"] * 1e4 * TCE_MWH * data[year, "consumption_"+fuel+"_pct"] / 100
    conversion = data[year, fuel+"_electricity_mwh"] / FUEL_EFFICIENCIES[fuel]
    residual = primary - conversion
    if not isfinite(residual) or residual <= 0:
        raise ValueError("Nonpositive conditional nonpower residual: "+fuel)
    return residual


def fit_nonpower(data, design):
    """Identify alpha independently of simulated power allocation.

    The residual contains non-energy inputs and unmodelled transformation and
    statistical differences. Fixed engineering efficiencies are assumptions.
    No evaluation observation is used, and no annual observed path is injected.
    """
    years = design["training_years"]
    anchor = 2014
    intensity = design["assumptions"]["service_intensity_decline"]
    x = [log(data[y, "real_gdp"] / data[anchor, "real_gdp"]) for y in years]
    denominator = sum(v*v for v in x)
    if denominator <= 0 or not 0 <= intensity < 1:
        raise ValueError("Invalid demand-identification drivers")
    fits = {}
    for fuel, efficiency in FUEL_EFFICIENCIES.items():
        initial = nonpower_residual(data, anchor, fuel)
        z = [log(nonpower_residual(data, y, fuel)/initial)-(y-anchor)*log(1-intensity) for y in years]
        alpha = sum(a*b for a,b in zip(x,z))/denominator
        rows = []
        for year, growth in zip(years,x):
            expected = nonpower_residual(data, year, fuel)
            fitted = initial * exp(alpha*growth) * (1-intensity)**(year-anchor)
            rows.append(dict(year=year, conditional_residual_mwh=expected, fitted_mwh=fitted,
                             relative_error=fitted/expected-1))
        fits[fuel] = dict(alpha=alpha, assumed_efficiency=efficiency, training=rows,
                          training_mape=sum(abs(r["relative_error"]) for r in rows)/len(rows))
    return dict(anchor_year=anchor, training_years=list(years), fits=fits,
                observed_final_energy=False, nonenergy_included=True,
                method="anchored log-GDP least squares on conditional nonpower residual",
                limitation="Depends on fixed conversion efficiencies; includes other transformation/statistical differences")


def identified_parameters(fitted):
    return {("activity_elasticity" if f=="coal" else f+"_activity_elasticity"): r["alpha"]
            for f,r in fitted["fits"].items()}
