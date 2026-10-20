"""Integration boundaries: do not alter the reviewed scientific implementations."""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import run_q2_pr14 as runner


class Q2PR14IntegrationTests(unittest.TestCase):
    def test_verified_payload_covers_the_frozen_upstream_code_and_all_cases(self):
        review, cases = runner.verify_payload()
        self.assertEqual(len(cases), 24)
        self.assertEqual(review['upstream_commit'], runner.UPSTREAM)
        self.assertFalse(review['scientific_code_modified'])
        self.assertFalse(review['raw_originals_reverified'])

    def test_new_default_dispatches_pr14_and_q3_keeps_its_entry(self):
        spec = importlib.util.spec_from_file_location('integrated_entry', ROOT/'run.py')
        entry = importlib.util.module_from_spec(spec); spec.loader.exec_module(entry)
        for args, expected in [
            (['q2'], ('run_q2_pr14.py', '--output-dir', 'outputs/q2_pr14/integrated')),
            (['q2', '--config', 'workflow/q2_pr14_integration.json'],
             ('run_q2_pr14.py', '--output-dir', 'outputs/q2_pr14/integrated')),
            (['q3'], ('run_q3.py', '--config', 'workflow/q3_inputs.json', '--output-dir', 'outputs/q3/p3_yx')),
            (['q1'], ('build_q1.py', '--output-dir', 'outputs/q1/p1_yx')),
        ]:
            with self.subTest(args=args), patch.object(sys, 'argv', ['run.py', *args]), \
                    patch.object(entry, 'script', return_value=0) as call:
                self.assertEqual(entry.main(), 0)
                call.assert_called_once_with(*expected)

    def test_outputs_cannot_overwrite_q1_q3_or_legacy_q2(self):
        for path in ('outputs/q1/p1_yx', 'outputs/q3/p3_yx', 'outputs/q2/p2_lb_national',
                     'outputs/research_n2/pr13_review2', 'outputs/q2_pr14/../../data', 'tmp/q2_integration'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                runner.output_folder(path)

    def test_unknown_case_and_bad_year_fail_without_launch_and_preserve_old_attempt(self):
        parent = ROOT/'tmp/q2_integration'; parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as tmp:
            folder = Path(tmp)
            runner.save(folder/'owner.json', {'owner': runner.OWNER})
            old = folder/'attempts/old'; old.mkdir(parents=True)
            (old/'marker').write_text('previous result', 'utf-8')
            for arguments in (['--only', 'fake'], ['--end-year', '2024'], ['--only', 'S0', 'S0']):
                runner.save(folder/'latest.json', {'status': 'passed', 'attempt': 'attempts/old'})
                with patch.object(runner.subprocess, 'Popen') as process:
                    self.assertEqual(runner.main(['--output-dir', str(folder), *arguments]), 1)
                    process.assert_not_called()
                self.assertEqual(runner.load(folder/'latest.json')['status'], 'failed')
                self.assertEqual((old/'marker').read_text('utf-8'), 'previous result')
                with self.assertRaises(ValueError): runner.verify_latest(folder)

    def test_unowned_output_directory_is_rejected_without_changes(self):
        parent = ROOT/'tmp/q2_integration'; parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=parent) as tmp:
            folder = Path(tmp); (folder/'user_file').write_text('keep', 'utf-8')
            with self.assertRaises(ValueError): runner.output_folder(folder)
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ['user_file'])

    def test_changed_runtime_reference_or_input_fails_closed(self):
        original = runner.sha
        for changed in ('vendor/q2_pr14/src/energy_model/q2_national.py',
                        'data/processed/q2_delivery/parsed_inputs.json',
                        'data/processed/q2_delivery/reference_paths/S0.json'):
            def changed_sha(path):
                return '0'*64 if Path(path) == ROOT/changed else original(path)
            with self.subTest(path=changed), patch.object(runner, 'sha', side_effect=changed_sha), \
                    self.assertRaises(ValueError):
                runner.verify_payload()

    def test_relocation_cannot_escape_stage(self):
        with self.assertRaises(ValueError):
            runner.within(ROOT/'tmp/q2_pr14/../../src', ROOT/'tmp/q2_pr14')

    def test_only_q2_dispatch_is_changed_from_accepted_main(self):
        # The original launcher is a small reviewed compatibility asset, not a
        # second entry point for users. Compare AST after removing Q2 dispatch.
        original = (ROOT/'vendor/q2_pr14/accepted_main_run.py').read_text('utf-8')
        actual = (ROOT/'run.py').read_text('utf-8')
        def without_q2(source):
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == 'main':
                    node.body = [n for n in node.body if not (
                        isinstance(n, ast.If) and ast.unparse(n.test) == "args.command == 'q2'")]
            return ast.dump(tree, include_attributes=False)
        self.assertEqual(without_q2(original), without_q2(actual))


if __name__ == '__main__':
    unittest.main()
