"""Dated exogenous activity, distinct from GDP and from device efficiency.

An observed annual activity is a realized operating driver in a retrospective
run, never a future value available to an earlier investment decision. Source
admission and useful-service mapping remain the input bundle's responsibility.
"""
from math import isfinite


def validate_activity_driver(driver, start_year, end_year):
    if 'activity_series' not in driver:
        return
    series = driver['activity_series']
    if 'gdp_elasticity' in driver:
        raise ValueError('Choose explicit activity or GDP response; do not multiply both')
    if not isinstance(series, dict) or series.get('base_year') != start_year:
        raise ValueError('Activity reference year must equal the model initial year')
    for key in ('id', 'unit', 'boundary'):
        if not isinstance(series.get(key), str) or not series[key].strip():
            raise ValueError('Activity needs an explicit identity, unit and boundary')
    if series.get('information_role') != 'realized_current_year_operation_only':
        raise ValueError('Activity information role must exclude future foresight')
    records = series.get('records')
    if not isinstance(records, list) or not records:
        raise ValueError('Dated activity records required')
    years = set()
    for row in records:
        if not isinstance(row, dict):
            raise ValueError('Each activity record must be a dated object')
        year = row.get('year')
        if type(year) is not int or year < start_year or year in years:
            raise ValueError('Duplicate or invalid activity year')
        years.add(year)
        value = row.get('value')
        if type(value) not in (int, float) or not isfinite(value) or value < 0:
            raise ValueError('Activity must be finite and nonnegative; zero is explicit inactivity')
        if row.get('unit') != series['unit'] or row.get('boundary') != series['boundary']:
            raise ValueError('Activity unit or scope changes require a separately reviewed bridge')
        if row.get('status') not in ('retrospective_observation', 'scenario_assumption'):
            raise ValueError('Separate activity observations from scenario assumptions')
        if not isinstance(row.get('source_or_assumption'), str) or not row['source_or_assumption'].strip():
            raise ValueError('Each activity year needs its source or explicit assumption')
    if not set(range(start_year, end_year + 1)) <= years:
        raise ValueError('Activity years missing; no interpolation or forward filling')
    base = next(r['value'] for r in records if r['year'] == start_year)
    if base <= 0:
        raise ValueError('Positive reference activity required for normalization')
    if any(not isfinite(r['value'] / base) for r in records):
        raise ValueError('Activity normalization overflow')


def activity_signal(driver, year):
    """Expose one realized year and its initial reference, not the whole path."""
    series = driver['activity_series']
    current = next((r for r in series['records'] if r['year'] == year), None)
    base = next((r for r in series['records'] if r['year'] == series['base_year']), None)
    if current is None or base is None:
        raise ValueError('Current or reference activity missing')
    return dict(series_id=series['id'], year=year, value=current['value'], unit=series['unit'],
                boundary=series['boundary'], status=current['status'],
                source_or_assumption=current['source_or_assumption'],
                base_year=series['base_year'], base_value=base['value'],
                activity_ratio=current['value'] / base['value'],
                information_role=series['information_role'])
