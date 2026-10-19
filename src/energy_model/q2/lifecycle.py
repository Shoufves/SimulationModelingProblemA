"""Explicit asset lifetimes and loss-driven exits; no default national ages.

Technical end and permit expiry suspend operation pending review. Neither is an
observed retirement. Endogenous exits use only settled margins, take effect next
year, and require separately declared permission for irreversible retirement.
"""
from math import isclose

from .operations import number


def validate_lifecycle(record, *, required=False, option=False):
    life = record.get('lifecycle')
    if life is None:
        if required:
            raise ValueError('National asset/option requires explicit lifecycle')
        return
    years = life['technical_life_years']
    if type(years) is not int or years < 1:
        raise ValueError('Technical lifetime must be a positive integer')
    permit = life['permit_valid_through']
    if permit is not None and type(permit) is not int:
        raise ValueError('Permit year must be explicit integer or declared non-applicable null')
    factors = life['maintenance_factors']
    if set(factors) != {'operating', 'standby', 'mothballed', 'retired'}:
        raise ValueError('State-specific maintenance factors required')
    for value in factors.values():
        number(value, 'maintenance factor')
    if factors['retired'] != 0:
        raise ValueError('Retired assets need separate decommissioning obligations')
    rule = life['exit_rule']
    if rule is not None:
        for key in ('mothball_after_loss_years', 'retire_after_loss_years'):
            if type(rule[key]) is not int or rule[key] < 1:
                raise ValueError('Loss persistence must be positive integer years')
        if rule['retire_after_loss_years'] <= rule['mothball_after_loss_years']:
            raise ValueError('Retirement must follow a distinct mothball period')
        if type(rule['retirement_permitted']) is not bool or type(rule['known_year']) is not int:
            raise ValueError('Exit permission and information date required')
        if type(rule['permit_effective_year']) is not int:
            raise ValueError('Retirement permit date required')
        number(rule['retirement_cost_per_unit'], 'retirement cost')
    if not option:
        count = life['initial_loss_years']
        if type(count) is not int or count < 0:
            raise ValueError('Opening loss history must be declared')


def fixed_maintenance(asset):
    if asset['state'] == 'retired':
        return 0.
    factors = asset.get('lifecycle', {}).get('maintenance_factors')
    factor = factors[asset['state']] if factors is not None else 1.
    return asset['quantity'] * asset['fixed_om_per_unit'] * factor


def validate_replacement(model, option):
    if option['replaces'] is None:
        return
    old = next(a for a in model.assets if a['id'] == option['replaces'])
    if old['owner'] != option['owner'] or old['kind'] != 'device' or option['kind'] != 'device':
        raise ValueError('Replacement must reference same-owner service equipment')
    before = model.component('device', old['component'])
    after = model.component('device', option['component'])
    if before['service'] != after['service']:
        raise ValueError('Equipment replacement must deliver the same service')
    removed = before['input_capacity_mw'] * before['service_per_mwh'] * option['replacement_ratio']
    added = after['input_capacity_mw'] * after['service_per_mwh']
    if not isclose(removed, added, rel_tol=1e-9, abs_tol=1e-9):
        raise ValueError('Replacement ratio must conserve rated service capacity')


def apply_event(model, event):
    asset = next(a for a in model.assets if a['id'] == event['asset'])
    if asset['state'] == 'retired':
        raise ValueError('Permanent retirement cannot be reversed')
    if event['permit_granted'] is not True:
        raise ValueError('Asset transition needs explicit legal permission')
    target = event['new_state']
    if target not in {'operating', 'standby', 'mothballed', 'retired'}:
        raise ValueError('Unknown lifecycle state')
    life = asset.get('lifecycle')
    renewal = 'technical_end_year' in event or 'permit_valid_through' in event
    if renewal:
        if life is None or 'cost' not in event:
            raise ValueError('Extension requires declared lifecycle and explicit cost')
        if 'technical_end_year' in event:
            end = event['technical_end_year']
            prior = asset.get('technical_end_year', asset['online_year'] + life['technical_life_years'])
            if type(end) is not int or end <= max(prior, model.year):
                raise ValueError('Extension must increase technical end date')
        if 'permit_valid_through' in event:
            end = event['permit_valid_through']
            prior = life['permit_valid_through']
            if type(end) is not int or end < model.year or (prior is not None and end <= prior):
                raise ValueError('Renewal must increase permit validity')
    cost = number(event.get('cost', 0.), 'lifecycle action cost')
    owner = model.sectors[asset['owner']]
    if cost > max(0., owner.cash):
        model.actions.append({'year': model.year, 'asset': asset['id'], 'event': event['id'],
                              'reason': 'lifecycle_action_unfunded', 'approved': False})
        return
    model.transfer(asset['owner'], 'external_economy', cost, 'lifecycle_resource', event['id'])
    if 'technical_end_year' in event:
        asset['technical_end_year'] = event['technical_end_year']
    if 'permit_valid_through' in event:
        life['permit_valid_through'] = event['permit_valid_through']
    asset['state'] = target
    asset.pop('review_required', None)
    model.actions.append({'year': model.year, 'asset': asset['id'], 'event': event['id'],
                          'new_state': target, 'approved': True, 'cost': cost})


