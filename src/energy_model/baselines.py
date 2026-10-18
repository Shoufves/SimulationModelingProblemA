"""Simple conditional hindcasts; these are not the multi-agent model."""

from math import exp, log, sqrt
from statistics import mean


def slope(xs: list[float], ys: list[float]) -> float:
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("Regression requires matching series with at least two points")
    center_x, center_y = mean(xs), mean(ys)
    denominator = sum((x - center_x) ** 2 for x in xs)
    if denominator <= 0:
        raise ValueError("Regression input has no variation")
    return sum((x - center_x) * (y - center_y) for x, y in zip(xs, ys)) / denominator


def fit_baselines(records: list[dict], train_end: int = 2021) -> dict:
    training = sorted(
        (row for row in records if row["year"] <= train_end),
        key=lambda row: row["year"],
    )
    if len(training) < 3 or training[-1]["year"] != train_end:
        raise ValueError("Training window is incomplete")
    for row in training:
        if row["energy_mtce"] <= 0 or row["real_gdp_index_2015"] <= 0:
            raise ValueError("Log regression requires positive energy and GDP")
    anchor = training[-1]
    years = [float(row["year"]) for row in training]
    log_energy = [log(row["energy_mtce"]) for row in training]
    log_gdp = [log(row["real_gdp_index_2015"]) for row in training]
    return {
        "train_years": [row["year"] for row in training],
        "anchor_year": train_end,
        "anchor_energy_mtce": anchor["energy_mtce"],
        "anchor_real_gdp_index": anchor["real_gdp_index_2015"],
        "energy_log_trend": slope(years, log_energy),
        "gdp_elasticity": slope(log_gdp, log_energy),
        "intensity_log_trend": slope(
            years, [energy - gdp for energy, gdp in zip(log_energy, log_gdp)]
        ),
        "method": "Fit slopes on training only; anchor all paths at final training observation",
    }


def predict_baselines(fitted: dict, year: int, real_gdp_index: float,
                      *, allow_in_sample: bool = False) -> dict:
    if (not allow_in_sample and year <= fitted["anchor_year"]) or real_gdp_index <= 0:
        raise ValueError("Prediction needs a later year and positive exogenous GDP")
    dt = year - fitted["anchor_year"]
    anchor = fitted["anchor_energy_mtce"]
    gdp_ratio = real_gdp_index / fitted["anchor_real_gdp_index"]
    return {
        "constant_intensity": anchor * gdp_ratio,
        "energy_time_trend": anchor * exp(fitted["energy_log_trend"] * dt),
        "gdp_elasticity": anchor * gdp_ratio ** fitted["gdp_elasticity"],
        "intensity_time_trend": (
            anchor * gdp_ratio * exp(fitted["intensity_log_trend"] * dt)
        ),
    }


def evaluate_baselines(records: list[dict], fitted: dict) -> dict:
    rows = []
    for record in sorted(records, key=lambda row: row["year"]):
        if record["year"] <= fitted["anchor_year"]:
            continue
        rows.append({
            "year": record["year"],
            "actual_energy_mtce": record["energy_mtce"],
            "predictions_mtce": predict_baselines(
                fitted, record["year"], record["real_gdp_index_2015"]
            ),
        })
    if not rows:
        raise ValueError("No holdout observations")
    metrics = {}
    for name in rows[0]["predictions_mtce"]:
        errors = [
            row["predictions_mtce"][name] - row["actual_energy_mtce"] for row in rows
        ]
        metrics[name] = {
            "mape_pct": mean(
                abs(error) / row["actual_energy_mtce"] * 100
                for row, error in zip(rows, errors)
            ),
            "rmse_mtce": sqrt(mean(error ** 2 for error in errors)),
            "mean_signed_error_mtce": mean(errors),
        }
    return {
        "evaluation": "Conditional hindcast using observed holdout GDP; not a GDP forecast",
        "rows": rows,
        "metrics": metrics,
    }
