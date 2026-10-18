"""Q1 boundary/counterexample tests. Synthetic fixtures are never national observations."""
import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'scripts'))
from energy_model.q1 import finite, ratio, annual_log_volatility, compound_index, spatial_difference, concentration
import build_q1 as q1
from q1_additional_analysis import derive, synthesize
from audit_workspace import is_external_history


class Q1MathTests(unittest.TestCase):
    def test_unknown_and_nonfinite_are_not_zero(self):
        for value in (None,'',True,float('nan'),float('inf')):
            with self.subTest(value=value),self.assertRaises(ValueError):finite(value)

    def test_net_export_can_be_negative_but_denominator_positive(self):
        self.assertEqual(ratio(-2,100),-2)
        for d in (0,-1,None):
            with self.assertRaises(ValueError):ratio(1,d)

    def test_log_returns_do_not_bridge_a_missing_year(self):
        r=annual_log_volatility({2015:100,2016:110,2018:121,2019:121})
        self.assertEqual(r['adjacent_pairs'],[(2015,2016),(2018,2019)])
        self.assertAlmostEqual(r['value'],math.log(1.1)/math.sqrt(2))
        self.assertIn(2017,r['missing_years'])

    def test_prices_ignore_out_of_window_and_reject_nonpositive(self):
        self.assertIsNone(annual_log_volatility({2014:12,2015:10,2016:15,2025:20})['value'])
        with self.assertRaises(ValueError):annual_log_volatility({2015:0,2016:15})

    def test_regional_distance_is_scale_invariant_and_symmetric(self):
        a={'A':90,'B':10};b={'A':10,'B':90}
        v,_=spatial_difference(a,b)
        self.assertAlmostEqual(v,.8)
        self.assertAlmostEqual(spatial_difference(b,a)[0],v)
        self.assertAlmostEqual(spatial_difference({'A':9,'B':1},b)[0],v)
        self.assertEqual(spatial_difference(a,a)[0],0)

    def test_region_mismatch_negative_and_zero_total_rejected(self):
        for a,b in [({'A':1},{'B':1}),({'A':-1},{'A':1}),({'A':0},{'A':1}),({}, {})]:
            with self.assertRaises(ValueError):spatial_difference(a,b)

    def test_grouped_hhi_bounds_cover_feasible_country_split(self):
        r=concentration([60,40],100,[False,True])
        self.assertEqual((r['lower'],r['upper']),(3600,5200))
        self.assertIsNone(r['point'])
        split=concentration([60,20,20],100,[False]*3)['point']
        self.assertLessEqual(r['lower'],split);self.assertLessEqual(split,r['upper'])

    def test_zero_regional_bin_does_not_obscure_exact_hhi(self):
        self.assertEqual(concentration([60,40,0],100,[False,False,True])['point'],5200)

    def test_hhi_mismatch_is_not_silently_renormalized(self):
        with self.assertRaises(ValueError):concentration([60,30],100,[False,False])

    def test_real_gdp_is_compounded_and_missing_growth_blocks(self):
        self.assertAlmostEqual(compound_index({2016:10,2017:-10},end=2017)[2017],99)
        with self.assertRaises(ValueError):compound_index({2016:5},end=2017)
        with self.assertRaises(ValueError):compound_index({2016:-100},end=2016)


