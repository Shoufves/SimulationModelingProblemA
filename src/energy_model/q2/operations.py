"""Constrained multi-carrier operations, with explicit service and resource books.

All flows are interval MWh (fuel: lower heating value); capacity is MW.
Representative weights affect annual totals, never inventory recurrence.
Storage exclusivity uses binary modes: those problems are MILPs, not pure LPs.
No default numeric inputs are supplied by this module.
"""
from copy import deepcopy
from math import fsum, isfinite

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import coo_matrix


class OperationError(RuntimeError):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def number(value, name, *, positive=False):
    if type(value) not in (int, float) or not isfinite(value):
        raise ValueError(f"{name}: finite numeric input required")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{name}: {'positive' if positive else 'nonnegative'} input required")
    return float(value)


def vector(value, name, size, *, positive=False):
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f"{name}: expected {size} interval values")
    return [number(v, name, positive=positive) for v in value]


def unique(rows, name):
    ids = [r['id'] for r in rows]
    if any(not isinstance(k, str) or not k for k in ids) or len(set(ids)) != len(ids):
        raise ValueError(f"{name}: unique nonempty identifiers required")


def validate(config):
    """Validate before constructing any constraints; missing is never zero."""
    if config['energy_unit'] != 'MWh_LHV' or config['currency_unit'] != 'constant_currency':
        raise ValueError('Explicit common energy and real-currency units required')
    hours = config['hours']
    n = len(hours)
    if not n:
        raise ValueError('Empty operation horizon')
    vector(hours, 'hours', n, positive=True)
    weights = vector(config['annual_weights'], 'annual_weights', n, positive=True)
    if config['information_mode'] not in {'announced_window', 'perfect_foresight_reference'}:
        raise ValueError('Unknown information window')
    nodes = config['nodes']
    if len(nodes) != len(set(nodes)) or not nodes:
        raise ValueError('Unique carrier nodes required')
    if set(config['spill_nodes']) - set(nodes):
        raise ValueError('Unknown spill carrier')
    for collection in ('sources', 'processes', 'services', 'devices', 'stores'):
        unique(config[collection], collection)
    for s in config['sources']:
        if s['node'] not in nodes:
            raise ValueError('Unknown source carrier')
        vector(s['limit_mw'], s['id'], n)
        for k in ('window_budget_mwh', 'resource_cost_per_mwh', 'primary_factor'):
            number(s[k], k)
        if type(s['nonfossil']) is not bool:
            raise ValueError('Nonfossil identity required')
    for p in config['processes']:
        if not p['outputs'] or not p['inputs']:
            raise ValueError('Conversion requires explicit input and output carriers')
        for flows in (p['inputs'], p['outputs']):
            if set(flows) - set(nodes):
                raise ValueError('Unknown conversion carrier')
            for v in flows.values():
                number(v, 'conversion coefficient', positive=True)
        if sum(p['outputs'].values()) > sum(p['inputs'].values()) + 1e-10:
            raise ValueError('Conversion creates energy; environment input must be explicit')
        for k in ('capacity_mw', 'initial_rate_mw', 'ramp_mw_per_hour',
                  'window_budget_mwh', 'resource_cost_per_mwh', 'gross_co2_t_per_mwh',
                  'captured_co2_t_per_mwh', 'liability_co2_t_per_mwh'):
            number(p[k], k)
        if p['captured_co2_t_per_mwh'] > p['gross_co2_t_per_mwh']:
            raise ValueError('Capture exceeds fossil combustion CO2')
        available = vector(p['availability'], 'availability', n)
        minimum = vector(p['minimum_fraction'], 'minimum_fraction', n)
        if any(a > 1 or m > a for a, m in zip(available, minimum)):
            raise ValueError('Invalid availability/minimum output fraction')
    services = {s['id']: s for s in config['services']}
    for s in services.values():
        vector(s['demand'], 'service demand', n)
        number(s['shortfall_weight'], 'shortfall weight', positive=True)
        if type(s['priority']) is not int or s['priority'] < 0 or not s['unit']:
            raise ValueError('Explicit service unit and nonnegative integer priority required')
    for d in config['devices']:
        if d['node'] not in nodes or d['service'] not in services:
            raise ValueError('Unknown device service/carrier')
        for k in ('service_per_mwh', 'input_capacity_mw', 'resource_cost_per_mwh',
                  'gross_co2_t_per_mwh', 'liability_co2_t_per_mwh'):
            number(d[k], k, positive=(k == 'service_per_mwh'))
    for s in config['stores']:
        if s['node'] not in nodes:
            raise ValueError('Unknown storage carrier')
        for k in ('capacity_mwh', 'initial_mwh', 'terminal_min_mwh', 'charge_mw',
                  'discharge_mw', 'throughput_cost_per_mwh'):
            number(s[k], k)
        for k in ('charge_efficiency', 'discharge_efficiency'):
            if not 0 < number(s[k], k, positive=True) <= 1:
                raise ValueError('Invalid storage efficiency')
        if max(s['initial_mwh'], s['terminal_min_mwh']) > s['capacity_mwh']:
            raise ValueError('Storage initial/terminal inventory exceeds capacity')
    # A weighted repeated block must return *every* stock to its initial value.
    # Variable weights with stock interconnection have no physical chronology.
    if any(w != 1 for w in weights):
        if len(set(weights)) != 1 or config['stock_boundary'] != 'cyclic':
            raise ValueError('Weighted inventory requires one uniformly repeated cyclic block')
    if config['stock_boundary'] not in {'cyclic', 'carry'}:
        raise ValueError('Unknown inventory boundary')
    for k in ('capture_storage_budget_t', 'carbon_price_per_t', 'solver_time_limit_s'):
        number(config[k], k, positive=(k == 'solver_time_limit_s'))
    unique(config['financial_limits'], 'financial_limits')
    for limit in config['financial_limits']:
        number(limit['available_cash'], 'available_cash')
        for term in limit['terms']:
            if term['kind'] not in {'source', 'process', 'device', 'charge', 'discharge', 'spill'}:
                raise ValueError('Unknown cash-flow variable kind')
            if type(term['coefficient']) not in (int, float) or not isfinite(term['coefficient']):
                raise ValueError('Invalid cash-flow coefficient')
    return config


