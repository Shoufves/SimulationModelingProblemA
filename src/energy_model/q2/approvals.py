"""Year-local replay of documented administrative non-issuance outcomes.

These events condition historical government decisions. They do not revoke
existing projects, forecast later decisions, or date the publication of evidence.
"""


def validate_approval_blocks(config):
    events = config.get('approval_blocks', [])
    if not isinstance(events, list):
        raise ValueError('Approval blocks must be an explicit list')
    options = {o['id'] for o in config['investment_options']}
    ids, keys = set(), set()
    for e in events:
        if (not isinstance(e.get('id'), str) or not e['id'] or e['id'] in ids or
                type(e.get('year')) is not int or e.get('option') not in options or
                e.get('basis') != 'realized_administrative_outcome' or
                not isinstance(e.get('evidence'), str) or not e['evidence']):
            raise ValueError('Invalid or untraceable approval block')
        key = (e['year'], e['option'])
        if key in keys:
            raise ValueError('Duplicate approval outcome for year/option')
        ids.add(e['id']); keys.add(key)


def current_approval_blocks(config, year):
    # Later outcomes never enter current option valuation or government action.
    return {e['option']:e for e in config.get('approval_blocks', []) if e['year'] == year}