class Q1InputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=json.loads((ROOT/'workflow/q1_inputs.json').read_text(encoding='utf-8'))
        q1.preflight(cls.config)
        cls.data,cls.history=q1.load_history(cls.config)

    def test_real_selected_price_window_is_explicit(self):
        for var in {r['variable'] for r in self.data['prices']}:
            expected=set(range(2015,2024 if var=='Natural gas, Europe' else 2025))
            self.assertEqual({r['year'] for r in self.data['prices'] if r['variable']==var and r['year']>=2015},expected)
        self.assertTrue(all(r['status'] in ('archived_reference','reviewed_release') for r in self.data['prices']))
        self.assertFalse(any(r['variable']=='Natural gas, Europe' and r['year']==2024 for r in self.data['prices']))

    def test_processing_hash_change_fails(self):
        c=copy.deepcopy(self.config);c['inputs'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'Input hash mismatch'):q1.preflight(c)

    def test_original_hash_change_fails(self):
        c=copy.deepcopy(self.config);next(iter(c['sources'].values()))['artifacts'][0]['sha256']='0'*64
        with self.assertRaisesRegex(ValueError,'Original hash mismatch'):q1.preflight(c)

    def test_input_path_escape_and_restricted_paths_blocked(self):
        for p in ('../outside.csv','data/restricted/anything.csv'):
            with self.assertRaises(ValueError):q1.local_path(p)

    def test_duplicate_observation_is_rejected(self):
        d=copy.deepcopy(self.data);d['national'].append(copy.deepcopy(q1.one(d,'national','consumption_10ktce',2024)))
        with self.assertRaisesRegex(ValueError,'Expected one'):q1.calculate(d)

    def test_wrong_regional_electricity_unit_is_rejected(self):
        d=copy.deepcopy(self.data);d['region_generation'][0]['unit']='TWh'
        with self.assertRaisesRegex(ValueError,'unit mismatch'):q1.calculate(d)

    def test_missing_province_is_rejected(self):
        d=copy.deepcopy(self.data);d['region_generation'].pop()
        with self.assertRaisesRegex(ValueError,'31 unique'):q1.calculate(d)

    def test_regional_resource_unit_is_not_silently_converted(self):
        d=copy.deepcopy(self.data);d['regional_resources'][0]['unit']='10^4 t'
        with self.assertRaisesRegex(ValueError,'resource selection/unit'):q1.calculate(d)

    def test_handoff_has_numeric_values_and_price_effective_years(self):
        inds,*_=q1.calculate(self.data)
        for r in inds:
            if r['indicator_id'].startswith('price_log_volatility_'):
                end=2024 if r['indicator_id'].endswith('Natural gas, Europe') else 2025
                self.assertEqual(r['effective_years'],';'.join(map(str,range(2015,end))))
        _,handoff=q1.handoff(self.history,inds)
        rows=[r for r in handoff if r['record_kind']=='numeric_observation_candidate']
        self.assertTrue(rows)
        self.assertTrue(all(r['value'] is not None and r['unit'] and r['candidate_refs'] for r in rows))

    def test_trade_year_mismatch_rejected(self):
        d=copy.deepcopy(self.data);d['pipeline'][0]['year']=2023
        with self.assertRaisesRegex(ValueError,'denominator mismatch'):q1.calculate(d)

    def test_cost_price_year_projection_and_lifetime_are_required(self):
        for key,value in [('unit','2024 USD/MWh'),('year',2024),('status','observed'),('lifetime_years','60')]:
            d=copy.deepcopy(self.data);d['cost_comparison'][0][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'Cost convention'):q1.calculate(d)

    def test_missing_matched_cost_technology_blocks_group(self):
        d=copy.deepcopy(self.data);d['cost_comparison'].pop()
        with self.assertRaisesRegex(ValueError,'matched cost'):q1.calculate(d)

    def test_published_balance_gap_is_not_a_balancing_plug(self):
        _,checks,_,_,_=q1.calculate(self.data)
        total=next(r for r in checks if r['account']=='total' and r['year']==2023)
        self.assertEqual(total['supply_arithmetic_residual'],0)
        self.assertEqual(total['published_supply_minus_consumption'],15520)
        self.assertEqual(total['published_balance'],15519)
        hydrogen=next(r for r in checks if r['account']=='hydrogen_route_sum')
        self.assertEqual(hydrogen['arithmetic_residual'],-18)

    def test_all_indicator_references_resolve_and_keys_are_unique(self):
        inds,*_=q1.calculate(self.data);inds+=derive(self.data);ids={r['record_id'] for r in self.history}
        self.assertEqual(len(inds),len({(r['indicator_id'],r['year']) for r in inds}))
        self.assertTrue(all(ref in ids for r in inds for ref in r['input_refs'].split(';') if ref))

    def test_additional_generation_units_cannot_silently_mix(self):
        d=copy.deepcopy(self.data)
        next(r for r in d['official2024'] if r['variable']=='generation_hydro')['unit']='TWh'
        with self.assertRaisesRegex(ValueError,'Generation share units'):derive(d)

    def test_regional_quota_exemptions_are_not_failures(self):
        inds=derive(self.data);byid={r['indicator_id']:r for r in inds}
        self.assertEqual(byid['renewable_consumption_share_below_target_count']['value'],3)
        self.assertEqual(byid['nonhydro_renewable_consumption_share_below_target_count']['value'],1)
        for r in self.data['renewable_regions']:
            if r['region'] in ('新疆','西藏'):self.assertFalse(r['variable'].endswith('_minimum'))

    def test_missing_xpcc_distributed_cell_is_not_zero(self):
        rs=[r for r in self.data['technology_regions'] if r['region']=='新疆兵团']
        self.assertEqual({r['variable'] for r in rs},{'pv_capacity','pv_central_capacity'})

    def test_missing_region_blocks_concentration(self):
        d=copy.deepcopy(self.data)
        d['technology_regions']=[r for r in d['technology_regions'] if not(r['variable']=='pv_capacity' and r['region']=='新疆兵团')]
        with self.assertRaisesRegex(ValueError,'region coverage'):derive(d)

    def test_multiyear_costs_and_december_prices_keep_their_scope(self):
        inds=derive(self.data);byid={r['indicator_id']:r for r in inds}
        self.assertEqual(byid['bioenergy_LCOE']['status'],'published_multiyear')
        self.assertIn('2000-2024',byid['bioenergy_LCOE']['boundary'])
        self.assertIn('December',byid['hydrogen_production_price_december']['boundary'])

    def test_hydrogen_lower_threshold_not_exact_total(self):
        inds,balances,*_=q1.calculate(self.data)
        self.assertTrue(next(r for r in balances if r['account']=='hydrogen_route_sum')['reported_is_lower_bound'])
        self.assertEqual(next(r for r in inds if r['indicator_id']=='electrolysis_hydrogen_output_share')['status'],'reference_ratio_to_lower_threshold')

    def test_per_carrier_assessment_and_synergies_have_actual_evidence(self):
        inds,*_=q1.calculate(self.data);inds+=derive(self.data)
        assessment,synergies=synthesize(self.data,self.history,inds)
        self.assertEqual(len(assessment),36);self.assertEqual(len(synergies),8)
        self.assertEqual(len({r['synergy_id'] for r in synergies}),len(synergies))
        self.assertTrue({r['synergy_id'] for r in synergies}.isdisjoint({r['indicator_id'] for r in inds}))
        ids={r['record_id'] for r in self.history}
        for r in assessment+synergies:
            self.assertTrue(r['input_refs'])
            self.assertTrue(set(r['input_refs'].split(';'))<=ids)
        self.assertTrue(all(r['applicable_conditions'] and r['tradeoff_or_failure'] and r['next_model_test'] for r in synergies))


