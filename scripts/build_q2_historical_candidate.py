"""Freeze a real-data aggregate diagnostic before fitting; never grant admission.

This is a deliberately reduced, falsifiable historical candidate. Its explicit
accounting approximations are not a physical national initial-state review.
The normal national_q2 entry continues to reject it.
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from energy_model.q2.io import dump, sha


def rows(name):
    with (ROOT / 'data/processed/q2' / name).open(encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def build():
    history = rows('history_observations.csv')
    h = {(int(r['year']), r['indicator']): float(r['value']) for r in history}
    power = {r['variable']: float(r['value']) for r in rows('power_2014_reference.csv')}
    samples = {r['id']: r for r in rows('technology_2010_samples.csv')}
    parameters = {r['id']: float(r['value']) for r in rows('technology_2010_parameters.csv')}
    # Only 2014 observations initialize the state. All later target values are
    # held in a separate file; the model receives historical GDP as a driver.
    tce_mwh = 29.3076 / 3.6
    total = h[2014, 'consumption_10ktce'] * 10000 * tce_mwh
    fuels = {f: total * h[2014, f'consumption_{f}_pct'] / 100 for f in ('coal', 'oil', 'gas')}
    caps = {t: h[2014, f'{t}_10kW'] * 10 for t in ('thermal', 'hydro', 'nuclear', 'wind', 'solar', 'other')}
    # Named NEA thermal shares reconstruct a split of the revised NBS total.
    # Unclassified thermal remains separately visible; it is not assigned coal.
    named = {f: caps['thermal'] * power[f'capacity_{f}'] / power['capacity_thermal'] for f in ('coal', 'gas')}
    efficiency = {'coal': .40, 'gas': .50}
    thermal_generation = power['generation_thermal'] * 100000
    fuel_power = {f: thermal_generation * named[f] / caps['thermal'] for f in named}
    residual = {f: fuels[f] - fuel_power.get(f, 0.) / efficiency.get(f, 1.) for f in fuels}
    if any(v <= 0 for v in residual.values()):
        raise ValueError('Invalid reconstructed residual fuel consumption')
    # This is an effective base-year inventory coefficient, NOT an observed
    # chemical combustion factor. It deliberately remains a diagnostic assumption.
    carbon = {f: h[2014, 'gcb_' + f.capitalize()] * 1e6 / fuels[f] for f in fuels}
    clean = ('hydro', 'nuclear', 'wind', 'solar')
    named_clean_generation = sum(power['generation_' + t] * 100000 for t in clean)
    substitution = total * h[2014, 'consumption_primary_electricity_other_pct'] / 100 / named_clean_generation
    duration, repeat = [6.] * 4, [365.] * 4
    # An announced representative day; shapes are assumptions, not weather/load.
    shape = [.90, 1., 1.10, 1.]
    average = {t: power['generation_' + t] * 100000 / (caps[t] * 8760) for t in clean}
    availability = {t: [average[t]] * 4 for t in clean}
    availability['solar'] = [0., 2 * average['solar'], 2 * average['solar'], 0.]
    availability.update(coal=[.85] * 4, gas=[.85] * 4)
    selected = {'coal': 'chn-c1', 'gas': 'chn-g1', 'hydro': 'chn-h1',
                'nuclear': 'chn-n1', 'wind': 'chn-W1', 'solar': 'chn-S2'}
    resource = {'coal': parameters['coal_price_main'] * 3.6,
                'gas': parameters['gas_price_main'] * 3.6, 'oil': 22.}
    resource.update({t + '_resource': (float(samples[selected[t]]['levelized_fuel_USD_2008_per_MWh'])
                                      if t == 'nuclear' else 0.) for t in clean})
    fuel_nodes = list(resource)
    op = {'energy_unit': 'MWh_LHV', 'currency_unit': 'constant_currency',
          'hours': duration, 'annual_weights': repeat, 'information_mode': 'announced_window',
          'nodes': fuel_nodes + ['electricity_bus', 'electricity'], 'spill_nodes': ['electricity_bus'],
          'sources': [], 'processes': [], 'services': [], 'devices': [], 'stores': [],
          'stock_boundary': 'cyclic', 'financial_limits': [], 'capture_storage_budget_t': 0.,
          'carbon_price_per_t': 0., 'solver_time_limit_s': 30.}
    assets, ownership = [], {}

    def asset(kind, identity, owner, quantity=1., fixed=0.):
        ownership[identity] = owner
        assets.append({'id': identity + '_opening', 'owner': owner, 'kind': kind,
                       'component': identity, 'quantity': quantity, 'online_year': 2014,
                       'state': 'operating', 'fixed_om_per_unit': fixed})

    for node in fuel_nodes:
        op['sources'].append({'id': node + '_supply', 'node': node,
                              'limit_mw': [total / 8760 * 4] * 4,
                              'window_budget_mwh': total * 4,
                              'resource_cost_per_mwh': resource[node] / 1e6,
                              'primary_factor': 1., 'nonfossil': node.endswith('_resource')})
        asset('source', node + '_supply', 'fuel')

    def process(identity, inputs, outputs, capacity, avail, cost, co2):
        return {'id': identity, 'inputs': inputs, 'outputs': outputs, 'capacity_mw': capacity,
                'availability': avail, 'minimum_fraction': [0.] * 4,
                'initial_rate_mw': 0., 'ramp_mw_per_hour': capacity,
                'window_budget_mwh': capacity * 8760,
                'resource_cost_per_mwh': cost / 1e6, 'gross_co2_t_per_mwh': co2,
                'captured_co2_t_per_mwh': 0., 'liability_co2_t_per_mwh': co2}

    options = []
    for technology, sample_id in selected.items():
        sample = samples[sample_id]
        fossil = technology in efficiency
        node = technology if fossil else technology + '_resource'
        input_factor = 1 / efficiency[technology] if fossil else 1.
        identity = technology + '_power'
        # One quantity unit is one MW. Costs are million constant 2008 USD.
        om = float(sample['levelized_om_USD_2008_per_MWh'])
        op['processes'].append(process(identity, {node: input_factor}, {'electricity_bus': 1.},
                                       1., availability[technology], om,
                                       carbon[technology] * input_factor if fossil else 0.))
        capacity = named[technology] if fossil else caps[technology]
        asset('process', identity, 'generation', capacity)
        lead = int(parameters.get('default_lead:' + technology, 5))
        option = {'id': technology + '_build', 'owner': 'generation', 'kind': 'process',
                  'component': identity, 'capex_per_unit': float(sample['overnight_USD_2008_per_kWe']) / 1000,
                  'annual_installation_units': power['new_capacity_' + ('thermal' if fossil else technology)] * 10,
                  'maximum_total_units': capacity * 20, 'fixed_om_per_unit': 0.,
                  'discount_rate': parameters['discount_rate_low'],
                  'economic_life': parameters['life:' + technology],
                  'expected_utilisation': sum(availability[technology]) / 4,
                  'replacement_ratio': 1., 'connection_per_unit': 1., 'subsidy_per_unit': 0.,
                  'lead_years': lead, 'construction_fractions': [1 / lead] * lead,
                  'expected_terminal_value_per_unit': 0.,
                  'funding_convention': 'fully_funded_nonremunerated_escrow',
                  'known_year': 2014, 'permit_known_year': 2014, 'permit_effective_year': 2014,
                  'cost_reference_year': 2014, 'replaces': None}
        if fossil:
            option['annual_installation_units'] *= named[technology] / caps['thermal']
        options.append(option)
    grid_loss = power['grid_loss_rate'] / 100
    op['processes'].append(process('aggregate_grid', {'electricity_bus': 1.},
                                   {'electricity': 1 - grid_loss}, total / 8760,
                                   [1.] * 4, 0., 0.))
    asset('process', 'aggregate_grid', 'grid')
    # Gross supply reconstruction, not total societal electricity consumption.
    gross = sum(fuel_power.values()) + named_clean_generation
    electricity = gross * (1 - grid_loss)
    shares = {'industrial_electricity': power['consumption_secondary_industry'],
              'other_electricity': power['consumption_primary_industry'] + power['consumption_tertiary_industry']
                                   + power['consumption_household']}
    base_service = {s: electricity * v / sum(shares.values()) for s, v in shares.items()}
    base_service.update({f + '_residual': v for f, v in residual.items()})
    for service_id, amount in base_service.items():
        electrical = service_id.endswith('electricity')
        node = 'electricity' if electrical else service_id.split('_')[0]
        owner = ('buildings' if service_id == 'other_electricity' else
                 'transport' if node == 'oil' else 'industrial')
        op['services'].append({'id': service_id, 'demand': [amount / 8760 * hours * v
                               for hours, v in zip(duration, shape)],
                               'unit': 'MWh_reconstructed_residual_or_electric_load',
                               'priority': 0, 'shortfall_weight': 1.})
        op['devices'].append({'id': service_id + '_device', 'node': node, 'service': service_id,
                             'service_per_mwh': 1., 'input_capacity_mw': total / 8760 * 4,
                             'resource_cost_per_mwh': 0.,
                             'gross_co2_t_per_mwh': 0. if electrical else carbon[node],
                             'liability_co2_t_per_mwh': 0. if electrical else carbon[node]})
        asset('device', service_id + '_device', owner)
    roles = {'fuel': 'fuel_supplier', 'generation': 'generator', 'industrial': 'industry',
             'transport': 'transport', 'buildings': 'building', 'grid': 'grid_storage', 'government': 'government'}
    agents = [{'id': identity, 'role': role, 'cash': 1e7, 'credit_limit': 0.,
               'initial_margins': {o['id']: 0. for o in options if o['owner'] == identity}}
              for identity, role in roles.items()]
    prices = {n: resource[n] / 1e6 for n in fuel_nodes}
    prices.update(electricity_bus=70 / 1e6, electricity=80 / 1e6)
    model = {'scope': 'historical_aggregate_candidate_not_admitted', 'seed': 17,
             'start_year': 2014, 'end_year': 2024, 'operation': op, 'agents': agents, 'assets': assets,
             'initial_projects': [], 'investment_options': options, 'asset_events': [],
             'other_accounts': {'clearing': 1e8, 'external_economy': 1e9, 'construction': 0.,
                                'escrow': 0., 'carbon_market': 0.},
             'behavior': {'expectation_update': .5, 'investment_adjustment': .6},
             'demand_drivers': {s: {'gdp_elasticity': 1. if s.endswith('electricity') else .4,
                                    'annual_intensity_improvement': 0.} for s in base_service},
             'gdp_growth': {str(y): h[y, 'real_gdp_growth_pct'] / 100 for y in range(2015, 2025)},
             'cost_decline': {o['id']: .10 if o['id'] == 'solar_build' else
                             .03 if o['id'] == 'wind_build' else 0. for o in options},
             'mechanisms': {'investment': True, 'replacement': False, 'expectation_learning': True},
             'policies': [{'id': 'constant_research_prices_not_actual_historical_policy',
                           'known_year': 2014, 'effective_year': 2014, 'node_prices': prices,
                           'service_prices': {s: 200 / 1e6 for s in base_service},
                           'carbon_price_per_t': 0., 'government_agent': 'government',
                           'subsidy_budget': 0., 'construction_units_limit': 150000., 'connection_limit': 150000.}]}

    def flow(kind, ids, coefficient):
        return {'kind': 'flow', 'flow_kind': kind, 'ids': ids, 'coefficient': coefficient}

    fossil_terms = [flow('source', [f + '_supply' for f in fuels], 1 / tce_mwh / 10000)]
    other_terms = [flow('process', [t + '_power' for t in clean], substitution / tce_mwh / 10000)]
    definitions = [{'id': 'consumption_10ktce', 'numerator': fossil_terms + other_terms, 'denominator': None,
                    'unit': '10^4 tce', 'boundary': 'NBS_2025_mainland_primary_consumption_proxy'}]
    for f in fuels:
        definitions.append({'id': 'consumption_' + f + '_share',
                            'numerator': [flow('source', [f + '_supply'], 1 / tce_mwh / 10000)],
                            'denominator': fossil_terms + other_terms, 'unit': 'fraction',
                            'boundary': 'NBS_2025_mainland_primary_consumption_proxy'})
    for t in ('wind', 'solar', 'nuclear'):
        definitions.append({'id': t + '_10kW', 'numerator': [{'kind': 'capacity', 'asset_kind': 'process',
                            'ids': [t + '_power'], 'coefficient': .1}], 'denominator': None,
                            'unit': '10^4 kW', 'boundary': 'NBS_2025_mainland_nameplate_capacity'})
    definitions.append({'id': 'gcb_fuel_co2', 'numerator': [{'kind': 'annual', 'field': 'gross_energy_co2_t',
                        'coefficient': 1e-6}], 'denominator': None, 'unit': 'Mt CO2',
                        'boundary': 'GCB_coal_oil_gas_categories_effective_coefficient_proxy'})
    observations = []
    for year in range(2015, 2025):
        for d in definitions:
            indicator = d['id']
            if indicator.endswith('_share'):
                value = h[year, indicator.replace('_share', '_pct')] / 100
                refs = [indicator.replace('_share', '_pct')]
            elif indicator == 'gcb_fuel_co2':
                refs = ['gcb_Coal', 'gcb_Oil', 'gcb_Gas']
                value = sum(h[year, k] for k in refs)
            else:
                refs, value = [indicator], h[year, indicator]
            observations.append({'year': year, 'indicator': indicator, 'value': value,
                                 'unit': d['unit'], 'boundary': d['boundary'],
                                 'comparison_status': 'assumption_based_proxy_not_reviewed_boundary_equivalence',
                                 'source_records': [r for r in history if int(r['year']) == year and r['indicator'] in refs]})
    def param(identity, grid, paths):
        return {'id': identity, 'grid': grid, 'bounds': [min(grid), max(grid)], 'paths': paths}
    experiment = {'windows': {'train': [2015, 2021], 'already_seen_holdout': [2022, 2024]},
                  'parameters': [param('residual_elasticity', [.2, .4, .6],
                    [['demand_drivers', s, 'gdp_elasticity'] for s in base_service if s.endswith('residual')]),
                    param('electricity_elasticity', [.7, 1., 1.3],
                    [['demand_drivers', s, 'gdp_elasticity'] for s in base_service if s.endswith('electricity')]),
                    param('investment_adjustment', [.25, .6, 1.], [['behavior', 'investment_adjustment']])],
                  'maximum_evaluations': 27, 'equivalent_loss_absolute_tolerance': .001,
                  'targets': [], 'rule_alternatives': ['adaptive_margin', 'instant_margin', 'no_investment'],
                  'selection': 'Minimum training loss across frozen rules and grids; never select by holdout',
                  'future_use': 'No S0 until structural accounting, policy and quality gates are resolved'}
    for d in definitions:
        identity = d['id']
        family = ('primary_mix' if identity.endswith('_share') else 'co2' if identity == 'gcb_fuel_co2'
                  else 'energy_consumption' if identity == 'consumption_10ktce' else 'capacity_or_generation')
        # Scales use the pre-training base only, not future target values.
        scale = (h[2014, identity.replace('_share', '_pct')] / 100 if identity.endswith('_share') else
                 sum(h[2014, k] for k in ('gcb_Coal', 'gcb_Oil', 'gcb_Gas')) if identity == 'gcb_fuel_co2'
                 else h[2014, identity])
        experiment['targets'].append({'id': identity, 'family': family, 'scale': scale,
                                     'weight': .25 / (3 if family in ('primary_mix', 'capacity_or_generation') else 1),
                                     'metric_type': 'share_fraction' if family == 'primary_mix' else 'total'})
    assumptions = [
        ('A01', 'Retrospective initialization', '2014 NBS values use the revised 2025 vintage; agents do not receive 2015-2024 targets. This is not a real-time historical forecast.'),
        ('A02', 'Vintage bridge', 'NEA2015-vintage proportions split NBS2025-vintage 2014 thermal capacity; the split is reconstructed, never an observed revised split.'),
        ('A03', 'Excluded capacity', 'Unclassified thermal, other generation and the 11e8 kWh NEA discrepancy are unmodelled. Hydro includes pumped storage in the observed category; the reduced proxy cannot claim storage or reliability fidelity.'),
        ('A04', 'Residual consumption', 'Primary fuel less reconstructed power input is a residual-account service. It includes transformation/nonenergy discrepancies and is NOT measured useful heat or transport activity. Sector owners are bookkeeping assignments.'),
        ('A05', 'Carbon bridge', 'GCB2014 coal/oil/gas emissions divided by NBS2014 fuel-equivalent energy provide fixed effective inventory coefficients. They are not chemical factors or a reviewed GCB/NBS equivalence. Cement, flaring, other and removals are excluded.'),
        ('A06', 'Primary electricity bridge', 'One fixed 2014 ratio maps named nonthermal generation to the NBS primary-electricity-and-other category. This proxy cannot identify nonfossil consumption or its changing statistical conversion.'),
        ('A07', 'Chronology', 'Four 6-hour blocks repeat 365 times. Assumed demand shape 0.9/1/1.1/1, flat non-solar availability and daytime solar preserve reference annual means. No measured weather, ramp events or reliability probabilities.'),
        ('A08', 'Supply envelope', 'All fuel sources have a finite four-times-2014-total-energy envelope; it is a deliberately nonbinding diagnostic bound, not domestic/import capacity. No inferred hourly import rate.'),
        ('A09', 'Technology mapping', 'Single named IEA2010 samples supply 2008USD costs; fleet coal/gas efficiencies 0.40/0.50 are assumptions below modern sample values 0.46/0.58. Nuclear resource is output-equivalent rather than reactor heat. All reported O&M is treated as variable for this variant, not claimed identified.'),
        ('A10', 'Prices and finance', 'All currency is million constant2008USD. Electricity bus/retail70/80USD per MWh, oil22USD per MWh and service200USD per MWh are research prices, not nominal tariffs. Large finite opening cash makes finance nonbinding; zero carbon/support is a control rule, not actual historical Chinese policy.'),
        ('A11', 'Queue and lifecycle', 'No verified initial queue, retirement schedule or ages. Empty queue and zero retirements are explicitly assumed for a diagnostic decade only. online_year2014 means bookkeeping entry, not actual commissioning. Not suitable for2060.'),
        ('A12', 'Investment supply chain', 'Annual build limits equal 2014 observed additions, split thermal by the reconstructed named shares; total construction/connection150GW per year, technology ceiling20times opening, hydro lead5years are assumptions. Wind/solar capex decline3%/10% per year; other costs fixed.'),
        ('A13', 'Grid and end use', 'Fixed NEA6.34% delivery loss; free aggregate grid operations and fixed one-for-one residual devices. No claimed endogenous fuel substitution, device replacement, regional network, H2, CCUS or storage.'),
        ('A14', 'Search and alternatives', 'Three bounded parameters,27candidates per rule; adaptive expectations0.5, instant expectations1, and no investment, all frozen before first fit. Zero intensity trend isolates elasticity. Already-seen holdout is evaluated only after training selection; failure cannot relax thresholds.'),
    ]
    initial = {'scope': model['scope'], 'reference_year': 2014, 'currency': 'million_USD_2008',
               'tce_LHV_MWh': tce_mwh, 'named_capacity_MW': {**named, **{t: caps[t] for t in clean}},
               'unmodelled_thermal_MW': caps['thermal'] - sum(named.values()),
               'unmodelled_other_MW': caps['other'], 'NEA_unallocated_generation_MWh': power['generation_unallocated_difference'] * 100000,
               'primary_fuel_MWh_equivalent': fuels, 'reconstructed_residual_MWh': residual,
               'effective_inventory_tCO2_per_MWh': carbon, 'primary_electricity_proxy_factor': substitution,
               'literature_samples': selected, 'base_services_MWh': base_service,
               'limitations': [a[0] for a in assumptions]}
    return {'model': model, 'experiment': experiment, 'definitions': definitions,
            'observations': observations, 'initialization': initial,
            'assumptions': [{'id': i, 'topic': t, 'statement': s, 'status': 'explicit_research_assumption_not_observation'}
                            for i, t, s in assumptions]}


def main():
    directory = ROOT / 'workflow/q2_candidates/v1'
    documents = build()
    documents['acceptance'] = json.loads((ROOT / 'workflow/q2_acceptance.json').read_text(encoding='utf-8'))
    references = ['history_observations.csv', 'power_2014_reference.csv',
                  'technology_2010_samples.csv', 'technology_2010_parameters.csv']
    artifacts = {('data/processed/q2/' + name): sha(ROOT / 'data/processed/q2' / name) for name in references}
    # Pin source originals and reviews as well as derived observations. Existing
    # substantive reviews authorize references, not this national model mapping.
    for name in ('q2_history_review.json', 'q2_initialization_reference_review.json', 'q2_technology_2010_review.json'):
        path = ROOT / 'data/catalog' / name
        artifacts[path.relative_to(ROOT).as_posix()] = sha(path)
    for name in references:
        for row in rows(name):
            p = row.get('source_path') or row.get('source')
            if p and (ROOT / p).is_file(): artifacts[p] = sha(ROOT / p)
    if directory.exists():
        # A rerun may verify reproducibility; it cannot silently overwrite a
        # configuration after its holdout has been evaluated.
        for name, document in documents.items():
            path = directory / (name + '.json')
            if not path.is_file() or json.loads(path.read_text(encoding='utf-8')) != document:
                raise ValueError('Frozen candidate differs; create an explicitly versioned new candidate')
        old = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
        if old['source_artifacts'] != artifacts:
            raise ValueError('Frozen candidate references changed')
        print('Existing frozen candidate exactly reproduced; no files changed')
        return
    directory.mkdir(parents=True)
    for name, document in documents.items(): dump(directory / (name + '.json'), document)
    dump(directory / 'manifest.json', {'version': 1, 'owner': 'p2/yx',
         'scope': 'historical_aggregate_candidate_not_admitted', 'national_admission': False,
         'frozen_before_first_fit': True, 'builder_sha256': sha(Path(__file__)),
         'inputs': {name: {'path': (directory / (name + '.json')).relative_to(ROOT).as_posix(),
                           'sha256': sha(directory / (name + '.json'))} for name in documents},
         'source_artifacts': artifacts,
         'admission_limitation': 'Real observations and literature; proxy accounting, assumptions and incomplete mechanisms must not pass national acceptance.'})
    print('Frozen real-data historical diagnostic candidate v1; not admitted to national_q2')


if __name__ == '__main__':
    main()
