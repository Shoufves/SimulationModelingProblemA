"""Observed initial queue is separate from assumed schedules and funding."""
import contextlib
import io
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_q2_queue_candidate as builder
import run_q2_historical_candidate as runner


class Q2NuclearQueueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.data = runner.load_frozen(ROOT / 'workflow/q2_candidates/v4/manifest.json')

    def test_queue_matches_original_and_excludes_operating_units(self):
        rows, _ = builder.queue_references()
        self.assertEqual(len(rows), 26)
        self.assertEqual(sum(float(r['capacity_MW']) for r in rows), 28450)
        self.assertFalse({'fuqing_1','yangjiang_1','fangjiashan_1'} & {r['id'] for r in rows})
        self.assertTrue(all(not r['online_year'] and not r['remaining_years'] and not r['remaining_cost'] for r in rows))

    def test_escrow_is_funded_not_created_and_matches_unpaid_schedule(self):
        models = self.data['structural_models']
        def cash(c): return sum(a['cash'] for a in c['agents']) + sum(c['other_accounts'].values())
        original = cash(models['empty_queue_control'])
        for name, c in models.items():
            self.assertAlmostEqual(cash(c), original, delta=1e-6)
            self.assertAlmostEqual(c['other_accounts']['escrow'], sum(p['remaining_cost'] for p in c['initial_projects']))
            runner.EnergyModel(c)  # Constructor independently validates schedules.
            for p in c['initial_projects']:
                self.assertLess(p['applied_year'], 2014)
                self.assertGreater(p['online_year'], 2014)
                self.assertEqual(p['applied_year'] + p['lead_years'], p['online_year'])

    def test_queue_commissions_without_new_investment_and_does_not_duplicate_stock(self):
        c = deepcopy(self.data['structural_models']['stage_schedule'])
        c['mechanisms']['investment'] = False; c['end_year'] = 2021
        result = runner.EnergyModel(c).run()
        def nuclear(y):
            return sum(a['quantity'] for a in result['assets'] if a['year'] == y and
                       a['component'] == 'nuclear_power' and a['state'] == 'operating')
        self.assertEqual(nuclear(2014), 20080)
        self.assertEqual(nuclear(2021), 20080 + 28450)
        self.assertTrue(all(abs(r['cash_residual']) < 1e-5 for r in result['annual']))
        self.assertAlmostEqual(result['annual'][-1]['accounts']['escrow'], 0., delta=1e-7)

    def test_common_delay_preserves_capacity_but_changes_timing(self):
        a = {p['id']:p for p in self.data['structural_models']['stage_schedule']['initial_projects']}
        b = {p['id']:p for p in self.data['structural_models']['stage_plus_two_years']['initial_projects']}
        self.assertEqual(set(a), set(b))
        for identity in a:
            self.assertEqual(a[identity]['quantity'], b[identity]['quantity'])
            self.assertEqual(a[identity]['online_year'] + 2, b[identity]['online_year'])

    def test_holdout_cannot_choose_queue_schedule(self):
        a = deepcopy(self.data)
        for p in a['experiment']['parameters']: p['grid'] = [p['grid'][0]]
        b = deepcopy(a)
        for r in b['observations']:
            if r['year'] >= 2022: r['value'] *= 1000
        with contextlib.redirect_stdout(io.StringIO()):
            left, right = runner.train_candidates(a), runner.train_candidates(b)
        self.assertEqual(left, right)
        self.assertEqual(len(left), 12)
        self.assertTrue(all(t['status'] == 'valid' for t in left))


if __name__ == '__main__': unittest.main()
