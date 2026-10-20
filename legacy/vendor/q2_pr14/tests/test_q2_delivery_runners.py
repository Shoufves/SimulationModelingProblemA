"""Regression checks for review(10): roundoff and process failure propagation."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from run_q2_portable import compare_reference
import run_q2_current_delivery as runner
import build_q2_answer_delivery as report_builder


class DeliveryRunnerTests(unittest.TestCase):
    def test_frozen_source_archive_is_exact_and_narrow(self):
        ROOT.joinpath('tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as tmp:
            root = Path(tmp)
            source = root/'scripts/run_q2_current_delivery.py'
            archive = root/'archive/pr14_review10/run_q2_current_delivery.py'
            source.parent.mkdir(parents=True); archive.parent.mkdir(parents=True)
            source.write_text('new'); archive.write_text('old')
            expected = report_builder.sha(archive)
            with patch.object(report_builder, 'ROOT', root):
                self.assertTrue(report_builder.verify_frozen_sources({'scripts/run_q2_current_delivery.py': expected}))
                archive.write_text('tampered')
                with self.assertRaises(ValueError):
                    report_builder.verify_frozen_sources({'scripts/run_q2_current_delivery.py': expected})
                model = root/'model.py'; model.write_text('new')
                with self.assertRaises(ValueError):
                    report_builder.verify_frozen_sources({'model.py': expected})

    def test_currency_roundoff_and_receipt(self):
        ref = {'year': 2025, 'resource_cost_cny': 1e12}
        got = {**ref, 'resource_cost_cny': 1e12+.00390625}
        result = compare_reference(got, ref)
        self.assertTrue(result['passed'])
        self.assertFalse(result['exact_match'])
        self.assertEqual(result['differences'][0]['absolute_difference'], .00390625)

    def test_real_changes_and_structure_rejected(self):
        for actual, expected in [
            ({'year': 2025.00000001}, {'year': 2025}),
            ({'resource_cost_cny': 1e12+1}, {'resource_cost_cny': 1e12}),
            ({'capacity_mw': 1001.}, {'capacity_mw': 1000.}),
            ({'status': True}, {'status': 1}),
            ({'name': 'S1'}, {'name': 'S0'}),
            ({'a': 1}, {'b': 1}), ([1], [1, 2]),
            ({'x': float('nan')}, {'x': float('nan')}),
            ({'x': float('inf')}, {'x': float('inf')}),
        ]:
            with self.subTest(actual=actual):
                self.assertFalse(compare_reference(actual, expected)['passed'])

    def test_equal_bad_residuals_rejected(self):
        for row in ({'max_residual': 2e-6},
                    {'cash_balance_residual_cny': 10., 'operating_resource_cost_cny': 1e12}):
            self.assertFalse(compare_reference(row, row)['passed'])

    def test_invalid_horizon_process_fails(self):
        for script in ('run_q2_current_delivery.py', 'run_q2_portable.py'):
            p = subprocess.run([sys.executable, '-B', str(ROOT/'scripts'/script),
                                '--end-year', '2024'], capture_output=True, text=True)
            self.assertEqual(p.returncode, 2, p.stderr)
            self.assertIn('--end-year must be', p.stderr)

    def _run_fake_batch(self, failed):
        # Isolate orchestration; the worker's caught-error branch is tested below.
        ROOT.joinpath('tmp').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as tmp:
            root = Path(tmp)
            config = {'scenarios': [{'name': 'S0'}], 'historical_runs': {'net58': 'history'}}
            def load(path):
                name = Path(path).name
                return {'results.json': {'source_sha256': {}},
                        'training_selection.json': {'scenarios': {'25': {'parameters': {}}}},
                        'design.json': {}, 'q2_current_delivery.json': config}[name]
            item = {'name': 'S0', 'status': 'failed' if failed else 'success',
                    'spec': {}, 'targets': [], 'summary': {}}
            pool = MagicMock()
            pool.__enter__.return_value.map.return_value = [item]
            with patch.object(runner, 'ROOT', root), patch.object(runner, 'load', side_effect=load), \
                 patch.object(runner, 'review'), patch.object(runner, 'preflight', return_value=({}, {})), \
                 patch.object(runner, 'build', return_value=(None, {}, [])), \
                 patch.object(runner, 'sha', return_value='test'), \
                 patch.object(runner, 'ProcessPoolExecutor', return_value=pool), \
                 patch.object(sys, 'argv', ['runner']):
                code = runner.main()
            status = json.loads(next(root.glob('outputs/q2_current_delivery/*/status.json')).read_text())
            self.assertEqual(code, int(failed))
            self.assertEqual(status['failures'], int(failed))
            self.assertEqual(status['status'], 'completed_with_failures' if failed else 'complete_conditional_scenarios')

    def test_success_exit_and_receipt(self):
        self._run_fake_batch(False)

    def test_failed_exit_and_receipt(self):
        self._run_fake_batch(True)

    def test_worker_exception_preserves_failure_receipt(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'tmp') as tmp:
            with patch.object(runner, 'WORKER', None):
                result = runner.trial(('unused', 25, {'name': 'S0'}, Path(tmp), 2060))
            self.assertEqual(result['status'], 'failed')
            self.assertTrue((Path(tmp)/'S0_failed.json').exists())


if __name__ == '__main__':
    unittest.main()
