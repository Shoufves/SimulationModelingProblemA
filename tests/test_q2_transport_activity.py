"""Transport quantities stay dated, disjoint and separate from fuel demand."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_q2_transport_activity import activity_series, prepare, reconcile


class TransportActivityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.transcription = json.loads((ROOT / 'data/catalog/q2_transport_activity_transcription.json').read_text(encoding='utf-8'))

    def rows(self):
        rows, diagnostics = reconcile(self.transcription)
        for row in rows:
            row['source_id'] = 'original_' + row['table']
        return rows, diagnostics

    def test_modes_reconcile_without_double_counting_ocean(self):
        rows, diagnostics = self.rows()
        self.assertEqual(len(rows), 132)
        self.assertEqual(len(diagnostics), 22)
        self.assertTrue(all(r['passed'] for r in diagnostics))
        freight = next(r for r in diagnostics if r['table'] == 'C16-08' and r['year'] == 2024)
        self.assertEqual(freight['disjoint_mode_sum'], 261952.19)
        self.assertEqual(freight['residual'], .81)
        self.assertEqual(freight['rounding_diagnostic_bound'], 1.155)
        self.assertTrue(all(r['energy_intensity'] is None and r['equipment_fuel_share'] is None for r in rows))

    def test_units_boundary_and_observation_status_survive_export(self):
        rows, _ = self.rows()
        passenger = activity_series(rows, 'C16-06', 'rail')
        freight = activity_series(rows, 'C16-08', 'rail')
        self.assertEqual(passenger['unit'], '10^8 passenger_km')
        self.assertEqual(freight['unit'], '10^8 tonne_km')
        self.assertEqual(passenger['records'][0]['value'], 11241.9)
        self.assertEqual(passenger['records'][-1]['value'], 15799.1)
        self.assertTrue(all(r['status'] == 'retrospective_observation' for r in passenger['records']))
        self.assertIn('commercial', activity_series(rows, 'C16-06', 'road')['boundary'])
        self.assertIn('international_routes', activity_series(rows, 'C16-06', 'civil_aviation')['boundary'])

    def test_mixed_totals_overlap_and_unbridged_transition_withheld(self):
        rows, _ = self.rows()
        for table, mode in [('C16-06', 'total'), ('C16-08', 'total'),
                            ('C16-08', 'ocean_subset'), ('C16-08', 'road'),
                            ('C16-06', 'water'), ('C16-08', 'water')]:
            with self.subTest(table=table, mode=mode), self.assertRaises(ValueError):
                activity_series(rows, table, mode)
        ocean = next(r for r in rows if (r['table'], r['year'], r['mode']) == ('C16-08', 2020, 'ocean_subset'))
        self.assertEqual(ocean['value'], 89897.)
        self.assertEqual(ocean['comparability'], 'unresolved_transition')
        changes = {(r['table'], r['mode']): r for r in self.transcription['suspicious_transitions']}
        self.assertEqual(changes['C16-08', 'road']['status'], 'documented_scope_change_no_backcast')
        self.assertEqual(changes['C16-08', 'water']['source_id'], 'MOT_TRANSPORT_SCOPE_2020_Q2')

    def test_duplicate_missing_units_roles_and_invalid_values_rejected(self):
        for change in ('duplicate', 'missing', 'unit', 'role', 'nan', 'negative', 'subset'):
            value = deepcopy(self.transcription)
            if change == 'duplicate': value['observations'].append(deepcopy(value['observations'][0]))
            elif change == 'missing': value['observations'].pop()
            elif change == 'unit': value['observations'][0]['unit'] = '10^8 tonne_km'
            elif change == 'role': value['observations'][0]['column_role'] = 'disjoint_mode'
            elif change == 'nan': value['observations'][0]['value_cell'] = 'NaN'
            elif change == 'negative': value['observations'][0]['value_cell'] = '-1'
            else: next(r for r in value['observations'] if r['mode'] == 'ocean_subset')['value_cell'] = '999999'
            with self.subTest(change=change), self.assertRaises(ValueError):
                reconcile(value)

    def test_original_digit_transposition_is_detected_without_tolerance_relaxation(self):
        value = deepcopy(self.transcription)
        next(r for r in value['observations'] if (r['table'], r['year'], r['mode']) == ('C16-06', 2018, 'road'))['value_cell'] = '9297.7'
        _, checks = reconcile(value)
        failed = [r for r in checks if not r['passed']]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]['residual'], -18.)
        self.assertEqual(failed[0]['rounding_diagnostic_bound'], .25)

    def test_arithmetic_failure_blocks_all_activity_exports(self):
        rows, checks = self.rows()
        checks[0]['passed'] = False
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as temporary:
            relative = Path(temporary).relative_to(ROOT).as_posix() + '/rejected'
            with patch('prepare_q2_transport_activity.reconcile', return_value=(rows, checks)):
                with self.assertRaisesRegex(ValueError, 'arithmetic unresolved'):
                    prepare(ROOT, relative)
            self.assertFalse((ROOT / relative).exists())

    def test_raw_or_transcription_tamper_rejected_before_output(self):
        review = json.loads((ROOT / 'data/catalog/q2_transport_activity_review.json').read_text(encoding='utf-8'))
        sources = {r['id']: r for r in json.loads((ROOT / 'data/catalog/q2_sources.json').read_text(encoding='utf-8'))}
        paths = ['data/catalog/q2_transport_activity_review.json', 'data/catalog/q2_sources.json']
        paths += [r['path'] for r in review['fingerprints']]
        paths += [sources[r['id']]['path'] for r in review['source_records']]
        for target in ('data/catalog/q2_transport_activity_transcription.json',
                       'data/raw/lb/base/nbs/yearbook2025/C16-06.jpg'):
            with self.subTest(target=target), tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as temporary:
                root = Path(temporary)
                for name in paths:
                    destination = root / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / name, destination)
                path = root / target
                path.write_bytes(path.read_bytes() + b'tampered')
                with self.assertRaisesRegex(ValueError, 'changed'):
                    prepare(root, 'outputs/rejected')
                self.assertFalse((root / 'outputs/rejected').exists())


if __name__ == '__main__':
    unittest.main()
