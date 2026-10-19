"""Material content consumes fuel and cash; omitted emissions remain unknown."""
from copy import deepcopy
import json
from math import fsum
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'src'))
import build_q2_nonenergy_episode as builder
import run_q2_nonenergy_episode as runner
from energy_model.q2.annual import EnergyModel


class NonenergyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = builder.build()
        cls.base = cls.data['model']
        cls.items = cls.data['initialization']['material_mappings']
        cls.split = cls.data['structural_models']['same_growth_split']
        cls.elasticities = dict(coal=0., oil=.5, gas=2.)
        cls.parent_result = EnergyModel(cls.base).run()
        cls.split_result = EnergyModel(cls.split).run()
        review = json.loads((ROOT / 'data/catalog/q2_apec_balance_review.json').read_text(encoding='utf-8'))
        cls.table = builder.parse_table((ROOT / review['ktoe_export']).read_text(encoding='utf-8-sig'), 'Unit:KTOE', review)

    def test_reported_cells_and_joint_missing_interval(self):
        items, bounds = builder.extract_material_reference(self.table)
        self.assertEqual(len(items), 5)
        self.assertEqual(bounds['reported_cells'], 8)
        self.assertEqual(bounds['unresolved_cells'], 64)
        self.assertEqual(bounds['total_nonenergy_control'], 182955.)
        self.assertEqual(bounds['mapped_centres_ktoe'], 182954.)
        self.assertEqual((bounds['unassigned_joint_lower_ktoe'], bounds['unassigned_joint_upper_ktoe']), (0., 5.5))
        self.assertEqual(fsum(i['input_MWh_LHV'] for i in items), 182954 * 11630)

    def test_changed_material_cells_rejected(self):
        for column, token in [('1. Coal', '-1'), ('3. Peat', '1'), ('1. Coal', '-')]:
            table = deepcopy(self.table)
            # A currently blank top-level product cannot be silently added.
            if column not in table[0]:
                column = table[0][builder.TOP_COLUMNS[2]]
            row = next(r for r in table if r[0] == '17.2 Industry sector')
            row[table[0].index(column)] = token
            with self.subTest(column=column, token=token), self.assertRaises(ValueError):
                builder.extract_material_reference(table)

    def test_duplicate_or_missing_material_rows_rejected(self):
        duplicate = deepcopy(self.table)
        duplicate.append(deepcopy(next(r for r in duplicate if r[0] == '17.2 Industry sector')))
        missing = [r for r in self.table if r[0] != '17.2 Industry sector']
        for table in (duplicate, missing):
            with self.subTest(rows=len(table)), self.assertRaises(ValueError):
                builder.extract_material_reference(table)

    def test_initial_fuel_capacity_and_money_preserved(self):
        checks = runner.initial_checks(self.base, self.split)
        self.assertEqual(len(checks), 3)
        self.assertEqual(self.base['agents'], self.split['agents'])
        self.assertEqual(self.base['other_accounts'], self.split['other_accounts'])
        self.assertEqual(self.base['initial_projects'], self.split['initial_projects'])
        self.assertEqual(self.base['investment_options'], self.split['investment_options'])

    def test_material_mapping_rejects_duplicates_invalid_owners_and_oversize(self):
        for change in ('duplicate', 'owner', 'oversize', 'carrier', 'negative', 'nonfinite'):
            items = deepcopy(self.items)
            if change == 'duplicate': items.append(deepcopy(items[0]))
            if change == 'owner': items[0]['owner'] = 'absent'
            if change == 'oversize': items[0]['input_MWh_LHV'] = 1e30
            if change == 'carrier': items[0]['carrier'] = 'unreviewed'
            if change == 'negative': items[0]['input_MWh_LHV'] = -1.
            if change == 'nonfinite': items[0]['input_MWh_LHV'] = float('nan')
            with self.subTest(change=change), self.assertRaises(ValueError):
                builder.split_material(self.base, items, self.elasticities)

    def test_no_double_partition_or_implicit_response(self):
        with self.assertRaises(ValueError):
            builder.split_material(self.split, self.items, self.elasticities)
        for values in ({'coal': 0., 'oil': 1.}, dict(coal=True, oil=1., gas=1.), dict(coal=3., oil=1., gas=1.)):
            with self.assertRaises(ValueError):
                builder.split_material(self.base, self.items, values)

    def test_material_still_consumes_fuel_and_owner_cash(self):
        rows = runner.material_rows('same_growth_split', self.split, self.split_result, self.items)
        self.assertEqual(len(rows), 55)
        self.assertTrue(all(r['supplied_MWh_LHV'] > 0 and r['purchase_million_USD2008'] > 0 for r in rows))
        self.assertTrue(all(r['actual_material_emissions_t'] is None and r['removal_credit_t'] == 0 for r in rows))
        self.assertEqual(len(runner.carrier_rows('same_growth_split', self.split_result)), 33)
        damaged = deepcopy(self.split_result)
        transaction = next(t for t in damaged['cash'] if t['reason'] == 'end_use_purchase' and 'nonenergy_' in t['reference'])
        transaction['amount'] = 0.
        with self.assertRaisesRegex(ValueError, 'Material fuel purchase'):
            runner.material_rows('bad', self.split, damaged, self.items)

    def test_full_parent_control_and_same_growth_reconciliation(self):
        retained = json.loads((ROOT / runner.PARENT_RESULT).read_text(encoding='utf-8'))['result']
        self.assertEqual(self.parent_result, retained)
        rows = runner.material_rows('same_growth_split', self.split, self.split_result, self.items)
        checks = runner.paired_control(self.parent_result, self.split_result, rows)
        self.assertEqual(len(checks), 11)
        self.assertTrue(all(r['abatement_claim'] is False for r in checks))

    def test_partial_carbon_never_uses_parent_metric_identity(self):
        definitions = runner.metric_definitions(self.data['definitions'], True)
        self.assertNotIn('gcb_fuel_co2', [d['id'] for d in definitions])
        self.assertIn(runner.PARTIAL_CARBON, [d['id'] for d in definitions])
        self.assertIn('gcb_fuel_co2', [d['id'] for d in self.data['definitions']])
        self.assertTrue(all(r['captured_co2_t'] == 0 for r in self.split_result['annual']))

    def test_all_responses_predeclared_without_fitting_or_observation_feedback(self):
        cases = self.data['episode']['cases']
        self.assertEqual(len(cases), 29)
        self.assertEqual(len({tuple(c['material_elasticities'].values()) for c in cases[2:]}), 27)
        manifest, parent = builder.history.load_frozen(ROOT / 'workflow/q2_candidates/v10/manifest.json')
        damaged = deepcopy(parent)
        for obs in damaged['observations']:
            obs['value'] = 1e30
        with patch.object(builder.history, 'load_frozen', return_value=(manifest, damaged)):
            rebuilt = builder.build()
        self.assertEqual(rebuilt['structural_models'], self.data['structural_models'])
        self.assertFalse(self.data['episode']['carbon_target_comparison_admitted'])

    def test_future_growth_cannot_change_earlier_ledgers(self):
        changed = deepcopy(self.split)
        changed['gdp_growth']['2024'] = .5
        after = EnergyModel(changed).run()
        for key in ('annual', 'cash', 'actions', 'assets', 'information', 'operations'):
            self.assertEqual([r for r in after[key] if r['year'] < 2024],
                             [r for r in self.split_result[key] if r['year'] < 2024])
        self.assertNotEqual(after['operations'][-1], self.split_result['operations'][-1])

    def test_binding_failure_happens_before_creating_output(self):
        destination = ROOT / 'outputs/q2/nonenergy_should_not_exist'
        self.assertFalse(destination.exists())
        with patch.object(builder, 'freeze', side_effect=ValueError('Reviewed source record changed')):
            with self.assertRaisesRegex(ValueError, 'Reviewed source'):
                runner.execute(destination.relative_to(ROOT).as_posix())
        self.assertFalse(destination.exists())


if __name__ == '__main__':
    unittest.main()
