"""mmj cost/review counterexamples adapted to lb's single Q1 pipeline."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'scripts'))
from energy_model.q1 import screening_lcoe, COST_ASSUMPTIONS
import build_q1 as q1
from scan_google_keys import scan_workspace


class CommonWindCostTests(unittest.TestCase):
    # mmj's non-reading scanner counterexample, using lb's temporary-fixture style.
    def test_scanner_never_opens_restricted_or_virtual_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ('data/restricted/private.txt', '.venv/secret.txt', 'public.txt'):
                path = root/name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'ordinary')
            original = Path.read_bytes
            def guarded(path):
                if 'restricted' in path.parts or '.venv' in path.parts:
                    raise AssertionError('Restricted content was opened')
                return original(path)
            with patch.object(Path, 'read_bytes', guarded):
                result = scan_workspace(root)
            self.assertTrue(result['passed'])
            self.assertEqual(result['files_scanned'], 1)
            self.assertIn('data/restricted', result['excluded_directories'])

    # These three numerical tests are ported from mmj baf1975 test_q1.py.
    def test_common_cost_zero_discount_and_monotonic_sensitivity(self):
        self.assertAlmostEqual(screening_lcoe(1000, 20, .5, 25, 0), (1000/25+20)/(8760*.5))
        self.assertLess(screening_lcoe(1000, 20, .5, 25, .03), screening_lcoe(1000, 20, .5, 25, .07))
        self.assertAlmostEqual(screening_lcoe(1000, 20, .5, 25, .05),
                               2*screening_lcoe(1000, 20, 1, 25, .05))

    def test_cost_nonphysical_parameters_fail(self):
        for cf in (0, -.1, 1.1, float('nan')):
            with self.assertRaises(ValueError):
                screening_lcoe(1000, 20, cf, 25, .05)

    def test_cost_near_zero_agrees_with_discounted_cash_flow(self):
        for rate in (0, 1e-20, 1e-12, .03, .05, .07):
            annuity = sum((1+rate)**(-year) for year in range(1, 26))
            discounted = (1000+20*annuity)/(8760*.5*annuity)
            with self.subTest(rate=rate):
                self.assertAlmostEqual(screening_lcoe(1000, 20, .5, 25, rate), discounted, places=13)


class SupplementIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT/'workflow/q1_inputs.json').read_text(encoding='utf-8'))
        q1.preflight(cls.config)
        cls.data, cls.history = q1.load_history(cls.config)

    def test_six_cost_results_match_independent_cash_flows(self):
        inds, *_ = q1.calculate(self.data)
        costs = {r['indicator_id']: r for r in inds if r['indicator_id'].startswith('screening_')}
        self.assertEqual(len(costs), 6)
        for tech, cap, om, cf in [('onshore_wind', 856, 29, .33), ('offshore_wind', 1520, 59, .37)]:
            for rate in (.03, .05, .07):
                annuity = sum((1+rate)**(-year) for year in range(1, 26))
                expected = (cap+om*annuity)/(8760*cf*annuity)
                row = costs[f'screening_{tech}_wacc_{rate}']
                self.assertTrue(math.isclose(expected, row['value'], rel_tol=1e-12))
                self.assertEqual(row['status'], 'conditional_common_financing_sensitivity')
                self.assertEqual(len(row['input_refs'].split(';')), 4)

    def test_invalid_sensitivity_and_unsupported_service_rejected(self):
        for rates in ([], [.03, .03], [-.01], [float('nan')], [float('inf')], ['.05'], [True]):
            assumptions = dict(COST_ASSUMPTIONS, real_wacc=rates)
            with self.subTest(rates=rates), self.assertRaisesRegex(ValueError, 'WACC'):
                q1.calculate(self.data, assumptions)
        with self.assertRaisesRegex(ValueError, 'unfirmed'):
            q1.calculate(self.data, dict(COST_ASSUMPTIONS, cost_service='firmed electricity'))

    def test_cost_unit_and_lifetime_mismatch_rejected(self):
        data = copy.deepcopy(self.data)
        data['cost_method'][0]['unit'] = '2018 USD/kW/year'
        with self.assertRaisesRegex(ValueError, 'Unit mismatch'):
            q1.calculate(data)
        with self.assertRaisesRegex(ValueError, 'lifetime'):
            q1.calculate(self.data, dict(COST_ASSUMPTIONS, common_life_years=30))

    def test_review_binding_rejects_changed_use_without_changed_bytes(self):
        for field in ('allowed_use', 'blocked_use', 'review'):
            config = copy.deepcopy(self.config)
            config['inputs'][0][field] = 'unreviewed national initialization'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'permitted uses'):
                q1.preflight(config)

    def test_review_cannot_be_omitted_or_replaced_by_unbound_receipt(self):
        config = copy.deepcopy(self.config)
        del config['evidence_review']
        with self.assertRaisesRegex(ValueError, 'Missing Q1 evidence'):
            q1.preflight(config)
        config = copy.deepcopy(self.config)
        config['evidence_review']['sha256'] = '0'*64
        with self.assertRaisesRegex(ValueError, 'Evidence review hash'):
            q1.preflight(config)

    def test_gdp_is_driver_and_other_targets_keep_their_roles(self):
        inds, *_ = q1.calculate(self.data)
        _, hands = q1.handoff(self.history, inds)
        gdp = [r for r in hands if r.get('variable') == 'real_gdp_growth_pct']
        self.assertEqual(len(gdp), 10)
        self.assertTrue(all(r['record_kind'] == 'exogenous_driver_candidate' for r in gdp))
        self.assertTrue(all(r['model_location'] == 'historical_activity_driver_not_fitting_target' for r in gdp))
        self.assertTrue(any(r.get('variable') == 'consumption_10ktce' and
                            r['record_kind'] == 'numeric_observation_candidate' for r in hands))

    def test_cost_parameters_are_not_duplicated_as_initial_state(self):
        inds, *_ = q1.calculate(self.data)
        _, hands = q1.handoff(self.history, inds)
        self.assertEqual(len(self.data['cost_method']), 6)
        costs = [r for r in hands if r.get('variable', '').startswith('screening_')]
        self.assertEqual(len(costs), 6)
        self.assertTrue(all(r['record_kind'] == 'derived_diagnostic' for r in costs))
        self.assertFalse(any(r['record_kind'] == 'numeric_observation_candidate' and
                             'cost_method:' in r['candidate_refs'] for r in hands))


if __name__ == '__main__':
    unittest.main()
