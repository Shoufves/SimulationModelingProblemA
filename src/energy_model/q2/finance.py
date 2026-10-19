"""Explicit project valuation at application time; not a financing market model.

Timing follows final / design 17.3: construction at offsets 0..L-1,
operating cash at L..L+H-1, expected terminal value at L+H. The current
annual engine reserves the full price in a non-remunerated escrow account.
Its liquidity opportunity cost is shown separately from resource spending.
"""
from math import fsum, isfinite


def finite(value, label, *, nonnegative=False):
    if type(value) not in (int,float) or not isfinite(value) or (nonnegative and value<0):
        raise ValueError('Invalid '+label)
    return float(value)


def validate_schedule(fractions, lead):
    if type(lead) is not int or lead<1 or not isinstance(fractions,list) or len(fractions)!=lead:
        raise ValueError('Construction fractions must cover each pre-commissioning year')
    for value in fractions:
        finite(value,'construction fraction',nonnegative=True)
    if abs(fsum(fractions)-1.)>1e-12:
        raise ValueError('Construction fractions must sum to one')


def validate_valuation(option):
    validate_schedule(option['construction_fractions'],option['lead_years'])
    life = finite(option['economic_life'],'economic life',nonnegative=True)
    if life<1 or not life.is_integer():
        raise ValueError('Economic life must be a positive whole number of annual cash flows')
    finite(option['discount_rate'],'discount rate',nonnegative=True)
    finite(option['expected_terminal_value_per_unit'],'expected terminal value')
    if option['funding_convention']!='fully_funded_nonremunerated_escrow':
        raise ValueError('Unsupported funding convention; cash engine uses fully funded escrow')


def project_value(option, capex, expected_operating_margin, *, operating_adjustments=None):
    """Flat cash-flow expectation from the agent's current updated margin only.

    Terminal value is an explicitly supplied expectation (may be a disposal
    liability); it is not automatically credited to cash or resource accounts.
    Optional dated adjustments contain only known, eligible contract cash flows,
    not unawarded capital grants or future realized prices. Expiring support is
    never capitalized over the full technical lifetime.
    """
    validate_valuation(option)
    capex = finite(capex,'capital cost',nonnegative=True)
    net_cash = finite(expected_operating_margin,'operating margin')-finite(
        option['fixed_om_per_unit'],'fixed O&M',nonnegative=True)
    lead, life = option['lead_years'], int(option['economic_life'])
    rate = option['discount_rate']
    discount = lambda offset: (1+rate)**(-offset)
    construction_pv = fsum(capex*f*discount(y) for y,f in enumerate(option['construction_fractions']))
    operation_factor = fsum(discount(y) for y in range(lead,lead+life))
    operating_pv = net_cash*operation_factor
    adjustment_pv = 0.
    if operating_adjustments is not None:
        if not isinstance(operating_adjustments,list) or len(operating_adjustments)!=life:
            raise ValueError('Operating adjustments must cover the valued operating life')
        adjustments=[finite(v,'known contract operating adjustment') for v in operating_adjustments]
        adjustment_pv=fsum(value*discount(lead+y) for y,value in enumerate(adjustments))
        operating_pv+=adjustment_pv
    terminal_pv = option['expected_terminal_value_per_unit']*discount(lead+life)
    resource_timing_npv = operating_pv+terminal_pv-construction_pv
    # Unspent escrow remains the owner's asset but earns no return. Adding this
    # opportunity cost makes private NPV equal to full funding at t=0; it is
    # neither an actual transfer nor an additional national resource expense.
    lock_cost = capex-construction_pv
    investment_npv = resource_timing_npv-lock_cost
    result = {'construction_present_value':construction_pv,'operating_present_value':operating_pv,
              'terminal_present_value':terminal_pv,'project_npv_before_funding_lock':resource_timing_npv,
              'funding_lock_opportunity_cost':lock_cost,'investment_npv':investment_npv,
              'expected_annual_operating_cash':net_cash,'first_operating_offset':lead,
              'last_operating_offset':lead+life-1,'terminal_value_offset':lead+life,
              'funding_convention':option['funding_convention'],
              'expectation_rule':'constant_current_updated_margin; no future realized cashflows',
              'construction_fractions':list(option['construction_fractions'])}
    if operating_adjustments is not None:
        result.pop('expected_annual_operating_cash')
        result.update(expected_contract_cash_by_operating_year=adjustments,
                      expected_base_annual_operating_cash=net_cash,
                      expected_operating_cash_by_operating_year=[net_cash+v for v in adjustments],
                      known_contract_present_value=adjustment_pv,
                      expectation_rule='constant_current_updated_base_margin plus dated eligible contract; no future realized cashflows')
    if not all(isfinite(v) for v in result.values() if type(v) in (int,float)):
        raise ValueError('Nonfinite project valuation')
    return result
