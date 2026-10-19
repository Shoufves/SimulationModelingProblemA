"""Partial 2024 state: preserve category, vintage, time basis and unknowns.

This is an initialization contract, not a national operating model. Annual
electricity use is not useful service; nameplate is not dispatch availability.
"""
from copy import deepcopy
from math import isfinite

from .io import AdmissionError


FACTORS = {'10^4 kW': ('MW', 10.), 'GW': ('MW', 1000.),
           'GWh': ('MWh', 1000.), '10^8 kWh': ('MWh', 100000.),
           'TWh': ('MWh', 1000000.), '%': ('fraction', .01)}


def normalize(records):
    result, identities = [], set()
    for original in records:
        row = deepcopy(original)
        if row['id'] in identities:
            raise ValueError('Duplicate current-state observation')
        identities.add(row['id'])
        if row['year'] != 2024 or row['geography'] != 'China_mainland':
            raise ValueError('Current-state year/geography mismatch')
        if row['basis'] not in {'year_end_nameplate', 'annual_flow', 'annual_use_share',
                                'reporting_fleet_capacity', 'reporting_coverage'}:
            raise ValueError('Unreviewed temporal or population basis')
        if not row.get('source') or not row.get('locator') or not row.get('vintage'):
            raise ValueError('Current-state provenance is incomplete')
        value = row['value']
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not isfinite(value) or value < 0:
            raise ValueError('Finite nonnegative observed value required; unknown is not zero')
        if row['unit'] not in FACTORS:
            raise ValueError('Unreviewed current-state conversion')
        unit, factor = FACTORS[row['unit']]
        if unit == 'fraction' and value > 100:
            raise ValueError('Invalid percent')
        row.update(normalized_value=value * factor, normalized_unit=unit)
        result.append(row)
    return result


def one(rows, identity, *, basis, unit):
    selected = [r for r in rows if r['id'] == identity]
    if len(selected) != 1 or selected[0]['basis'] != basis or selected[0]['normalized_unit'] != unit:
        raise ValueError('Observation is missing or has incompatible scope: ' + identity)
    return selected[0]


def build_state(records):
    rows = normalize(records)
    capacities = {}
    for kind in ('total', 'thermal', 'hydro', 'nuclear', 'wind', 'solar', 'other'):
        row = one(rows, 'NBS:' + kind, basis='year_end_nameplate', unit='MW')
        if row['vintage'] != 'NBS_2025_C09-15':
            raise ValueError('Do not splice capacity vintages')
        capacities[kind] = row['normalized_value']
    capacity_residual = capacities['total'] - sum(v for k, v in capacities.items() if k != 'total')
    # Source rounding is retained as a residual, never reassigned to a technology.
    # Explicit diagnostic bound: seven displayed integer 10^4 kW cells, each
    # with a half-unit rounding allowance. This is not measurement precision.
    if abs(capacity_residual) > 35.:
        raise ValueError('Capacity categories exceed the declared rounding allowance')
    for prefix, vintage in [('DEMAND:', 'NEA_2025-01-20'), ('GAS:', 'CHINA_GAS_REPORT_2025')]:
        if any(r['vintage'] != vintage for r in rows if r['id'].startswith(prefix)):
            raise ValueError('Do not splice demand or gas-use vintages')
    demand = {kind: one(rows, 'DEMAND:' + kind, basis='annual_flow', unit='MWh')['normalized_value']
              for kind in ('total', 'primary', 'secondary', 'tertiary', 'household')}
    demand_residual = demand['total'] - sum(v for k, v in demand.items() if k != 'total')
    if abs(demand_residual) > 1e-6:
        raise ValueError('Four electricity categories do not reconcile')
    gas = {kind: one(rows, 'GAS:' + kind, basis='annual_use_share', unit='fraction')['normalized_value']
           for kind in ('city', 'industrial', 'power', 'chemical')}
    if abs(sum(gas.values()) - 1.) > 1e-12:
        raise ValueError('Gas use categories do not reconcile')
    components = []

    def component(identity, kind, capacity, source, missing, **extra):
        components.append(dict(id=identity, kind=kind, capacity_mw=capacity,
            evidence=source, operating_availability=None, age_distribution=None,
            missing_fields=missing, **extra))

    component('wind_power', 'process', capacities['wind'], ['NBS:wind'],
              ['operating_availability', 'age_distribution'])
    component('nuclear_power', 'process', capacities['nuclear'], ['NBS:nuclear'],
              ['operating_availability', 'age_distribution', 'unit_identity_and_licensing'])
    for identity, why in [('coal_power', 'thermal_fuel_partition'), ('gas_power', 'thermal_fuel_partition'),
                          ('conventional_hydro', 'same_vintage_hydro_partition'),
                          ('solar_PV', 'same_vintage_solar_partition'),
                          ('other_generation', 'technology_and_fuel_identity')]:
        component(identity, 'process', None, [],
                  [why, 'capacity_mw', 'operating_availability', 'age_distribution'])
    pumped = one(rows, 'RENEW:pumped_hydro_capacity', basis='year_end_nameplate', unit='MW')
    component('pumped_hydro', 'store', pumped['normalized_value'], [pumped['id']],
              ['same_vintage_hydro_partition', 'energy_capacity_mwh', 'initial_soc_mwh',
               'efficiency', 'operating_availability', 'age_distribution'],
              energy_capacity_mwh=None, initial_soc_mwh=None, efficiency=None,
              status='separate_NEA_release_not_added_to_NBS_hydro')
    power = one(rows, 'STORAGE:power', basis='year_end_nameplate', unit='MW')
    energy = one(rows, 'STORAGE:energy', basis='year_end_nameplate', unit='MWh')
    component('new_storage', 'store', power['normalized_value'], [power['id'], energy['id']],
              ['technology_composition', 'initial_soc_mwh', 'efficiency',
               'operating_availability', 'age_distribution'],
              energy_capacity_mwh=energy['normalized_value'], initial_soc_mwh=None, efficiency=None,
              status='nameplate_only_excludes_pumped_hydro')
    gaps = [dict(component=c['id'], field=f) for c in components for f in c['missing_fields']]
    gaps.extend(dict(component=c, field=f) for c, f in (
        ('fuel_supply', 'dated_supply_inventory_and_withdrawal'),
        ('end_use', 'useful_services_device_capacity_efficiency_and_age'),
        ('project_queue', 'identity_status_remaining_cost_and_schedule'),
        ('finance', 'opening_cash_credit_and_commitments'),
        ('chronology', 'matched_load_weather_and_operating_profiles')))
    state = dict(reference_date='2024-12-31', scope='partial_current_state_not_admitted',
        capacity_vintage='NBS_2025_C09-15', national_generation_capacity_mw=capacities,
        components=components, electricity_annual_mwh=demand, gas_annual_use_shares=gas,
        initialization_complete=False, national_acceptance=False, unresolved_fields=gaps,
        checks=dict(capacity_sum_residual_mw=capacity_residual,
                    electricity_category_residual_mwh=demand_residual,
                    gas_share_sum=sum(gas.values())),
        restrictions=[
            'Year-end nameplate never becomes annual effective capacity or an availability curve.',
            'Reliability reporting fleets cannot supply national coal/gas capacities or extrapolation weights.',
            'Hydro already includes pumped storage; solar includes more than PV. No mixed-vintage subtraction.',
            'New storage power and energy are known, but SOC/efficiency/age and technology composition are unknown.',
            'All-society electricity use is not delivered useful service; do not apply a second unreviewed loss factor.',
            'Gas use shares do not provide a matched physical consumption denominator or hourly supply.',
            'A historical fitted 2024 endpoint is not an observed 2024 initialization.'])
    return state, rows


