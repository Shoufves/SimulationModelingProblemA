"""Research-only roundoff allowance for one accumulated currency statistic.

The pinned PR14 comparator, scientific thresholds and cash residual limits are
unchanged. At ~1.8e14 CNY a binary64 ULP is 0.03125 CNY, so its 0.02 CNY cap
cannot accept even adjacent representable totals. Permit at most four ULPs for
this single cumulative field, retaining the original comparison everywhere else.
"""
import math

TOTAL_PATH = '/summary/discounted_resource_cost_cny'


def cumulative_cost_tolerance(actual, expected):
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in (actual, expected)):
        raise ValueError('Cumulative costs must be finite numbers')
    return max(0.02, 4 * max(math.ulp(actual), math.ulp(expected)))


def compare_reproduction(actual, expected):
    from run_q2_portable import compare_reference
    report = compare_reference(actual, expected)
    report['upstream_passed'] = report['passed']
    report['tolerances']['research_cumulative_cost'] = dict(
        path=TOTAL_PATH, absolute_floor_cny=0.02, maximum_ulps=4,
        rationale='Bounded binary64 roundoff of the discounted cumulative total only')
    accepted = False
    for difference in report['differences']:
        if difference['path'] == TOTAL_PATH:
            tolerance = cumulative_cost_tolerance(difference['actual'], difference['expected'])
            difference['upstream_tolerance'] = difference['tolerance']
            difference['tolerance'] = tolerance
            difference['difference_in_ulps'] = difference['absolute_difference'] / max(
                math.ulp(difference['actual']), math.ulp(difference['expected']))
            accepted = difference['absolute_difference'] <= tolerance
    if accepted:
        report['failures'] = [item for item in report['failures']
                              if not (item['path'] == TOTAL_PATH and item['reason'] == 'numeric tolerance exceeded')]
    report['passed'] = not report['failures']
    report['exact_match'] = report['passed'] and not report['differences']
    return report
