"""Auditable reduced-form bridge to NBS primary-energy categories.

The effective coefficient includes non-electric use and boundary differences.
It is NOT measured generation coal consumption or a physical conversion factor.
Only training years estimate its drift; evaluation observations are diagnostic.
"""
from math import exp, log, isfinite

CLEAN = ("hydro", "nuclear", "wind", "solar", "biofuel")
SCOPE_EVIDENCE = {
    "data/raw/q2_scope/nbs_fossil_nonfossil_20260417.html": dict(
        url="https://www.stats.gov.cn/hd/lyzx/zxgk/202605/t20260509_1963653.html",
        locator="Energy Statistics Department reply dated 2026-04-17, reply content",
        phrases=["两个分类涵盖了所有能源品种", "一次能源、二次能源消费不能重复计算"]),
    "data/raw/q2_scope/nbs_energy_transition_20260604.html": dict(
        url="https://www.stats.gov.cn/sj/sjjd/202606/t20260604_1963892.html",
        locator="2026-06-04, section 3(2); category explanation only, no 2025 observations enter model",
        phrases=["煤、油、气、非化石能源四足鼎立", "一次电力及其他能源占比由", "顺利实现非化石能源消费比重"]),
    "data/raw/lb/base/nbs/yearbook2025/sm09.txt": dict(
        url="https://www.stats.gov.cn/sj/ndsj/2025/html/sm09.htm",
        locator="Energy chapter methodological notes, section 4 items 3 and 4",
        phrases=["电力折算标准煤系数按平均发电煤耗计算", "每千瓦小时折0.1229千克标准煤"]),
}


def observed_coefficient(data, year):
    clean = sum(data[year, tech + "_electricity_mwh"] for tech in CLEAN)
    peo = data[year, "consumption_10ktce"] * 1e4 * data[year, "consumption_primary_electricity_other_pct"] / 100
    if clean <= 0 or peo <= 0:
        raise ValueError("Nonpositive statistical bridge anchor")
    return peo / clean


def fit_bridge(data, design):
    spec = design["statistical_bridge"]
    anchor = spec["training_anchor_year"]
    tau = spec["trend_decay_years"]
    if anchor != 2014 or tau <= 0 or not isfinite(tau):
        raise ValueError("Invalid frozen statistical bridge specification")
    c0 = observed_coefficient(data, anchor)
    years = design["training_years"]
    x = [tau * (1 - exp(-(y-anchor)/tau)) for y in years]
    z = [log(observed_coefficient(data, y)/c0) for y in years]
    rate = sum(a*b for a,b in zip(x,z)) / sum(a*a for a in x)
    return dict(log_rate=rate,anchor_year=anchor,anchor_tce_per_mwh=c0,
                training_years=list(years),trend_decay_years=tau,
                interpretation="effective statistical coefficient, not physical generation coal rate")


def coefficient(data, design, initial_year, year, variant=None):
    variant = variant or {}
    anchor = observed_coefficient(data, initial_year)
    fit = design["statistical_bridge"]["fitted"]
    tau = variant.get("bridge_decay_years", fit["trend_decay_years"])
    drift = fit["log_rate"] * variant.get("bridge_trend_multiplier", 1)
    if tau <= 0 or not isfinite(tau):
        raise ValueError("Invalid bridge decay horizon")
    return anchor * exp(drift*tau*(1-exp(-(year-initial_year)/tau))) * variant.get("primary_bridge_multiplier", 1)


def bridge_diagnostics(data, design):
    """Isolate conversion error with observed generation/fossils, not ABM error."""
    anchor = design["statistical_bridge"]["training_anchor_year"]
    rows = []
    for y in design["training_years"] + design["evaluation_years"]:
        clean = sum(data[y,t+"_electricity_mwh"] for t in CLEAN)
        total = data[y,"consumption_10ktce"]*1e4
        observed_share = data[y,"consumption_primary_electricity_other_pct"]/100
        fossil = total * (1-observed_share)
        for method, c in (("training_damped_trend",coefficient(data,design,anchor,y)),
                          ("constant_initial_anchor",observed_coefficient(data,anchor))):
            estimated = clean*c
            share = estimated/(fossil+estimated)
            rows.append(dict(year=y,split="training" if y in design["training_years"] else "already_seen_evaluation",
                method=method,observed_coefficient_tce_per_mwh=observed_coefficient(data,y),
                estimated_coefficient_tce_per_mwh=c,observed_share=observed_share,estimated_share=share,
                residual_share=share-observed_share,observed_nonfossil_tce=total*observed_share,
                estimated_nonfossil_tce=estimated,independent_source=False))
    return rows