class Q1OutputTests(unittest.TestCase):
    def test_failed_attempt_preserves_previous_output_without_claiming_success(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'outputs/q1/test';out.mkdir(parents=True)
            (out/'report.md').write_text('previous success',encoding='utf-8')
            q1.dump(out/'run_manifest.json',{'owner':'p1/lb','status':'success'})
            (root/'workflow').mkdir()
            q1.dump(root/'workflow/q1_inputs.json',{'inputs':[{'id':'absent','path':'missing.csv','sha256':'0'*64,'source_map':{}}],'sources':{}})
            with patch.object(q1,'ROOT',root):self.assertEqual(q1.run('outputs/q1/test'),1)
            self.assertEqual((out/'report.md').read_text(encoding='utf-8'),'previous success')
            fail=json.loads((out.parent/'test.failed-attempt.json').read_text(encoding='utf-8'))
            self.assertEqual(fail['status'],'failed');self.assertFalse(fail['output_valid_for_this_attempt'])
            self.assertFalse(list(out.parent.glob('.q1-stage-*')))

    def test_unowned_output_and_non_output_path_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=root/'outputs/q1/other';out.mkdir(parents=True)
            (out/'report.md').write_text('other member',encoding='utf-8')
            with patch.object(q1,'ROOT',root):
                for path in ('outputs/q1/other','data/unsafe'):
                    with self.assertRaises(ValueError):q1.run(path)
            self.assertEqual((out/'report.md').read_text(encoding='utf-8'),'other member')


class AuditPortabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=json.loads((ROOT/'archive/organization_20261017/file_disposition.json').read_text(encoding='utf-8'))

    def test_only_six_original_external_duplicates_are_exempt(self):
        self.assertEqual(sum(is_external_history(r) for r in self.rows),6)
        self.assertFalse(any(is_external_history(r) for r in self.rows if r['action']=='protect'))

    def test_exemption_cannot_be_used_for_arbitrary_path_escape(self):
        original=next(r for r in self.rows if is_external_history(r))
        for edits in ({'target':'../B题/../../outside.pdf'},{'action':'protect'},
                      {'sha256':'0'*64},{'target':'../A题/a.pdf'},{'path':'data/raw/important.pdf'}):
            with self.subTest(edits=edits):self.assertFalse(is_external_history(dict(original,**edits)))


if __name__=='__main__':unittest.main()
