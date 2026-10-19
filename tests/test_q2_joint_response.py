"""Information separation and exact-parent controls for the v12 joint fit."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import run_q2_joint_response as joint


class JointResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.data = joint.history.load_frozen(ROOT / 'workflow/q2_candidates/v10/manifest.json')
        selected = json.loads((ROOT / 'outputs/q2/historical_candidate_v10/training_selection.json').read_text(encoding='utf-8'))['selected']
        cls.model = joint.history.parameterize(
            joint.history.rule_model(cls.data['structural_models'][selected['structure']], selected['rule']),
            cls.data['experiment']['parameters'], selected['parameters'])
        cls.parent_loss = selected['loss']

    def test_exact_parent_objective(self):
        residuals = joint.training_residuals(self.model, self.data)
        self.assertEqual(len(residuals), 56)
        self.assertAlmostEqual(float(residuals @ residuals), self.parent_loss, places=13)

    def test_holdout_targets_and_future_gdp_cannot_change_training(self):
        changed = deepcopy(self.data)
        for row in changed['observations']:
            if row['year'] >= 2022:
                row['value'] = -9999999
        future = deepcopy(self.model)
        for year in range(2022, 2025):
            future['gdp_growth'][str(year)] = 0.8
        baseline = joint.envelope_model(self.model, 2.0)
        intervention = joint.envelope_model(future, 2.0)
        np.testing.assert_array_equal(joint.training_residuals(baseline, self.data),
                                      joint.training_residuals(intervention, changed))
        self.assertNotEqual(baseline['policies'][-1], intervention['policies'][-1])

    def test_envelope_zero_replays_physical_and_financial_trajectory(self):
        original = joint.history.EnergyModel(self.model).run()
        control = joint.history.EnergyModel(joint.envelope_model(self.model, 0.0)).run()
        for key in ('annual', 'assets', 'projects', 'cash', 'operations', 'lifecycle_queue'):
            self.assertEqual(original[key], control[key], key)

    def test_hypothetical_envelope_preserves_original_inputs_and_dated_visibility(self):
        saved = deepcopy(self.model)
        transformed = joint.envelope_model(self.model, 1.0)
        self.assertEqual(saved, self.model)
        index = 1.0
        for year, policy in zip(range(2014, 2025), transformed['policies']):
            if year > 2014:
                index *= 1 + self.model['gdp_growth'][str(year)]
            self.assertEqual(policy['known_year'], year)
            self.assertEqual(policy['effective_year'], year)
            self.assertAlmostEqual(policy['construction_units_limit'], 150000 * index)
            self.assertAlmostEqual(policy['connection_limit'], 150000 * index)
        transformed['policies'] = saved['policies']
        self.assertEqual(transformed, saved)


if __name__ == '__main__':
    unittest.main()
