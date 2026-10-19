"""Training information boundary and a derivative at bounded coordinates."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import run_q2_allocation_candidate as candidate


class AllocationCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.data = candidate.history.load_frozen(ROOT / 'workflow/q2_candidates/v10/manifest.json')
        cls.model = json.loads((ROOT / 'outputs/q2/historical_candidate_v12/selected_model.json').read_text(encoding='utf-8'))

    def test_normalized_derivative_is_defined_at_zero_and_one(self):
        expected = np.array([[1., 2.], [-3., 4.]])
        fun = lambda x: expected @ x
        for point in (np.array([0., 1.]), np.array([1e-14, 1. - 1e-14])):
            np.testing.assert_allclose(candidate.bounded_jacobian(fun, point, 1e-4), expected, rtol=1e-10)

    def test_future_gdp_and_holdout_values_cannot_change_training(self):
        current = candidate.candidate_model(self.model, 1., 'proportional_requests', 'instant_margin')
        changed = deepcopy(self.model)
        for year in range(2022, 2025):
            changed['gdp_growth'][str(year)] = .5
        changed = candidate.candidate_model(changed, 1., 'proportional_requests', 'instant_margin')
        data = deepcopy(self.data)
        for row in data['observations']:
            if row['year'] >= 2022:
                row['value'] *= 999
        np.testing.assert_array_equal(candidate.joint.training_residuals(current, self.data),
                                      candidate.joint.training_residuals(changed, data))

    def test_no_initial_asset_queue_funding_or_observation_changes(self):
        original = deepcopy(self.model)
        result = candidate.candidate_model(self.model, 0., 'proportional_requests', 'instant_margin')
        self.assertEqual(self.model, original)
        for key in ('assets', 'initial_projects', 'agents', 'other_accounts', 'operation',
                    'demand_drivers', 'investment_options', 'investment_groups'):
            self.assertEqual(result[key], original[key])


if __name__ == '__main__':
    unittest.main()
