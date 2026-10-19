"""Dated generation revenue contracts; no default tariff or policy eligibility.

An offer is not an awarded contract. Eligibility is fixed at application using
only published terms and the declared commissioning date. Pooled, physically
identical cohorts share dispatch pro rata by operating capacity. Different
physical technologies must use different process components.

Legacy quotes are in model currency. An explicit nominal_currency quote instead
requires an annual conversion in the visible policy snapshot. Future realized
conversion paths are never read by this module or by project valuation.
"""
from copy import deepcopy

from .operations import number


COMMON=('id','known_year','output_carrier','price_mode','price_per_mwh','payer','source_or_assumption')


def validate_contract(contract, *, offer=False):
    if not isinstance(contract,dict) or any(k not in contract for k in COMMON):
        raise ValueError('Incomplete generation revenue contract')
    for key in ('id','output_carrier','payer','source_or_assumption'):
        if not isinstance(contract[key],str) or not contract[key].strip():
            raise ValueError('Contract identity, carrier, payer and evidence required')
    if type(contract['known_year']) is not int:
        raise ValueError('Contract information year required')
    if contract['price_mode'] not in {'premium','fixed_total_price'}:
        raise ValueError('Contract must distinguish premium and total sale price')
    number(contract['price_per_mwh'],'contract price')
    if 'nominal_currency' in contract and (not isinstance(contract['nominal_currency'],str) or
                                          not contract['nominal_currency'].strip()):
        raise ValueError('Explicit nominal quote currency required')
    keys=('application_from_year','application_through_year','commission_by_year','support_years') if offer else ('start_year','end_year')
    if any(type(contract.get(k)) is not int for k in keys):
        raise ValueError('Integer contract eligibility and operating dates required')
    if offer:
        if contract['application_from_year']>contract['application_through_year'] or contract['support_years']<1:
            raise ValueError('Invalid contract application window or support duration')
        if contract['commission_by_year']<contract['application_from_year']:
            raise ValueError('Contract commissioning deadline precedes application window')
    elif contract['start_year']>contract['end_year']:
        raise ValueError('Contract expires before operation starts')
    if not offer and 'commission_by_year' in contract:
        if type(contract['commission_by_year']) is not int or contract['commission_by_year']<contract['start_year']:
            raise ValueError('Awarded contract commissioning deadline is invalid')


def award_contract(offer, application_year, commissioning_year):
    validate_contract(offer,offer=True)
    if (offer['known_year']>application_year or
            not offer['application_from_year']<=application_year<=offer['application_through_year'] or
            commissioning_year>offer['commission_by_year']):
        return None
    if commissioning_year<=application_year:
        raise ValueError('Contract award cannot remove construction lead time')
    result={k:deepcopy(offer[k]) for k in COMMON}
    if 'nominal_currency' in offer:
        result['nominal_currency']=offer['nominal_currency']
    result.update(start_year=commissioning_year,end_year=commissioning_year+offer['support_years']-1,
                  application_year=application_year,commission_by_year=offer['commission_by_year'])
    return result


def validate_currency_conversions(config):
    """Validate declared units and dates; missing active-year values fail at use."""
    indexed=any('nominal_currency' in r.get('revenue_contract',{})
                for group in ('assets','initial_projects','investment_options') for r in config[group])
    snapshots=any('currency_conversions' in policy for policy in config['policies'])
    if not indexed and not snapshots:
        return
    model_currency=config.get('model_currency')
    if not isinstance(model_currency,str) or not model_currency.strip():
        raise ValueError('Nominal contracts require explicit model_currency')
    for policy in config['policies']:
        conversions=policy.get('currency_conversions',{})
        if not isinstance(conversions,dict):
            raise ValueError('Currency conversions must be keyed by nominal currency')
        for currency, item in conversions.items():
            if not isinstance(currency,str) or not currency.strip() or not isinstance(item,dict):
                raise ValueError('Invalid currency conversion identity')
            if item.get('model_currency')!=model_currency:
                raise ValueError('Currency conversion target differs from model currency')
            number(item.get('factor'),'nominal-to-model currency factor',positive=True)
            if (type(item.get('conversion_year')) is not int or type(item.get('known_year')) is not int or
                    item['conversion_year']!=policy['effective_year'] or item['known_year']>policy['known_year']):
                raise ValueError('Currency conversion date is inconsistent with visible policy')
            if not isinstance(item.get('source_or_assumption'),str) or not item['source_or_assumption'].strip():
                raise ValueError('Currency conversion needs a source or explicit assumption')


def settlement_price(contract, policy, year=None):
    """Convert only the requested current snapshot, never extend an old factor."""
    quote=number(contract['price_per_mwh'],'contract price')
    currency=contract.get('nominal_currency')
    if currency is None:
        return quote
    if type(year) is not int:
        raise ValueError('Nominal price conversion requires explicit current year')
    conversion=policy.get('currency_conversions',{}).get(currency)
    if (conversion is None or conversion['conversion_year']!=year or conversion['known_year']>year):
        raise ValueError('Missing visible current-year currency conversion: '+currency)
    return number(quote*number(conversion['factor'],'nominal-to-model currency factor',positive=True),
                  'converted contract price')


def price_adjustment(contract, policy, year=None):
    """Increment above common carrier revenue; a fixed total price may claw back."""
    price=number(policy['node_prices'][contract['output_carrier']],'common carrier price')
    return settlement_price(contract,policy,year)-(price if contract['price_mode']=='fixed_total_price' else 0.)


def active(contract, year):
    return contract['known_year']<=year and contract['start_year']<=year<=contract['end_year']