class LinearBook:
    def __init__(self):
        self.names, self.bounds, self.integrality = [], [], []
        self.rows, self.lower, self.upper, self.labels = [], [], [], []

    def variable(self, name, upper, lower=0., integer=False):
        i = len(self.names)
        self.names.append(name)
        self.bounds.append((lower, upper))
        self.integrality.append(int(integer))
        return i

    def constraint(self, row, lower, upper, label):
        self.rows.append(dict(row))
        self.lower.append(lower)
        self.upper.append(upper)
        self.labels.append(label)

    def matrix(self):
        ri, ci, values = [], [], []
        for r, row in enumerate(self.rows):
            for c, v in row.items():
                ri.append(r); ci.append(c); values.append(v)
        return coo_matrix((values, (ri, ci)), shape=(len(self.rows), len(self.names))).tocsc()

    def solve(self, objective, time_limit):
        c = np.zeros(len(self.names))
        for i, v in objective.items():
            c[i] = v
        a = self.matrix()
        lb, ub = np.array(self.lower), np.array(self.upper)
        if any(self.integrality):
            result = milp(c, integrality=np.array(self.integrality),
                          bounds=Bounds(*np.array(self.bounds).T),
                          constraints=LinearConstraint(a, lb, ub),
                          options={'time_limit': time_limit, 'mip_rel_gap': 0.0})
        else:
            equal = lb == ub
            neq = ~equal
            # All inequalities constructed below are upper bounds.
            if np.any(np.isfinite(lb[neq])):
                raise ValueError('Internal unsupported two-sided LP inequality')
            result = linprog(c, A_ub=a[neq] if np.any(neq) else None,
                             b_ub=ub[neq] if np.any(neq) else None,
                             A_eq=a[equal] if np.any(equal) else None,
                             b_eq=ub[equal] if np.any(equal) else None,
                             bounds=self.bounds, method='highs',
                             options={'time_limit': time_limit})
        if not result.success:
            raise OperationError('infeasible' if result.status == 2 else 'solver_failed',
                                 f'HiGHS status {result.status}: {result.message}')
        x = result.x
        activity = a @ x
        violations = np.maximum(np.maximum(lb - activity, activity - ub), 0)
        scale = np.maximum(1., np.maximum(abs(activity), np.where(np.isfinite(ub), abs(ub), 0)))
        if np.any(violations > 1e-6 + 1e-8 * scale):
            raise OperationError('residual_failure', 'Constraint residual exceeds fixed tolerance')
        for i, (lo, hi) in enumerate(self.bounds):
            if x[i] < lo - 1e-6 or x[i] > hi + 1e-6:
                raise OperationError('residual_failure', 'Variable bound violated')
            if self.integrality[i] and abs(x[i] - round(x[i])) > 1e-6:
                raise OperationError('residual_failure', 'Storage mode is not integral')
        # Audit objectives must not depend on BLAS reduction order. Reconstruct
        # the same dot product with a deterministic, accurate scalar summation.
        return x, fsum(float(ci)*float(xi) for ci, xi in zip(c, x)), float(max(violations, default=0))


