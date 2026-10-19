"""Accounting boundary counterexamples on the retained original balances."""
import copy
import csv
import importlib.util
import json
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


apec = module('prepare_q2_apec_balance')
coal = module('prepare_q2_coal_bridge')


class APECBalanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = json.loads((ROOT/'data/catalog/q2_apec_balance_review.json').read_text(encoding='utf-8'))
        cls.text = (ROOT/cls.review['ktoe_export']).read_text(encoding='utf-8')
        cls.ktoe = apec.parse_table(cls.text, 'Unit:KTOE', cls.review)
        cls.pj = apec.parse_table((ROOT/cls.review['pj_export']).read_text(encoding='utf-8'), 'Unit:Peta Joule', cls.review)

    def test_retained_units_and_html_match(self):
        self.assertEqual(len(apec.crosscheck_units(self.ktoe, self.pj)), 1301)
        html = apec.HTMLTable()
        html.feed((ROOT/self.review['ktoe_html']).read_text(encoding='utf-8'))
        self.assertEqual(html.rows, self.ktoe)

    def test_dash_and_signed_zero_are_not_conflated(self):
        self.assertIsNone(apec.value('-'))
        self.assertEqual(apec.value('-0'), Decimal(0))
        rows = apec.extract(self.ktoe, self.review)
        self.assertEqual(sum(r['value'] is None for r in rows), 5539)
        self.assertEqual(sum(r['negative_zero'] for r in rows), 8)
        self.assertTrue(all(r['value_PJ'] is None for r in rows if r['value'] is None))

    def test_unknown_tokens_are_rejected(self):
        for token in ('', 'NaN', 'nan', 'inf', '..', '1,234', '1.5', '=1+1'):
            with self.subTest(token=token), self.assertRaises(ValueError):
                apec.value(token)

    def test_geography_year_caption_and_reordered_labels_fail(self):
        for old, new in [('China\t2014', 'Hong Kong\t2014'), ('China\t2014', 'China\t2015'),
                         ('Unit:KTOE', 'Unit:Peta Joule'), ('8.2 LNG', '8.2 Natural gas')]:
            with self.subTest(old=old), self.assertRaises(ValueError):
                apec.parse_table(self.text.replace(old, new, 1), 'Unit:KTOE', self.review)

    def test_output_rows_override_main_unit(self):
        rows = apec.extract(self.ktoe, self.review)
        power = next(r for r in rows if r['source_tsv_line'] == 97 and r['column_role'] == 'total_control')
        heat = next(r for r in rows if r['source_tsv_line'] == 98 and r['column_role'] == 'total_control')
        self.assertEqual((power['unit'], power['value']), ('GWh', 5794457))
        self.assertAlmostEqual(power['value_PJ'], 20860.0452)
        self.assertEqual((heat['unit'], heat['value']), ('ktoe', 103518))
        self.assertAlmostEqual(heat['value_PJ'], 4334.091624)
        bad = copy.deepcopy(self.pj)
        bad[94][71] = str(int(bad[94][71]) + 1)
        with self.assertRaisesRegex(ValueError, 'cross-unit'):
            apec.crosscheck_units(self.ktoe, bad)

    def test_cross_export_missing_or_numeric_corruption_fails(self):
        for c, replacement in [(1, '-'), (2, '0'), (71, '999999')]:
            bad = copy.deepcopy(self.pj)
            bad[1][c] = replacement
            with self.subTest(column=c), self.assertRaises(ValueError):
                apec.crosscheck_units(self.ktoe, bad)

    def test_total_nonenergy_and_final_sectors_are_separate(self):
        checks = apec.accounting_checks(self.ktoe)
        self.assertEqual(sum(c['status'].startswith('passed') for c in checks), 57)
        self.assertEqual(sum(c['status'].startswith('not_testable') for c in checks), 468)
        selected = {c['identity']: c for c in checks if c['total_cell'][1] == 71}
        self.assertEqual(selected['energy_and_nonenergy_final']['residual'], 0)
        self.assertEqual(selected['three_final_energy_sectors']['residual'], 0)
        bad = copy.deepcopy(self.ktoe)
        bad[61][71] = bad[60][71]
        with self.assertRaisesRegex(ValueError, 'energy_and_nonenergy'):
            apec.accounting_checks(bad)

    def test_statistical_discrepancy_cannot_disappear_into_demand(self):
        bad = copy.deepcopy(self.ktoe)
        bad[59][71] = '0'
        with self.assertRaisesRegex(ValueError, 'supply_to_final'):
            apec.accounting_checks(bad)

    def test_hierarchy_avoids_double_counting_and_missing_not_passed(self):
        self.assertNotIn(50, apec.TOP_COLUMNS)
        self.assertNotIn(72, apec.TOP_COLUMNS)
        self.assertNotIn(43, apec.TOP_COLUMNS)
        self.assertIn(42, apec.TOP_COLUMNS)
        item = apec.check_identity(self.ktoe, 'missing', (1, 71), [(1, 2)])
        self.assertEqual(item['status'], 'not_testable_unresolved_symbol')
        self.assertIsNone(item['residual'])

    def test_missing_final_energy_has_joint_bounds_not_zero_fill(self):
        rows = apec.final_energy_bounds(self.ktoe)
        self.assertEqual(len(rows), 54)
        expected = {65:(10,5.5),79:(12,3.5),86:(9,5.5)}
        for line, (count, upper) in expected.items():
            sector = [r for r in rows if r['source_tsv_line'] == line]
            missing = [r for r in sector if r['status']=='bounded_unassigned_missing']
            self.assertEqual(len(missing), count)
            self.assertTrue(all(r['reported_value'] is None for r in missing))
            self.assertEqual({r['missing_group_sum_upper'] for r in sector}, {upper})
            self.assertEqual(len({r['missing_group'] for r in missing}), 1)
            # Equal allocation is one feasible witness, not an imputation made
            # by the extractor. Independent upper bounds cannot all be spent.
            self.assertGreater(sum(r['individual_upper'] for r in missing), upper)

    def test_impossible_or_signed_final_use_does_not_get_forced_closed(self):
        for replacement in ('-1', '99999999'):
            bad = copy.deepcopy(self.ktoe)
            bad[62][1] = replacement
            with self.subTest(replacement=replacement), self.assertRaises(ValueError):
                apec.final_energy_bounds(bad)
        bad = copy.deepcopy(self.ktoe)
        bad[62][71] = '-'
        with self.assertRaises(ValueError): apec.final_energy_bounds(bad)


class CoalBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.review = json.loads((ROOT/'data/catalog/q2_coal_bridge_review.json').read_text(encoding='utf-8'))
        with (ROOT/'data/processed/q2/national_balance_2014_reference.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.cells = {r['source_cell']: r for r in csv.DictReader(f)}
        with (ROOT/'data/processed/q2/nbs2014_accounts.csv').open(encoding='utf-8-sig', newline='') as f:
            cls.nbs = {(r['table'], r['account']): r for r in csv.DictReader(f)}

    def test_original_raw_coal_mismatch_is_category_error(self):
        rows = coal.bridge(self.cells, self.nbs, self.review['mappings'])
        self.assertEqual(len(rows), 15)
        power = rows[0]
        self.assertEqual(power['ceads_value'], 184525.3)
        self.assertEqual(power['difference_ceads_minus_nbs'], 0)
        bad = copy.deepcopy(self.review['mappings'][:1])
        bad[0]['ceads_cells'] = ['B54']
        with self.assertRaisesRegex(ValueError, 'rounding'):
            coal.bridge(self.cells, self.nbs, bad)

    def test_merged_gangue_is_not_silently_added_to_nbs_coal(self):
        bad = copy.deepcopy(self.review['mappings'][:1])
        bad[0]['ceads_cells'].append('E54')
        with self.assertRaisesRegex(ValueError, 'rounding'):
            coal.bridge(self.cells, self.nbs, bad)

    def test_missing_wrong_unit_and_duplicate_cells_rejected(self):
        for field, replacement in [('value', ''), ('unit_as_published', '104 tce')]:
            bad = copy.deepcopy(self.cells)
            bad['B54'][field] = replacement
            with self.subTest(field=field), self.assertRaises(ValueError):
                coal.bridge(bad, self.nbs, self.review['mappings'])
        bad = copy.deepcopy(self.review['mappings'][:1])
        bad[0]['ceads_cells'].append('B54')
        with self.assertRaisesRegex(ValueError, 'repeated'):
            coal.bridge(self.cells, self.nbs, bad)


if __name__ == '__main__': unittest.main()
