import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from energy_model.q2.quality import historical_quality


class Q2QualityTests(unittest.TestCase):
    def setUp(self):
        families=['energy_consumption','primary_mix','capacity_or_generation','co2']
        self.targets=[{'id':k,'family':k,'scale':1.,'metric_type':'share_fraction' if k=='primary_mix' else 'total'} for k in families]
        self.fit={'history_fit':[],'baselines':[]}
        for k in families:
            for year in (2022,2023,2024):
                self.fit['history_fit'].append({'indicator':k,'year':year,'window':'already_seen_holdout',
                    'status':'compared','value':.5,'simulated':.5,'residual':0.,'unit':'fixture','boundary':'fixture'})
                self.fit['baselines'].append({'indicator':k,'year':year,'method':'last_training_observation',
                    'observed':.5,'residual':.1,'unit':'fixture','boundary':'fixture'})
        self.criteria={'maximum_holdout_mape_each_target':.15,'maximum_holdout_share_absolute_error':.05,
                       'maximum_holdout_normalized_rmse_ratio_to_persistence':1.}

    def assess(self):
        return historical_quality(self.fit,self.targets,self.criteria,{'already_seen_holdout':[2022,2024]})

    def test_pass_does_not_mutate_frozen_input_and_errors_fail(self):
        before=deepcopy(self.fit); self.assertTrue(self.assess()['passed']);self.assertEqual(self.fit,before)
        r=self.fit['history_fit'][0];r.update(simulated=.8,residual=.3)
        self.assertFalse(self.assess()['passed'])
        self.assertIn('mape_exceeded',self.assess()['targets'][0]['reasons'])

    def test_missing_year_cannot_improve_quality_by_exclusion(self):
        self.fit['history_fit'].pop()
        self.assertFalse(self.assess()['passed'])
        self.assertIn('incomplete_holdout_coverage',self.assess()['targets'][-1]['reasons'])

    def test_perfect_persistence_and_zero_observation_are_explicit(self):
        for r in self.fit['baselines']:r['residual']=0.
        self.assertTrue(self.assess()['passed'])
        self.fit['history_fit'][0].update(simulated=.5001,residual=.0001)
        self.assertIn('model_worse_than_exact_persistence',self.assess()['targets'][0]['reasons'])
        self.fit['history_fit'][0].update(value=0.,simulated=.1,residual=.1)
        self.fit['baselines'][0]['observed']=0.
        self.assertIn('nonzero_prediction_at_zero_observation',self.assess()['targets'][0]['reasons'])

    def test_share_units_and_baseline_boundary_cannot_be_mixed(self):
        self.targets[1]['metric_type']='percent'
        self.assertIn('primary_mix_fraction_definition_missing',self.assess()['targets'][1]['reasons'])
        self.fit['baselines'][0]['boundary']='different'
        with self.assertRaisesRegex(ValueError,'boundary'):self.assess()


if __name__=='__main__':unittest.main()
