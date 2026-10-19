"""Current-state category/time guards and missing-value rejection."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from energy_model.q2.current_state import build_state, normalize, require_complete_state
from energy_model.q2.io import AdmissionError


class CurrentStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = json.loads((ROOT / 'data/catalog/q2_current_state_transcription.json').read_text(
            encoding='utf-8'))['observations']

    def test_nameplate_storage_does_not_create_soc_or_pumped_energy(self):
        state, _ = build_state(self.rows)
        by_id = {r['id']: r for r in state['components']}
        self.assertEqual(by_id['new_storage']['capacity_mw'], 73760.)
        self.assertEqual(by_id['new_storage']['energy_capacity_mwh'], 168200.)
        self.assertIsNone(by_id['new_storage']['initial_soc_mwh'])
        self.assertIsNone(by_id['pumped_hydro']['energy_capacity_mwh'])
        self.assertEqual(state['national_generation_capacity_mw']['hydro'], 435520.)
        self.assertIsNone(by_id['conventional_hydro']['capacity_mw'])

    def test_reporting_fleet_cannot_become_national_coal_gas(self):
        state, _ = build_state(self.rows)
        for c in state['components']:
            if c['id'] in ('coal_power', 'gas_power'):
                self.assertIsNone(c['capacity_mw'])
        changed = deepcopy(self.rows)
        row = next(r for r in changed if r['id'] == 'NBS:thermal')
        row['basis'] = 'reporting_fleet_capacity'
        with self.assertRaisesRegex(ValueError, 'incompatible scope'):
            build_state(changed)

    def test_national_capacity_vintages_not_spliced(self):
        changed = deepcopy(self.rows)
        next(r for r in changed if r['id'] == 'NBS:solar')['vintage'] = 'NEA_2025-01-21'
        with self.assertRaisesRegex(ValueError, 'vintages'):
            build_state(changed)

    def test_annual_generation_cannot_initialize_capacity(self):
        changed = deepcopy(self.rows)
        row = next(r for r in changed if r['id'] == 'NBS:wind')
        row.update(unit='TWh', basis='annual_flow', value=991.6)
        with self.assertRaisesRegex(ValueError, 'incompatible scope'):
            build_state(changed)

    def test_missing_duplicate_future_and_nonfinite_observations_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            normalize(self.rows + self.rows[:1])
        for field, value in [('value', None), ('value', float('nan')), ('value', True),
                             ('year', 2025), ('unit', 'GWh_per_year')]:
            with self.subTest(field=field, value=value):
                changed = deepcopy(self.rows)
                changed[0][field] = value
                with self.assertRaises(ValueError):
                    normalize(changed)

    def test_demand_and_gas_categories_checked_without_overlapping_totals(self):
        state, _ = build_state(self.rows)
        self.assertEqual(state['electricity_annual_mwh']['total'], 9852100000.)
        self.assertEqual(state['checks']['electricity_category_residual_mwh'], 0.)
        self.assertAlmostEqual(state['checks']['gas_share_sum'], 1.)
        for identity in ('DEMAND:secondary', 'GAS:power'):
            changed = deepcopy(self.rows)
            next(r for r in changed if r['id'] == identity)['value'] += 1
            with self.assertRaisesRegex(ValueError, 'reconcile'):
                build_state(changed)

    def test_admission_flags_and_deleted_gap_list_cannot_hide_unknown_fields(self):
        state, _ = build_state(self.rows)
        state.update(initialization_complete=True, unresolved_fields=[])
        with self.assertRaises(AdmissionError) as caught:
            require_complete_state(state)
        self.assertIn(dict(component='gas_power', field='capacity_mw'), caught.exception.gaps)
        self.assertIn(dict(component='new_storage', field='initial_soc_mwh'), caught.exception.gaps)
        state['components'] = []
        with self.assertRaisesRegex(AdmissionError, 'components'):
            require_complete_state(state)

    def test_rounding_residual_retained_without_changing_other(self):
        changed = deepcopy(self.rows)
        next(r for r in changed if r['id'] == 'NBS:total')['value'] += 1
        state, _ = build_state(changed)
        self.assertEqual(state['checks']['capacity_sum_residual_mw'], 10.)
        self.assertEqual(state['national_generation_capacity_mw']['other'], 50.)


if __name__ == '__main__':
    unittest.main()
