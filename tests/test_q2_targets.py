import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
from energy_model.q2.annual import EnergyModel
from energy_model.q2.experiments import metric_rows
from energy_model.q2.targets import national_report
from q2_cases import annual_case
from test_q2_experiments import definitions


def fixture():
    # Hand-calculable accounting fixture; these are not national observations.
    boundary='synthetic_common_CO2_inventory';energy='synthetic_primary_accounting'
    model={'start_year':2024,'end_year':2060,'gdp_growth':{str(y):0. for y in range(2025,2061)}}
    spec={'primary_energy_boundary':energy,'co2_boundary':boundary,'gdp_basis':'fixture_real_index',
          'accounting_review_reference':'synthetic fixture only',
          'metric_bindings':{k:{'indicator':k} for k in ('primary_energy_mtce','nonfossil_primary_mtce','gross_energy_co2_mt','captured_co2_mt')},
          'gdp_base':{'year':2024,'value':100.,'basis':'fixture_real_index','source_or_assumption':'fixture'},
          'nonenergy_and_removal_path':[{'year':y,'co2_boundary':boundary,'unit':'Mt CO2','nonenergy_positive_co2_mt':10.,
                                       'net_removals_co2_mt':5.,'source_or_assumption':'fixture'} for y in range(2024,2061)],
          'historical_anchors':[{'year':y,'primary_energy_mtce':100.,'positive_co2_mt':100.,'gdp_real':50.,
                                 'primary_energy_boundary':energy,'co2_boundary':boundary,'gdp_basis':'fixture_real_index',
                                 'source_or_assumption':'fixture'} for y in range(2005,2024)],'policy_targets':[]}
    for year,indicator,threshold,op in [(2030,'nonfossil_primary_share',.25,'ge'),(2060,'nonfossil_primary_share',.8,'ge'),
            (2030,'carbon_intensity_reduction_vs_2005',.65,'gt'),(2030,'carbon_intensity_reduction_vs_2025',.17,'ge'),
            (2030,'sustained_peak_year',2030,'le'),(2060,'net_co2_mt',0.,'le')]:
        spec['policy_targets'].append({'year':year,'indicator':indicator,'threshold':threshold,'comparison':op,
             'unit':'year' if indicator=='sustained_peak_year' else 'Mt CO2' if indicator=='net_co2_mt' else 'fraction',
             'boundary':energy if indicator=='nonfossil_primary_share' else boundary,
             'source_id':'synthetic target','source_locator':'test fixture; no policy admission'})
    rows=[]
    for y in range(2024,2061):
        for k,v in [('primary_energy_mtce',100.),('nonfossil_primary_mtce',25.),
                    ('gross_energy_co2_mt',90.-(y-2024)),('captured_co2_mt',10.)]:
            rows.append({'year':y,'indicator':k,'value':v,'unit':'Mtce' if 'primary' in k else 'Mt CO2',
                         'boundary':energy if 'primary' in k else boundary})
    criteria={'minimum_following_years':5,'maximum_rebound_fraction':0.,'minimum_final_decline_fraction':.01}
    return rows,model,spec,criteria


