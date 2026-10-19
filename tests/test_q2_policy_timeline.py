"""Historical information and grandfathering cannot be overwritten by hindsight."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_q2_policy_timeline as policy


class PolicyTimelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review, cls.document = policy.load_reviewed(ROOT)

    def test_future_publication_not_visible_from_signed_date(self):
        self.assertEqual(policy.visible_schedules(self.document, '2014-12-31'), [])
        self.assertEqual(len(policy.visible_schedules(self.document, '2015-01-09')), 1)
        before = policy.visible_schedules(self.document, '2015-12-23')
        after = policy.visible_schedules(self.document, '2015-12-24')
        self.assertEqual(len(before), 1)
        self.assertEqual(len(after), 4)
        self.assertIn('wind_2018_announced_3044', {s['id'] for s in after})
        self.assertNotIn('wind_2018_revised_2729', {s['id'] for s in after})

    def test_cancellation_is_not_retroactive_and_grandfathered_cohorts_remain(self):
        before = {s['id'] for s in policy.visible_schedules(self.document, '2016-12-27')}
        after = {s['id'] for s in policy.visible_schedules(self.document, '2016-12-28')}
        self.assertIn('wind_2018_announced_3044', before)
        self.assertNotIn('wind_2018_announced_3044', after)
        self.assertIn('wind_2018_revised_2729', after)
        self.assertTrue({'wind_2015_3008', 'wind_2016_3044', 'pv_2016_3044', 'pv_2017_2729'} <= after)
        self.assertEqual(len(self.document['schedules']), 6)

    def test_invalid_cross_technology_replacement_rejected(self):
        document = deepcopy(self.document)
        old = next(s for s in document['schedules'] if s['superseded_by'])
        old['superseded_by'] = 'pv_2017_2729'
        with self.assertRaisesRegex(ValueError, 'Replacement'):
            policy.validate(document)

    def test_original_or_transcription_tamper_cannot_pass_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {r['path'] for r in self.review['fingerprints']}
            paths.update(['data/catalog/q2_policy_timeline_review.json', 'data/catalog/q2_sources.json'])
            for name in paths:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            policy.load_reviewed(root)
            for name in [self.review['fingerprints'][0]['path'], 'data/catalog/q2_policy_timeline_transcription.json']:
                target = root / name
                original = target.read_bytes()
                target.write_bytes(original + b' ')
                with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
                    policy.load_reviewed(root)
                target.write_bytes(original)
            review = deepcopy(self.review)
            review['checks'][0]['passed'] = False
            (root / 'data/catalog/q2_policy_timeline_review.json').write_text(json.dumps(review), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'not substantively reviewed'):
                policy.load_reviewed(root)


if __name__ == '__main__':
    unittest.main()
