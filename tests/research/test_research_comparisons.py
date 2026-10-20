"""Adversarial comparison examples; no simulation-derived approval labels."""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from summarize_n2_research import compare
from verify_n2_research import dominates


def record(name,heat,cost=100.,carbon=100.):
    return dict(name=name,summary=dict(retention_mw_year=20.,discounted_resource_cost_cny=cost,
        cumulative_positive_co2_t=carbon,forecast_solves=1,final_initial_coal_mw=0.),
        services=[dict(year=2030,services={'electricity':dict(fraction=.5),'heat':dict(fraction=heat)})])


class ComparisonTests(unittest.TestCase):
    def test_maximum_hides_another_service_regression(self):
        a,b=record('a',.10,90),record('b',.05)
        self.assertAlmostEqual(compare(a,b)['maximum_service_fraction_regret'],.05)
        self.assertFalse(dominates(a,b))

    def test_cost_emissions_tradeoff_is_not_dominance(self):
        self.assertFalse(dominates(record('a',.05,90,101),record('b',.05)))
        self.assertTrue(dominates(record('a',.05,90,100),record('b',.05)))
        self.assertFalse(dominates(record('a',.05),record('b',.05)))

    def test_missing_service_cannot_improve_comparison(self):
        a,b=record('a',.05),record('b',.05)
        del a['services'][0]['services']['heat']
        with self.assertRaises(ValueError):compare(a,b)


if __name__=='__main__':unittest.main()
