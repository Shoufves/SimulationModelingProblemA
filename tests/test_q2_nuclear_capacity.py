"""Prevent code collisions, future leakage and permit-to-operation promotion."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import prepare_q2_nuclear_capacity as subject


class NuclearCapacityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.transcription = json.loads((ROOT/'data/catalog/q2_nuclear_capacity_2015_transcription.json').read_text(encoding='utf-8'))
        cls.permits = json.loads((ROOT/'data/catalog/q2_nuclear_permit_2015_supplement_review.json').read_text(encoding='utf-8'))

    def test_source_local_code_collision_does_not_join_different_plants(self):
        rows, conflicts, checks = subject.reconcile(self.transcription, self.permits)
        self.assertEqual(checks['units'], 8)
        self.assertEqual(checks['capacity_MWe'], 8980)
        self.assertEqual(checks['source_code_conflicts'], 2)
        self.assertEqual({r['id']:r['capacity_MWe'] for r in rows if r['site']=='tianwan'},
                         {'tianwan_5':1080,'tianwan_6':1080})
        self.assertEqual(conflicts[0]['wrong_CNS_join_ids'], ['fangchenggang_3'])

    def test_pending_release_and_missing_start_remain_unknown(self):
        rows, _, checks = subject.reconcile(self.transcription, self.permits)
        self.assertEqual(checks['start_date_reported_units'], 6)
        self.assertEqual(checks['approved_without_start_date_units'], 2)
        six = next(r for r in rows if r['id']=='tianwan_6')
        self.assertIsNone(six['construction_start_date'])
        self.assertIsNone(six['first_concrete_release_date'])
        self.assertFalse(checks['national_model_admission'])
        self.assertTrue(all(r['first_grid_date'] is None and r['operating_permission_date'] is None for r in rows))

    def test_missing_date_cannot_be_filled_from_permit(self):
        for field in ('first_concrete_release_date','construction_start_date',
                      'operating_permission_date','commercial_operation_date','first_grid_date'):
            with self.subTest(field=field):
                bad = deepcopy(self.transcription)
                six = next(r for r in bad['observations'] if r['id']=='tianwan_6')
                six[field] = six['construction_permit_date']
                with self.assertRaises(ValueError): subject.reconcile(bad, self.permits)

    def test_duplicate_missing_or_wrong_plant_is_rejected(self):
        for change in ('duplicate','missing','wrong_plant'):
            with self.subTest(change=change):
                bad = deepcopy(self.transcription)
                if change=='duplicate': bad['observations'].append(deepcopy(bad['observations'][0]))
                elif change=='missing': bad['observations'].pop()
                else: bad['observations'][0]['plant']='防城港核电厂'
                with self.assertRaises(ValueError): subject.reconcile(bad, self.permits)

    def test_out_of_scope_units_dates_and_nonfinite_capacity_rejected(self):
        for field, value in [('capacity_MWe',float('nan')),('capacity_MWe',-1),
                             ('capacity_MWe',True),('construction_permit_date','2016-01-01')]:
            with self.subTest(field=field,value=value):
                bad=deepcopy(self.transcription); bad['observations'][0][field]=value
                with self.assertRaises(ValueError): subject.reconcile(bad,self.permits)
        bad=deepcopy(self.transcription); bad['capacity_unit']='MW(th)'
        with self.assertRaises(ValueError): subject.reconcile(bad,self.permits)

    def test_pin_rejects_corrupted_original_before_writing_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            path='data/catalog/q2_nuclear_capacity_2015_review.json'
            review=json.loads((ROOT/path).read_text(encoding='utf-8'))
            for rel in [path]+[r['path'] for r in review['fingerprints']]:
                dest=root/rel; dest.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(ROOT/rel,dest)
            (root/review['fingerprints'][0]['path']).write_bytes(b'changed')
            out=root/'result'
            with self.assertRaisesRegex(ValueError,'Nuclear reference changed'):
                subject.prepare(root,out)
            self.assertFalse(out.exists())


if __name__ == '__main__': unittest.main()
