"""Sector mappings conserve parent inputs; training never selects on holdout."""
import contextlib
from copy import deepcopy
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import build_q2_sector_candidate as builder
import run_q2_sector_candidate as runner


class SectorCandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=builder.build()
        cls.items,cls.bounds=builder.source_reference()
        cls.name=cls.data['experiment']['structural_alternatives'][0]
        cls.parent=cls.data['control_models'][cls.name]
        cls.split=cls.data['structural_models'][cls.name]

    def test_nine_reported_groups_preserve_missing_vs_reported_zero(self):
        self.assertEqual([r['value_ktoe'] for r in self.items],
                         [567527,50933,45462,3086,229170,17949,110973,80204,40917])
        road=next(i for i in self.items if i['id']=='final_transport_oil')
        other=next(i for i in self.items if i['id']=='final_other_oil')
        self.assertEqual(len(road['unresolved_product_cells']),1)
        self.assertEqual(road['unresolved_product_cells'][0]['raw_token'],'-')
        self.assertEqual(other['cells'][0]['raw_token'],'0')
        self.assertEqual([r['missing_top_cells'] for r in self.bounds],[10,12,9])
        self.assertEqual([r['joint_missing_upper_ktoe'] for r in self.bounds],[5.5,3.5,5.5])

    def test_partition_conserves_initial_fuel_capacity_and_money_without_mutation(self):
        before=deepcopy(self.parent)
        split,mappings=builder.partition(self.parent,self.items)
        self.assertEqual(self.parent,before)
        self.assertEqual(split,self.split)
        self.assertEqual(len(runner.initial_checks(self.parent,split)),3)
        self.assertEqual(split['agents'],self.parent['agents'])
        self.assertEqual(split['other_accounts'],self.parent['other_accounts'])
        self.assertEqual(split['initial_projects'],self.parent['initial_projects'])
        self.assertTrue(all(m['remaining_unresolved_MWh']>0 for m in mappings))

    def test_duplicate_missing_and_invalid_sector_inputs_rejected(self):
        for action in ('duplicate','missing','negative','nonfinite','owner','too_large'):
            items=deepcopy(self.items)
            if action=='duplicate': items.append(deepcopy(items[0]))
            if action=='missing': items.pop()
            if action=='negative': items[0]['input_MWh_LHV']=-1
            if action=='nonfinite': items[0]['input_MWh_LHV']=float('nan')
            if action=='owner': items[0]['owner']='transport'
            if action=='too_large': items[0]['input_MWh_LHV']=1e30
            with self.subTest(action=action),self.assertRaises(ValueError):
                builder.partition(self.parent,items)

    def test_different_year_or_twice_partition_not_allowed(self):
        changed=deepcopy(self.parent)
        changed['start_year']=2024
        for model in (changed,self.split):
            with self.assertRaises(ValueError): builder.partition(model,self.items)

    def test_sector_response_does_not_change_other_sectors_or_unresolved_uses(self):
        parameters=self.data['experiment']['parameters']
        values={p['id']:1. for p in parameters}
        base=runner.history.parameterize(self.split,parameters,values)
        values['transport_gdp_response']=2.
        changed=runner.history.parameterize(self.split,parameters,values)
        for service in base['demand_drivers']:
            if service.startswith('final_transport_'):
                self.assertNotEqual(base['demand_drivers'][service],changed['demand_drivers'][service])
            else:
                self.assertEqual(base['demand_drivers'][service],changed['demand_drivers'][service])

    def test_same_growth_classification_has_no_physical_or_proxy_carbon_effect(self):
        parent=runner.history.EnergyModel(self.parent).run()
        split=runner.history.EnergyModel(self.split).run()
        checks=runner.classification_check(self.name,parent,split)
        self.assertEqual(len(checks),11)
        rows=runner.sector_accounts(self.name,self.split,split,self.items)
        self.assertEqual(len(rows),99)
        self.assertTrue(all(r['fuel_payment_million_USD2008']>0 for r in rows))
        self.assertTrue(all(r['useful_service_quantity'] is None for r in rows))

    def test_missing_or_wrong_sector_payment_fails_reconciliation(self):
        result=runner.history.EnergyModel(self.split).run()
        item=next(t for t in result['cash'] if t['reason']=='end_use_purchase' and 'final_industry_oil' in t['reference'])
        item['payer']='transport'
        with self.assertRaisesRegex(ValueError,'wrong account'):
            runner.sector_accounts(self.name,self.split,result,self.items)

    def test_holdout_targets_cannot_change_training_trials_or_winner(self):
        data=deepcopy(self.data)
        names=[data['experiment']['structural_alternatives'][0],data['experiment']['structural_alternatives'][-1]]
        data['experiment']['structural_alternatives']=names
        for key in ('structural_models','control_models'):
            data[key]={name:data[key][name] for name in names}
        for p in data['experiment']['parameters']: p['grid']=[0.,2.]
        changed=deepcopy(data)
        for obs in changed['observations']:
            if obs['year']>=2022: obs['value']*=1000
        with contextlib.redirect_stdout(io.StringIO()):
            before,after=runner.train(data),runner.train(changed)
        self.assertEqual(len(before),18)
        self.assertEqual(before,after)
        self.assertEqual(runner.winners(before,names),runner.winners(after,names))
        self.assertEqual(sum(t['kind']=='unchanged_v10_control' for t in before),2)

    def test_failed_solver_trials_are_retained_and_cannot_be_selected(self):
        data=deepcopy(self.data)
        for p in data['experiment']['parameters']: p['grid']=[0.]
        with patch.object(runner.history,'EnergyModel',side_effect=ValueError('synthetic solver failure')):
            trials=runner.train(data)
        self.assertEqual(len(trials),12)
        self.assertTrue(all(t['status']=='failed' and t['loss'] is None for t in trials))
        with self.assertRaisesRegex(ValueError,'No valid candidate'):
            runner.winners(trials,data['experiment']['structural_alternatives'])

    def test_changed_review_fingerprint_fails_before_output_directory_creation(self):
        target=ROOT/'outputs/q2/sector_should_not_exist'
        self.assertFalse(target.exists())
        with patch.object(builder,'sha',return_value='0'*64):
            with self.assertRaisesRegex(ValueError,'Reviewed sector reference changed'):
                runner.execute(target.relative_to(ROOT).as_posix())
        self.assertFalse(target.exists())

    def test_scope_and_original_carbon_proxy_are_not_promoted(self):
        self.assertEqual(self.split['scope'],'historical_aggregate_candidate_not_admitted')
        self.assertFalse(self.data['initialization']['national_admission'])
        self.assertIn('not the partial-carbon',self.data['experiment']['carbon_accounting'])
        for carrier in builder.PRODUCTS:
            before=next(d for d in self.parent['operation']['devices'] if d['id']==carrier+'_residual_device')
            after=[d for d in self.split['operation']['devices'] if d['node']==carrier]
            self.assertTrue(all(d['gross_co2_t_per_mwh']==before['gross_co2_t_per_mwh'] for d in after))


if __name__=='__main__': unittest.main()
