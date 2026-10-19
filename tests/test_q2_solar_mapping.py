"""Source timing, shared ceilings, inherited controls and holdout isolation."""
import contextlib
import io
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import build_q2_solar_candidate as builder
import run_q2_historical_candidate as history


class Q2SolarMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=builder.build()

    def test_information_precedes_application_and_commissioning(self):
        model=deepcopy(self.data['structural_models']['date_and_resource_ceiling'])
        model['end_year']=2016
        result=history.EnergyModel(history.rule_model(model,'instant_margin')).run()
        self.assertFalse(any(a.get('option')=='solar_new_build' and a['year']==2014 for a in result['actions']))
        approved=[a for a in result['actions'] if a.get('option')=='solar_new_build' and a.get('approved_units',0)>0]
        self.assertEqual(approved[0]['year'],2015)
        self.assertEqual(approved[0]['online_year'],2016)
        self.assertFalse(any(a['component']=='solar_new_power' and a['year']<2016 for a in result['assets']))

    def test_resource_bound_does_not_expand_annual_limits_or_cash(self):
        parent=self.data['structural_models']['v5_control']
        corrected=self.data['structural_models']['date_and_resource_ceiling']
        for field in ('assets','initial_projects','agents','other_accounts','policies','operation','gdp_growth'):
            self.assertEqual(parent[field],corrected[field])
        model=history.EnergyModel(corrected)
        group=next(g for g in corrected['investment_groups'] if g['id']=='solar_construction')
        annual,headroom=model.group_limits(group)
        self.assertAlmostEqual(annual,16340.)
        self.assertAlmostEqual(headroom,2200000.-24860.)
        option=next(o for o in corrected['investment_options'] if o['id']=='solar_new_build')
        self.assertAlmostEqual(model.installation_limit(option),annual)
        self.assertTrue(all(o['maximum_total_units']==2200000. for o in corrected['investment_options']
                            if o.get('investment_group')=='solar_construction'))

    def test_control_exactly_preserves_parent_selected_parameter_model(self):
        _,model,_,_=builder.load_parent()
        self.assertEqual(self.data['structural_models']['v5_control'],model)
        self.assertEqual(self.data['experiment']['parameters'],[])
        self.assertEqual(self.data['experiment']['maximum_evaluations'],1)

    def test_alternatives_do_not_share_mutable_ceiling_or_date(self):
        data=deepcopy(self.data)
        group=data['structural_models']['date_and_resource_ceiling']['investment_groups'][1]
        group['maximum_total_units']=1.
        self.assertEqual(data['structural_models']['date_only']['investment_groups'][1]['maximum_total_units'],497200.)
        self.assertEqual(data['structural_models']['resource_ceiling_only']['investment_groups'][1]['maximum_total_units'],2200000.)

    def test_holdout_cannot_choose_structure_or_rule(self):
        changed=deepcopy(self.data)
        for row in changed['observations']:
            if row['year']>=2022: row['value']*=100
        with contextlib.redirect_stdout(io.StringIO()):
            original=history.train_candidates(self.data)
            perturbed=history.train_candidates(changed)
        self.assertEqual(original,perturbed)
        self.assertEqual(len(original),12)
        self.assertTrue(all(r['status']=='valid' for r in original))

    def test_changed_original_is_rejected(self):
        with patch.object(builder,'sha',return_value='tampered'):
            with self.assertRaisesRegex(ValueError,'Solar reference changed'):
                builder.references()


if __name__=='__main__':
    unittest.main()