def solve_operation(config):
    """Return auditable flows or raise typed failure; never return fake zero deficits."""
    try:
        c = validate(deepcopy(config))
    except (KeyError, TypeError, ValueError) as exc:
        raise OperationError('invalid_input', str(exc)) from exc
    book = LinearBook()
    n = len(c['hours'])
    balance = {(t, node): {} for t in range(n) for node in c['nodes']}
    service = {(t, s['id']): {} for t in range(n) for s in c['services']}
    variables, costs, liabilities = {}, {}, {}
    capture = {}

    def add(row, i, coefficient):
        row[i] = row.get(i, 0.) + coefficient

    def var(kind, identity, t, upper, lower=0., integer=False):
        i = book.variable(f'{kind}:{identity}:{t}', upper, lower, integer)
        variables[kind, identity, t] = i
        return i

    for s in c['sources']:
        budget = {}
        for t, h in enumerate(c['hours']):
            i = var('source', s['id'], t, s['limit_mw'][t] * h)
            add(balance[t, s['node']], i, 1.)
            costs[i] = s['resource_cost_per_mwh'] * c['annual_weights'][t]
            budget[i] = 1.
        book.constraint(budget, -np.inf, s['window_budget_mwh'], f"source_budget:{s['id']}")
    for p in c['processes']:
        budget = {}
        for t, h in enumerate(c['hours']):
            i = var('process', p['id'], t, p['capacity_mw'] * h * p['availability'][t],
                    p['capacity_mw'] * h * p['minimum_fraction'][t])
            for node, v in p['inputs'].items():
                add(balance[t, node], i, -v)
            for node, v in p['outputs'].items():
                add(balance[t, node], i, v)
            costs[i] = p['resource_cost_per_mwh'] * c['annual_weights'][t]
            liabilities[i] = p['liability_co2_t_per_mwh'] * c['annual_weights'][t]
            capture[i] = p['captured_co2_t_per_mwh']
            budget[i] = 1.
            # Piecewise constant output rates; ramp interval is elapsed duration.
            delta = p['ramp_mw_per_hour'] * h
            if t == 0:
                book.constraint({i: 1/h}, -np.inf, p['initial_rate_mw'] + delta, 'ramp_up')
                book.constraint({i: -1/h}, -np.inf, delta - p['initial_rate_mw'], 'ramp_down')
            else:
                prev = variables['process', p['id'], t-1]
                row = {i: 1/h, prev: -1/c['hours'][t-1]}
                book.constraint(row, -np.inf, delta, 'ramp_up')
                book.constraint({k: -v for k, v in row.items()}, -np.inf, delta, 'ramp_down')
        if c['stock_boundary'] == 'cyclic':
            first, last = variables['process', p['id'], 0], variables['process', p['id'], n-1]
            row = {first: 1/c['hours'][0]}
            add(row, last, -1/c['hours'][-1])
            delta = p['ramp_mw_per_hour'] * c['hours'][0]
            book.constraint(row, -np.inf, delta, 'cyclic_ramp_up')
            book.constraint({k: -v for k,v in row.items()}, -np.inf, delta, 'cyclic_ramp_down')
        book.constraint(budget, -np.inf, p['window_budget_mwh'], f"process_budget:{p['id']}")
    book.constraint(capture, -np.inf, c['capture_storage_budget_t'], 'capture_storage_budget')
    for d in c['devices']:
        for t, h in enumerate(c['hours']):
            i = var('device', d['id'], t, d['input_capacity_mw'] * h)
            add(balance[t, d['node']], i, -1.)
            add(service[t, d['service']], i, d['service_per_mwh'])
            costs[i] = d['resource_cost_per_mwh'] * c['annual_weights'][t]
            liabilities[i] = d['liability_co2_t_per_mwh'] * c['annual_weights'][t]
    for s in c['stores']:
        for t, h in enumerate(c['hours']):
            charge = var('charge', s['id'], t, s['charge_mw'] * h)
            discharge = var('discharge', s['id'], t, s['discharge_mw'] * h)
            stock = var('stock', s['id'], t, s['capacity_mwh'])
            mode = var('charge_mode', s['id'], t, 1, integer=True)
            book.constraint({charge: 1, mode: -s['charge_mw'] * h}, -np.inf, 0, 'charge_mode')
            book.constraint({discharge: 1, mode: s['discharge_mw'] * h},
                            -np.inf, s['discharge_mw'] * h, 'discharge_mode')
            row = {stock: 1, charge: -s['charge_efficiency'], discharge: 1/s['discharge_efficiency']}
            opening = s['initial_mwh'] if t == 0 else 0.
            if t:
                add(row, variables['stock', s['id'], t-1], -1.)
            book.constraint(row, opening, opening, f"inventory:{s['id']}:{t}")
            add(balance[t, s['node']], charge, -1.)
            add(balance[t, s['node']], discharge, 1.)
            costs[charge] = costs[discharge] = s['throughput_cost_per_mwh'] * c['annual_weights'][t]
        last = variables['stock', s['id'], n-1]
        if c['stock_boundary'] == 'cyclic':
            book.constraint({last: 1}, s['initial_mwh'], s['initial_mwh'], 'cyclic_inventory')
        else:
            book.constraint({last: -1}, -np.inf, -s['terminal_min_mwh'], 'terminal_inventory')
    priorities = {}
    for s in c['services']:
        objective = priorities.setdefault(s['priority'], {})
        for t, demand in enumerate(s['demand']):
            i = var('shortfall', s['id'], t, demand)
            add(service[t, s['id']], i, 1.)
            objective[i] = s['shortfall_weight'] * c['annual_weights'][t]
            book.constraint(service[t, s['id']], demand, demand, f"service:{s['id']}:{t}")
    for node in c['spill_nodes']:
        for t in range(n):
            i = var('spill', node, t, np.inf)
            add(balance[t, node], i, -1.)
    for (t, node), row in balance.items():
        book.constraint(row, 0., 0., f'carrier:{node}:{t}')
    for limit in c['financial_limits']:
        row = {}
        for term in limit['terms']:
            for t,w in enumerate(c['annual_weights']):
                key = term['kind'], term['id'], t
                if key not in variables:
                    raise OperationError('invalid_input', f'Unknown cash-flow binding {key}')
                add(row, variables[key], term['coefficient'] * w)
        book.constraint(row, -np.inf, limit['available_cash'], f"cash_limit:{limit['id']}")
    stages = []
    for priority, objective in sorted(priorities.items()):
        x, value, residual = book.solve(objective, c['solver_time_limit_s'])
        stages.append({'stage': f'service_priority_{priority}', 'objective': value, 'max_violation': residual})
        # Divide both sides by the same positive coefficient scale. This is
        # exactly the same lexicographic equality, not a relaxed service target.
        # Annual weights (e.g.365) otherwise magnify roundoff in a national-scale
        # deficit enough for the next LP to reject a feasible first-stage point.
        scale = max(objective.values())
        book.constraint({i: v/scale for i, v in objective.items()}, value/scale, value/scale,
                        f'fixed_shortfall:{priority}')
    # Permit liability is an explicit policy transfer, separate from resource costs.
    objective = dict(costs)
    for i, liability in liabilities.items():
        objective[i] = objective.get(i, 0.) + c['carbon_price_per_t'] * liability
    x, value, residual = book.solve(objective, c['solver_time_limit_s'])
    stages.append({'stage': 'resource_plus_compliance', 'objective': value, 'max_violation': residual})
    rows = []
    for (kind, identity, t), i in variables.items():
        rows.append({'kind': kind, 'id': identity, 'step': t, 'hours': c['hours'][t],
                     'annual_weight': c['annual_weights'][t], 'value': float(x[i])})
    residuals = [{'step': t, 'node': node, 'residual_mwh': float(sum(x[i]*v for i,v in row.items()))}
                 for (t, node), row in balance.items()]
    totals = {'resource_cost': sum(x[i]*v for i,v in costs.items()),
              'compliance_transfer': c['carbon_price_per_t'] * sum(x[i]*v for i,v in liabilities.items()),
              'gross_energy_co2_t': 0., 'captured_co2_t': 0.,
              'primary_mwh': 0., 'nonfossil_primary_mwh': 0.}
    for collection, kind in (('processes', 'process'), ('devices', 'device')):
        for p in c[collection]:
            activity = sum(x[variables[kind, p['id'], t]] * w for t,w in enumerate(c['annual_weights']))
            totals['gross_energy_co2_t'] += activity * p['gross_co2_t_per_mwh']
            if collection == 'processes':
                totals['captured_co2_t'] += activity * p['captured_co2_t_per_mwh']
    for s in c['sources']:
        primary = sum(x[variables['source', s['id'], t]] * w for t,w in enumerate(c['annual_weights'])) * s['primary_factor']
        totals['primary_mwh'] += primary
        if s['nonfossil']:
            totals['nonfossil_primary_mwh'] += primary
    totals['positive_energy_co2_t'] = totals['gross_energy_co2_t'] - totals['captured_co2_t']
    totals = {k: float(v) for k,v in totals.items()}
    deficits = {s['id']: float(sum(x[variables['shortfall', s['id'], t]] * w
                                  for t,w in enumerate(c['annual_weights']))) for s in c['services']}
    return {'status': 'optimal', 'solver': 'scipy-highs-milp' if any(book.integrality) else 'scipy-highs-lp',
            'information_mode': c['information_mode'], 'stages': stages, 'flows': rows,
            'balances': residuals, 'totals': totals, 'service_shortfalls': deficits,
            'closing_stocks': {s['id']: float(x[variables['stock', s['id'], n-1]]) for s in c['stores']},
            'closing_process_rates': {p['id']: float(x[variables['process', p['id'], n-1]] / c['hours'][-1])
                                      for p in c['processes']}}
