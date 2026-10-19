"""Actual usage, service units, and bounded real-input replacement mapping."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import run_q2_device_mapping as episode
from prepare_q2_end_use import normalize
from energy_model.q2.annual import EnergyModel
from q2_cases import annual_case


class ReplacementUsageTests(unittest.TestCase):
    def setup_case(self):
        config=annual_case()
        config['end_year']=2024
        config['policies'][0]['node_prices']['electricity']=1.
        config['investment_options'][1]['device_utilisation_rule']='replaced_device_observed'
        model=EnergyModel(config)
        option=model.config['investment_options'][1]
        component=model.component('device',option['component'])
        flow=dict(kind='device',id='gas_heat',step=0,hours=1.,annual_weight=1.,value=6.)
        return model,option,component,dict(flows=[flow])

    def test_uses_old_dispatch_not_new_default_and_weights_energy_once(self):
        model,option,component,result=self.setup_case()
        self.assertAlmostEqual(model.expected_activity(option,component,result)[1],.006)
        self.assertAlmostEqual(model.margin_per_unit(option,component,model.visible_policy(),result),.018)
        result['flows'][0].update(hours=6.,annual_weight=365.,value=36.)
        model.config['operation']['hours']=[6.]
        model.config['operation']['annual_weights']=[365.]
        hours,usage=model.expected_activity(option,component,result)
        self.assertEqual(hours,2190.)
        self.assertAlmostEqual(usage,.006)

    def test_idle_and_nonoperating_old_stock_has_no_variable_saving(self):
        model,option,component,result=self.setup_case()
        result['flows'][0]['value']=0.
        self.assertEqual(model.margin_per_unit(option,component,model.visible_policy(),result),0.)
        old=next(a for a in model.assets if a['id']=='gas_heat_asset')
        old['state']='standby'
        result['flows'][0]['value']=6.
        self.assertEqual(model.expected_activity(option,component,result)[1],0.)

    def test_uses_total_operating_cohort_stock_and_real_maintenance_factor(self):
        model,option,component,result=self.setup_case()
        old=next(a for a in model.assets if a['id']=='gas_heat_asset')
        other=deepcopy(old);other['id']='second_cohort'
        model.assets.append(other)
        self.assertAlmostEqual(model.expected_activity(option,component,result)[1],.003)
        old.update(state='mothballed',fixed_om_per_unit=100.,lifecycle={
            'maintenance_factors':{'operating':1.,'standby':.5,'mothballed':.1,'retired':0.}})
        self.assertAlmostEqual(model.margin_per_unit(option,component,model.visible_policy(),result),.02)

    def test_missing_duplicate_or_impossible_usage_is_rejected(self):
        model,option,component,result=self.setup_case()
        for flows in ([], result['flows']*2, [dict(result['flows'][0],value=2000.)]):
            with self.subTest(flows=flows), self.assertRaises(ValueError):
                model.expected_activity(option,component,dict(flows=flows))

    def test_invalid_rule_or_nonreplacement_use_is_rejected(self):
        for variant in ('unknown','generator','new_device'):
            config=annual_case()
            if variant=='unknown':config['investment_options'][1]['device_utilisation_rule']='guessed'
            elif variant=='generator':config['investment_options'][0]['device_utilisation_rule']='replaced_device_observed'
            else:
                config['investment_options'][1].update(device_utilisation_rule='replaced_device_observed',replaces=None)
            with self.subTest(variant=variant),self.assertRaises(ValueError):EnergyModel(config)


class ServiceMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent=json.loads((ROOT/'outputs/q2/historical_candidate_v12/selected_model.json').read_text(encoding='utf-8'))
        cls.performance={r['id']:r for r in episode.prepare()}
        cls.reference=episode.residential_oil_reference()

    def test_inverse_transport_intensity_and_thermal_cop(self):
        self.assertEqual(self.performance['building_heat_pump']['service_per_MWh_input'],3.5)
        self.assertEqual(self.performance['petroleum_passenger_car']['service_per_MWh_input'],2250.)
        self.assertAlmostEqual(self.performance['battery_passenger_car']['service_per_MWh_input'],3600/.69)
        self.assertTrue(all(not r['economic_use_admitted'] for r in self.performance.values()))
        with self.assertRaises(ValueError):normalize(dict(performance_value=0.,performance_unit='%'))
        with self.assertRaises(ValueError):normalize(dict(performance_value=1.,performance_unit='MJ/tonne_km'))

    def test_unpartitioned_control_is_not_reported_as_zero_residential_consumption(self):
        self.assertEqual(episode.annual_rows('parent',self.parent,{}),[])

    def test_real_residential_input_and_classification_preserve_fuel(self):
        saved=deepcopy(self.parent)
        model,mapping=episode.split_residential(self.parent,.1,self.reference,self.performance)
        self.assertEqual(saved,self.parent)
        self.assertEqual(self.reference['value_ktoe'],26375.)
        self.assertAlmostEqual(mapping['useful_heat_MWh'],26375*11630*.1*.85)
        op=model['operation']
        old=next(s for s in self.parent['operation']['services'] if s['id']=='oil_residual')
        residual=next(s for s in op['services'] if s['id']=='oil_residual')
        heat=next(s for s in op['services'] if s['id']==episode.SERVICE)
        for before,remainder,useful in zip(old['demand'],residual['demand'],heat['demand']):
            self.assertAlmostEqual(before,remainder+useful/.85,places=7)
        for fraction in (0.,-1.,2.):
            with self.subTest(fraction=fraction),self.assertRaises(ValueError):
                episode.split_residential(self.parent,fraction,self.reference,self.performance)
        with self.assertRaises(ValueError):episode.split_residential(model,.1,self.reference,self.performance)

    def test_offer_conserves_rated_service_and_uses_hypothetical_cost(self):
        split,mapping=episode.split_residential(self.parent,.1,self.reference,self.performance)
        offered,pricing=episode.add_offer(split,mapping,self.performance,'replaced_device_observed',.5)
        option=offered['investment_options'][-1]
        self.assertTrue(offered['mechanisms']['replacement'])
        self.assertAlmostEqual(option['replacement_ratio']*mapping['initial_rated_heat_MW'],1.)
        self.assertAlmostEqual(pricing['observed_utilisation'],.04325)
        self.assertEqual(option['capex_per_unit'],.5*pricing['break_even_capex_million_USD2008_per_MW_heat'])
        self.assertTrue(pricing['cost_is_not_an_observation'])


if __name__=='__main__':unittest.main()
