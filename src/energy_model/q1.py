"""Deterministic Q1 statistics. No imputation, forecasting or composite ranking."""
import math
import statistics


def finite(value):
    if value is None or value == "" or isinstance(value, bool):
        raise ValueError("Missing/non-numeric observation")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite observation")
    return result


def ratio(numerator, denominator, scale=100.0):
    n, d = finite(numerator), finite(denominator)
    if d <= 0:
        raise ValueError("Denominator must be positive")
    return scale * n / d


def annual_log_volatility(observations, start=2015, end=2024):
    """Sample SD of adjacent observed annual log returns; never bridge missing years."""
    values = {int(y): finite(v) for y, v in observations.items() if start <= int(y) <= end}
    if any(v <= 0 for v in values.values()):
        raise ValueError("Prices must be positive")
    pairs = [(y-1, y) for y in range(start+1, end+1) if y-1 in values and y in values]
    returns = [math.log(values[b] / values[a]) for a, b in pairs]
    return dict(value=statistics.stdev(returns) if len(returns) > 1 else None,
                observed_years=sorted(values), missing_years=sorted(set(range(start, end+1))-values.keys()),
                adjacent_pairs=pairs, n_returns=len(returns), ddof=1)


def segmented_price_volatility(rows, start=2015, end=2024):
    """Separate definitions; mixed years are retained as evidence, never as returns."""
    window = [r for r in rows if start <= int(r['year']) <= end]
    if len({int(r['year']) for r in window}) != len(window):
        raise ValueError('Duplicate price year')
    segments = {}
    excluded = []
    for r in window:
        if not r.get('definition_segment') or r.get('annual_definition_status') not in ('homogeneous', 'mixed'):
            raise ValueError('Missing price definition review')
        if r['annual_definition_status'] == 'mixed':
            excluded.append(int(r['year']))
        else:
            segments.setdefault(r['definition_segment'], {})[int(r['year'])] = r.get('_value', r['value'])
    results = []
    for segment, values in sorted(segments.items()):
        result = annual_log_volatility(values, min(values), max(values))
        result.update(definition_segment=segment, excluded_mixed_years=sorted(excluded),
                      coverage_years=sorted(int(r['year']) for r in window),
                      missing_window_years=sorted(set(range(start, end+1))-{int(r['year']) for r in window}))
        results.append(result)
    return results


def spatial_difference(generation, consumption):
    if set(generation) != set(consumption) or not generation:
        raise ValueError("Region sets must be nonempty and identical")
    g = {k: finite(v) for k, v in generation.items()}
    c = {k: finite(v) for k, v in consumption.items()}
    if min(g.values()) < 0 or min(c.values()) < 0 or sum(g.values()) <= 0 or sum(c.values()) <= 0:
        raise ValueError("Invalid regional totals")
    differences = {k: g[k]/sum(g.values())-c[k]/sum(c.values()) for k in sorted(g)}
    return 0.5*sum(abs(v) for v in differences.values()), differences


def concentration(values, total, grouped):
    """Grouped bins give an upper bound on country HHI; named countries give lower bound."""
    if len(values) != len(grouped) or not values:
        raise ValueError("Origin metadata mismatch")
    vals = [finite(x) for x in values]
    total = finite(total)
    if total <= 0 or min(vals) < 0 or not math.isclose(sum(vals), total, rel_tol=1e-8, abs_tol=1e-8):
        raise ValueError("Origins do not reconcile with the same-source total")
    parts = [(v/total)**2*10000 for v in vals]
    lower = sum(p for p, isgroup in zip(parts, grouped) if not isgroup)
    upper = sum(parts)
    return dict(lower=lower, upper=upper, grouped_hhi=upper,
                point=upper if not any(flag and v > 0 for flag, v in zip(grouped, vals)) else None)


def compound_index(growth, base=2015, end=2024):
    index = {base: 100.0}
    for year in range(base+1, end+1):
        if year not in growth:
            raise ValueError(f"Missing growth for {year}")
        g = finite(growth[year])
        if g <= -100:
            raise ValueError("Invalid GDP growth")
        index[year] = index[year-1]*(1+g/100)
    return index
