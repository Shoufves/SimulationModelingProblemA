"""Information time, cohort separation, rebasing and selection regressions."""
import contextlib
import io
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_q2_historical_candidate as base
import build_q2_mapping_candidate as builder
import run_q2_historical_candidate as runner


class Q2MappingCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.data = runner.load_frozen(ROOT / 'workflow/q2_candidates/v2r1/manifest.json')

    def test_new_cohort_not_in_opening_stock_or_before_publication(self):
        model = deepcopy(self.data['structural_models']['new_project_cohort'])
        self.assertFalse(any(a['component'] == 'solar_new_power' for a in model['assets']))
        model['end_year'] = 2015
        result = runner.EnergyModel(model).run()
        self.assertFalse(any(a.get('option') == 'solar_new_build' for a in result['actions']))
        self.assertTrue(all(r['value'] == 0 for o in result['operations']
                            for r in o['result']['flows'] if r['id'] == 'solar_new_power'))

    def test_shared_accounting_terms_count_each_cohort_once(self):
        # Rebuild exercises Python aliases before JSON serialization, the source
        # of the failed initial v2. National primary-total terms are shared.
        data = builder.build()
        for d in data['definitions']:
            for term in d['numerator'] + (d['denominator'] or []):
                ids = term.get('ids', [])
                self.assertEqual(len(ids), len(set(ids)))
                if 'solar_power' in ids:
                    self.assertEqual(ids.count('solar_new_power'), 1)
        model = deepcopy(data['model']); model['end_year'] = 2014
        metrics = runner.metric_rows(runner.EnergyModel(model).run(), data['definitions'])
        observed_capacity = next(r['value'] for r in metrics if r['indicator'] == 'solar_10kW')
        self.assertAlmostEqual(observed_capacity, 2486.)

    def test_price_rebasing_has_correct_direction_and_units(self):
        ref, _ = builder.references()
        d = ref['deflator']['values']
        grid = self.data['experiment']['parameters'][-1]['grid']
        for actual, original in zip(grid, [1320., 2205., 3090.]):
            self.assertAlmostEqual(actual * 1000 * d['2014'] / d['2008'], original)
            self.assertLess(actual, original / 1000)

    def test_future_targets_do_not_change_mapping_models_or_search(self):
        original = base.rows
        def rows(name):
            records = original(name)
            if name == 'history_observations.csv':
                for r in records:
                    if int(r['year']) > 2014 and r['indicator'] != 'real_gdp_growth_pct':
                        r['value'] = str(float(r['value']) * 3)
            return records
        with patch.object(base, 'rows', rows):
            changed = builder.build()
        for name in ('structural_models', 'model', 'experiment', 'initialization'):
            self.assertEqual(changed[name], self.data[name])
        self.assertNotEqual(changed['observations'], self.data['observations'])

    def test_holdout_does_not_choose_mapping_rule_or_parameters(self):
        a = deepcopy(self.data)
        for p in a['experiment']['parameters']:
            p['grid'] = [p['grid'][0]]
        b = deepcopy(a)
        for r in b['observations']:
            if r['year'] >= 2022:
                r['value'] *= 100
        with contextlib.redirect_stdout(io.StringIO()):
            left, right = runner.train_candidates(a), runner.train_candidates(b)
        self.assertEqual(left, right)
        self.assertEqual(len(left), 6)
        self.assertTrue(all(t['status'] == 'valid' for t in left))


if __name__ == '__main__':
    unittest.main()
