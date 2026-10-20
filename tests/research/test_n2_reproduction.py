"""Reject real/structural changes while accepting bounded cumulative roundoff."""
from copy import deepcopy
import math
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT/'tmp/n2/pr14/scripts'),str(ROOT/'tmp/n2/pr14/src'),str(ROOT/'scripts')]
from compare_n2_reproduction import compare_reproduction,cumulative_cost_tolerance


def sample():
    return dict(summary=dict(discounted_resource_cost_cny=183094555717863.20),
                decisions=[dict(year=2030,retained=['coal_1'],fee_cny=20.)],
                paths=[dict(year=2030,resource_cost_cny=100.,max_residual=0.,cash_balance_residual_cny=0.)],
                services=[dict(year=2030,services={'nonenergy_feedstock/gas':dict(fraction=0.)})])


class ReproductionTests(unittest.TestCase):
    def test_one_ulp_cumulative_difference_passes_without_claiming_exact_match(self):
        expected=sample();actual=deepcopy(expected)
        v=expected['summary']['discounted_resource_cost_cny']
        actual['summary']['discounted_resource_cost_cny']=math.nextafter(v,math.inf)
        report=compare_reproduction(actual,expected)
        self.assertFalse(report['upstream_passed'])
        self.assertTrue(report['passed'],report)
        self.assertFalse(report['exact_match'])
        self.assertEqual(report['differences'][0]['difference_in_ulps'],1)

    def test_four_ulp_bound_and_real_difference(self):
        expected=sample();v=expected['summary']['discounted_resource_cost_cny']
        self.assertEqual(cumulative_cost_tolerance(v,v),.125)
        for ulps,passed in ((4,True),(5,False),(32,False)):
            actual=deepcopy(expected);actual['summary']['discounted_resource_cost_cny']=v+ulps*math.ulp(v)
            self.assertEqual(compare_reproduction(actual,expected)['passed'],passed)

    def test_decisions_services_cash_and_other_currency_stay_strict(self):
        expected=sample()
        for mutation in (
            lambda a:a['decisions'][0].update(retained=[]),
            lambda a:a['decisions'][0].update(year=2031),
            lambda a:a['paths'][0].update(resource_cost_cny=100.03125),
            lambda a:a['paths'][0].update(cash_balance_residual_cny=.011),
            lambda a:a['services'][0]['services']['nonenergy_feedstock/gas'].update(fraction=.1),
            lambda a:a['services'][0]['services'].pop('nonenergy_feedstock/gas')):
            actual=deepcopy(expected);mutation(actual)
            self.assertFalse(compare_reproduction(actual,expected)['passed'])

    def test_nonfinite_and_small_scale_totals_do_not_gain_unbounded_tolerance(self):
        expected=sample()
        for value in (float('nan'),float('inf')):
            actual=deepcopy(expected);actual['summary']['discounted_resource_cost_cny']=value
            self.assertFalse(compare_reproduction(actual,expected)['passed'])
        self.assertEqual(cumulative_cost_tolerance(10.,10.),.02)
        expected['summary']['discounted_resource_cost_cny']=10.
        actual=deepcopy(expected);actual['summary']['discounted_resource_cost_cny']=10.03
        self.assertFalse(compare_reproduction(actual,expected)['passed'])


if __name__=='__main__':unittest.main()
