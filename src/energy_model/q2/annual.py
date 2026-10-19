"""Mesa annual decisions coupled to constrained within-year operations.

All finance, prices, technology and demand assumptions must be supplied explicitly.
The clearing account and external-economy account expose transfers rather than
adding them to national resource costs. A configured input is not data admission.
"""
from copy import deepcopy
from .approvals import validate_approval_blocks, current_approval_blocks
from math import isfinite

from mesa import Agent, Model

from .operations import OperationError, number, solve_operation, unique
from .finance import project_value, validate_schedule, validate_valuation
from .contracts import active, award_contract, price_adjustment, validate_contract, validate_currency_conversions
from .deployment import allocate_requests, resolve_deployment, validate_deployment
from .demand import activity_signal, validate_activity_driver
from .lifecycle import (apply_event, fixed_maintenance, propose_exits, restrict_expired_assets,
                        validate_lifecycle, validate_replacement)


ROLES = {'fuel_supplier', 'generator', 'industry', 'transport', 'building', 'grid_storage', 'government'}
COMPONENTS = {'source': 'sources', 'process': 'processes', 'device': 'devices', 'store': 'stores'}
STATES = {'operating', 'standby', 'mothballed', 'retired'}


class SectorAgent(Agent):
    def __init__(self, model, spec):
        super().__init__(model)
        self.identity = spec['id']
        self.role = spec['role']
        self.cash = float(spec['cash'])
        self.credit_limit = float(spec['credit_limit'])
        self.expectations = dict(spec['initial_margins'])

    def propose(self, snapshot, operation):
        model = self.model
        proposals = []
        for option in sorted(model.config['investment_options'], key=lambda x:x['id']):
            if option['owner'] != self.identity or option['known_year'] > model.year:
                continue
            component = model.component(option['kind'], option['component'])
            margin = model.margin_per_unit(option, component, snapshot, operation)
            previous = self.expectations[option['id']]
            rate = model.config['behavior']['expectation_update']
            if model.config['mechanisms']['expectation_learning'] is False:
                rate = 0.
            expected = rate * margin + (1-rate) * previous
            self.expectations[option['id']] = expected
            capex = model.capex(option)
            contract, adjustments = model.expected_contract_cash(option, component, snapshot, operation)
            valuation = project_value(option, capex, expected, operating_adjustments=adjustments)
            # Device replacement uses same-service expenditure saving, not revenue.
            permit_end = option.get('lifecycle',{}).get('permit_valid_through')
            permission_horizon_ok = permit_end is None or permit_end >= model.year+option['lead_years']+int(option['economic_life'])-1
            viable = valuation['investment_npv'] > 0 and permission_horizon_ok
            decision = {'year': model.year, 'agent': self.identity, 'option': option['id'],
                        'observed_margin': margin, 'previous_expectation': previous,
                        'updated_expectation': expected, **valuation, 'proposed': viable,
                        'permission_covers_valued_operation':permission_horizon_ok,
                        'information_cutoff': model.year, 'information_id': snapshot['id']}
            if contract is not None:
                decision['expected_revenue_contract']=contract
            if 'device_utilisation_rule' in option:
                _, used_utilisation = model.expected_activity(option, component, operation)
                decision['device_utilisation_rule'] = option['device_utilisation_rule']
                decision['valuation_utilisation'] = used_utilisation
            if 'investment_group' in option:
                decision['investment_group'] = option['investment_group']
                decision['installation_limit_units'] = model.installation_limit(option)
            model.actions.append(decision)
            if not viable or model.config['mechanisms']['investment'] is False:
                continue
            pending = sum(p['quantity'] for p in model.projects if p['option'] == option['id'] and p['state'] == 'building')
            in_use = sum(a['quantity'] for a in model.assets if a['kind'] == option['kind'] and a['component'] == option['component'] and a['state'] != 'retired')
            headroom = max(0., option['maximum_total_units'] - in_use - pending)
            quantity = min(headroom, model.installation_limit(option)) * model.config['behavior']['investment_adjustment']
            if option['replaces'] is not None:
                old = next(a for a in model.assets if a['id'] == option['replaces'])
                already = sum(p['replacement_units'] for p in model.projects
                              if p['state'] == 'building' and p['replaces'] == old['id'])
                available = max(0., old['quantity'] - already) if old['state'] != 'retired' else 0.
                quantity = min(quantity, available / option['replacement_ratio'])
            quantity = min(quantity, max(0., self.cash) / capex)
            if quantity > 1e-10:
                proposals.append({'option': option['id'], 'owner': self.identity,
                                  'quantity': quantity, 'benefit_per_cost': valuation['investment_npv'] / capex})
        return proposals


