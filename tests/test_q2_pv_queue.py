"""Latent initial states must respect vintage, commissioning and escrow."""
from copy import deepcopy
import contextlib
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import run_q2_historical_candidate as history
from build_q2_pv_queue_candidate import build, with_pv_queue


class PVQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, data = history.load_frozen(ROOT / 'workflow/q2_candidates/v9/manifest.json')
        cls.base = data['model']

    def test_zero_queue_preserves_entire_model(self):
        self.assertEqual(with_pv_queue(self.base, 0), self.base)

    def test_queue_reserves_cash_and_commissions_only_after_paid_year(self):
        original = deepcopy(self.base)
        model = with_pv_queue(self.base, 1)
        self.assertEqual(self.base, original)
        total = lambda m: sum(a['cash'] for a in m['agents']) + sum(m['other_accounts'].values())
        self.assertAlmostEqual(total(model), total(original), places=6)
        queue = model['initial_projects'][-1]
        self.assertEqual(queue['component'], 'solar_power')
        self.assertEqual(queue['quantity'], 8170)
        self.assertEqual(queue['cost'], 8170 * 2.878)
        self.assertEqual(queue['remaining_cost'], queue['cost'] / 2)
        model['end_year'] = 2015
        model['mechanisms']['investment'] = False
        result = history.EnergyModel(model).run()
        old = [r for r in result['assets'] if r['year'] == 2014 and r['component'] == 'solar_power']
        new = [r for r in result['assets'] if r['year'] == 2015 and r['component'] == 'solar_power']
        self.assertEqual(sum(r['quantity'] for r in old), 24860)
        self.assertEqual(sum(r['quantity'] for r in new), 24860 + 8170)
        project = next(p for p in result['projects'] if p['id'] == queue['id'] and p['year'] == 2015)
        self.assertEqual(project['remaining_cost'], 0)
        self.assertEqual(project['state'], 'operating')
        paid = [r for r in result['cash'] if r['reference'] == queue['id']]
        self.assertEqual(sum(r['amount'] for r in paid), queue['cost'] / 2)
        self.assertTrue(all(r['year'] == 2014 for r in paid))

    def test_invalid_or_duplicate_or_unfunded_latent_state_rejected(self):
        for value in (-1, .5, 3, True, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                with_pv_queue(self.base, value)
        with self.assertRaises(ValueError):
            with_pv_queue(with_pv_queue(self.base, 1), 1)
        poor = deepcopy(self.base)
        next(a for a in poor['agents'] if a['id'] == 'generation')['cash'] = 1
        with self.assertRaises(ValueError):
            with_pv_queue(poor, 1)

    def test_future_new_technology_cannot_become_opening_queue(self):
        changed = deepcopy(self.base)
        next(o for o in changed['investment_options'] if o['id'] == 'solar_build')['known_year'] = 2015
        with self.assertRaises(ValueError):
            with_pv_queue(changed, 1)

    def test_holdout_cannot_select_latent_queue_or_rates(self):
        data = build()
        # Keep all six structures/rules but use two endpoint pairs for a
        # quick information-boundary counterexample, not the scientific fit.
        for parameter in data['experiment']['parameters']:
            parameter['grid'] = parameter['grid'][::8]
        changed = deepcopy(data)
        for row in changed['observations']:
            if row['year'] >= 2022:
                row['value'] *= 1000
        with contextlib.redirect_stdout(io.StringIO()):
            before = history.train_candidates(data)
            after = history.train_candidates(changed)
        self.assertEqual(before, after)
        self.assertEqual(len(before), 72)
        self.assertTrue(all(r['status'] == 'valid' for r in before))


if __name__ == '__main__':
    unittest.main()