def restrict_expired_assets(model):
    for asset in model.assets:
        life = asset.get('lifecycle')
        if life is None or asset['state'] == 'retired' or asset['quantity'] == 0:
            continue
        reasons = []
        end = asset.get('technical_end_year', asset['online_year'] + life['technical_life_years'])
        if model.year >= end:
            reasons.append('technical_life_review')
        if life['permit_valid_through'] is not None and model.year > life['permit_valid_through']:
            reasons.append('permit_expired')
        if reasons:
            if asset.get('review_required') != reasons or asset['state'] != 'mothballed':
                model.actions.append({'year': model.year, 'asset': asset['id'],
                                      'new_state': 'mothballed', 'reason': reasons})
            asset['state'] = 'mothballed'
            asset['review_required'] = reasons


def propose_exits(model):
    """Attribute component cash margin by active quantity, then update loss runs."""
    ledger = [r for r in model.cash_ledger if r['year'] == model.year]
    for asset in sorted(model.assets, key=lambda a: a['id']):
        life = asset.get('lifecycle')
        if life is None or life['exit_rule'] is None or asset['state'] == 'retired' or asset['quantity'] == 0:
            continue
        rule = life['exit_rule']
        if rule['known_year'] > model.year:
            continue
        ref = asset['kind'] + ':' + asset['component']
        total = sum(a['quantity'] for a in model.assets if a['kind'] == asset['kind'] and
                    a['component'] == asset['component'] and a['state'] == 'operating')
        margin = 0.
        if asset['state'] == 'operating' and total:
            margin = sum(r['amount'] * (int(r['payee'] == asset['owner']) - int(r['payer'] == asset['owner']))
                         for r in ledger if r['reference'] == ref) * asset['quantity'] / total
            # Contract payments are already assigned to the entitled cohort;
            # applying the capacity share again would dilute its actual margin.
            margin += sum(r['amount'] * (int(r['payee'] == asset['owner']) - int(r['payer'] == asset['owner']))
                          for r in ledger if r.get('asset')==asset['id'] and r['reason'] in
                          {'operating_contract_support','operating_contract_clawback'})
        margin -= fixed_maintenance(asset)
        previous = asset.get('consecutive_loss_years', life['initial_loss_years'])
        asset['consecutive_loss_years'] = previous + 1 if margin < -1e-9 else 0
        count = asset['consecutive_loss_years']
        target = None
        if (count >= rule['retire_after_loss_years'] and rule['retirement_permitted'] and
                rule['permit_effective_year'] <= model.year):
            target = 'retired'
        elif count >= rule['mothball_after_loss_years'] and asset['state'] != 'mothballed':
            target = 'mothballed'
        model.actions.append({'year': model.year, 'asset': asset['id'], 'settled_asset_margin': margin,
                              'consecutive_loss_years': count, 'exit_proposal': target,
                              'information_cutoff': model.year})
        if target is not None:
            model.pending_asset_events.append({
                'id': f"exit:{asset['id']}@{model.year}", 'asset': asset['id'],
                'known_year': model.year, 'effective_year': model.year + 1,
                'permit_granted': True, 'new_state': target,
                'cost': asset['quantity'] * rule['retirement_cost_per_unit'] if target == 'retired' else 0.})
