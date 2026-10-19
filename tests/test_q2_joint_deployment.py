"""Joint search must retain information separation and independent rate controls."""
import contextlib
from copy import deepcopy
import io
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import run_q2_historical_candidate as history
from run_q2_joint_deployment_comparison import training_winners


class JointDeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.data = history.load_frozen(ROOT / 'workflow/q2_candidates/v9/manifest.json')

    def test_holdout_values_do_not_change_joint_structure_rate_or_rule_selection(self):
        data = deepcopy(self.data)
        for parameter in data['experiment']['parameters']:
            parameter['grid'] = parameter['grid'][::8]
        changed = deepcopy(data)
        for row in changed['observations']:
            if row['year'] >= 2022:
                row['value'] *= 1000
        with contextlib.redirect_stdout(io.StringIO()):
            before, after = history.train_candidates(data), history.train_candidates(changed)
        self.assertEqual(before, after)
        self.assertEqual(len(before), 24)
        self.assertTrue(all(r['status'] == 'valid' for r in before))
        structures = data['experiment']['structural_alternatives']
        self.assertEqual(training_winners(before, structures), training_winners(after, structures))

    def test_wind_rate_intervention_preserves_solar_limit_and_original_model(self):
        base = self.data['structural_models']['technology_frontiers']
        saved = deepcopy(base)
        parameters = self.data['experiment']['parameters']
        values = {p['id']: p['grid'][0] for p in parameters}
        low = history.parameterize(base, parameters, values)
        values['wind_stock_expansion_rate'] = parameters[0]['grid'][-1]
        high = history.parameterize(base, parameters, values)
        self.assertEqual(base, saved)
        wind = next(i for i, g in enumerate(base['investment_groups']) if g['id'] == 'wind_construction')
        solar = next(i for i, g in enumerate(base['investment_groups']) if g['id'] == 'solar_construction')
        self.assertEqual(low['investment_groups'][solar], high['investment_groups'][solar])
        self.assertNotEqual(low['investment_groups'][wind], high['investment_groups'][wind])
        high['investment_groups'][wind] = deepcopy(low['investment_groups'][wind])
        self.assertEqual(low, high)


if __name__ == '__main__':
    unittest.main()
