"""Real-data diagnostic isolation and the large weighted-deficit regression."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
import build_q2_historical_candidate as builder
import run_q2_historical_candidate as runner
from energy_model.q2.annual import EnergyModel
from energy_model.q2.experiments import parameterize
from energy_model.q2.io import AdmissionError, dump, load_bundle, sha
from energy_model.q2.operations import solve_operation


class Q2HistoricalCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.data = runner.load_frozen(ROOT / 'workflow/q2_candidates/v1/manifest.json')

    def test_future_observed_targets_do_not_enter_state_or_parameter_bounds(self):
        original = builder.rows
        def changed_rows(name):
            records = original(name)
            if name == 'history_observations.csv':
                for row in records:
                    if int(row['year']) >= 2015 and row['indicator'] != 'real_gdp_growth_pct':
                        row['value'] = str(float(row['value']) * 7)
            return records
        with patch.object(builder, 'rows', changed_rows):
            altered = builder.build()
        for key in ('model', 'experiment', 'initialization'):
            self.assertEqual(altered[key], self.data[key])
        self.assertNotEqual(altered['observations'], self.data['observations'])

    def test_missing_initial_observation_is_not_imputed_zero(self):
        original = builder.rows
        def changed_rows(name):
            records = original(name)
            if name == 'history_observations.csv':
                next(r for r in records if r['year'] == '2014' and r['indicator'] == 'consumption_10ktce')['value'] = ''
            return records
        with patch.object(builder, 'rows', changed_rows):
            with self.assertRaises(ValueError): builder.build()

    def test_holdout_targets_cannot_select_training_rule_or_parameters(self):
        data = deepcopy(self.data)
        # A small test search tests separation; production retains the frozen81.
        for p in data['experiment']['parameters']: p['grid'] = [p['grid'][1]]
        changed = deepcopy(data)
        for row in changed['observations']:
            if row['year'] >= 2022: row['value'] *= 1000
        with contextlib.redirect_stdout(io.StringIO()):
            a, b = runner.train_candidates(data), runner.train_candidates(changed)
        self.assertEqual(a, b)
        self.assertTrue(all(t['status'] == 'valid' for t in a))

    def test_national_entry_rejects_diagnostic_scope(self):
        with self.assertRaisesRegex(AdmissionError, 'scientific scope'):
            load_bundle(ROOT, self.manifest)

    def test_original_and_config_tampering_are_both_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'original.txt'; source.write_text('original', encoding='utf-8')
            model = root / 'model.json'; dump(model, {'scope': self.manifest['scope']})
            manifest = root / 'manifest.json'
            dump(manifest, {'scope': self.manifest['scope'], 'national_admission': False,
                            'source_artifacts': {'original.txt': sha(source)},
                            'inputs': {'model': {'path': 'model.json', 'sha256': sha(model)}}})
            with patch.object(runner, 'ROOT', root):
                runner.load_frozen(manifest)
                source.write_text('changed', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, 'reference changed'): runner.load_frozen(manifest)
                source.write_text('original', encoding='utf-8')
                dump(model, {'scope': 'national_q2'})
                with self.assertRaisesRegex(ValueError, 'candidate input changed'): runner.load_frozen(manifest)

    def test_large_weighted_service_optimum_remains_feasible_in_cost_stage(self):
        # This frozen real-data training case used to fail in2020 ONLY after a
        # successful minimum-deficit LP. Annual365 weighting magnified roundoff.
        config = parameterize(self.data['model'], self.data['experiment']['parameters'],
                              {'residual_elasticity': .2, 'electricity_elasticity': 1.,
                               'investment_adjustment': .25})
        config['end_year'] = 2020
        result = EnergyModel(config).run()
        operation = result['operations'][-1]
        solved = operation['result']
        deficit = sum(solved['service_shortfalls'].values())
        self.assertGreater(deficit, 1e6)
        self.assertAlmostEqual(deficit, solved['stages'][0]['objective'], delta=1.)
        # Multiplying all annual objective/financial coefficients by the same
        # positive scalar must preserve the physical optimum, including deficit.
        unit_weight = deepcopy(operation['input']); unit_weight['annual_weights'] = [1.] * 4
        for limit in unit_weight['financial_limits']: limit['available_cash'] /= 365
        unit = solve_operation(unit_weight)
        self.assertAlmostEqual(sum(unit['service_shortfalls'].values()) * 365, deficit, delta=1.)
        self.assertAlmostEqual(unit['totals']['resource_cost'] * 365, solved['totals']['resource_cost'], delta=.001)


if __name__ == '__main__': unittest.main()
