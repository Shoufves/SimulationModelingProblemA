import sys
import unittest
from copy import deepcopy
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'tests'))
from energy_model.q2.annual import EnergyModel
from energy_model.q2.experiments import calibration, metric_rows, net_co2, peak_assessment, sensitivity
from q2_cases import annual_case


def historical_case():
    c=annual_case()
    c['start_year']=2014;c['end_year']=2024
    for collection in ('assets','policies','investment_options'):
        for row in c[collection]:
            for k in row:
                if k.endswith('_year') and type(row[k]) is int: row[k]-=10
    c['gdp_growth']={str(y):.02 for y in range(2015,2025)}
    return c


def definitions():
    base={'denominator':None,'unit':'fixture_unit','boundary':'synthetic_engineering_only'}
    return [{**base,'id':'energy','numerator':[{'kind':'annual','field':'primary_mwh','coefficient':1.}]},
            {**base,'id':'nonfossil_share','numerator':[{'kind':'annual','field':'nonfossil_primary_mwh','coefficient':1.}],
             'denominator':[{'kind':'annual','field':'primary_mwh','coefficient':1.}]},
            {**base,'id':'capacity','numerator':[{'kind':'capacity','asset_kind':'process','ids':['solar_power'],'coefficient':1.}]},
            {**base,'id':'co2','numerator':[{'kind':'annual','field':'positive_energy_co2_t','coefficient':1.}]}]


def experiment():
    families=['energy_consumption','primary_mix','capacity_or_generation','co2']
    return {'windows':{'train':[2015,2021],'already_seen_holdout':[2022,2024]},
            'parameters':[{'id':'elasticity','bounds':[.5,1.5],'grid':[.5,1.,1.5],
                           'paths':[['demand_drivers',s,'gdp_elasticity'] for s in ('industry','building','mobility')]}],
            'targets':[{'id':d['id'],'family':family,'scale':1.,'weight':.25,
                        'metric_type':'share_fraction' if family=='primary_mix' else 'total'} for d,family in zip(definitions(),families)],
            'maximum_evaluations':3,'equivalent_loss_absolute_tolerance':1e-12}


class Q2ExperimentTests(unittest.TestCase):
    def test_grid_calibration_and_holdout_never_select_parameters(self):
        c=historical_case();obs=metric_rows(EnergyModel(c).run(),definitions())
        base=calibration(c,definitions(),obs,experiment())
        self.assertEqual(base['best_parameters'],{'elasticity':1.})
        self.assertAlmostEqual(base['training_loss'],0.)
        changed=deepcopy(obs)
        for r in changed:
            if r['year']>=2022:r['value']*=10.
        other=calibration(c,definitions(),changed,experiment())
        self.assertEqual(base['trials'],other['trials'])
        self.assertEqual(base['best_parameters'],other['best_parameters'])
        self.assertGreater(other['holdout_loss'],base['holdout_loss'])
        self.assertEqual(len(base['baselines']),24)

    def test_boundaries_and_units_are_not_silently_spliced(self):
        c=historical_case();obs=metric_rows(EnergyModel(c).run(),definitions())
        for r in obs:r['boundary']='different_inventory'
        with self.assertRaisesRegex(ValueError,'Every frozen'):calibration(c,definitions(),obs,experiment())

    def test_actual_three_factor_sensitivity(self):
        c=annual_case()
        factors=[{'id':'gdp_growth','values':[0.,.1],'paths':[['gdp_growth',str(y)] for y in range(2025,2029)]},
                 {'id':'technology_cost_decline','values':[0.,.1],'paths':[['cost_decline','solar_build']]},
                 {'id':'carbon_price','values':[0.,20.],'paths':[['policies',0,'carbon_price_per_t']]}]
        for f in factors:f.update(rationale='engineering switch test',source_or_assumption='synthetic fixture')
        rows=sensitivity(c,definitions(),factors)
        self.assertEqual(len({r['case'] for r in rows}),8)
        self.assertTrue(all(r['status']=='optimal' for r in rows))
        self.assertGreater(len({r['value'] for r in rows if r['indicator']=='energy' and r['year']==2028}),1)

    def test_peak_terminal_peak_plateau_rebound_and_missing(self):
        assess=lambda v:peak_assessment(v,3,0.,.01)
        self.assertEqual(assess({2020:10.,2021:11.,2022:12.})['status'],'insufficient_following_years')
        self.assertEqual(assess({2020:10.,2021:9.,2022:11.,2023:10.})['peak_year'],None)
        self.assertEqual(assess({2020:10.,2021:9.,2022:8.,2023:7.})['peak_year'],2020)
        self.assertEqual(assess({2020:10.,2021:10.,2022:10.,2023:10.})['peak_year'],None)
        with self.assertRaises(ValueError):assess({2020:10.,2022:8.})

    def test_net_co2_capture_not_removal_and_zero_denominator(self):
        r=net_co2(10.,2.,3.,4.,common_boundary=True)
        self.assertEqual(r['positive_co2'],11.)
        self.assertEqual(r['net_co2'],7.)
        self.assertAlmostEqual(r['neutralization_ratio'],4/11)
        self.assertIsNone(net_co2(0.,0.,0.,2.,common_boundary=True)['neutralization_ratio'])
        with self.assertRaises(ValueError):net_co2(10.,0.,1.,None,common_boundary=True)
        with self.assertRaises(ValueError):net_co2(10.,0.,1.,2.,common_boundary=False)


if __name__=='__main__':unittest.main()