class Q2TargetTests(unittest.TestCase):
    def run_fixture(self,items):return national_report(*items)

    def test_all_outputs_capture_once_and_two_distinct_intensity_baselines(self):
        r=self.run_fixture(fixture());year=next(y for y in r['annual'] if y['year']==2030)
        self.assertEqual(year['positive_co2_mt'],84.)
        self.assertEqual(year['net_co2_mt'],79.)
        self.assertAlmostEqual(year['neutralization_ratio'],5/84)
        self.assertAlmostEqual(year['carbon_intensity_reduction_vs_2005'],.58)
        self.assertAlmostEqual(year['carbon_intensity_reduction_vs_2025'],1-84/89)
        self.assertEqual(len(r['annual']),37);self.assertEqual(len(r['indicators']),22)
        self.assertEqual(r['peak']['peak_year'],2023)
        self.assertTrue(r['accounting_complete'])
        self.assertTrue(r['all_target_comparisons_determined'])
        self.assertFalse(next(t for t in r['targets'] if t['indicator']=='net_co2_mt')['target_met'])

    def test_gdp_sensitivity_changes_report_using_actual_model_driver(self):
        values=fixture();base=self.run_fixture(values)
        values[1]['gdp_growth']={str(y):.02 for y in range(2025,2061)}
        changed=self.run_fixture(values)
        self.assertAlmostEqual(changed['annual'][-1]['gdp_real'],100*1.02**36)
        self.assertLess(changed['annual'][-1]['energy_intensity'],base['annual'][-1]['energy_intensity'])

    def test_accounting_boundary_units_missing_and_overlapping_history_rejected(self):
        for mode in ('co2e','missing_removal','wrong_unit','overlap_history','missing_metric','bad_share','duplicate_metric'):
            x=fixture()
            if mode=='co2e':x[2]['nonenergy_and_removal_path'][0]['co2_boundary']='GHG CO2e'
            elif mode=='missing_removal':x[2]['nonenergy_and_removal_path'][0]['net_removals_co2_mt']=None
            elif mode=='wrong_unit':x[0][0]['unit']='MWh'
            elif mode=='overlap_history':x[2]['historical_anchors'][-1]['year']=2024
            elif mode=='missing_metric':x[0].pop()
            elif mode=='bad_share':x[0][1]['value']=101.
            else:x[0].append(deepcopy(x[0][0]))
            with self.subTest(mode=mode),self.assertRaises(ValueError):self.run_fixture(x)

    def test_target_threshold_not_used_to_change_path(self):
        x=fixture();base=self.run_fixture(x)
        for t in x[2]['policy_targets']:t['threshold']*=2
        changed=self.run_fixture(x)
        self.assertEqual(base['annual'],changed['annual']);self.assertEqual(base['peak'],changed['peak'])

    def test_late_peak_is_failure_of_2030_criterion_not_false_missing_input(self):
        x=fixture()
        for row in x[0]:
            if row['indicator']=='gross_energy_co2_mt':row['value']=100.+row['year']-2024
        r=self.run_fixture(x)
        p=next(t for t in r['targets'] if t['indicator']=='sustained_peak_year')
        self.assertIsNone(p['value']);self.assertIs(p['target_met'],False)
        self.assertEqual(p['status'],'insufficient_following_years')

    def test_zero_positive_emissions_keeps_undefined_ratio_but_reports_net_emissions(self):
        x=fixture()
        for row in x[0]:
            if 'co2' in row['indicator']:row['value']=0.
        for row in x[2]['nonenergy_and_removal_path']:row['nonenergy_positive_co2_mt']=0.
        r=self.run_fixture(x)
        self.assertIsNone(r['annual'][-1]['neutralization_ratio'])
        self.assertEqual(r['annual'][-1]['net_co2_mt'],-5.)
        self.assertTrue(next(t for t in r['targets'] if t['indicator']=='net_co2_mt')['target_met'])

    def test_missing_policy_target_or_carbon_boundary_is_not_accepted(self):
        x=fixture();x[2]['policy_targets'].pop()
        with self.assertRaisesRegex(ValueError,'complete'):self.run_fixture(x)
        x=fixture();x[2]['policy_targets'][-1]['boundary']='GHG CO2e'
        with self.assertRaisesRegex(ValueError,'Policy target unit/boundary'):self.run_fixture(x)

    def test_missing_component_is_not_a_valid_zero_metric(self):
        r=EnergyModel(annual_case()).run();d=definitions()
        d[2]['numerator'][0]['ids']=['nonexistent_plant']
        with self.assertRaisesRegex(ValueError,'absent'):metric_rows(r,d)
        d=definitions();d[0]['numerator']=[{'kind':'flow','flow_kind':'source','ids':['typo'],'coefficient':1.}]
        with self.assertRaisesRegex(ValueError,'absent'):metric_rows(r,d)
        d=definitions();d[0]['numerator']=[]
        with self.assertRaisesRegex(ValueError,'Empty metric'):metric_rows(r,d)


if __name__=='__main__':unittest.main()
