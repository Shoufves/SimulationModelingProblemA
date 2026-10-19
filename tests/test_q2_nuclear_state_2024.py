"""Do not turn source-row agreement into invented asset identity or dates."""
from copy import deepcopy
import csv
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_q2_nuclear_state_2024 import prepare, reconcile


class NuclearState2024Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.transcription = json.loads((ROOT / 'data/catalog/q2_nuclear_state_2024_transcription.json').read_text(encoding='utf-8'))
        with (ROOT / 'data/processed/unified/nbs_history.csv').open(encoding='utf-8-sig') as f:
            cls.nbs = next(r for r in csv.DictReader(f) if r['year'] == '2024' and r['variable'] == 'nuclear_10kW')

    def test_missing_and_after_cutoff_dates_not_initialized_as_current(self):
        rows, _, checks = reconcile(self.transcription, self.nbs)
        by_id = {r['source_row_id']: r for r in rows}
        self.assertIsNone(by_id['operating:57']['first_grid_date'])
        self.assertIsNone(by_id['construction:12']['construction_start_date'])
        self.assertEqual(by_id['operating:58']['commercial_status_at_cutoff'], 'after_cutoff')
        self.assertEqual(by_id['operating:58']['first_grid_date'], '2024-11-28')
        self.assertTrue(all(r['future_commissioning_date'] is None and r['remaining_construction_cost'] is None for r in rows))
        self.assertEqual(checks['rated_operating_MW'], 60880.94)
        self.assertEqual(checks['rated_under_construction_MW'], 32309.1)
        self.assertFalse(checks['national_model_admission'])

    def test_labels_neither_deduplicated_nor_silently_renamed(self):
        rows, diagnostics, checks = reconcile(self.transcription, self.nbs)
        by_id = {r['source_row_id']: r for r in rows}
        self.assertEqual(len(rows), 85)
        self.assertEqual(by_id['operating:49']['unit_cell'], '3号机组')
        self.assertEqual(checks['identity_ambiguous_rows'], ['operating:48', 'operating:49'])
        self.assertEqual(checks['identity_context_required_rows'], ['operating:56', 'construction:07'])
        self.assertNotEqual(by_id['operating:56']['technology_cell'], by_id['construction:07']['technology_cell'])
        mismatch = next(d for d in diagnostics if d['check'] == 'operating_vs_nbs_2024')
        self.assertEqual(mismatch['difference'], 5.094)
        self.assertEqual(mismatch['decision'], 'unresolved_boundary_and_capacity_difference')

    def test_added_queue_commissioning_or_invalid_timing_rejected(self):
        for field, value, index in [('first_grid_cell', '2024/12/31', 58),
                                    ('construction_start_cell', '2025/1/1', 58),
                                    ('commercial_operation_cell', '1984/1/1', 0),
                                    ('commercial_operation_cell', '2026/1/1', 57)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                changed = deepcopy(self.transcription)
                changed['rows'][index][field] = value
                reconcile(changed, self.nbs)

    def test_wrong_units_nonfinite_capacity_and_wrong_total_rejected(self):
        for value in ('NaN', 'Infinity', '-1', '350'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                changed = deepcopy(self.transcription)
                changed['rows'][0]['rated_capacity_cell'] = value
                reconcile(changed, self.nbs)
        wrong = deepcopy(self.nbs)
        wrong['unit'] = 'MW'
        with self.assertRaises(ValueError):
            reconcile(self.transcription, wrong)

    def test_changed_original_rejected_before_outputs(self):
        review = json.loads((ROOT / 'data/catalog/q2_nuclear_state_2024_review.json').read_text(encoding='utf-8'))
        registry = json.loads((ROOT / 'data/catalog/q2_sources.json').read_text(encoding='utf-8'))
        sources = {r['id']: r for r in registry}
        paths = ['data/catalog/q2_nuclear_state_2024_review.json', 'data/catalog/q2_sources.json']
        paths += [r['path'] for r in review['fingerprints']]
        paths += [sources[r['id']]['path'] for r in review['source_records']]
        with tempfile.TemporaryDirectory(dir=ROOT / 'tmp') as temporary:
            root = Path(temporary)
            for name in paths:
                destination = root / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, destination)
            target = root / 'data/raw/q2/nnsa_nuclear_construction_2024.png'
            target.write_bytes(target.read_bytes() + b'tampered')
            with self.assertRaisesRegex(ValueError, 'source original changed'):
                prepare(root, 'outputs/rejected')
            self.assertFalse((root / 'outputs/rejected').exists())


if __name__ == '__main__':
    unittest.main()
