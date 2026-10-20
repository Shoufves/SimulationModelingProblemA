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
from transition_research.retirement import activate,RetirementModel
from transition_research.anchored import activate as activate_anchored
from transition_research.current_information import activate as activate_current
from energy_model.q2_forward_current import ForwardModel


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


if __name__=='__main__':unittest.main()
