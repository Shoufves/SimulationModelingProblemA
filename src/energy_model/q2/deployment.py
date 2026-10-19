"""Explicit alternatives to an assumed common MW deployment bottleneck.

Technology frontiers remain finite and shared across cohorts. Their sum is a
redundant aggregate envelope, not evidence of national construction/grid capacity.
Only unit-MW generation investment options support this scoped alternative.
"""
from copy import deepcopy
from math import fsum

from .operations import number


RULES = {'fixed_global', 'technology_frontiers'}


def validate_deployment(config):
    enabled = False
    for policy in config['policies']:
        allocation = policy.get('approval_allocation', 'benefit_priority')
        if allocation not in {'benefit_priority', 'proportional_requests'}:
            raise ValueError('Unknown investment approval allocation rule')
        enabled |= allocation == 'proportional_requests'
        if 'deployment_limit_rules' not in policy:
            continue
        rules = policy['deployment_limit_rules']
        if (not isinstance(rules, dict) or set(rules) != {'construction', 'connection'}
                or any(rule not in RULES for rule in rules.values())):
            raise ValueError('Explicit construction/connection deployment rules required')
        for field in ('construction_units_limit', 'connection_limit'):
            number(policy[field], 'declared deployment reference ' + field)
        enabled |= 'technology_frontiers' in rules.values()
    if not enabled:
        return
    components = {p['id']: p for p in config['operation']['processes']}
    ungrouped = set()
    for option in config['investment_options']:
        process = components.get(option['component'])
        if (option['kind'] != 'process' or process is None or process['capacity_mw'] != 1
                or option['replaces'] is not None):
            raise ValueError('Deployment alternatives require unit-MW generation additions only')
        if 'investment_group' not in option:
            if option['component'] in ungrouped:
                raise ValueError('Multiple cohorts must share an explicit investment group')
            ungrouped.add(option['component'])


def frontier_rows(model):
    """Opening-year state only; queued stock does not expand productive capacity."""
    eligible = [o for o in model.config['investment_options']
                if max(o['known_year'], o['permit_known_year'], o['permit_effective_year']) <= model.year]
    members = {}
    for option in eligible:
        key = ('group', option['investment_group']) if 'investment_group' in option else ('option', option['id'])
        members.setdefault(key, []).append(option)
    groups = {g['id']: g for g in model.config.get('investment_groups', [])}
    rows = []
    for (kind, identity), options in sorted(members.items()):
        if kind == 'group':
            annual, headroom = model.group_limits(groups[identity])
        else:
            option = options[0]
            stock = fsum(a['quantity'] for a in model.assets if a['kind'] == option['kind']
                         and a['component'] == option['component'] and a['state'] != 'retired')
            queue = fsum(p['quantity'] for p in model.projects if p['kind'] == option['kind']
                         and p['component'] == option['component'] and p['state'] == 'building')
            annual = option['annual_installation_units']
            headroom = max(0., option['maximum_total_units'] - stock - queue)
        capacity = min(annual, headroom)
        coefficient = max(o['connection_per_unit'] for o in options)
        rows.append({'frontier_type': kind, 'frontier_id': identity,
                     'visible_permitted_options': sorted(o['id'] for o in options),
                     'annual_limit_MW': annual, 'remaining_total_headroom_MW': headroom,
                     'construction_envelope_MW': capacity,
                     'maximum_connection_per_MW': coefficient,
                     'connection_envelope': capacity * coefficient})
    return rows


def resolve_deployment(model, policy):
    rules = policy.get('deployment_limit_rules')
    if rules is None or 'technology_frontiers' not in rules.values():
        return policy
    result = deepcopy(policy)
    rows = frontier_rows(model)
    result['deployment_frontier_snapshot'] = rows
    result['deployment_reference_limits'] = {
        'construction_units_limit': policy['construction_units_limit'],
        'connection_limit': policy['connection_limit']}
    for field, rule, component in (
            ('construction_units_limit', 'construction', 'construction_envelope_MW'),
            ('connection_limit', 'connection', 'connection_envelope')):
        if rules[rule] == 'technology_frontiers':
            result[field] = fsum(r[component] for r in rows)
            number(result[field], 'resolved deployment ' + field)
    return result


def allocate_requests(model, proposals, policy, blocks):
    """Pro rata allocation of feasible requests, before shared-budget approval.

This optional generation-only rule preserves positive-NPV application decisions.
It does not optimize investment or introduce observed capacity targets. Group
caps and owner funds are applied before the common construction/connection cap.
Unused capacity is not reassigned after pro rata scaling. No subsidy is assumed
when checking whether the owner can fully fund its request.
"""
    if policy.get('approval_allocation', 'benefit_priority') == 'benefit_priority':
        return proposals, []
    result = deepcopy(proposals)
    options = {o['id']: o for o in model.config['investment_options']}
    if len({p['option'] for p in result}) != len(result):
        raise ValueError('Duplicate investment requests')
    original = {p['option']: p['quantity'] for p in result}
    for p in result:
        option = options[p['option']]
        number(p['quantity'], 'requested investment quantity')
        if p['owner'] != option['owner']:
            raise ValueError('Investment request owner differs from option')
        if (option['id'] in blocks or max(option['known_year'], option['permit_known_year'],
                option['permit_effective_year']) > model.year):
            p['quantity'] = 0.
        stock = fsum(a['quantity'] for a in model.assets if a['kind'] == option['kind']
                     and a['component'] == option['component'] and a['state'] != 'retired')
        queue = fsum(q['quantity'] for q in model.projects if q['kind'] == option['kind']
                     and q['component'] == option['component'] and q['state'] == 'building')
        p['quantity'] = min(p['quantity'], model.installation_limit(option),
                            max(0., option['maximum_total_units'] - stock - queue))
    for group in model.config.get('investment_groups', []):
        selected = [p for p in result if options[p['option']].get('investment_group') == group['id']]
        total = fsum(p['quantity'] for p in selected)
        factor = min(1., min(model.group_limits(group)) / total) if total else 1.
        for p in selected:
            p['quantity'] *= factor
    for owner in sorted({p['owner'] for p in result}):
        selected = [p for p in result if p['owner'] == owner]
        cost = fsum(p['quantity'] * model.capex(options[p['option']]) for p in selected)
        factor = min(1., max(0., model.sectors[owner].cash) / cost) if cost else 1.
        for p in selected:
            p['quantity'] *= factor
    construction = fsum(p['quantity'] for p in result)
    connection = fsum(p['quantity'] * options[p['option']]['connection_per_unit'] for p in result)
    factor = min(1., policy['construction_units_limit'] / construction if construction else 1.,
                 policy['connection_limit'] / connection if connection else 1.)
    audit = []
    for p in result:
        feasible = p['quantity']
        p['quantity'] *= factor
        audit.append(dict(year=model.year, option=p['option'], allocation_rule='proportional_requests',
            original_request_units=original[p['option']], feasible_request_units=feasible,
            common_allocation_fraction=factor, allocated_request_units=p['quantity']))
    return result, audit
