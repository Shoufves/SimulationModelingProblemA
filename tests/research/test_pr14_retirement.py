"""Run separately: pinned PR14 and current research have different namespaces."""
from pathlib import Path
import sys
import json
from copy import deepcopy
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
PIN=ROOT/'tmp/n2/pr14'
sys.path[:0]=[str(PIN/'src'),str(PIN/'scripts'),str(ROOT/'src')]
import energy_model.q2_national as national
if PIN.resolve() not in Path(national.__file__).resolve().parents:
    raise RuntimeError('Run research tests in a separate process against pinned PR14')
from q2_delivery_snapshot import decode,build_snapshot
from energy_model.q2_forward_current import activate_forward
from run_q2_portable import compare_reference
from transition_research.retirement import activate,RetirementModel,services
from transition_research.anchored import activate as activate_anchored
from transition_research.current_information import activate as activate_current
from energy_model.q2_forward_current import ForwardModel


def feedstock_dispatch_pair():
    """Identical inputs except coal capacity: material shortages trade places."""
    fuel=dict(domestic_mw=[20],import_mw=[0],domestic_cost_per_mwh=1,
              import_cost_per_mwh=1,emission_t_per_mwh=.3,tank_mwh=0,
              initial_mwh=0,injection_mw=0,withdrawal_mw=0)
    plant=dict(input='coal',output='electricity',efficiency=1,capacity_mw=20,
               availability=[1],variable_cost_per_mwh=0,minimum_fraction=0,
               ramp_mw_per_hour=100,window_energy_budget_mwh=20)
    op=dict(periods=[dict(hours=1)],annual_repeats=1,cyclic=True,
            grid=dict(efficiency=1,power_mw=100),
            storage=dict(power_mw=0,energy_mwh=0,initial_mwh=0,
                         charge_efficiency=1,discharge_efficiency=1,throughput_cost=0),
            fuels=dict(coal=deepcopy(fuel),gas=deepcopy(fuel)),
            plants=dict(coal=deepcopy(plant),gas={**plant,'input':'gas','variable_cost_per_mwh':10}),
            demands=dict(building=dict(sector='building',carrier='electricity',efficiency=1,
                                       input_capacity_mw=20,priority=0,service_mwh=[20]),
                         coal_material=dict(sector='nonenergy_feedstock',carrier='coal',efficiency=1,
                                            input_capacity_mw=20,priority=1,service_mwh=[20]),
                         gas_material=dict(sector='nonenergy_feedstock',carrier='gas',efficiency=1,
                                           input_capacity_mw=20,priority=1,service_mwh=[20])))
    retired=deepcopy(op);retired['plants']['coal']['capacity_mw']=0
    return op,retired,national.operate_national(op),national.operate_national(retired)


class RetirementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw=json.loads((PIN/'data/processed/q2_delivery/parsed_inputs.json').read_text('utf-8'))

    def model(self,rule='paired_guard',acceleration=5):
        record=decode(self.raw['net58/25'])
        m,_,_=build_snapshot(record,25,{})
        activate_forward(m,record['config'],{'name':'test'},end_year=2060)
        activate(m,rule=rule,acceleration=acceleration)
        return m

    def test_disabled_retirement_preserves_upstream_reference(self):
        m=self.model('schedule',0);m.run(2030)
        reference=json.loads((PIN/'data/processed/q2_delivery/reference_paths/S0.json').read_text('utf-8'))
        expected=[r for r in reference['paths'] if r['year']<=2030]
        result=compare_reference(m.paths,expected)
        self.assertTrue(result['passed'],result['failures'])
        self.assertEqual(m.research_decisions,[])

    def test_mesa_bound_hook_really_executes(self):
        m=self.model('cost_order');m.run(2028)
        self.assertIs(m._user_step.__func__,RetirementModel.step)
        self.assertEqual(m.steps,4)
        self.assertTrue(m.research_decisions)
        self.assertGreater(sum(d['fee_cny'] for d in m.research_decisions),0)

    def test_static_forecast_restores_live_state(self):
        m=self.model();m.run(2026);m.year-=1
        due=[c for c in m.cohorts if c.get('research_due')==2028]
        before=deepcopy((m.cohorts,m.paths,m.fuel_stocks,m.storage_soc,m.projects,m.grid.queue))
        m.forecast(due,set(),horizon=3)
        self.assertEqual(before,(m.cohorts,m.paths,m.fuel_stocks,m.storage_soc,m.projects,m.grid.queue))

    def test_solver_failure_restores_exit_dates_and_cache(self):
        m=self.model();m.run(2026)
        due=[c for c in m.cohorts if c.get('research_due')==2028]
        before=deepcopy(m.cohorts);cache=m.planning_cache
        with patch('transition_research.retirement.operate_national',side_effect=RuntimeError('injected solver failure')):
            with self.assertRaisesRegex(RuntimeError,'injected solver failure'):
                m.forecast(due,{c['id'] for c in due},horizon=3)
        self.assertEqual(before,m.cohorts)
        self.assertIs(cache,m.planning_cache)

    def test_nonfinite_retention_fee_rejected_before_activation(self):
        for fee in (float('nan'),float('inf')):
            record=decode(self.raw['net58/25']);m,_,_=build_snapshot(record,25,{})
            activate_forward(m,record['config'],{'name':'invalid-fee'},end_year=2060)
            with self.assertRaises(ValueError):activate(m,rule='schedule',retention_fee=fee)
            self.assertFalse(hasattr(m,'research'))

    def test_rollout_restores_state_and_cannot_see_future_event(self):
        m=self.model('rollout_guard');m.run(2026);m.year-=1
        due=[c for c in m.cohorts if c.get('research_due')==2028]
        before=deepcopy((m.cohorts,m.paths,m.fuel_stocks,m.storage_soc,m.projects,m.grid.queue,m.finance))
        first=m.rollout_forecast(due,set(),horizon=2)
        m.forward_spec['event']={'start_year':2027,'end_year':2030,'gas_import_multiplier':.01,'renewable_availability_multiplier':.01}
        second=m.rollout_forecast(due,set(),horizon=2)
        self.assertEqual(first,second)
        self.assertEqual(before,(m.cohorts,m.paths,m.fuel_stocks,m.storage_soc,m.projects,m.grid.queue,m.finance))
        self.assertEqual({k.split('/')[0] for k in first},{'2027','2028'})

    def test_zero_retention_budget_cannot_create_free_capacity(self):
        m=self.model('cost_order');m.research['public_budget_fraction']=0
        m.run(2030)
        self.assertTrue(m.research_decisions)
        self.assertEqual(sum(d['deferred_mw'] for d in m.research_decisions),0)
        self.assertTrue(all(c['exit_year']==c['research_due'] for c in m.cohorts if 'research_due' in c))

    def test_max_deferral_and_transfer_pair(self):
        m=self.model('cost_order');m.run(2033)
        self.assertTrue(all(c['exit_year']<=c['research_deadline']<=c['research_natural'] for c in m.cohorts if 'research_due' in c))
        for d in m.research_decisions:
            self.assertLessEqual(d['fee_cny'],d['budget_cny'])
            self.assertEqual(d['treasury_transfer_cny']+d['contractor_receipt_cny'],0)

    def test_anchor_cannot_create_retention_when_original_rule_releases(self):
        record=decode(self.raw['net58/25']);m,_,_=build_snapshot(record,25,{})
        activate_forward(m,record['config'],{'name':'anchor-test'},end_year=2060)
        activate_anchored(m,rule='anchored_guard',acceleration=5)
        m.run(2026)
        with patch.object(m,'forecast',return_value={'2028/electricity':0.}), \
             patch.object(m,'rollout_forecast',side_effect=AssertionError('Unnecessary rollout')):
            fee=m.retirement_decision()
        self.assertEqual(fee,0)
        self.assertFalse(m.research_decisions[-1]['anchor_would_retain'])
        self.assertEqual(m.research_decisions[-1]['retained'],[])

    def test_anchor_can_release_demonstrably_irrelevant_retention(self):
        record=decode(self.raw['net58/25']);m,_,_=build_snapshot(record,25,{})
        activate_forward(m,record['config'],{'name':'anchor-test'},end_year=2060)
        activate_anchored(m,rule='anchored_guard',acceleration=5)
        m.run(2026)
        with patch.object(m,'forecast',return_value={'2028/electricity':.5}), \
             patch.object(m,'rollout_forecast',return_value={'2028/electricity':.5}):
            fee=m.retirement_decision()
        self.assertEqual(fee,0)
        self.assertTrue(m.research_decisions[-1]['anchor_would_retain'])
        self.assertFalse(m.research_decisions[-1]['hard_limit_feasible'])
        self.assertEqual(m.research_decisions[-1]['rule'],'anchored_guard')

    def test_current_information_rollout_cannot_read_future_gdp_regime(self):
        record=decode(self.raw['net58/25']);m,_,_=build_snapshot(record,25,{})
        activate_forward(m,record['config'],{'name':'GDP-test'},end_year=2060)
        activate_current(m,rule='anchored_guard',acceleration=0)
        m.run(2028)
        m.year-=1  # the real hook runs at the just-settled year's decision stage
        original_map=m.a['gdp_future'];original_map['2031_2040']=.25
        original_driver=ForwardModel.drivers;observed=[]
        def driver(branch):
            original_driver(branch);observed.append(branch.current_growth)
        with patch.object(ForwardModel,'drivers',driver):
            m.rollout_forecast([],set(),horizon=3)
        self.assertEqual(len(observed),3)
        self.assertTrue(all(abs(v-m.current_growth)<1e-12 for v in observed))
        self.assertIs(m.a['gdp_future'],original_map)
        self.assertEqual(original_map['2031_2040'],.25)

    def test_actual_lp_material_counterexample_is_detected(self):
        op,retired,keep,release=feedstock_dispatch_pair()
        retired['plants']['coal']['capacity_mw']=20
        self.assertEqual(op,retired)
        for result in (keep,release):
            self.assertLessEqual(abs(result['max_residual']),1e-6)
        a,b=services(keep),services(release)
        self.assertEqual(a['building']['fraction'],0)
        self.assertEqual(b['building']['fraction'],0)
        self.assertAlmostEqual(a['nonenergy_feedstock/coal']['fraction'],1)
        self.assertAlmostEqual(a['nonenergy_feedstock/gas']['fraction'],0)
        self.assertAlmostEqual(b['nonenergy_feedstock/coal']['fraction'],0)
        self.assertAlmostEqual(b['nonenergy_feedstock/gas']['fraction'],1)
        self.assertEqual(sum(v['unmet'] for k,v in a.items() if k.startswith('nonenergy')),
                         sum(v['unmet'] for k,v in b.items() if k.startswith('nonenergy')))
        self.assertFalse(all(b[k]['fraction']<=a[k]['fraction']+1e-8 for k in a))

    def test_paired_guard_rejects_lp_material_harm(self):
        _,_,keep,release=feedstock_dispatch_pair()
        m=self.model('rollout_guard');m.run(2026)
        def forecast(due,retained,*,horizon):
            return {'2028/'+s:v['fraction'] for s,v in services(keep if retained else release).items()}
        with patch.object(m,'rollout_forecast',side_effect=forecast):
            m.retirement_decision()
        self.assertTrue(m.research_decisions[-1]['retained'])
        self.assertTrue(any(not e['accepted'] and e['max_excess']>.99 for e in m.research_decisions[-1]['evaluations']))

    def test_energy_substitution_preserved_but_all_materials_separate(self):
        rows=[]
        for carrier in ('coal','oil','gas'):
            rows.append(dict(sector='nonenergy_feedstock',carrier=carrier,requested_service_mwh=10,unmet_service_mwh=1))
            rows.append(dict(sector='building',carrier=carrier,requested_service_mwh=10,unmet_service_mwh=1))
        grouped=services(dict(demand=rows))
        self.assertEqual(set(grouped),{'building','nonenergy_feedstock/coal','nonenergy_feedstock/oil','nonenergy_feedstock/gas'})
        self.assertEqual(grouped['building']['requested'],30)
        self.assertEqual(grouped['nonenergy_feedstock/oil']['requested'],10)

    def test_material_without_identity_fails_closed(self):
        with self.assertRaises(ValueError):
            services(dict(demand=[dict(sector='nonenergy_feedstock',requested_service_mwh=10,unmet_service_mwh=0)]))


if __name__=='__main__':unittest.main()
