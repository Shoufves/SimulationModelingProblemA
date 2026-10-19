"""Small, hand-solvable engineering inputs; no national data or assumptions."""
from copy import deepcopy


def source(identity, node, limits, cost=0., nonfossil=False):
    return {'id': identity, 'node': node, 'limit_mw': limits,
            'window_budget_mwh': 100000., 'resource_cost_per_mwh': cost,
            'primary_factor': 1., 'nonfossil': nonfossil}


def process(identity, inputs, outputs, cap, availability, cost=0., co2=0.):
    return {'id': identity, 'inputs': inputs, 'outputs': outputs, 'capacity_mw': cap,
            'availability': availability, 'minimum_fraction': [0.] * len(availability),
            'initial_rate_mw': 0., 'ramp_mw_per_hour': 10000.,
            'window_budget_mwh': 100000., 'resource_cost_per_mwh': cost,
            'gross_co2_t_per_mwh': co2, 'captured_co2_t_per_mwh': 0.,
            'liability_co2_t_per_mwh': co2}


def service(identity, demand, priority=0):
    return {'id': identity, 'demand': demand, 'unit': 'MWh_useful_service',
            'priority': priority, 'shortfall_weight': 1.}


def device(identity, node, service_id, efficiency=1., cap=1000., co2=0.):
    return {'id': identity, 'node': node, 'service': service_id, 'service_per_mwh': efficiency,
            'input_capacity_mw': cap, 'resource_cost_per_mwh': 0.,
            'gross_co2_t_per_mwh': co2, 'liability_co2_t_per_mwh': co2}


def store(identity='battery', node='electricity', initial=0., cap=10., power=10., efficiency=1.):
    return {'id': identity, 'node': node, 'initial_mwh': initial, 'capacity_mwh': cap,
            'terminal_min_mwh': 0., 'charge_mw': power, 'discharge_mw': power,
            'charge_efficiency': efficiency, 'discharge_efficiency': efficiency,
            'throughput_cost_per_mwh': .001}


def empty(hours):
    return {'energy_unit': 'MWh_LHV', 'currency_unit': 'constant_currency',
            'hours': hours, 'annual_weights': [1.] * len(hours),
            'information_mode': 'announced_window', 'nodes': ['electricity', 'gas'],
            'spill_nodes': ['electricity'], 'sources': [], 'processes': [],
            'services': [], 'devices': [], 'stores': [], 'stock_boundary': 'carry',
            'financial_limits': [],
            'capture_storage_budget_t': 0., 'carbon_price_per_t': 0., 'solver_time_limit_s': 30.}


def shared_gas():
    c = empty([1.])
    c['sources'] = [source('gas_supply', 'gas', [10.], 1.)]
    c['processes'] = [process('gas_power', {'gas': 2.}, {'electricity': 1.}, 10., [1.], co2=.4)]
    c['services'] = [service('industry', [6.], 0), service('building', [5.], 1)]
    c['devices'] = [device('gas_heat', 'gas', 'industry', co2=.2), device('appliance', 'electricity', 'building')]
    return c


def storage_window():
    c = empty([1., 1.])
    c['sources'] = [source('renewable', 'electricity', [10., 0.], nonfossil=True),
                    source('gas_supply', 'gas', [10., 0.], 1.)]
    c['processes'] = [process('gas_power', {'gas': 1.}, {'electricity': 1.}, 10., [1., 1.], co2=.2)]
    c['services'] = [service('load', [10., 10.])]
    c['devices'] = [device('load_device', 'electricity', 'load')]
    c['stores'] = [store()]
    return c


def annual_case():
    op = shared_gas()
    op['nodes'] += ['sunlight', 'oil']
    op['sources'] += [source('sun', 'sunlight', [100.], nonfossil=True), source('oil_supply','oil',[10.],2.)]
    op['processes'] += [process('solar_power', {'sunlight':1.}, {'electricity':1.}, 1., [1.])]
    op['services'] += [service('mobility',[2.])]
    op['devices'] += [device('car','oil','mobility',co2=.3),device('heat_pump','electricity','industry',efficiency=2.,cap=1.)]
    ownership = {'gas_supply':'fuel','sun':'fuel','oil_supply':'fuel','gas_power':'generation','solar_power':'generation',
                 'gas_heat':'industrial','appliance':'buildings','car':'transport','heat_pump':'industrial'}
    roles = {'fuel':'fuel_supplier','generation':'generator','industrial':'industry','transport':'transport',
             'buildings':'building','grid':'grid_storage','government':'government'}
    agents = [{'id':i,'role':r,'cash':100.,'credit_limit':0.,'initial_margins':{}} for i,r in roles.items()]
    agents[1]['initial_margins'] = {'solar_build':0.}
    agents[2]['initial_margins'] = {'heat_upgrade':0.}
    assets = []
    for kind,collection in [('source','sources'),('process','processes'),('device','devices')]:
        for row in op[collection]:
            assets.append({'id':row['id']+'_asset','owner':ownership[row['id']],'kind':kind,
                           'component':row['id'],'quantity':0. if row['id'] in ('solar_power','heat_pump') else 1.,
                           'online_year':2024,'state':'operating','fixed_om_per_unit':0.})
    option = {'id':'solar_build','owner':'generation','kind':'process','component':'solar_power',
              'capex_per_unit':.1,'annual_installation_units':3.,'maximum_total_units':6.,
              'fixed_om_per_unit':0.,'discount_rate':.05,'economic_life':20.,'expected_utilisation':1.,
              'replacement_ratio':1.,'connection_per_unit':1.,'subsidy_per_unit':0.,'lead_years':2,
              'construction_fractions':[.5,.5],'expected_terminal_value_per_unit':0.,
              'funding_convention':'fully_funded_nonremunerated_escrow',
              'known_year':2024,'permit_known_year':2024,'permit_effective_year':2024,
              'cost_reference_year':2024,'replaces':None}
    upgrade = deepcopy(option)
    upgrade.update(id='heat_upgrade',owner='industrial',kind='device',component='heat_pump',
                   replaces='gas_heat_asset',replacement_ratio=.002,annual_installation_units=1.,maximum_total_units=2.)
    return {'scope':'synthetic_engineering_only','seed':17,'start_year':2024,'end_year':2028,
            'operation':op,'agents':agents,'assets':assets,'initial_projects':[],
            'investment_options':[option,upgrade], 'asset_events':[],
            'other_accounts':{'clearing':1000.,'external_economy':100000.,'construction':0.,'escrow':0.,'carbon_market':0.},
            'behavior':{'expectation_update':.5,'investment_adjustment':1.},
            'demand_drivers':{s['id']:{'gdp_elasticity':1.,'annual_intensity_improvement':0.} for s in op['services']},
            'gdp_growth':{str(y):.02 for y in range(2025,2029)},
            'cost_decline':{'solar_build':.02,'heat_upgrade':.02},
            'mechanisms':{'investment':True,'replacement':True,'expectation_learning':True},
            'policies':[{'id':'fixture_policy','known_year':2024,'effective_year':2024,
                         'node_prices':{'gas':2.,'oil':3.,'sunlight':0.,'electricity':6.},
                         'service_prices':{'industry':10.,'building':10.,'mobility':10.},
                         'carbon_price_per_t':0.,'government_agent':'government','subsidy_budget':0.,
                         'construction_units_limit':5.,'connection_limit':5.}]}
