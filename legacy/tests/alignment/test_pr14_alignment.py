"""Run in a fresh interpreter: unittest discover -s tests/alignment."""
from copy import deepcopy
import csv
import importlib.util
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import run_q3_pr14 as current
from energy_model.q2_national import operate_national as annual_dispatch
from energy_model.q2_forward_current import ForwardModel
from q3_pr14.dispatch import operate_national as event_dispatch
from q3_pr14.events import run_event, interaction
from q3_pr14.services import service_key
from q3_pr14.transition import worst_service


class AlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=current.preflight()
        cls.model=current.make_model(cls.config,{}).run(2060)
        cls.snapshot=cls.model.snapshots[2030]
        cls.events={s:run_event(cls.snapshot,cls.config,s) for s in ('S0','SG','SW','SGW')}

    def test_all_s0_years_fields_and_discrete_values_match_pr14(self):
        result=current.baseline_check(self.model.paths,self.config)
        self.assertTrue(result['passed'])
        self.assertGreater(result['numeric_fields'],3000)
        self.assertEqual([p['year'] for p in self.model.paths],list(range(2025,2061)))

    def test_baseline_comparator_rejects_missing_extra_and_changed_fields(self):
        for mode in ('missing','extra','value','year'):
            paths=deepcopy(self.model.paths)
            if mode=='missing':paths[0].pop('positive_co2_t')
            if mode=='extra':paths[0]['invented_field']=0
            if mode=='value':paths[0]['positive_co2_t']+=1
            if mode=='year':paths[0]['year']=2026
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                current.baseline_check(paths,self.config)

    def test_event_extension_is_exact_native_dispatch_when_cyclic(self):
        op=deepcopy(self.snapshot['operation'])
        self.assertEqual(annual_dispatch(op),event_dispatch(op))

    def test_all_stores_and_fuels_are_continuous_across_days(self):
        for event in self.events.values():
            rows=event['rows']
            for kind,key in (('fuel','fuel'),('additional_storage','store')):
                for name in {r[key] for r in rows[kind]}:
                    seq=[r for r in rows[kind] if r[key]==name]
                    self.assertEqual(len(seq),48)
                    for a,b in zip(seq,seq[1:]):
                        opening=(b['closing_mwh']-b['fill_mwh']+b['withdrawal_mwh']
                                 if kind=='fuel' else b['opening_mwh'])
                        self.assertAlmostEqual(a['closing_mwh'],opening,places=5)
            for a,b in zip(rows['storage'],rows['storage'][1:]):
                self.assertAlmostEqual(a['closing_mwh'],b['opening_mwh'],places=5)
            self.assertIn('pumped_hydro',event['terminal_additional_soc'])
            self.assertLessEqual(event['max_residual'],1e-6)

    def test_additional_storage_terminal_value_included(self):
        base=self.snapshot['operation'];event=self.events['SGW']
        value=sum((p['initial_mwh']-event['terminal_stocks'][f])*p['domestic_cost_per_mwh'] for f,p in base['fuels'].items())
        value+=(base['storage']['initial_mwh']-event['terminal_soc'])*self.snapshot['electricity_value']
        value+=sum((p['initial_mwh']-event['terminal_additional_soc'][k])*self.snapshot['electricity_value'] for k,p in base['additional_storage'].items())
        self.assertAlmostEqual(value,event['stock_value_adjustment_cny'],places=3)

    def test_nonenergy_services_do_not_dilute_each_other(self):
        rows=[dict(sector='nonenergy_feedstock',carrier='coal',requested_service_mwh=1000,unmet_service_mwh=0),
              dict(sector='nonenergy_feedstock',carrier='gas',requested_service_mwh=1,unmet_service_mwh=1)]
        self.assertEqual(worst_service({},dict(demand=rows)),1)
        self.assertNotEqual(service_key(rows[0]),service_key(rows[1]))
        self.assertIn('nonenergy_feedstock/gas',{r['service'] for r in self.events['S0']['metrics']})

    def test_no_shock_is_identity_and_snapshot_is_immutable(self):
        before=deepcopy(self.snapshot);cfg=deepcopy(self.config)
        cfg['event'].update(gas_loss_fraction=0,wind_factor=1,solar_factor=1,hydro_factor=1)
        a=run_event(before,cfg,'S0');b=run_event(before,cfg,'SGW')
        self.assertEqual(a['rows'],b['rows']);self.assertEqual(before,self.snapshot)

    def test_gas_shock_targets_import_only(self):
        for a,b in zip(self.events['S0']['rows']['sources'],self.events['SG']['rows']['sources']):
            self.assertEqual(a['domestic_mw'],b['domestic_mw'])
            self.assertEqual(a['other_import_mw'],b['other_import_mw'])
        self.assertLess(min(r['available_mw'] for r in self.events['SG']['rows']['sources']),
                        min(r['available_mw'] for r in self.events['S0']['rows']['sources']))

    def test_frozen_gas_has_same_snapshot_and_never_adds_output(self):
        ref=self.events['S0'];frozen=run_event(self.snapshot,self.config,'SGW',frozen_gas=ref['gas_response'])
        self.assertEqual(ref['snapshot_hash'],frozen['snapshot_hash'])
        self.assertTrue(all(a<=b+1e-4 for a,b in zip(frozen['gas_response'],ref['gas_response'])))

    def test_biomass_fossil_carbon_preserved(self):
        event=self.events['S0'];ef=self.snapshot['operation']['fuels']['biomass']['emission_t_per_mwh']
        self.assertGreater(ef,0)
        for row in event['rows']['fuel']:
            if row['fuel']=='biomass':
                self.assertAlmostEqual(row['combustion_co2_t'],(row['direct_mwh']+row['conversion_mwh'])*ef,places=4)

    def test_retirement_dates_affect_pr14_capacity_and_keep_natural_life(self):
        options=dict(vR=.02,vE=.25,delay=1,rule='rolling_guard')
        model=current.make_model(self.config,dict(h01=options)).run(2035)
        managed=[c for c in model.cohorts if 'q3_exit' in c]
        self.assertTrue(managed)
        self.assertTrue(model.retirement_log)
        for c in managed:
            self.assertEqual(c['exit_year'],c['q3_exit'])
            self.assertLessEqual(c['exit_year'],c['q3_natural_exit'])
            self.assertLessEqual(c['exit_year'],c['q3_due']+3)
        exits=[r for r in model.retirement_log if r['action']=='early_retired']
        self.assertTrue(all(r['year']<r['natural_exit'] for r in exits))
        self.assertAlmostEqual(sum(r['capacity_mw'] for r in exits),model.retired_early_mw)
        cohort=next(c for c in managed if c['status']=='retired')
        year=cohort['exit_year'];original=model.generation_capacity('coal',year)
        cohort['exit_year']=cohort['q3_natural_exit']
        if cohort['exit_year']>year:
            self.assertGreater(model.generation_capacity('coal',year),original)

    def test_fixed_projects_shift_only_the_original_clean_queue(self):
        options=dict(vR=.02,vE=.25,delay=3,rule='schedule')
        ref=current.make_model(self.config,{})
        model=current.make_model(self.config,dict(h01=options,fixed_pipeline=True))
        self.assertEqual([p['id'] for p in ref.projects],[p['id'] for p in model.projects])
        for a,b in zip(ref.projects,model.projects):
            self.assertEqual(b['online_year']-a['online_year'],3 if a['tech'] in ('wind','solar','hydro','nuclear') else 0)

    def test_paid_policy_respects_budget_and_construction_lag(self):
        model=current.make_model(self.config,dict(policy=['storage','gas'])).run(2027)
        self.assertTrue(model.public_ledger)
        for row in model.public_ledger:
            self.assertGreater(row['online'],row['decision'])
            self.assertLessEqual(row['amount_cny'],row['budget_cny']+.01)
        for row in model.paths:
            self.assertLessEqual(row['q3_public_commitment_cny'],row['q3_public_budget_cny']+.01)
        self.assertTrue(any(r['kind']=='q3_public_construction' for r in model.finance))

    def test_original_case_grid_and_thresholds_retained(self):
        old=current.load(ROOT/'workflow/q3_inputs.json')
        self.assertEqual(current.protocol.case_specs(old),current.protocol.case_specs(self.config))
        self.assertEqual(len(current.protocol.case_specs(self.config)),187)
        for key in ('h01','policy','event','search','scenarios','information'):
            self.assertEqual(old[key],self.config[key])

    def test_pr14_factory_classification_is_not_raw_record_label(self):
        model=current.make_model(self.config,{})
        self.assertAlmostEqual(model.data[2024,'oil_electricity_mwh']/1e6,9.449634196584221)
        self.assertEqual(model.initial_capacities['hydro'],376830)
        self.assertEqual(model.operating_boundary.stores['pumped_hydro']['operation']['power_mw'],58690)

    def test_current_q1_preserves_indicator_bytes_and_original_values(self):
        old=ROOT/'outputs/q1/p1_yx';new=ROOT/'outputs/q1/pr14_aligned'
        self.assertEqual((old/'indicators.csv').read_bytes(),(new/'indicators.csv').read_bytes())
        def read(p):
            with p.open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
        a=read(old/'history.csv');b=read(new/'history.csv')
        self.assertEqual(len(a),2176);self.assertEqual(len(a),len(b))
        for x,y in zip(a,b):
            for key in set(x)-{'variable','boundary'}:
                self.assertEqual(x[key],y[key])
        self.assertEqual(sum(x['variable']!=y['variable'] for x,y in zip(a,b)),21)


if __name__=='__main__':
    unittest.main()
