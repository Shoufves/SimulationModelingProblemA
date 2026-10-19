"""Guard units, reference scope, source signs and training-only model selection."""
import contextlib
import io
import json
import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import build_q2_fuel_candidate as builder
import prepare_q2_national_balance as balance
import run_q2_historical_candidate as runner


class Q2FuelMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _, cls.data = runner.load_frozen(ROOT/'workflow/q2_candidates/v5/manifest.json')

    def test_physical_gas_conversion_and_only_demand_changes(self):
        gas_input,_ = builder.references()
        # Billion/cubic metre scale mistakes change this by orders of magnitude.
        self.assertAlmostEqual(gas_input,228.2*1e8*38.931/3600,delta=1e-6)
        original = deepcopy(self.data['structural_models']['capacity_share_control'])
        changed = deepcopy(self.data['structural_models']['gas_power_input_reference'])
        before = next(s for s in original['operation']['services'] if s['id']=='gas_residual')
        after = next(s for s in changed['operation']['services'] if s['id']=='gas_residual')
        annual = sum(d*w for d,w in zip(after['demand'],changed['operation']['annual_weights']))
        self.assertAlmostEqual(annual+gas_input,self.data['initialization']['primary_fuel_MWh_equivalent']['gas'],delta=1e-5)
        self.assertGreater(sum(after['demand']),sum(before['demand']))
        after['demand']=before['demand']
        self.assertEqual(original,changed)

    def test_upstream_selection_is_training_only_and_acceptance_unchanged(self):
        data,model,parent,selection = builder.load_parent()
        self.assertEqual(selection['structure'],'stage_schedule')
        self.assertEqual(self.data['acceptance'],data['acceptance'])
        self.assertEqual(self.data['experiment']['targets'],data['experiment']['targets'])
        for c in self.data['structural_models'].values():
            for name in ('investment_options','investment_groups','initial_projects','assets','policies'):
                self.assertEqual(c[name],model[name])
        self.assertEqual(len(self.data['experiment']['parameters']),3)
        self.assertTrue(all(p['bounds']==[0.,2.] for p in self.data['experiment']['parameters']))

    def test_holdout_cannot_select_fuel_response_or_initialization(self):
        a=deepcopy(self.data)
        for p in a['experiment']['parameters']: p['grid']=[1.]
        b=deepcopy(a)
        for r in b['observations']:
            if r['year']>=2022: r['value']*=1000
        with contextlib.redirect_stdout(io.StringIO()):
            left,right=runner.train_candidates(a),runner.train_candidates(b)
        self.assertEqual(left,right)
        self.assertEqual(len(left),6)
        self.assertTrue(all(t['status']=='valid' for t in left))

    def test_carrier_response_can_change_without_other_demands(self):
        a=deepcopy(self.data['model']);a['end_year']=2015
        b=deepcopy(a);b['demand_drivers']['gas_residual']['gdp_elasticity']=2.
        # Check engine activity state directly, independent of dispatch merit.
        ma,mb=runner.EnergyModel(a),runner.EnergyModel(b)
        ma.run();mb.run()
        for service in ma.activities:
            if service=='gas_residual': self.assertGreater(mb.activities[service],ma.activities[service])
            else: self.assertEqual(mb.activities[service],ma.activities[service])


class Q2NationalBalanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import openpyxl
        except ImportError:
            raise unittest.SkipTest('Optional original-XLSX extraction requires requirements-q2-data.txt')
        cls.openpyxl=openpyxl
        cls.review=json.loads((ROOT/'data/catalog/q2_national_balance_review.json').read_text(encoding='utf-8'))

    def sheet(self):
        self.book=self.openpyxl.load_workbook(ROOT/self.review['source_path'],data_only=False)
        self.addCleanup(self.book.close)
        return self.book['2014']

    def test_actual_source_signs_memos_and_controls(self):
        rows,checks=balance.extract(self.sheet(),self.review)
        cells={r['source_cell']:r for r in rows}
        self.assertEqual(len(rows),1260);self.assertEqual(len(checks),60)
        self.assertTrue(all(c['passed'] for c in checks))
        self.assertEqual(cells['T54']['value'],-42686.5)
        self.assertEqual(cells['F60']['row_role'],'memo_not_additive')
        self.assertEqual(cells['R67']['row_role'],'memo_not_additive')
        self.assertEqual(cells['R65']['value'],1509.8)
        self.assertEqual(cells['R63']['value'],20.3)
        self.assertNotEqual(cells['R65']['value'],1868.94)

    def test_formula_is_not_replaced_by_a_cached_number(self):
        sheet=self.sheet();sheet['R54']='=1+1'
        with self.assertRaisesRegex(ValueError,'Formula'):
            balance.extract(sheet,self.review)

    def test_missing_detail_does_not_become_zero(self):
        sheet=self.sheet();sheet['R54']=None
        with self.assertRaisesRegex(ValueError,'missing'):
            balance.extract(sheet,self.review)

    def test_nonadditive_missing_memo_is_preserved(self):
        sheet=self.sheet();sheet['R67']=None
        rows,checks=balance.extract(sheet,self.review)
        record=next(r for r in rows if r['source_cell']=='R67')
        self.assertIsNone(record['value']);self.assertEqual(record['status'],'original_blank')
        self.assertTrue(all(c['passed'] for c in checks))

    def test_wrong_sign_or_unit_fails_before_downstream_mapping(self):
        sheet=self.sheet();sheet['T54']=42686.5
        with self.assertRaisesRegex(ValueError,'arithmetic'):
            balance.extract(sheet,self.review)
        sheet=self.sheet();sheet['R2']='104 tn'
        with self.assertRaisesRegex(ValueError,'unit'):
            balance.extract(sheet,self.review)


if __name__=='__main__':unittest.main()