def require_complete_state(state):
    """Do not allow an admission flag to hide unresolved physical fields."""
    gaps = list(state.get('unresolved_fields', []))
    required = {'wind_power', 'nuclear_power', 'coal_power', 'gas_power',
                'conventional_hydro', 'solar_PV', 'other_generation', 'pumped_hydro', 'new_storage'}
    if len(state['components']) != len(required) or {c['id'] for c in state['components']} != required:
        raise AdmissionError('Missing or unexpected current-state components')
    for c in state['components']:
        fields = ['capacity_mw', 'operating_availability', 'age_distribution']
        if c['kind'] == 'store':
            fields += ['energy_capacity_mwh', 'initial_soc_mwh', 'efficiency']
        for f in fields:
            if c.get(f) is None and dict(component=c['id'], field=f) not in gaps:
                gaps.append(dict(component=c['id'], field=f))
    if gaps or not state.get('initialization_complete') or state.get('scope') == 'partial_current_state_not_admitted':
        raise AdmissionError('2024 physical initialization remains incomplete', gaps)
    return state


def compare_historical_endpoint(state, model, result):
    """Retrospective diagnostics only: never reset an evaluated historical path."""
    if model['end_year'] != 2024:
        raise ValueError('Expected a historical 2024 endpoint')
    process = {p['id']: p for p in model['operation']['processes']}
    assets = [a for a in result['assets'] if a['year'] == 2024 and a['kind'] == 'process'
              and a['state'] != 'retired']
    observed = state['national_generation_capacity_mw']
    mapping = {'wind': ['wind_power'], 'nuclear': ['nuclear_power'],
               'solar': ['solar_power', 'solar_new_power']}
    rows = []
    for label, ids in mapping.items():
        value = sum(a['quantity'] * process[a['component']]['capacity_mw']
                    for a in assets if a['component'] in ids)
        rows.append(dict(indicator=label + '_capacity', model_value=value,
                         reference_value=observed[label], unit='MW',
                         difference=value - observed[label],
                         relative_difference=(value / observed[label] - 1),
                         scope='existing_aggregate_proxy_mapping_not_physical_identity'))
    op = next(r for r in result['operations'] if r['year'] == 2024)
    flows = op['result']['flows']
    gas_processes = {p['id']: p for p in op['input']['processes'] if 'gas' in p['inputs']}
    gas_use = sum(r['value'] * r['annual_weight'] * gas_processes[r['id']]['inputs']['gas']
                  for r in flows if r['kind'] == 'process' and r['id'] in gas_processes)
    gas_supply = sum(r['value'] * r['annual_weight'] for r in flows
                     if r['kind'] == 'source' and r['id'] in
                     {s['id'] for s in op['input']['sources'] if s['node'] == 'gas'})
    rows.append(dict(indicator='gas_power_input_share', model_value=gas_use / gas_supply if gas_supply else None,
        reference_value=state['gas_annual_use_shares']['power'], unit='fraction',
        difference=None, relative_difference=None,
        scope='structural_diagnostic_only_model_LHV_vs_report_volume_boundary_not_equated'))
    return rows