class EnergyModel(Model):
    def __init__(self, config):
        super().__init__(seed=config['seed'])
        self.config = deepcopy(config)
        self.year = config['start_year']
        self.assets = deepcopy(config['assets'])
        self.projects = deepcopy(config['initial_projects'])
        self.pending_asset_events = []
        self.cash_ledger, self.actions, self.asset_ledger, self.project_ledger = [], [], [], []
        self.information, self.operations, self.annual_rows = [], [], []
        self._validate()
        self.sectors = {s['id']: SectorAgent(self, s) for s in sorted(config['agents'],key=lambda a:a['id'])}
        self.accounts = dict(config['other_accounts'])
        self._opening_total = sum(a.cash for a in self.sectors.values()) + sum(self.accounts.values())
        self.base_demands = {s['id']: list(s['demand']) for s in config['operation']['services']}
        self.activities = {k: 1. for k in self.base_demands}
        self.stocks = {s['id']: s['initial_mwh'] for s in config['operation']['stores']}
        self.rates = {p['id']: p['initial_rate_mw'] for p in config['operation']['processes']}

    def _validate(self):
        c = self.config
        if type(c['start_year']) is not int or type(c['end_year']) is not int or c['end_year'] < c['start_year']:
            raise ValueError('Invalid simulation years')
        for group in ('agents', 'assets', 'initial_projects', 'investment_options', 'policies', 'asset_events'):
            unique(c[group], group)
        agents = {a['id']:a for a in c['agents']}
        if {a['role'] for a in agents.values()} != ROLES:
            raise ValueError('All seven final agent roles must be represented')
        for a in agents.values():
            number(a['cash'], 'opening cash'); number(a['credit_limit'], 'credit limit')
        if set(agents) & set(c['other_accounts']):
            raise ValueError('Duplicate cash account')
        if not {'clearing', 'external_economy', 'construction', 'escrow', 'carbon_market'} <= set(c['other_accounts']):
            raise ValueError('Explicit settlement accounts required')
        for account, amount in c['other_accounts'].items():
            number(amount, account)
        for k in ('expectation_update', 'investment_adjustment'):
            if not 0 <= number(c['behavior'][k], k) <= 1:
                raise ValueError('Behavioral rate must be in [0,1]')
        for a in c['assets']:
            if a['owner'] not in agents or a['kind'] not in COMPONENTS or a['state'] not in STATES:
                raise ValueError('Unknown asset owner/type/state')
            number(a['quantity'], 'asset quantity')
            number(a['fixed_om_per_unit'], 'fixed O&M')
            if a['online_year'] > c['start_year']:
                raise ValueError('Future capacity belongs in project queue')
            self.component(a['kind'], a['component'])
            validate_lifecycle(a, required=c['scope']=='national_q2')
            self.validate_revenue_contract(a,agents)
        for option in c['investment_options']:
            if option['owner'] not in agents or option['id'] not in agents[option['owner']]['initial_margins']:
                raise ValueError('Investment owner/initial expectation missing')
            self.component(option['kind'], option['component'])
            for k in ('capex_per_unit', 'annual_installation_units', 'maximum_total_units',
                      'fixed_om_per_unit', 'discount_rate', 'economic_life', 'expected_utilisation',
                      'replacement_ratio', 'connection_per_unit', 'subsidy_per_unit'):
                number(option[k], k, positive=k in {'capex_per_unit','economic_life','replacement_ratio'})
            if type(option['lead_years']) is not int or option['lead_years'] < 1:
                raise ValueError('Investment cannot commission in application year')
            if option['expected_utilisation'] > 1:
                raise ValueError('Utilisation above one')
            utilisation_rule = option.get('device_utilisation_rule', 'declared')
            if utilisation_rule not in {'declared', 'replaced_device_observed'}:
                raise ValueError('Unknown device utilisation expectation rule')
            if 'device_utilisation_rule' in option and (option['kind'] != 'device' or option['replaces'] is None):
                raise ValueError('Device utilisation rule requires a replacement option')
            validate_valuation(option)
            if option['replaces'] is not None and option['replaces'] not in {a['id'] for a in c['assets']}:
                raise ValueError('Unknown replacement asset')
            validate_lifecycle(option, required=c['scope']=='national_q2', option=True)
            if 'lifecycle' in option and option['economic_life']>option['lifecycle']['technical_life_years']:
                raise ValueError('Valued operating life exceeds declared technical life')
            validate_replacement(self, option)
            self.validate_revenue_contract(option,agents,offer=True)
        groups = c.get('investment_groups', [])
        unique(groups, 'investment_groups')
        group_map = {g['id']: g for g in groups}
        claimed = set()
        for group in groups:
            if group['kind'] not in COMPONENTS or not group['components'] or len(set(group['components'])) != len(group['components']):
                raise ValueError('Invalid investment group components')
            for identity in group['components']:
                self.component(group['kind'], identity)
                key = (group['kind'], identity)
                if key in claimed:
                    raise ValueError('Overlapping investment groups')
                claimed.add(key)
            for field in ('annual_installation_floor', 'stock_expansion_rate', 'maximum_total_units'):
                number(group[field], 'investment group ' + field)
        for option in c['investment_options']:
            identity = option.get('investment_group')
            group = group_map.get(identity)
            if identity is not None and (group is None or option['kind'] != group['kind'] or option['component'] not in group['components']):
                raise ValueError('Investment option group missing or incompatible')
            if (option['kind'], option['component']) in claimed and identity is None:
                raise ValueError('Grouped component option cannot bypass shared capacity')
        validate_deployment(c)
        validate_approval_blocks(c)
        for p in c['initial_projects']:
            validate_lifecycle(p, required=c['scope']=='national_q2', option=True)
            self.validate_revenue_contract(p,agents)
            number(p['cost'],'initial project cost',positive=True)
            number(p['remaining_cost'],'initial project remaining cost')
            number(p['quantity'],'initial project quantity')
            if p['applied_year'] >= c['start_year'] or p['online_year'] < c['start_year']:
                raise ValueError('Initial project chronology invalid')
            if p['state'] != 'building' or p['remaining_cost'] < 0 or p['quantity'] < 0:
                raise ValueError('Invalid initial project')
            validate_schedule(p['construction_fractions'],p['lead_years'])
            if p['online_year']!=p['applied_year']+p['lead_years']:
                raise ValueError('Initial project lead time differs from commissioning date')
            expected_remaining = p['cost']*sum(f for offset,f in enumerate(p['construction_fractions'])
                                              if p['applied_year']+offset>=c['start_year'])
            if abs(expected_remaining-p['remaining_cost'])>1e-7*max(1.,p['cost']):
                raise ValueError('Initial project balance differs from unpaid construction schedule')
        if abs(sum(p['remaining_cost'] for p in c['initial_projects']) - c['other_accounts']['escrow']) > 1e-7:
            raise ValueError('Initial queue commitments do not match escrow')
        # Service-level driver paths must exist before execution, including holdout years.
        ids = {s['id'] for s in c['operation']['services']}
        if set(c['demand_drivers']) != ids:
            raise ValueError('Every service needs a separately declared activity driver')
        for service, driver in c['demand_drivers'].items():
            if 'activity_series' in driver:
                validate_activity_driver(driver, c['start_year'], c['end_year'])
            else:
                number(driver['gdp_elasticity'], 'gdp elasticity')
            if not 0 <= number(driver['annual_intensity_improvement'], 'intensity improvement') < 1:
                raise ValueError('Invalid intensity path')
            for y in range(c['start_year']+1, c['end_year']+1):
                v = c['gdp_growth'][str(y)]
                if type(v) not in (int,float) or not isfinite(v) or v <= -1:
                    raise ValueError('Invalid GDP driver')
        for key in ('investment','replacement','expectation_learning'):
            if type(c['mechanisms'][key]) is not bool:
                raise ValueError('Explicit mechanism switch required')

        validate_currency_conversions(c)
        if any('revenue_contract' in r for group in ('assets','initial_projects','investment_options') for r in c[group]):
            for policy in c['policies']:
                number(policy['operating_support_budget'],'annual gross operating-support budget')

    def validate_revenue_contract(self, record, agents, *, offer=False):
        if 'revenue_contract' not in record:
            return
        contract=record['revenue_contract']
        validate_contract(contract,offer=offer)
        if record['kind']!='process' or contract['output_carrier'] not in self.component('process',record['component'])['outputs']:
            raise ValueError('Generation contract must name a process output carrier')
        if contract['payer'] not in agents or agents[contract['payer']]['role']!='government':
            raise ValueError('Generation support requires an explicit government payer')
        if not offer:
            if contract['known_year']>self.config['start_year']:
                raise ValueError('Opening asset or queue cannot contain a future unknown contract award')
            if contract['start_year']<record['online_year']:
                raise ValueError('Contract cannot pay before commissioning')
            if 'remaining_cost' in record and 'commission_by_year' not in contract:
                raise ValueError('Queued contract requires an explicit commissioning deadline')

    def component(self, kind, identity):
        return next(v for v in self.config['operation'][COMPONENTS[kind]] if v['id'] == identity)

    def cash(self, identity):
        return self.sectors[identity].cash if identity in self.sectors else self.accounts[identity]

    def transfer(self, payer, payee, amount, reason, reference, *, asset=None, contract=None):
        if not isfinite(amount) or amount < -1e-7:
            raise ValueError('Invalid cash transfer')
        amount = max(0., float(amount))
        if not amount:
            return
        for identity, sign in ((payer,-1), (payee,1)):
            if identity in self.sectors:
                self.sectors[identity].cash += sign * amount
            else:
                self.accounts[identity] += sign * amount
        self.cash_ledger.append({'year':self.year,'payer':payer,'payee':payee,'amount':amount,
                                 'reason':reason,'reference':reference})
        if asset is not None:
            self.cash_ledger[-1].update(asset=asset,contract=contract)

    def visible_policy(self):
        visible = [p for p in self.config['policies'] if p['known_year'] <= self.year and p['effective_year'] <= self.year]
        if not visible:
            raise ValueError(f'No visible policy for {self.year}')
        keys = [(p['effective_year'],p['known_year']) for p in visible]
        if len(keys) != len(set(keys)):
            raise ValueError('Ambiguous simultaneous policy snapshots')
        policy = deepcopy(max(visible,key=lambda p:(p['effective_year'],p['known_year'])))
        return resolve_deployment(self, policy)

    def capex(self, option):
        # Historical costs must be provided by historical option vintages; this
        # declared forward trend applies only after its reference year.
        decline = self.config['cost_decline'][option['id']]
        if not 0 <= decline < 1:
            raise ValueError('Invalid cost decline')
        return option['capex_per_unit'] * (1-decline) ** max(0,self.year-option['cost_reference_year'])

    def group_limits(self, group):
        """Declared stock-based supply-chain hypothesis, never future targets.

        Only productive commissioned stock expands annual execution capacity.
        All surviving stock and pending projects consume the shared total ceiling.
        """
        assets = [a for a in self.assets if a['kind'] == group['kind'] and a['component'] in group['components']]
        productive = sum(a['quantity'] for a in assets if a['state'] == 'operating')
        installed = sum(a['quantity'] for a in assets if a['state'] != 'retired')
        pending = sum(p['quantity'] for p in self.projects if p['kind'] == group['kind'] and
                      p['component'] in group['components'] and p['state'] == 'building')
        annual = max(group['annual_installation_floor'], group['stock_expansion_rate'] * productive)
        return annual, max(0., group['maximum_total_units'] - installed - pending)

    def installation_limit(self, option):
        identity = option.get('investment_group')
        if identity is None:
            return option['annual_installation_units']
        group = next(g for g in self.config['investment_groups'] if g['id'] == identity)
        return min(self.group_limits(group))

    def advance_assets(self):
        for p in self.projects:
            if p['state'] != 'building':
                continue
            if self.year >= p['online_year']:
                if abs(p['remaining_cost'])>1e-7*max(1.,p['cost']):
                    raise ValueError('Commissioning with unpaid construction schedule')
                p['remaining_cost'] = 0.
                p['state'] = 'operating'
                self.assets.append({'id':p['id'], 'owner':p['owner'], 'kind':p['kind'],
                                    'component':p['component'], 'quantity':p['quantity'],
                                    'online_year':self.year, 'state':'operating',
                                    'fixed_om_per_unit':p['fixed_om_per_unit'],
                                    **({'lifecycle':deepcopy(p['lifecycle'])} if 'lifecycle' in p else {})})
                if 'revenue_contract' in p:
                    if self.year>p['revenue_contract']['commission_by_year']:
                        raise ValueError('Commissioning missed awarded contract deadline; explicit reassessment required')
                    self.assets[-1]['revenue_contract']=deepcopy(p['revenue_contract'])
                if 'lifecycle' in self.assets[-1]:
                    self.assets[-1]['lifecycle']['initial_loss_years'] = 0
                if p['replaces'] is not None:
                    old = next(a for a in self.assets if a['id'] == p['replaces'])
                    if p['replacement_units'] > old['quantity'] + 1e-8:
                        raise ValueError('Invalid commissioned replacement')
                    old['quantity'] -= p['replacement_units']
                    if old['quantity'] < 1e-8:
                        old['state'] = 'retired'; old['quantity'] = 0.
            elif self.year > p['applied_year']:
                offset = self.year-p['applied_year']
                payment = (p['remaining_cost'] if offset==p['lead_years']-1 else
                           min(p['remaining_cost'],p['cost']*p['construction_fractions'][offset]))
                self.transfer('escrow','construction',payment,'construction_progress',p['id'])
                p['remaining_cost'] -= payment
        events = [*self.config['asset_events'], *self.pending_asset_events]
        applicable = [e for e in events if e['effective_year']==self.year and e['known_year']<=self.year]
        if len({e['asset'] for e in applicable}) != len(applicable):
            raise ValueError('Conflicting same-year asset events require explicit resolution')
        for event in sorted(applicable, key=lambda e:e['id']):
            apply_event(self,event)
        restrict_expired_assets(self)

    def operating_config(self, snapshot):
        op = deepcopy(self.config['operation'])
        for kind, collection in COMPONENTS.items():
            for comp in op[collection]:
                quantity = sum(a['quantity'] for a in self.assets if a['kind'] == kind and
                               a['component'] == comp['id'] and a['state'] == 'operating')
                if kind == 'source':
                    comp['limit_mw'] = [v*quantity for v in comp['limit_mw']]
                    comp['window_budget_mwh'] *= quantity
                elif kind == 'process':
                    for k in ('capacity_mw','ramp_mw_per_hour','window_budget_mwh'):
                        comp[k] *= quantity
                    comp['initial_rate_mw'] = min(self.rates[comp['id']],comp['capacity_mw'])
                elif kind == 'device':
                    comp['input_capacity_mw'] *= quantity
                else:
                    for k in ('capacity_mwh','charge_mw','discharge_mw'):
                        comp[k] *= quantity
                    if self.stocks[comp['id']] > comp['capacity_mwh'] + 1e-8:
                        raise ValueError('Retirement would destroy stored energy; explicit disposition required')
                    comp['initial_mwh'] = self.stocks[comp['id']]
        for s in op['services']:
            driver = self.config['demand_drivers'][s['id']]
            if 'activity_series' in driver:
                self.activities[s['id']] = activity_signal(driver, self.year)['activity_ratio']
            elif self.year > self.config['start_year']:
                growth = self.config['gdp_growth'][str(self.year)]
                self.activities[s['id']] *= (1+growth) ** driver['gdp_elasticity']
            intensity = (1-driver['annual_intensity_improvement']) ** (self.year-self.config['start_year'])
            s['demand'] = [v*self.activities[s['id']]*intensity for v in self.base_demands[s['id']]]
        op['carbon_price_per_t'] = snapshot['carbon_price_per_t']
        op['financial_limits'] = self.finance_limits(op,snapshot)
        return op

    def owner(self, kind, identity):
        owners = {a['owner'] for a in self.assets if a['kind'] == kind and a['component'] == identity}
        owners.update(o['owner'] for o in self.config['investment_options'] if o['kind'] == kind and o['component'] == identity)
        if len(owners) != 1:
            raise ValueError(f'Component {identity} requires one unambiguous owner')
        return next(iter(owners))

    def unit_transactions(self, op, policy):
        """Bind every modelled transfer to the physical activity that causes it."""
        prices = policy['node_prices']; carbon = policy['carbon_price_per_t']
        terms = []
        def tx(kind, identity, payer, payee, coefficient, reason):
            number(coefficient, reason)
            terms.append({'kind':kind,'id':identity,'payer':payer,'payee':payee,
                          'coefficient':coefficient,'reason':reason})
        for s in op['sources']:
            owner = self.owner('source',s['id'])
            tx('source',s['id'],'clearing',owner,prices[s['node']],'carrier_sale')
            tx('source',s['id'],owner,'external_economy',s['resource_cost_per_mwh'],'source_resource')
        for p in op['processes']:
            owner = self.owner('process',p['id'])
            tx('process',p['id'],owner,'clearing',sum(v*prices[k] for k,v in p['inputs'].items()),'conversion_purchase')
            tx('process',p['id'],'clearing',owner,sum(v*prices[k] for k,v in p['outputs'].items()),'conversion_sale')
            tx('process',p['id'],owner,'external_economy',p['resource_cost_per_mwh'],'conversion_resource')
            tx('process',p['id'],owner,'carbon_market',carbon*p['liability_co2_t_per_mwh'],'compliance')
        for d in op['devices']:
            owner = self.owner('device',d['id'])
            tx('device',d['id'],owner,'clearing',prices[d['node']],'end_use_purchase')
            tx('device',d['id'],owner,'external_economy',d['resource_cost_per_mwh'],'end_use_resource')
            tx('device',d['id'],'external_economy',owner,policy['service_prices'][d['service']]*d['service_per_mwh'],'service_sale')
            tx('device',d['id'],owner,'carbon_market',carbon*d['liability_co2_t_per_mwh'],'compliance')
        for s in op['stores']:
            owner = self.owner('store',s['id'])
            tx('charge',s['id'],owner,'clearing',prices[s['node']],'storage_purchase')
            tx('discharge',s['id'],'clearing',owner,prices[s['node']],'storage_sale')
            for kind in ('charge','discharge'):
                tx(kind,s['id'],owner,'external_economy',s['throughput_cost_per_mwh'],'storage_resource')
        # Identical physical cohorts share their component's dispatched output
        # pro rata. A premium applies only to the entitled operating cohort.
        for asset in sorted(self.assets,key=lambda a:a['id']):
            contract=asset.get('revenue_contract')
            if contract is None or asset['state']!='operating' or not active(contract,self.year):
                continue
            total=sum(a['quantity'] for a in self.assets if a['kind']=='process' and
                      a['component']==asset['component'] and a['state']=='operating')
            if not total or not asset['quantity']:
                continue
            component=self.component('process',asset['component'])
            increment=price_adjustment(contract,policy,self.year)*component['outputs'][contract['output_carrier']]*asset['quantity']/total
            payer,payee=(contract['payer'],asset['owner']) if increment>=0 else (asset['owner'],contract['payer'])
            tx('process',asset['component'],payer,payee,abs(increment),
               'operating_contract_support' if increment>=0 else 'operating_contract_clawback')
            terms[-1]['contract_id']=contract['id']
            terms[-1]['contract_asset']=asset['id']
        return terms

    def finance_limits(self, op, policy):
        terms = self.unit_transactions(op,policy)
        limits = []
        for identity in [*self.sectors, *self.accounts]:
            agent = self.sectors.get(identity)
            bound = self.cash(identity) + (agent.credit_limit if agent else 0.)
            if agent:
                bound -= sum(fixed_maintenance(a) for a in self.assets if a['owner']==identity)
            if bound < -1e-6:
                raise OperationError('financial_infeasible',f'{identity}: credit exhausted before dispatch')
            row = []
            for t in terms:
                coefficient = t['coefficient'] * (int(t['payer'] == identity)-int(t['payee'] == identity))
                if coefficient:
                    row.append({'kind':t['kind'],'id':t['id'],'coefficient':coefficient})
            limits.append({'id':identity,'available_cash':max(0.,bound),'terms':row})
        if 'operating_support_budget' in policy:
            support=[{'kind':t['kind'],'id':t['id'],'coefficient':t['coefficient']} for t in terms
                     if t['reason']=='operating_contract_support']
            limits.append({'id':'__gross_operating_support_budget__',
                           'available_cash':policy['operating_support_budget'],'terms':support})
        return limits

    def settle(self, op, result, policy):
        amounts = {}
        for row in result['flows']:
            key = row['kind'],row['id']
            amounts[key] = amounts.get(key,0.) + row['value'] * row['annual_weight']
        for term in self.unit_transactions(op,policy):
            reference=term['kind']+':'+term['id']
            if 'contract_id' in term:
                reference+=':'+term['contract_id']+':'+term['contract_asset']
            self.transfer(term['payer'],term['payee'],amounts.get((term['kind'],term['id']),0.) * term['coefficient'],
                          term['reason'],reference,asset=term.get('contract_asset'),contract=term.get('contract_id'))
        for asset in self.assets:
            if asset['state']!='retired':
                self.transfer(asset['owner'],'external_economy',fixed_maintenance(asset),
                              'fixed_om',asset['id'])
        for identity,agent in self.sectors.items():
            if agent.cash < -agent.credit_limit - 1e-6:
                raise OperationError('financial_infeasible',f'{identity}: annual settlement exceeded credit')
        for identity,balance in self.accounts.items():
            if balance < -1e-6:
                raise OperationError('financial_infeasible',f'{identity}: settlement account exhausted')

    def expected_activity(self, option, component, result):
        h = sum(a*b for a,b in zip(self.config['operation']['hours'],self.config['operation']['annual_weights']))
        utilisation = option['expected_utilisation']
        quantity = sum(a['quantity'] for a in self.assets if a['kind']==option['kind'] and
                       a['component']==component['id'] and a['state']=='operating')
        if quantity>0 and option['kind'] in ('source','process'):
            activity=sum(r['value']*r['annual_weight'] for r in result['flows']
                         if r['kind']==option['kind'] and r['id']==component['id'])
            potential = (component['capacity_mw']*h if option['kind']=='process' else
                         sum(mw*hours*w for mw,hours,w in zip(component['limit_mw'],self.config['operation']['hours'],self.config['operation']['annual_weights'])))
            utilisation=activity/(quantity*potential) if potential else 0.
        elif option['kind']=='device' and option.get('device_utilisation_rule')=='replaced_device_observed':
            old_asset = next(a for a in self.assets if a['id']==option['replaces'])
            old = self.component('device', old_asset['component'])
            # Dispatch is recorded by component, not by individual asset. Use
            # the common utilisation of its operating stock; do not attribute
            # other cohorts' production to a standby/retired replacement target.
            stock = sum(a['quantity'] for a in self.assets if a['kind']=='device'
                        and a['component']==old['id'] and a['state']=='operating')
            potential = stock * old['input_capacity_mw'] * h
            rows = [r for r in result['flows'] if r['kind']=='device' and r['id']==old['id']]
            if len(rows)!=len(self.config['operation']['hours']) or {r['step'] for r in rows}!=set(range(len(rows))):
                raise ValueError('Complete unique dispatch steps required for replacement valuation')
            activity = sum(r['value']*r['annual_weight'] for r in rows)
            utilisation = (activity/potential if potential>0 and old_asset['state']=='operating'
                           and old_asset['quantity']>0 else 0.)
            if not isfinite(utilisation) or utilisation < -1e-8 or utilisation > 1+1e-8:
                raise ValueError('Observed replacement utilisation outside physical capacity')
            utilisation = min(1., max(0., utilisation))
        return h,utilisation

    def expected_contract_cash(self, option, component, policy, result):
        offer=option.get('revenue_contract')
        if offer is None:
            return None,None
        start=self.year+option['lead_years']
        contract=award_contract(offer,self.year,start)
        if contract is None:
            return None,None
        h,utilisation=self.expected_activity(option,component,result)
        output=component['capacity_mw']*h*utilisation*component['outputs'][contract['output_carrier']]
        # Keep today's conversion fixed in the expectation. Future policy
        # snapshots/realized FX are intentionally unavailable to this valuation.
        increment=output*price_adjustment(contract,policy,self.year)
        return contract,[increment if active(contract,y) else 0.
                         for y in range(start,start+int(option['economic_life']))]

    def margin_per_unit(self, option, component, policy, result):
        h,utilisation=self.expected_activity(option,component,result)
        price = policy['node_prices']; carbon = policy['carbon_price_per_t']
        if option['kind'] == 'process':
            margin = (sum(v*price[k] for k,v in component['outputs'].items()) -
                      sum(v*price[k] for k,v in component['inputs'].items()) - component['resource_cost_per_mwh'] -
                      carbon * component['liability_co2_t_per_mwh'])
            return margin * component['capacity_mw'] * h * utilisation
        if option['kind'] == 'source':
            return (price[component['node']] - component['resource_cost_per_mwh']) * sum(
                mw*hours*w for mw,hours,w in zip(component['limit_mw'],self.config['operation']['hours'],self.config['operation']['annual_weights'])) * utilisation
        if option['kind'] == 'device':
            if option['replaces'] is None or self.config['mechanisms']['replacement'] is False:
                return 0.
            old_asset = next(a for a in self.assets if a['id']==option['replaces'])
            old = self.component('device',old_asset['component'])
            if old['service'] != component['service']:
                raise ValueError('Equipment comparison must deliver the same service')
            def unit_cost(d):
                return (price[d['node']]+d['resource_cost_per_mwh']+carbon*d['liability_co2_t_per_mwh']) / d['service_per_mwh']
            avoided_fixed = old_asset['fixed_om_per_unit'] * option['replacement_ratio']
            if option.get('device_utilisation_rule')=='replaced_device_observed':
                avoided_fixed = (fixed_maintenance(old_asset)/old_asset['quantity']*option['replacement_ratio']
                                 if old_asset['quantity']>0 else 0.)
            return ((unit_cost(old)-unit_cost(component))*component['service_per_mwh']*component['input_capacity_mw']*h*utilisation
                    + avoided_fixed)
        # Storage capacity is only financed from an observed dispatch margin;
        # no unpriced reliability benefit is invented to force a build.
        quantity = sum(a['quantity'] for a in self.assets if a['kind']=='store' and a['component']==component['id'] and a['state']=='operating')
        if quantity == 0:
            return self.sectors[option['owner']].expectations[option['id']]
        net = 0.
        for row in result['flows']:
            if row['id']==component['id'] and row['kind'] in ('charge','discharge'):
                sign = 1 if row['kind']=='discharge' else -1
                net += row['value']*row['annual_weight']*(sign*price[component['node']]-component['throughput_cost_per_mwh'])
        return net/quantity

    def approve(self, proposals, policy):
        blocks = current_approval_blocks(self.config, self.year)
        proposals, allocation = allocate_requests(self, proposals, policy, blocks)
        self.actions.extend(allocation)
        construction = policy['construction_units_limit']
        connection = policy['connection_limit']
        government = self.sectors[policy['government_agent']]
        subsidy_budget = min(policy['subsidy_budget'], max(0.,government.cash))
        group_remaining = {g['id']: min(self.group_limits(g)) for g in self.config.get('investment_groups', [])}
        for proposal in sorted(proposals,key=lambda p:(-p['benefit_per_cost'],p['owner'],p['option'])):
            option = next(o for o in self.config['investment_options'] if o['id']==proposal['option'])
            if option['id'] in blocks:
                event = blocks[option['id']]
                self.actions.append({'year':self.year,'option':option['id'],'approved_units':0.,
                                     'requested_units':proposal['quantity'],
                                     'reason':'realized_administrative_nonissuance',
                                     'event':event['id'],'evidence':event['evidence']})
                continue
            owner = self.sectors[proposal['owner']]
            quantity = min(proposal['quantity'],construction,max(0.,owner.cash)/self.capex(option))
            group = option.get('investment_group')
            if group is not None:
                quantity = min(quantity, group_remaining[group])
            if option['connection_per_unit'] > 0:
                quantity = min(quantity,connection/option['connection_per_unit'])
            if option['permit_known_year'] > self.year or option['permit_effective_year'] > self.year:
                quantity = 0.
            if option['replaces'] is not None:
                old = next(a for a in self.assets if a['id']==option['replaces'])
                reserved = sum(p['replacement_units'] for p in self.projects
                               if p['state']=='building' and p['replaces']==old['id'])
                available = max(0.,old['quantity']-reserved) if old['state']!='retired' else 0.
                quantity = min(quantity,available/option['replacement_ratio'])
            if quantity <= 1e-10:
                self.actions.append({'year':self.year,'option':option['id'],'approved_units':0.,'reason':'budget_engineering_or_permit'})
                continue
            cost = quantity*self.capex(option)
            subsidy = min(subsidy_budget,quantity*option['subsidy_per_unit'],cost)
            pid = f"{option['id']}@{self.year}"
            self.transfer(policy['government_agent'],owner.identity,subsidy,'investment_subsidy',pid)
            self.transfer(owner.identity,'escrow',cost,'capital_commitment',pid)
            lead = option['lead_years']
            p = {'id':pid,'option':option['id'],'owner':owner.identity,'kind':option['kind'],
                 'component':option['component'],'quantity':quantity,'applied_year':self.year,
                 'online_year':self.year+lead,'lead_years':lead,'cost':cost,'remaining_cost':cost,
                 'state':'building','replaces':option['replaces'],
                 'construction_fractions':list(option['construction_fractions']),
                 'fixed_om_per_unit':option['fixed_om_per_unit'],
                 'replacement_units':quantity*option['replacement_ratio'] if option['replaces'] else 0.}
            if 'lifecycle' in option:
                p['lifecycle'] = deepcopy(option['lifecycle'])
            if 'revenue_contract' in option:
                award=award_contract(option['revenue_contract'],self.year,p['online_year'])
                if award is not None:
                    p['revenue_contract']=award
            self.projects.append(p)
            # First physical construction spending is at application, offset 0.
            # Committed but unspent money remains escrow, not resource cost.
            initial_payment = cost*option['construction_fractions'][0]
            self.transfer('escrow','construction',initial_payment,'construction_progress',pid)
            p['remaining_cost'] -= initial_payment
            construction -= quantity; connection -= quantity*option['connection_per_unit']; subsidy_budget -= subsidy
            if group is not None:
                group_remaining[group] -= quantity
            self.actions.append({'year':self.year,'option':option['id'],'approved_units':quantity,'project':pid,
                                 'online_year':p['online_year'],'cost':cost,'subsidy':subsidy})

    def step(self):
        if self.year > self.config['end_year']:
            raise ValueError('Simulation horizon exhausted')
        self.advance_assets()
        policy = self.visible_policy()
        self.information.append({'year':self.year,'policy':deepcopy(policy),
                                 'visible_option_ids':[o['id'] for o in self.config['investment_options'] if o['known_year']<=self.year]})
        op = self.operating_config(policy)
        signals = {service: activity_signal(driver, self.year)
                   for service, driver in self.config['demand_drivers'].items() if 'activity_series' in driver}
        if signals:
            self.information[-1]['realized_activity_signals'] = signals
        result = solve_operation(op)
        self.settle(op,result,policy)
        self.operations.append({'year':self.year,'input':op,'result':result})
        self.stocks.update(result['closing_stocks']); self.rates.update(result['closing_process_rates'])
        proposals = []
        for identity in sorted(self.sectors):
            proposals.extend(self.sectors[identity].propose(policy,result))
        self.approve(proposals,policy)
        propose_exits(self)
        closing = sum(a.cash for a in self.sectors.values())+sum(self.accounts.values())
        residual = closing-self._opening_total
        if abs(residual) > 1e-6+1e-8*max(1.,abs(self._opening_total)):
            raise ValueError('Cash transfers do not conserve total account balances')
        escrow = sum(p['remaining_cost'] for p in self.projects if p['state']=='building')
        if abs(escrow-self.accounts['escrow']) > 1e-6:
            raise ValueError('Outstanding commitments differ from escrow cash')
        self.asset_ledger.extend({'year':self.year,**deepcopy(a)} for a in self.assets)
        self.project_ledger.extend({'year':self.year,**deepcopy(p)} for p in self.projects)
        fixed_om=sum(t['amount'] for t in self.cash_ledger if t['year']==self.year and t['reason']=='fixed_om')
        construction_cost=sum(t['amount'] for t in self.cash_ledger if t['year']==self.year and
                              t['reason'] in ('construction_completion','construction_progress'))
        lifecycle_cost=sum(t['amount'] for t in self.cash_ledger if t['year']==self.year and t['reason']=='lifecycle_resource')
        row = {'year':self.year,**result['totals'],'service_shortfalls':result['service_shortfalls'],
               'fixed_om_resource_cost':fixed_om,'construction_resource_cost':construction_cost,
               'lifecycle_resource_cost':lifecycle_cost,
               'total_resource_cost':result['totals']['resource_cost']+fixed_om+construction_cost+lifecycle_cost,
               'cash_residual':residual,'committed_cash':escrow,
               'agent_cash':{i:a.cash for i,a in self.sectors.items()},'accounts':dict(self.accounts)}
        if 'operating_support_budget' in policy:
            row['operating_support_paid']=sum(t['amount'] for t in self.cash_ledger
                if t['year']==self.year and t['reason']=='operating_contract_support')
            row['operating_support_clawback']=sum(t['amount'] for t in self.cash_ledger
                if t['year']==self.year and t['reason']=='operating_contract_clawback')
        self.annual_rows.append(row)
        self.year += 1
        return row

    def run(self):
        while self.year <= self.config['end_year']:
            self.step()
        return {'annual':self.annual_rows,'assets':self.asset_ledger,'projects':self.project_ledger,
                'actions':self.actions,'information':self.information,'cash':self.cash_ledger,
                'operations':self.operations,'lifecycle_queue':deepcopy(self.pending_asset_events)}
